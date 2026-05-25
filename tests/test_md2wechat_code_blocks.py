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
    assert html.count("●") == 3


def test_markdown_code_block_hides_default_label():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]
    html = md2wechat.md_to_html_body("```Markdown\nhello\n```", theme)
    assert "Markdown" not in html
    assert html.count("●") == 3


def test_named_code_block_keeps_custom_label():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]
    html = md2wechat.md_to_html_body("```Terminal\nhello\n```", theme)
    assert "Terminal" in html


def test_feishu_image_grid_renders_two_columns_without_touching_paragraphs():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES["羊羊AI视频"]
    html = md2wechat.md_to_html_body(
        '## 小标题\n\n正文第一段。\n\n<!-- feishu-grid:[{"width":"0.5","images":[{"src":"left.jpg","alt":"left"}]},{"width":"0.5","images":[{"src":"right.jpg","alt":"right"}]}] -->',
        theme,
    )

    assert 'font-size: 22px' in html
    assert 'margin: 16px 0 0' in html
    assert 'display: table; width: 100%' in html
    assert html.count('display: table-cell') == 2
    assert 'border-radius: 10px' in html
    assert 'box-shadow: rgba(20, 28, 38, 0.14) 0 6px 18px' in html
