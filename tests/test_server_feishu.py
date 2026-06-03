import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "web" / "server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("workbench_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_json_from_cli_rejects_none_with_clear_error():
    server = load_server_module()
    try:
        server.parse_json_from_cli(None)
    except RuntimeError as exc:
        assert "没有返回 JSON" in str(exc)
    else:
        raise AssertionError("parse_json_from_cli(None) should raise RuntimeError")


def test_parse_json_from_cli_accepts_prefixed_json():
    server = load_server_module()
    assert server.parse_json_from_cli("notice\n{\"ok\": true}") == {"ok": True}


def test_parse_json_from_cli_ignores_trailing_cli_noise():
    server = load_server_module()
    output = """[lark-cli] [WARN] proxy detected
{"ok": true, "data": {"document": {"content": "hello"}}}
lark-cli 1.0.34 available, current 1.0.33
"""
    assert server.parse_json_from_cli(output) == {"ok": True, "data": {"document": {"content": "hello"}}}


def test_convert_markdown_can_preserve_feishu_paragraphs_and_bold():
    server = load_server_module()
    result = server.convert_markdown(
        "# 标题\n\n第一段。不要被拆。\n\n2. **第二段加粗序号**",
        "西羊石AI视频",
        preserve_paragraphs=True,
    )
    html = result["contentHtml"]

    assert "第一段。不要被拆。" in html
    assert html.count("第一段。不要被拆。") == 1
    assert ">2.</span>" in html
    assert '<span style="font-weight: bold;">第二段加粗序号</span>' in html


def test_rich_content_html_sanitizes_and_preserves_inline_styles():
    server = load_server_module()
    result = server.rich_content_html(
        '<h1>富文本标题</h1><p onclick="bad()"><span style="color: rgb(255, 0, 0); font-weight: 700;">红色加粗</span>'
        '<script>alert(1)</script><a href="javascript:alert(2)">坏链接</a></p>',
        "羊羊AI视频",
    )
    html = result["contentHtml"]

    assert result["title"] == "富文本标题"
    assert "font-size: 17px" in html
    assert "font-size: 22px" in html
    assert "color: rgb(255, 0, 0)" in html
    assert "font-weight: 700" in html
    assert "onclick" not in html
    assert "script" not in html
    assert "javascript:" not in html


def test_extract_feishu_document_converts_html_payload_to_markdown_and_html():
    server = load_server_module()
    payload = {
        "document": {
            "title": "飞书标题",
            "content": '<h1>飞书标题</h1><p><strong>第一段</strong></p><ol start="2"><li>第二项</li></ol>',
        }
    }
    result = server.extract_feishu_document(payload, "https://example.feishu.cn/docx/AbCd")

    assert "# 飞书标题" in result["markdown"]
    assert "**第一段**" in result["markdown"]
    assert "2. 第二项" in result["markdown"]
    assert result["html"] == ""


def test_extract_feishu_document_preserves_image_grid_in_markdown():
    server = load_server_module()
    payload = {
        "document": {
            "title": "飞书标题",
            "content": '<grid><column width-ratio="0.5"><img src="left.jpg" name="left.jpg"/></column>'
            '<column width-ratio="0.5"><img src="right.jpg" name="right.jpg"/></column></grid>',
        }
    }
    result = server.extract_feishu_document(payload, "https://example.feishu.cn/docx/AbCd")
    markdown = result["markdown"]

    assert "<!-- feishu-grid:" in markdown
    assert "left.jpg" in markdown
    assert "right.jpg" in markdown


def test_extract_feishu_document_preserves_complex_html_blocks():
    server = load_server_module()
    payload = {
        "document": {
            "title": "复杂飞书文档",
            "content": (
                "<blockquote><p>引用内容</p></blockquote>"
                "<table><tr><th>能力</th><th>状态</th></tr><tr><td><strong>表格</strong></td><td>保留</td></tr></table>"
                '<figure><video><source href="https://example.com/demo.mp4"/></video></figure>'
                '<cite><a href="https://example.com/ref">引用文档</a></cite>'
                '<p><cite title="无正文引用文档" type="doc"></cite></p>'
            ),
        }
    }
    result = server.extract_feishu_document(payload, "https://example.feishu.cn/docx/AbCd")
    markdown = result["markdown"]

    assert "> 引用内容" in markdown
    assert "> \n\n引用内容" not in markdown
    assert "| 能力 | 状态 |" in markdown
    assert "| **表格** | 保留 |" in markdown
    assert "![飞书视频](https://example.com/demo.mp4)" in markdown
    assert "> 引用：[引用文档](https://example.com/ref)" in markdown
    assert "> 引用：无正文引用文档" in markdown


