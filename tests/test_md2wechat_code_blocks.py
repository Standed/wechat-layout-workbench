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


def test_feishu_grid_renders_video_placeholder():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]
    html = md2wechat.md_to_html_body(
        '<!-- feishu-grid:[{"width":"0.5","images":[{"src":"https://example.com/demo.mp4","alt":"演示视频","type":"video"}]},{"width":"0.5","images":[{"src":"right.jpg","alt":"right"}]}] -->',
        theme,
    )

    assert 'display: table; width: 100%' in html
    assert html.count('display: table-cell') == 2
    assert '视频占位：演示视频' in html
    assert 'https://example.com/demo.mp4' not in html
    assert 'right.jpg' in html


def test_feishu_stream_image_markdown_renders_as_video_placeholder():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]
    src = 'https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=abc'
    html = md2wechat.md_to_html_body(f'![飞书视频]({src})', theme)

    assert '视频占位：飞书视频' in html
    assert src not in html
    assert '<img' not in html


def test_feishu_stream_image_with_image_alt_stays_image():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]
    src = 'https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=abc'
    html = md2wechat.md_to_html_body(f'![test.jpg]({src})', theme)

    assert '视频占位' not in html
    assert '<img' in html
    assert src in html


def test_image_alt_text_renders_as_caption_when_meaningful():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]
    html = md2wechat.md_to_html_body(
        "![《丧尸清道夫》成片开场氛围片段](https://example.com/image.gif)",
        theme,
    )

    assert '<img src="https://example.com/image.gif"' in html
    assert "《丧尸清道夫》成片开场氛围片段" in html
    assert "font-size: 13px" in html


def test_generic_image_alt_does_not_render_as_caption():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]
    html = md2wechat.md_to_html_body("![test.jpg](https://example.com/test.jpg)", theme)

    assert '<img src="https://example.com/test.jpg"' in html
    assert html.count("test.jpg") == 2
    assert "font-size: 13px" not in html


def test_ordered_list_uses_wechat_stable_inline_markers():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]
    html = md2wechat.md_to_html_body(
        "1. 第一项\n2. 第二项",
        theme,
    )

    assert "display: table-cell" not in html
    assert "1.</span>" in html
    assert "2.</span>" in html
    assert "text-align-last: left" in html
    assert "letter-spacing: 0" in html


def test_toc_uses_second_and_third_level_when_no_body_h1():
    md2wechat = load_md2wechat_module()
    items = md2wechat.extract_toc_items(
        "## 一、工具准备\n\n正文\n\n### 1. 安装工具\n\n### 2. 登录飞书\n\n## 二、写在最后"
    )

    assert items == [
        {"title": "工具准备", "children": ["安装工具", "登录飞书"]},
        {"title": "写在最后", "children": []},
    ]


def test_toc_uses_body_h1_and_h2_when_both_exist():
    md2wechat = load_md2wechat_module()
    items = md2wechat.extract_toc_items(
        "# 一、资产构建\n\n## 1. 角色设计\n\n### 更深层会被忽略\n\n# 二、总结"
    )

    assert items == [
        {"title": "资产构建", "children": ["角色设计"]},
        {"title": "总结", "children": []},
    ]


def test_full_html_includes_generated_toc_before_body_headings():
    md2wechat = load_md2wechat_module()
    theme = md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]
    parsed = md2wechat.parse_markdown("# 文章标题\n\n## 一、工具准备\n\n### 1. 安装工具")
    html = md2wechat.build_full_html(parsed, theme)

    assert '<strong style="box-sizing: border-box;">目录</strong>' in html
    assert "工具准备" in html
    assert "安装工具" in html
    assert html.index('<strong style="box-sizing: border-box;">目录</strong>') < html.index("<h3")
