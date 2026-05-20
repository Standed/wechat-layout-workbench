#!/usr/bin/env python3
"""Local web workbench for converting Markdown into WeChat-ready HTML."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from base64 import b64decode
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import md2wechat  # noqa: E402


ACCOUNT_KEYS = {
    "西羊石AI视频": "main",
    "羊羊AI视频": "yangy",
    "西羊石AI短剧": "dramas",
    "小石的AI智能体工坊": "gongfang",
}

SAMPLE_PATHS = {
    "西羊石AI视频": "output/main/md/260507-ChatGPT真正好用的关键是先让它反问你.md",
    "羊羊AI视频": "output/main/md/260507-ChatGPT真正好用的关键是先让它反问你.md",
    "西羊石AI短剧": "output/dramas/md/260315-做了一年AI短剧，我们总结出一套可复用的制作流程.md",
    "小石的AI智能体工坊": "output/gongfang/md/260323-飞书为什么成了 OpenClaw 在中国最先落地的工作容器.md",
}

COVER_STYLES = {
    "西羊石AI视频": {
        "tone": "AI 视频一线实战者，真诚、有经验感、创业者视角，高级科技编辑感",
        "palette": "温暖米白、深墨黑、克制紫色点缀、少量哑金色",
        "visual": "一个关于 AI 视频生产的强视觉隐喻，避免抽象霓虹电路",
    },
    "羊羊AI视频": {
        "tone": "AI 视频实操分享者，直接、清爽、有行动感，适合训练营和团队共用",
        "palette": "干净白色、深海军蓝、明亮科技蓝、少量青色高光",
        "visual": "一个清爽的 AI 视频创作工作台，蓝色界面、素材卡片、分镜时间线和生成进度形成视觉锤",
    },
    "西羊石AI短剧": {
        "tone": "AI 短剧垂直赛道，专业、实操、案例驱动，有影视制作感",
        "palette": "暖奶油色、黑棕色、低饱和陶土红、柔和金色",
        "visual": "一个有记忆点的短剧制作场景，例如分镜板、角色资产卡、导演监视器或片场灯光",
    },
    "小石的AI智能体工坊": {
        "tone": "技术极客、程序员转型创业者，克制、有哲学感，理性中带温度",
        "palette": "暖灰、纸张质感、代码黑、克制橙色点缀",
        "visual": "一个智能体或软件工作台隐喻，精确、有思考感，避免通用机器人吉祥物",
    },
}

SETTINGS_PATH = ROOT / "config" / "workbench-settings.json"

FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]


def content_from_full_html(html: str) -> str:
    start_marker = '<div id="content">'
    end_marker = "</div>\n</body>"
    start = html.find(start_marker)
    end = html.find(end_marker)
    if start == -1 or end == -1:
        return html
    return html[start + len(start_marker) : end].strip()


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {"accounts": {}}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"accounts": {}}


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def markdown_fragment_to_html(markdown: str, theme: dict) -> str:
    text = markdown.strip()
    if not text:
        return ""
    if "<" in text and ">" in text:
        return text
    return md2wechat.md_to_html_body(text, theme, preserve_paragraphs=True)


def theme_for_account(account: str) -> dict:
    base = md2wechat.ACCOUNT_THEMES.get(account, md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT]).copy()
    account_settings = load_settings().get("accounts", {}).get(account, {})
    header = account_settings.get("header", "").strip()
    footer = account_settings.get("footer", "").strip()
    if header:
        base["custom_header_html"] = markdown_fragment_to_html(header, base)
    if footer:
        base["custom_footer_html"] = markdown_fragment_to_html(footer, base)
    return base


def convert_markdown(markdown: str, account: str) -> dict:
    parsed = md2wechat.parse_markdown(markdown)
    if not parsed["title"]:
        parsed["title"] = "未命名文章"
    theme = theme_for_account(account)
    full_html = md2wechat.build_full_html(parsed, theme)
    return {
        "title": parsed["title"],
        "account": account,
        "contentHtml": content_from_full_html(full_html),
        "fullHtml": full_html,
    }


def feishu_doc_id(doc: str) -> str:
    match = re.search(r"/(?:docx|docs|wiki)/([A-Za-z0-9]+)", doc)
    if match:
        return match.group(1)
    return safe_slug(doc)[:32] or "feishu-doc"


def cli_text(result: subprocess.CompletedProcess[str] | None) -> str:
    if result is None:
        return ""
    return "\n".join(part for part in (result.stdout, result.stderr) if part).strip()


def normalize_lark_error(text: str) -> str:
    if "deprecated" in text.lower() and "api-version v2" in text.lower():
        return "当前 lark-cli / lark-doc skill 仍在使用旧版 v1 API。请先运行 lark-cli update，然后重新启动本项目。"
    return text


def parse_json_from_cli(output: str | None) -> dict:
    output = output or ""
    start = output.find("{")
    if start == -1:
        raise RuntimeError(output.strip() or "lark-cli 没有返回 JSON。")
    return json.loads(output[start:])


def run_lark_cli(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("lark-cli")
    if not executable:
        raise RuntimeError(
            "未找到 lark-cli，无法导入飞书链接。请先安装 @larksuite/cli 并完成登录；"
            "如果使用 Docker，请确认镜像已重新 build，并挂载了 .lark-cli 配置目录。"
        )
    return subprocess.run(
        [executable, *args],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def lark_cli_health() -> dict:
    executable = shutil.which("lark-cli")
    if not executable:
        return {
            "ok": False,
            "available": False,
            "error": "未找到 lark-cli。请安装 @larksuite/cli，或使用已内置 lark-cli 的 Docker 镜像。",
        }
    health = {"ok": True, "available": True, "path": executable}
    version = subprocess.run(
        [executable, "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    health["version"] = (version.stdout or version.stderr).strip()
    try:
        status = run_lark_cli(["auth", "status", "--verify"], timeout=30)
    except Exception as exc:
        health["ok"] = False
        health["authOk"] = False
        health["error"] = f"lark-cli 健康检查失败：{exc}"
        return health
    health["authOk"] = status.returncode == 0
    if status.returncode != 0:
        health["ok"] = False
        health["error"] = cli_text(status) or "lark-cli auth status --verify 未通过。请执行 lark-cli auth login。"
    else:
        try:
            health["auth"] = parse_json_from_cli(status.stdout)
        except Exception:
            health["auth"] = (status.stdout or "").strip()
    return health


def download_feishu_media(token: str, out_dir: Path) -> str | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / token
    existing = sorted(out_dir.glob(f"{token}.*"))
    if existing:
        return existing[0].relative_to(ROOT).as_posix()
    result = run_lark_cli(
        [
            "docs",
            "+media-download",
            "--token",
            token,
            "--output",
            stem.relative_to(ROOT).as_posix(),
            "--overwrite",
        ],
        timeout=90,
    )
    if result.returncode != 0:
        return None
    try:
        data = parse_json_from_cli(cli_text(result))
        saved_path = Path(data["data"]["saved_path"])
    except Exception:
        matches = sorted(out_dir.glob(f"{token}.*"))
        saved_path = matches[0] if matches else None
    if saved_path and Path(saved_path).exists():
        return Path(saved_path).resolve().relative_to(ROOT).as_posix()
    return None


def replace_feishu_images(markdown: str, doc: str) -> str:
    doc_id = feishu_doc_id(doc)
    out_dir = ROOT / "output" / "_feishu_media" / doc_id

    def repl(match: re.Match) -> str:
        attrs = match.group(0)
        token_match = re.search(r'token="([^"]+)"', attrs)
        width_match = re.search(r'width="([^"]+)"', attrs)
        height_match = re.search(r'height="([^"]+)"', attrs)
        if not token_match:
            return ""
        token = token_match.group(1)
        media_path = download_feishu_media(token, out_dir)
        alt_bits = ["飞书图片"]
        if width_match and height_match:
            alt_bits.append(f'{width_match.group(1)}x{height_match.group(1)}')
        if not media_path:
            return f"\n\n> 图片下载失败：{token}\n\n"
        return f"\n\n![{' '.join(alt_bits)}]({media_path})\n\n"

    return re.sub(r"<image\s+[^>]*?/>", repl, markdown)


def fetch_feishu_markdown(doc: str) -> str:
    if not doc.strip():
        raise RuntimeError("请提供飞书文档链接。")
    health = lark_cli_health()
    if not health.get("ok"):
        raise RuntimeError(health.get("error") or "飞书导入环境未就绪，请先检查 lark-cli。")
    result = run_lark_cli(
        [
            "docs",
            "+fetch",
            "--api-version",
            "v2",
            "--doc",
            doc.strip(),
            "--format",
            "json",
        ],
        timeout=90,
    )
    if result.returncode != 0:
        detail = normalize_lark_error(cli_text(result) or "lark-cli docs +fetch 执行失败。")
        raise RuntimeError(detail.strip())
    data = parse_json_from_cli(cli_text(result))
    if not data.get("ok"):
        raise RuntimeError(json.dumps(data.get("error", data), ensure_ascii=False))
    payload = data["data"]
    markdown = payload.get("markdown") or payload.get("document", {}).get("content") or ""
    if not markdown:
        raise RuntimeError("飞书返回为空，可能没有文档权限或文档格式暂不支持。")
    title = (payload.get("title") or payload.get("document", {}).get("title") or "").strip()
    if title and not re.search(r"^\s*#\s+", markdown, flags=re.MULTILINE):
        markdown = f"# {title}\n\n{markdown}"
    return replace_feishu_images(markdown, doc)


def safe_slug(text: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.strip(), flags=re.UNICODE)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:48] or "cover"


def short_cover_text(title: str) -> str:
    clean = re.sub(r"[#*_`<>]", "", title).strip()
    brand_terms = ["NotebookLM", "Gemini", "Gems", "Veo", "Codex", "Claude Code", "Agent", "OpenClaw", "Seedance", "可灵"]
    for term in brand_terms:
        if term.lower() in clean.lower():
            suffix_map = {
                "NotebookLM": "助教",
                "Gemini": "工作流",
                "Gems": "工作流",
                "Veo": "AI视频",
                "Codex": "编程助手",
                "Claude Code": "编程助手",
                "Agent": "智能体",
                "OpenClaw": "工作入口",
                "Seedance": "AI视频",
                "可灵": "AI视频",
            }
            suffix = suffix_map.get(term, "实测")
            return f"{term}{suffix}"
    pattern_map = [
        (["助教", "课程", "SOP"], "AI助教"),
        (["短剧", "角色"], "短剧避坑"),
        (["提示词", "公式"], "提示词公式"),
        (["工作流", "流程"], "AI工作流"),
        (["创业", "公司"], "AI创业"),
    ]
    for keywords, label in pattern_map:
        if any(keyword in clean for keyword in keywords):
            return label
    for sep in ["，", "：", "？", "！", ",", ":", "?", "!"]:
        if sep in clean:
            clean = clean.split(sep, 1)[0]
            break
    return clean[:12] or "封面标题"


def plain_article_text(article_text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", article_text or "")
    text = re.sub(r"`{3}[\s\S]*?`{3}", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[#*_`>|-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def infer_visual_hammer(title: str, article_text: str, account: str) -> str:
    text = f"{title} {plain_article_text(article_text)}"
    rules = [
        (["NotebookLM", "资料库", "助教", "课程", "SOP"], "一张桌面上摊开的课程资料、SOP 卡片和发光的 AI 助教对话窗口，形成“24 小时在线助教”的视觉锤"),
        (["Gemini", "Gems", "Veo"], "一个创作者工作台上，Gemini、NotebookLM、Veo 三类工具像三块发光模块连接成一条自动化流水线"),
        (["短剧", "角色", "分镜", "剧本"], "导演监视器、角色资产卡、分镜板和片场灯光组成的 AI 短剧制作台，强调角色一致性和制作流程"),
        (["提示词", "公式", "分镜"], "一张被拆解成六个彩色模块的 AI 视频提示词公式图，旁边有电影场记板和镜头取景框"),
        (["Agent", "智能体", "代码", "Codex", "Claude Code"], "一个安静的程序员工作台，代码窗口、任务卡片和 AI Agent 节点连接成清晰的工程控制台"),
        (["创业", "公司", "团队", "增长"], "小团队会议桌上的增长看板、项目卡片和一束聚光，呈现 AI 创业小作坊的真实工作现场"),
    ]
    for keywords, hammer in rules:
        if any(keyword.lower() in text.lower() for keyword in keywords):
            return hammer
    return COVER_STYLES.get(account, COVER_STYLES["西羊石AI视频"])["visual"]


def build_cover_prompt(title: str, account: str, cover_text: str = "", visual_hammer: str = "", article_text: str = "") -> str:
    style = COVER_STYLES.get(account, COVER_STYLES["西羊石AI视频"])
    headline = cover_text or short_cover_text(title)
    article_brief = plain_article_text(article_text)
    hammer = visual_hammer.strip() or infer_visual_hammer(title, article_text, account)
    return f"""用途：生成微信公众号文章封面背景图，比例固定为 2.35:1 横屏。

