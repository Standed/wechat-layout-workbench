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