def test_extract_feishu_document_grid_keeps_video_source():
    server = load_server_module()
    payload = {
        "document": {
            "title": "飞书标题",
            "content": '<grid><column width-ratio="0.5"><video><source href="https://example.com/left.mp4"/></video></column>'
            '<column width-ratio="0.5"><img src="right.jpg" name="right.jpg"/></column></grid>',
        }
    }
    result = server.extract_feishu_document(payload, "https://example.feishu.cn/docx/AbCd")
    markdown = result["markdown"]

    assert "<!-- feishu-grid:" in markdown
    assert "left.mp4" in markdown
    assert '"type":"video"' in markdown
    assert "right.jpg" in markdown


def test_extract_feishu_document_continues_split_ordered_lists():
    server = load_server_module()
    payload = {
        "document": {
            "title": "飞书标题",
            "content": (
                "<ol><li seq=\"auto\">第一项</li></ol>"
                "<ol><li seq=\"auto\">第二项</li></ol>"
                "<ol><li seq=\"auto\">第三项</li></ol>"
                "<p>普通段落</p>"
                "<ol><li seq=\"1\">重新开始</li></ol>"
            ),
        }
    }
    markdown = server.extract_feishu_document(payload, "https://example.feishu.cn/docx/AbCd")["markdown"]

    assert "1. 第一项" in markdown
    assert "2. 第二项" in markdown
    assert "3. 第三项" in markdown
    assert "1. 重新开始" in markdown


def test_feishu_doc_id_accepts_openapi_query_params():
    server = load_server_module()

    assert server.feishu_doc_id("https://example.feishu.cn/docx/AbCd") == "AbCd"
    assert server.feishu_doc_id("https://example.feishu.cn/docx?document_id=QueryId") == "QueryId"
    assert server.feishu_doc_id("https://example.feishu.cn/wiki?obj_token=WikiToken") == "WikiToken"


def test_image_extension_keeps_gif_by_content_type_and_file_header():
    server = load_server_module()

    assert server.image_extension("image/gif") == ".gif"
    assert server.image_extension("application/octet-stream", b"GIF89a...") == ".gif"
    assert server.image_extension("application/octet-stream", b"RIFFxxxxWEBP...") == ".webp"


def test_presigned_r2_get_url_defaults_to_one_day():
    from urllib.parse import parse_qs, urlparse

    server = load_server_module()
    url = server.presigned_r2_get_url(
        {
            "bucket": "bucket",
            "accessKeyId": "access",
            "secretAccessKey": "secret",
            "endpoint": "https://example.r2.cloudflarestorage.com",
        },
        "temp/wechat-layout/Doc123/image.png",
    )

    assert url is not None
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.path == "/bucket/temp/wechat-layout/Doc123/image.png"
    assert params["X-Amz-Expires"] == ["86400"]
    assert params["X-Amz-Signature"][0]


def test_cached_r2_url_refreshes_old_signed_ttl(monkeypatch):
    from urllib.parse import parse_qs, urlparse

    server = load_server_module()
    monkeypatch.setattr(server, "save_r2_cache", lambda cache: None)
    config = {
        "bucket": "bucket",
        "accessKeyId": "access",
        "secretAccessKey": "secret",
        "endpoint": "https://example.r2.cloudflarestorage.com",
    }
    cache = {
        "output/_feishu_media/Doc123/image.png": {
            "sha256": "digest",
            "key": "temp/wechat-layout/Doc123/image.png",
            "mode": "signed",
            "expiresAtEpoch": 9999999999,
            "url": (
                "https://example.r2.cloudflarestorage.com/bucket/temp/wechat-layout/Doc123/image.png"
                "?X-Amz-Expires=604800&X-Amz-Signature=old"
            ),
        }
    }

    url = server.cached_r2_url(cache, "output/_feishu_media/Doc123/image.png", "digest", config)

    assert url is not None
    params = parse_qs(urlparse(url).query)
    assert params["X-Amz-Expires"] == ["86400"]
    assert params["X-Amz-Signature"][0] != "old"