文章标题：{title}
封面短标题：{headline}
目标账号：{account}
账号气质：{style["tone"]}
文章全文内容：{article_brief or "根据文章标题进行封面创意。"}

核心视觉锤：{hammer}

画面要求：
1. 做一张有吸引力、有记忆点、有视觉锤的公众号封面背景。
2. 风格是高级中文科技媒体 / 创作者杂志封面，精致、清晰、第一眼有冲击力。
3. 画面必须是 2.35:1 超宽横图构图，适合微信公众号头图。
4. 左侧 42% 保留相对干净的标题安全区，右侧或中右侧放核心视觉锤。
5. 视觉主体要明确，轮廓一眼能看懂，不要做成抽象背景。
6. 光影要有层次，整体有电影感和编辑感，但不要过度炫技。
7. 色彩参考：{style["palette"]}。

非常重要：
图片模型只生成背景和视觉元素，不要生成任何文字。
不要出现中文、英文、字母、数字、标题、按钮、logo、水印、伪 UI 文案。
封面标题会由本地程序后期叠加，所以画面里必须完全无字。

避免：
廉价 AI 感、紫蓝霓虹渐变、杂乱电路板、随机漂浮图标、默认机器人头像、假仪表盘、过多小元素、文字乱码。"""


def pick_font(size: int):
    from PIL import ImageFont

    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in text:
        candidate = current + ch
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def overlay_cover_text(image_bytes: bytes, title: str, account: str, cover_text: str = "") -> bytes:
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFilter

    width, height = 1584, 672
    im = Image.open(BytesIO(image_bytes)).convert("RGB")
    src_ratio = im.width / im.height
    target_ratio = width / height
    if src_ratio > target_ratio:
        new_h = height
        new_w = int(height * src_ratio)
    else:
        new_w = width
        new_h = int(width / src_ratio)
    im = im.resize((new_w, new_h))
    im = im.crop(((new_w - width) // 2, (new_h - height) // 2, (new_w + width) // 2, (new_h + height) // 2))

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    account_key = ACCOUNT_KEYS.get(account, "main")
    accent = {
        "main": (113, 18, 151),
        "yangy": (0, 122, 255),
        "dramas": (174, 88, 64),
        "gongfang": (210, 80, 30),
    }.get(account_key, (113, 18, 151))

    panel = Image.new("RGBA", (760, height), (20, 18, 16, 168))
    panel = panel.filter(ImageFilter.GaussianBlur(0.2))
    overlay.alpha_composite(panel, (0, 0))
    draw.rectangle((0, 0, 18, height), fill=accent + (235,))
    draw.rounded_rectangle((78, 86, 188, 118), radius=16, fill=accent + (230,))
    draw.text((96, 91), "封面", font=pick_font(20), fill=(255, 255, 255, 245))

    headline = cover_text or short_cover_text(title)
    title_font = pick_font(100 if len(headline) <= 6 else 88 if len(headline) <= 9 else 76)
    subtitle_font = pick_font(32)
    lines = wrap_text(draw, headline, title_font, 560)[:2]
    y = 170
    for line in lines:
        draw.text((76, y), line, font=title_font, fill=(255, 255, 255, 255))
        y += int(title_font.size * 1.12)
    draw.rounded_rectangle((78, y + 10, 268, y + 22), radius=6, fill=(214, 168, 65, 245))

    subtitle = title if headline != title else ""
    if subtitle:
        sub_lines = wrap_text(draw, subtitle, subtitle_font, 560)[:2]
        sy = y + 54
        for line in sub_lines:
            draw.text((78, sy), line, font=subtitle_font, fill=(245, 241, 232, 235))
            sy += 44

    draw.text((78, height - 78), account, font=pick_font(28), fill=(245, 241, 232, 230))
    im = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def call_openai_image(prompt: str) -> bytes:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        raise RuntimeError("未设置 OPENAI_API_KEY。已生成提示词，但无法直接调用 OpenAI 图片接口。")

    payload = {
        "model": os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2"),
        "prompt": prompt,
        "size": os.environ.get("OPENAI_IMAGE_SIZE", "1584x672"),
        "quality": os.environ.get("OPENAI_IMAGE_QUALITY", "high"),
        "n": 1,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI 图片生成失败：{detail}") from exc

    item = data.get("data", [{}])[0]
    b64 = item.get("b64_json")
    if not b64:
        raise RuntimeError("OpenAI 图片接口没有返回 b64_json。")
    return b64decode(b64)


def generate_cover(title: str, account: str, cover_text: str = "", visual_hammer: str = "", article_text: str = "") -> dict:
    prompt = build_cover_prompt(title, account, cover_text, visual_hammer, article_text)
    background = call_openai_image(prompt)
    final = overlay_cover_text(background, title, account, cover_text)
    account_key = ACCOUNT_KEYS.get(account, "main")
    out_dir = ROOT / "output" / account_key / "covers" / "workbench"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{time.strftime('%y%m%d-%H%M')}-{safe_slug(cover_text or title)}.png"
    out_path = out_dir / filename
    out_path.write_bytes(final)
    rel_path = out_path.relative_to(ROOT).as_posix()
    return {
        "prompt": prompt,
        "path": rel_path,
        "url": f"/api/file?path={rel_path}",
    }


def card_font(size: int):
    return pick_font(size)


def card_wrap(draw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in text:
        if ch == "\n":
            if current:
                lines.append(current)
            current = ""
            continue
        candidate = current + ch
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines or [""]


def extract_card_blocks(markdown: str) -> tuple[str, list[dict]]:
    title = "未命名文章"
    blocks: list[dict] = []
    lines = markdown.splitlines()
    paragraph: list[str] = []
    in_code = False
    code_lines: list[str] = []
    code_lang = ""

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            text = " ".join(part.strip() for part in paragraph if part.strip())
            if text:
                blocks.append({"type": "paragraph", "text": text})
            paragraph = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                blocks.append({"type": "code", "text": "\n".join(code_lines).strip(), "lang": code_lang or "Terminal"})
                code_lines = []
                code_lang = ""
                in_code = False
            else:
                flush_paragraph()
                in_code = True
                code_lang = stripped[3:].strip()
            continue
        if in_code:
            code_lines.append(line.rstrip())
            continue
        if not stripped:
            flush_paragraph()
            continue
        if stripped.startswith("# "):
            flush_paragraph()
            text = stripped[2:].strip()
            if title == "未命名文章":
                title = text
            else:
                blocks.append({"type": "h1", "text": text})
            continue
        if stripped.startswith("## "):
            flush_paragraph()
            blocks.append({"type": "h2", "text": stripped[3:].strip()})
            continue
        image = re.match(r"!\[(.*?)\]\((.+?)\)$", stripped)
        if image:
            flush_paragraph()
            blocks.append({"type": "image", "alt": image.group(1).strip() or "图片", "src": image.group(2).strip()})
            continue
        if re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            flush_paragraph()
            blocks.append({"type": "list", "text": re.sub(r"^([-*]|\d+\.)\s+", "", stripped)})
            continue
        paragraph.append(stripped)
    flush_paragraph()
    if in_code and code_lines:
        blocks.append({"type": "code", "text": "\n".join(code_lines).strip(), "lang": code_lang or "Terminal"})
    return title, blocks


def open_card_image(src: str):
    from io import BytesIO
    from PIL import Image

    if src.startswith("data:image/"):
        try:
            header, b64 = src.split(",", 1)
            return Image.open(BytesIO(b64decode(b64))).convert("RGB")
        except Exception:
            return None
    if src.startswith("/api/file?path="):
        src = unquote(src.split("=", 1)[1])
    if src.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(src, timeout=20) as response:
                return Image.open(BytesIO(response.read())).convert("RGB")
        except Exception:
            return None
    path = (ROOT / src).resolve()
    if ROOT in path.parents and path.is_file():
        try:
            return Image.open(path).convert("RGB")
        except Exception:
            return None
    return None


def render_card_image(markdown: str, account: str) -> dict:
    from io import BytesIO
    from PIL import Image, ImageDraw

    title, blocks = extract_card_blocks(markdown)
    width = 820
    content_w = 650
    margin_x = 85
    page_bg = "#6854e8"
    paper = "#fffdf8"
    ink = "#1e1e1e"
    muted = "#68635c"
    accent = md2wechat.ACCOUNT_THEMES.get(account, md2wechat.ACCOUNT_THEMES[md2wechat.DEFAULT_ACCOUNT])["primary"]
    f_title = card_font(36)
    f_h1 = card_font(29)
    f_h2 = card_font(25)
    f_body = card_font(22)
    f_small = card_font(17)
    f_code = card_font(18)

    temp = Image.new("RGB", (width, 1000), page_bg)
    draw = ImageDraw.Draw(temp)
    y = 54
    y += 26
    for line in card_wrap(draw, title, f_title, content_w):
        y += f_title.size + 14
    y += 28
    for block in blocks:
        kind = block["type"]
        if kind in ("paragraph", "list"):
            line_prefix = "• " if kind == "list" else ""
            for line in card_wrap(draw, line_prefix + block["text"], f_body, content_w):
                y += f_body.size + 13
            y += 10
        elif kind == "h1":
            y += 20 + f_h1.size + 16
        elif kind == "h2":
            y += 18 + f_h2.size + 14
        elif kind == "code":
            lines = block["text"].splitlines()[:24] or [""]
            y += 46 + len(lines) * 28 + 26
        elif kind == "image":
            im = open_card_image(block["src"])
            if im:
                ratio = content_w / im.width
                y += int(im.height * ratio) + 26
                if block.get("alt") and block["alt"] not in ("图片", "image"):
                    y += f_small.size + 16
            else:
                y += 120
    y += 80

    height = min(max(y, 1200), 28000)
    img = Image.new("RGB", (width, height), page_bg)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((44, 30, width - 44, height - 34), radius=22, fill=paper)
    y = 70
    draw.rounded_rectangle((margin_x, y, margin_x + 118, y + 32), radius=16, fill=accent)
    draw.text((margin_x + 22, y + 6), account, font=f_small, fill="#ffffff")
    y += 54
    for line in card_wrap(draw, title, f_title, content_w):
        draw.text((margin_x, y), line, font=f_title, fill=ink)
        y += f_title.size + 14
    y += 22
    draw.line((margin_x, y, margin_x + 92, y), fill=accent, width=4)
    y += 34

    for block in blocks:
        kind = block["type"]
        if y > height - 160:
            break
        if kind in ("paragraph", "list"):
            line_prefix = "• " if kind == "list" else ""
            for line in card_wrap(draw, line_prefix + block["text"], f_body, content_w):
                draw.text((margin_x, y), line, font=f_body, fill=ink)
                y += f_body.size + 13
            y += 10
        elif kind == "h1":
            y += 18
            draw.text((margin_x, y), block["text"], font=f_h1, fill=ink)
            y += f_h1.size + 18
            draw.line((margin_x, y, margin_x + content_w, y), fill="#ebe5dc", width=2)
            y += 18
        elif kind == "h2":
            y += 18
            draw.rectangle((margin_x, y + 3, margin_x + 7, y + f_h2.size + 8), fill=accent)
            draw.text((margin_x + 18, y), block["text"], font=f_h2, fill=ink)
            y += f_h2.size + 20
        elif kind == "code":
            lines = block["text"].splitlines()[:24] or [""]
            box_h = 46 + len(lines) * 28 + 20
            draw.rounded_rectangle((margin_x, y, margin_x + content_w, y + box_h), radius=12, fill="#1f2328")
            for i, color in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
                draw.ellipse((margin_x + 18 + i * 24, y + 17, margin_x + 30 + i * 24, y + 29), fill=color)
            draw.text((margin_x + 100, y + 12), block.get("lang") or "Terminal", font=f_small, fill="#aeb6bf")
            cy = y + 50
            for line in lines:
                draw.text((margin_x + 22, cy), line[:62], font=f_code, fill="#f5f7fa")
                cy += 28
            y += box_h + 24
        elif kind == "image":
            source = open_card_image(block["src"])
            if source:
                ratio = content_w / source.width
                new_size = (content_w, max(1, int(source.height * ratio)))
                source = source.resize(new_size)
                img.paste(source, (margin_x, y))
                y += new_size[1] + 10
                if block.get("alt") and block["alt"] not in ("图片", "image"):
                    caption = block["alt"].replace("飞书图片", "").strip()
                    if caption:
                        for line in card_wrap(draw, caption, f_small, content_w):
                            tw = draw.textbbox((0, 0), line, font=f_small)[2]
                            draw.text((margin_x + (content_w - tw) / 2, y), line, font=f_small, fill=muted)
                            y += f_small.size + 8
                y += 18
            else:
                draw.rounded_rectangle((margin_x, y, margin_x + content_w, y + 96), radius=10, outline="#ded8cf", width=2)
                draw.text((margin_x + 24, y + 34), "图片暂不可用", font=f_body, fill=muted)
                y += 122

    draw.text((margin_x, height - 76), "Powered by 西羊石公众号排版工作台", font=f_small, fill="#8b857d")
    account_key = ACCOUNT_KEYS.get(account, "main")
    out_dir = ROOT / "output" / account_key / "cards" / "workbench"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{time.strftime('%y%m%d-%H%M')}-{safe_slug(title)}.png"
    img.save(out_path, format="PNG")
    rel_path = out_path.relative_to(ROOT).as_posix()
    return {"path": rel_path, "url": f"/api/file?path={rel_path}", "title": title}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:
        sys.stdout.write("%s - %s\n" % (self.address_string(), format % args))

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self.send_json(200, {"ok": True, "larkCli": lark_cli_health()})
            return

        if self.path == "/api/settings":
            self.send_json(200, load_settings())
            return

        if self.path == "/api/accounts":
            self.send_json(
                200,
                {
                    "accounts": [
                        {
                            "name": name,
                            "key": ACCOUNT_KEYS[name],
                            "author": md2wechat.ACCOUNT_THEMES[name]["author"],
                            "primary": md2wechat.ACCOUNT_THEMES[name]["primary"],
                            "accent": md2wechat.ACCOUNT_THEMES[name]["accent"],
                        }
                        for name in ACCOUNT_KEYS
                    ]
                },
            )
            return

        if self.path.startswith("/api/sample?account="):
            account = unquote(self.path.split("=", 1)[1])
            raw_path = SAMPLE_PATHS.get(account)
            if not raw_path:
                self.send_json(404, {"error": "示例账号不存在"})
                return
            sample_path = (ROOT / raw_path).resolve()
            if not sample_path.exists():
                self.send_json(404, {"error": "示例文件不存在"})
                return
            self.send_json(200, {"markdown": sample_path.read_text(encoding="utf-8")})
            return

        if self.path.startswith("/api/sample?path="):
            raw_path = unquote(self.path.split("=", 1)[1])
            sample_path = (ROOT / raw_path).resolve()
            if ROOT not in sample_path.parents or sample_path.suffix != ".md" or not sample_path.exists():
                self.send_json(404, {"error": "示例文件不存在"})
                return
            self.send_json(200, {"markdown": sample_path.read_text(encoding="utf-8")})
            return

        if self.path.startswith("/api/file?path="):
            raw_path = unquote(self.path.split("=", 1)[1])
            file_path = (ROOT / raw_path).resolve()
            if ROOT not in file_path.parents or not file_path.is_file():
                self.send_json(404, {"error": "文件不存在"})
                return
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        super().do_GET()

    def do_POST(self) -> None:
        if self.path not in ("/api/convert", "/api/cover-prompt", "/api/generate-cover", "/api/import-feishu", "/api/export-card", "/api/settings"):
            self.send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if self.path == "/api/settings":
                account = payload.get("account", "").strip()
                if account not in ACCOUNT_KEYS:
                    self.send_json(400, {"error": "未知账号"})
                    return
                settings = load_settings()
                settings.setdefault("accounts", {})[account] = {
                    "header": payload.get("header", "").strip(),
                    "footer": payload.get("footer", "").strip(),
                }
                save_settings(settings)
                self.send_json(200, settings)
                return

            if self.path == "/api/import-feishu":
                doc = payload.get("doc", "").strip()
                if not doc:
                    self.send_json(400, {"error": "请先粘贴飞书 docx 链接"})
                    return
                try:
                    self.send_json(200, {"markdown": fetch_feishu_markdown(doc)})
                except Exception as exc:
                    self.send_json(500, {"error": str(exc), "diagnostics": {"larkCli": lark_cli_health()}})
                return

            if self.path == "/api/export-card":
                markdown = payload.get("markdown", "")
                account = payload.get("account", md2wechat.DEFAULT_ACCOUNT)
                if not markdown.strip():
                    self.send_json(400, {"error": "请先导入或粘贴正文"})
                    return
                self.send_json(200, render_card_image(markdown, account))
                return

            if self.path == "/api/cover-prompt":
                title = payload.get("title", "").strip()
                account = payload.get("account", md2wechat.DEFAULT_ACCOUNT)
                cover_text = payload.get("coverText", "").strip()
                visual_hammer = payload.get("visualHammer", "").strip()
                article_text = payload.get("articleText", "").strip()
                if not title:
                    self.send_json(400, {"error": "请先填写文章标题"})
                    return
                self.send_json(
                    200,
                    {
                        "prompt": build_cover_prompt(title, account, cover_text, visual_hammer, article_text),
                        "coverText": cover_text or short_cover_text(title),
                    },
                )
                return

            if self.path == "/api/generate-cover":
                title = payload.get("title", "").strip()
                account = payload.get("account", md2wechat.DEFAULT_ACCOUNT)
                cover_text = payload.get("coverText", "").strip()
                visual_hammer = payload.get("visualHammer", "").strip()
                article_text = payload.get("articleText", "").strip()
                if not title:
                    self.send_json(400, {"error": "请先填写文章标题"})
                    return
                self.send_json(200, generate_cover(title, account, cover_text, visual_hammer, article_text))
                return

            markdown = payload.get("markdown", "")
            account = payload.get("account", md2wechat.DEFAULT_ACCOUNT)
            if not markdown.strip():
                self.send_json(400, {"error": "请先粘贴 Markdown 正文"})
                return
            self.send_json(200, convert_markdown(markdown, account))
        except Exception as exc:  # pragma: no cover - surfaced in browser
            self.send_json(500, {"error": str(exc)})


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    host = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"WeChat layout workbench: http://{display_host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
