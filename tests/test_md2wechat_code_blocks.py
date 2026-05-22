import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MD2WECHAT_PATH = ROOT / "scripts" / "md2wechat.py"


def load_md2wechat_module():
    spec = importlib.util.spec_from_file_location("md2wechat_under_test", MD2WECHAT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_plain_text_code_block_hides_default_label():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]
    html = md2wechat.md_to_html_body("```Plain Text\nhello\n```", theme)
    assert "Plain Text" not in html
    assert "rgb(36, 42, 51)" in html


def test_named_code_block_keeps_custom_label():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]
    html = md2wechat.md_to_html_body("```Terminal\nhello\n```", theme)
    assert "Terminal" in html