def test_attach_r2_image_sources_adds_public_url_for_feishu_media(monkeypatch, tmp_path):
    server = load_server_module()
    monkeypatch.setattr(server, "ROOT", tmp_path)
    media_dir = server.ROOT / "output" / "_feishu_media" / "Doc123"
    media_dir.mkdir(parents=True, exist_ok=True)
    image_path = media_dir / "image-token.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(server, "r2_config", lambda: {"configured": True})
    monkeypatch.setattr(server, "upload_file_to_r2", lambda path: "https://assets.example.com/temp/image-token.png")

    html = '<section><img data-local-src="output/_feishu_media/Doc123/image-token.png" src="" alt="飞书图片"/></section>'
    result = server.attach_r2_image_sources(html)

    assert 'data-local-src="output/_feishu_media/Doc123/image-token.png"' in result
    assert 'data-r2-src="https://assets.example.com/temp/image-token.png"' in result


def test_attach_r2_image_sources_ignores_non_feishu_local_images(monkeypatch):
    server = load_server_module()

    monkeypatch.setattr(server, "r2_config", lambda: {"configured": True})
    monkeypatch.setattr(server, "upload_file_to_r2", lambda path: (_ for _ in ()).throw(AssertionError("should not upload")))

    html = '<img data-local-src="output/main/images/example.png" src="" alt="本地图"/>'

    assert server.attach_r2_image_sources(html) == html


