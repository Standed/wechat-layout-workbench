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
