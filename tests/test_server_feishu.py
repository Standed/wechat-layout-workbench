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