def test_fetch_feishu_document_openapi_converts_blocks_and_grid(monkeypatch):
    server = load_server_module()

    calls = []

    def fake_request(path, method="GET", body=None, token="", timeout=30):
        calls.append(path)
        if path == "/auth/v3/tenant_access_token/internal":
            return {"tenant_access_token": "tenant-token"}
        if path == "/docx/v1/documents/Doc123":
            return {"data": {"document": {"title": "飞书标题"}}}
        if path.startswith("/docx/v1/documents/Doc123/blocks"):
            return {
                "data": {
                    "items": [
                        {"block_id": "page", "block_type": 1, "children": ["h2", "p1", "grid"]},
                        {
                            "block_id": "h2",
                            "block_type": 4,
                            "heading2": {"elements": [{"text_run": {"content": "小标题", "text_element_style": {"bold": True}}}]},
                        },
                        {
                            "block_id": "p1",
                            "block_type": 2,
                            "text": {"elements": [{"text_run": {"content": "第一段", "text_element_style": {}}}]},
                        },
                        {"block_id": "grid", "block_type": 24, "children": ["c1", "c2"]},
                        {"block_id": "c1", "block_type": 25, "grid_column": {"width_ratio": "0.5"}, "children": ["img1"]},
                        {"block_id": "c2", "block_type": 25, "grid_column": {"width_ratio": "0.5"}, "children": ["img2"]},
                        {"block_id": "img1", "block_type": 27, "image": {"token": "left-token"}},
                        {"block_id": "img2", "block_type": 27, "image": {"token": "right-token"}},
                    ],
                    "has_more": False,
                }
            }
        raise AssertionError(f"unexpected path: {path}")

    def fake_download(token, out_dir, tenant_token):
        assert tenant_token == "tenant-token"
        return f"output/_feishu_media/Doc123/{token}.jpg"

    monkeypatch.setenv("FEISHU_APP_ID", "app-id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "app-secret")
    monkeypatch.setattr(server, "feishu_openapi_request", fake_request)
    monkeypatch.setattr(server, "download_feishu_media_openapi", fake_download)

    result = server.fetch_feishu_document_openapi("https://example.feishu.cn/docx/Doc123")

    assert result["source"] == "feishuOpenApi"
    assert result["documentId"] == "Doc123"
    assert "# 飞书标题" in result["markdown"]
    assert "## **小标题**" in result["markdown"]
    assert "第一段" in result["markdown"]
    assert "<!-- feishu-grid:" in result["markdown"]
    assert "left-token.jpg" in result["markdown"]
    assert "right-token.jpg" in result["markdown"]
    assert any("/blocks?" in call for call in calls)


def test_feishu_blocks_to_markdown_rebuilds_table_cells():
    server = load_server_module()
    blocks = [
        {"block_id": "page", "block_type": 1, "children": ["table"]},
        {"block_id": "table", "block_type": 31, "table": {"column_size": 2}, "children": ["a1", "a2", "b1", "b2"]},
        {"block_id": "a1", "block_type": 32, "table_cell": {"row_index": 0, "column_index": 0, "elements": [{"text_run": {"content": "能力"}}]}},
        {"block_id": "a2", "block_type": 32, "table_cell": {"row_index": 0, "column_index": 1, "elements": [{"text_run": {"content": "状态"}}]}},
        {"block_id": "b1", "block_type": 32, "table_cell": {"row_index": 1, "column_index": 0, "elements": [{"text_run": {"content": "表格"}}]}},
        {"block_id": "b2", "block_type": 32, "table_cell": {"row_index": 1, "column_index": 1, "elements": [{"text_run": {"content": "保留"}}]}},
    ]

    markdown = server.feishu_blocks_to_markdown(blocks, "tenant-token", "Doc123")

    assert "| 能力 | 状态 |" in markdown
    assert "| 表格 | 保留 |" in markdown


def test_feishu_blocks_to_markdown_continues_ordered_blocks():
    server = load_server_module()
    blocks = [
        {"block_id": "page", "block_type": 1, "children": ["o1", "o2", "o3", "p1", "o4"]},
        {"block_id": "o1", "block_type": 13, "ordered": {"elements": [{"text_run": {"content": "第一项"}}]}},
        {"block_id": "o2", "block_type": 13, "ordered": {"elements": [{"text_run": {"content": "第二项"}}]}},
        {"block_id": "o3", "block_type": 13, "ordered": {"elements": [{"text_run": {"content": "第三项"}}]}},
        {"block_id": "p1", "block_type": 2, "text": {"elements": [{"text_run": {"content": "普通段落"}}]}},
        {"block_id": "o4", "block_type": 13, "ordered": {"seq": 1, "elements": [{"text_run": {"content": "重新开始"}}]}},
    ]

    markdown = server.feishu_blocks_to_markdown(blocks, "tenant-token", "Doc123")

    assert "1. 第一项" in markdown
    assert "2. 第二项" in markdown
    assert "3. 第三项" in markdown
    assert "普通段落" in markdown
    assert "1. 重新开始" in markdown


def test_fetch_feishu_document_prefers_openapi_when_configured(monkeypatch):
    server = load_server_module()

    monkeypatch.setenv("FEISHU_APP_ID", "app-id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "app-secret")
    monkeypatch.setattr(server, "fetch_feishu_document_openapi", lambda doc: {"markdown": "# openapi", "html": "", "source": "feishuOpenApi"})

    def should_not_call_lark_cli(doc):
        raise AssertionError("lark-cli should not be called when OpenAPI succeeds")

    monkeypatch.setattr(server, "fetch_feishu_document_lark_cli", should_not_call_lark_cli)

    assert server.fetch_feishu_document("https://example.feishu.cn/docx/Doc123")["source"] == "feishuOpenApi"


def test_fetch_feishu_document_falls_back_to_lark_cli(monkeypatch):
    server = load_server_module()

    monkeypatch.setenv("FEISHU_APP_ID", "app-id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "app-secret")
    monkeypatch.setattr(server, "fetch_feishu_document_openapi", lambda doc: (_ for _ in ()).throw(RuntimeError("openapi failed")))
    monkeypatch.setattr(server, "fetch_feishu_document_lark_cli", lambda doc: {"markdown": "# cli", "html": "", "source": "larkCli"})

    assert server.fetch_feishu_document("https://example.feishu.cn/docx/Doc123")["source"] == "larkCli"
