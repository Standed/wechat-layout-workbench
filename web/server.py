#!/usr/bin/env python3
"""Local web workbench for converting Markdown into WeChat-ready HTML."""

from __future__ import annotations

import json
import hashlib
import hmac
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
from html import unescape
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse


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
R2_CACHE_PATH = ROOT / "output" / "_feishu_media" / ".r2-cache.json"
VIDEO_AGENT_PRO_ENV = ROOT.parent / "vibeAgent" / "finalAgent" / "video-agent-pro" / ".env.local"
R2_TEMP_IMAGE_TTL_SECONDS = 86400
R2_SIGNED_URL_REFRESH_MARGIN_SECONDS = 900

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


def load_env_file(path: Path, keys: set[str]) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in keys or os.environ.get(name):
            continue
        os.environ[name] = value.strip().strip('"').strip("'")


def ensure_r2_env_loaded() -> None:
    keys = {"R2_BUCKET_NAME", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "NEXT_PUBLIC_R2_PUBLIC_URL"}
    custom_env = os.environ.get("R2_ENV_FILE", "").strip()
    if custom_env:
        load_env_file(Path(custom_env).expanduser(), keys)
    load_env_file(VIDEO_AGENT_PRO_ENV, keys)


def r2_config() -> dict:
    ensure_r2_env_loaded()
    config = {
        "bucket": os.environ.get("R2_BUCKET_NAME", "").strip(),
        "accessKeyId": os.environ.get("R2_ACCESS_KEY_ID", "").strip(),
        "secretAccessKey": os.environ.get("R2_SECRET_ACCESS_KEY", "").strip(),
        "endpoint": os.environ.get("R2_ENDPOINT", "").strip().rstrip("/"),
        "publicUrl": os.environ.get("NEXT_PUBLIC_R2_PUBLIC_URL", "").strip().rstrip("/"),
    }
    config["configured"] = all(config.values())
    return config


def r2_health() -> dict:
    config = r2_config()
    missing = []
    labels = {
        "bucket": "R2_BUCKET_NAME",
        "accessKeyId": "R2_ACCESS_KEY_ID",
        "secretAccessKey": "R2_SECRET_ACCESS_KEY",
        "endpoint": "R2_ENDPOINT",
        "publicUrl": "NEXT_PUBLIC_R2_PUBLIC_URL",
    }
    for key, label in labels.items():
        if not config.get(key):
            missing.append(label)
    return {
        "ok": config["configured"],
        "configured": config["configured"],
        "publicUrl": config["publicUrl"] if config["publicUrl"] else "",
        "envFallback": str(VIDEO_AGENT_PRO_ENV) if VIDEO_AGENT_PRO_ENV.exists() else "",
        "missing": missing,
        "error": "" if config["configured"] else "未配置 Cloudflare R2，公众号复制会回退为 data URL 图片。",
    }


def r2_cache() -> dict:
    if not R2_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(R2_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_r2_cache(cache: dict) -> None:
    R2_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    R2_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def aws_signing_key(secret: str, date_stamp: str, region: str = "auto", service: str = "s3") -> bytes:
    key = ("AWS4" + secret).encode("utf-8")
    for value in (date_stamp, region, service, "aws4_request"):
        key = hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
    return key


def public_r2_url(public_url: str, key: str) -> str:
    return f"{public_url.rstrip('/')}/{quote(key, safe='/~')}"


def canonical_query(params: dict[str, str]) -> str:
    return "&".join(
        f"{quote(str(name), safe='-_.~')}={quote(str(value), safe='-_.~')}"
        for name, value in sorted(params.items())
    )


def presigned_r2_get_url(config: dict, key: str, expires: int = R2_TEMP_IMAGE_TTL_SECONDS) -> str | None:
    parsed = urlparse(config["endpoint"])
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    expires = max(60, min(int(expires), R2_TEMP_IMAGE_TTL_SECONDS))
    date_stamp = time.strftime("%Y%m%d", time.gmtime())
    amz_date = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    credential_scope = f"{date_stamp}/auto/s3/aws4_request"
    canonical_uri = f"/{quote(config['bucket'], safe='')}/{quote(key, safe='/~')}"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{config['accessKeyId']}/{credential_scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    query = canonical_query(params)
    canonical_request = "\n".join(["GET", canonical_uri, query, f"host:{parsed.netloc}\n", "host", "UNSIGNED-PAYLOAD"])
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signature = hmac.new(
        aws_signing_key(config["secretAccessKey"], date_stamp),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{config['endpoint']}{canonical_uri}?{query}&X-Amz-Signature={signature}"


def r2_url_accessible(url: str) -> bool:
    if not url:
        return False
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=20) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def signed_url_uses_current_ttl(url: str) -> bool:
    try:
        params = parse_qs(urlparse(url).query)
    except Exception:
        return False
    return (params.get("X-Amz-Expires") or [""])[0] == str(R2_TEMP_IMAGE_TTL_SECONDS)


def cached_r2_url(cache: dict, rel: str, digest: str, config: dict) -> str | None:
    cached = cache.get(rel)
    if not cached or cached.get("sha256") != digest:
        return None
    if cached.get("mode") == "signed":
        try:
            expires_at = float(cached.get("expiresAtEpoch") or 0)
        except (TypeError, ValueError):
            expires_at = 0
        if (
            cached.get("url")
            and expires_at > time.time() + R2_SIGNED_URL_REFRESH_MARGIN_SECONDS
            and signed_url_uses_current_ttl(cached["url"])
        ):
            return cached["url"]
    if cached.get("mode") == "public" and cached.get("url"):
        return cached["url"]
    if cached.get("url") and "X-Amz-Signature=" not in cached["url"] and r2_url_accessible(cached["url"]):
        cached["mode"] = "public"
        return cached["url"]
    key = cached.get("key")
    if key:
        signed_url = presigned_r2_get_url(config, key)
        if signed_url:
            cached.update({
                "url": signed_url,
                "mode": "signed",
                "expiresAtEpoch": time.time() + R2_TEMP_IMAGE_TTL_SECONDS,
                "signedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            save_r2_cache(cache)
            return signed_url
    return None


def r2_key_for_file(path: Path, body: bytes) -> str:
    rel = path.relative_to(ROOT).as_posix()
    parts = rel.split("/")
    doc_id = parts[2] if len(parts) >= 4 and parts[:2] == ["output", "_feishu_media"] else "misc"
    digest = hashlib.sha256(body).hexdigest()[:16]
    ext = image_extension(mimetypes.guess_type(path.name)[0] or "", body).lstrip(".")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", path.stem).strip("-")[:36] or "image"
    return f"temp/wechat-layout/{time.strftime('%Y/%m/%d')}/{doc_id}/{digest}-{stem}.{ext}"


def upload_file_to_r2(path: Path) -> str | None:
    config = r2_config()
    if not config["configured"] or not path.is_file():
        return None
    body = path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    rel = path.relative_to(ROOT).as_posix()
    cache = r2_cache()
    cached_url = cached_r2_url(cache, rel, digest, config)
    if cached_url:
        return cached_url

    key = r2_key_for_file(path, body)
    parsed = urlparse(config["endpoint"])
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    content_type = mimetypes.guess_type(path.name)[0] or f"image/{image_extension('', body).lstrip('.')}"
    payload_hash = hashlib.sha256(body).hexdigest()
    date_stamp = time.strftime("%Y%m%d", time.gmtime())
    amz_date = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    canonical_uri = f"/{quote(config['bucket'], safe='')}/{quote(key, safe='/~')}"
    headers = {
        "cache-control": f"public, max-age={R2_TEMP_IMAGE_TTL_SECONDS}",
        "content-type": content_type,
        "host": parsed.netloc,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
    canonical_request = "\n".join(["PUT", canonical_uri, "", canonical_headers, signed_headers, payload_hash])
    credential_scope = f"{date_stamp}/auto/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signature = hmac.new(
        aws_signing_key(config["secretAccessKey"], date_stamp),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    auth = (
        "AWS4-HMAC-SHA256 "
        f"Credential={config['accessKeyId']}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    request = urllib.request.Request(
        f"{config['endpoint']}{canonical_uri}",
        data=body,
        headers={**headers, "Authorization": auth},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            if response.status not in (200, 201):
                return None
    except Exception:
        return None
    public_url = public_r2_url(config["publicUrl"], key)
    if r2_url_accessible(public_url):
        url = public_url
        mode = "public"
        expires_at = None
    else:
        url = presigned_r2_get_url(config, key)
        mode = "signed"
        expires_at = time.time() + R2_TEMP_IMAGE_TTL_SECONDS
    if not url:
        return None
    cache[rel] = {
        "sha256": digest,
        "key": key,
        "url": url,
        "publicUrl": public_url,
        "mode": mode,
        "expiresAtEpoch": expires_at,
        "uploadedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_r2_cache(cache)
    return url


def attach_r2_image_sources(html: str) -> str:
    if 'data-local-src="' not in (html or ""):
        return html
    if not r2_config()["configured"]:
        return html

    def repl(match: re.Match) -> str:
        tag = match.group(0)
        local_match = re.search(r'\bdata-local-src="([^"]+)"', tag)
        if not local_match or 'data-r2-src="' in tag:
            return tag
        rel = unescape(local_match.group(1))
        if not rel.startswith("output/_feishu_media/"):
            return tag
        path = (ROOT / rel).resolve()
        if ROOT not in path.parents or not path.is_file():
            return tag
        url = upload_file_to_r2(path)
        if not url:
            return tag
        suffix = "/>" if tag.endswith("/>") else ">"
        base = tag[:-2] if suffix == "/>" else tag[:-1]
        return base + f' data-r2-src="{sanitize_attr_value(url)}"{suffix}'

    return re.sub(r"<img\b[^>]*>", repl, html or "", flags=re.I)


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


def convert_markdown(markdown: str, account: str, preserve_paragraphs: bool = False) -> dict:
    if preserve_paragraphs and "<!-- sentence-split: off -->" not in markdown:
        markdown = f"<!-- sentence-split: off -->\n\n{markdown}"
    parsed = md2wechat.parse_markdown(markdown)
    if not parsed["title"]:
        parsed["title"] = "未命名文章"
    theme = theme_for_account(account)
    full_html = md2wechat.build_full_html(parsed, theme)
    content_html = attach_r2_image_sources(content_from_full_html(full_html))
    full_html = attach_r2_image_sources(full_html)
    return {
        "title": parsed["title"],
        "account": account,
        "contentHtml": content_html,
        "fullHtml": full_html,
    }


SAFE_HTML_TAGS = {
    "a", "b", "blockquote", "br", "code", "del", "div", "em", "figcaption", "figure",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre",
    "s", "section", "span", "strong", "sub", "sup", "table", "tbody", "td", "th",
    "thead", "tr", "u", "ul",
}

SAFE_HTML_ATTRS = {
    "alt", "class", "colspan", "data-local-src", "data-r2-src", "height", "href", "name", "rowspan",
    "src", "style", "target", "title", "width",
}


def feishu_grid_style() -> str:
    return (
        "display: table; width: 100%; table-layout: fixed; "
        "border-spacing: 8px 0; margin: 16px -4px 18px -4px"
    )


def feishu_column_style(width_ratio: str) -> str:
    try:
        width = max(0.15, min(float(width_ratio or "0.5"), 1.0)) * 100
    except ValueError:
        width = 50
    return f"display: table-cell; width: {width:.3f}%; vertical-align: top"


def sanitize_style(style: str) -> str:
    if not style:
        return ""
    chunks = []
    for raw in style.split(";"):
        if ":" not in raw:
            continue
        name, value = raw.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        lowered = value.lower()
        if not name or "expression" in lowered or "javascript:" in lowered:
            continue
        if "url(" in lowered and not re.search(r"url\(['\"]?data:image/", lowered):
            continue
        chunks.append(f"{name}: {value}")
    return "; ".join(chunks)


def sanitize_attr_value(value: str) -> str:
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class RichHtmlSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.grid_depth = 0
        self.column_depth = 0

    def html(self) -> str:
        return "".join(self.parts).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "meta", "link", "title"):
            self.skip_depth += 1
            return
        if not self.skip_depth and tag == "grid":
            self.grid_depth += 1
            self.parts.append(f'<section style="{feishu_grid_style()}">')
            return
        if not self.skip_depth and tag == "column":
            attrs_dict = {name.lower(): value or "" for name, value in attrs}
            self.column_depth += 1
            self.parts.append(f'<section style="{feishu_column_style(attrs_dict.get("width-ratio", ""))}">')
            return
        if self.skip_depth or tag not in SAFE_HTML_TAGS:
            return
        cleaned = []
        for name, value in attrs:
            name = name.lower()
            if name.startswith("on") or name not in SAFE_HTML_ATTRS:
                continue
            value = value or ""
            if name in ("href", "src") and re.match(r"^\s*javascript:", value, flags=re.I):
                continue
            if name == "style":
                value = sanitize_style(value)
                if not value:
                    continue
            cleaned.append(f'{name}="{sanitize_attr_value(value)}"')
        if tag == "img" and self.column_depth:
            cleaned.append('data-feishu-grid-image="1"')
        suffix = (" " + " ".join(cleaned)) if cleaned else ""
        self.parts.append(f"<{tag}{suffix}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in ("br", "hr", "img"):
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "meta", "link", "title"):
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if not self.skip_depth and tag in ("grid", "column"):
            if tag == "grid" and self.grid_depth:
                self.grid_depth -= 1
            if tag == "column" and self.column_depth:
                self.column_depth -= 1
            self.parts.append("</section>")
            return
        if self.skip_depth or tag not in SAFE_HTML_TAGS or tag in ("br", "hr", "img"):
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self.skip_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.skip_depth:
            self.parts.append(f"&#{name};")


def sanitize_rich_html(html: str) -> str:
    parser = RichHtmlSanitizer()
    parser.feed(html or "")
    parser.close()
    return parser.html()


def title_from_rich_html(html: str) -> str:
    for pattern in (r"<title[^>]*>(.*?)</title>", r"<h1[^>]*>(.*?)</h1>", r"<h2[^>]*>(.*?)</h2>"):
        match = re.search(pattern, html or "", flags=re.I | re.S)
        if match:
            title = re.sub(r"<[^>]+>", "", match.group(1))
            title = unescape(re.sub(r"\s+", " ", title)).strip()
            if title:
                return title
    return "未命名文章"


def append_inline_style(tag: str, extra_style: str) -> str:
    match = re.search(r'\sstyle="([^"]*)"', tag, flags=re.I)
    if match:
        style = sanitize_style(f"{match.group(1)}; {extra_style}")
        return tag[: match.start(1)] + sanitize_attr_value(style) + tag[match.end(1) :]
    suffix = "/>" if tag.endswith("/>") else ">"
    base = tag[:-2] if suffix == "/>" else tag[:-1]
    return base + f' style="{sanitize_attr_value(sanitize_style(extra_style))}"{suffix}'


def normalize_rich_html_layout(html: str, theme: dict) -> str:
    paragraph_font_size = theme.get("paragraph_font_size")
    paragraph_margin = theme.get("paragraph_margin")
    h2_font_size = theme.get("h2_font_size")
    image_margin = theme.get("image_margin")
    if not any((paragraph_font_size, paragraph_margin, h2_font_size, image_margin)):
        return html

    def style_p(match: re.Match) -> str:
        extra = []
        if paragraph_font_size:
            extra.append(f"font-size: {paragraph_font_size}")
        extra.append("line-height: 2em")
        if paragraph_margin:
            extra.append(f"margin: {paragraph_margin}")
        return append_inline_style(match.group(0), "; ".join(extra))

    def style_heading(match: re.Match) -> str:
        return append_inline_style(match.group(0), f"font-size: {h2_font_size}") if h2_font_size else match.group(0)

    def style_img(match: re.Match) -> str:
        tag = match.group(0)
        is_grid_image = 'data-feishu-grid-image="1"' in tag
        extra = ["display: inline-block", "max-width: 100%", "height: auto"]
        if is_grid_image:
            extra.extend([
                "width: 100%",
                "border-radius: 8px",
                "box-shadow: rgba(20, 28, 38, 0.08) 0 4px 14px",
            ])
        if image_margin:
            extra.append("margin: 0" if is_grid_image else f"margin: {image_margin}")
        return append_inline_style(tag, "; ".join(extra))

    html = re.sub(r"<p\b[^>]*>", style_p, html, flags=re.I)
    html = re.sub(r"<h[1-3]\b[^>]*>", style_heading, html, flags=re.I)
    html = re.sub(r"<img\b[^>]*>", style_img, html, flags=re.I)
    html = html.replace(' data-feishu-grid-image="1"', "")
    return html


def rich_content_html(raw_html: str, account: str) -> dict:
    theme = theme_for_account(account)
    clean_html = sanitize_rich_html(raw_html)
    if not clean_html:
        raise RuntimeError("请先粘贴富文本正文。")
    clean_html = normalize_rich_html_layout(clean_html, theme)
    paragraph_font_size = theme.get("paragraph_font_size", "15px")
    header = md2wechat.build_header(theme)
    footer = md2wechat.build_footer(theme, theme["author"], [])
    content_html = (
        f'<section style="font-size: {paragraph_font_size}; line-height: 1.8; color: rgb(51, 51, 51); '
        'font-family: -apple-system, BlinkMacSystemFont, Helvetica Neue, PingFang SC, '
        'Hiragino Sans GB, Microsoft YaHei, Arial, sans-serif; '
        'word-break: break-word; margin-bottom: 16px;">'
        f"{header}{clean_html}{footer}</section>"
    )
    content_html = attach_r2_image_sources(content_html)
    return {
        "title": title_from_rich_html(raw_html),
        "account": account,
        "contentHtml": content_html,
        "fullHtml": content_html,
    }


def feishu_doc_id(doc: str) -> str:
    match = re.search(r"/(?:docx|docs|wiki)/([A-Za-z0-9]+)", doc)
    if match:
        return match.group(1)
    parsed = urlparse(doc)
    params = parse_qs(parsed.query)
    for key in ("document_id", "obj_token"):
        value = (params.get(key) or [""])[0]
        if value:
            return value
    return safe_slug(doc)[:32] or "feishu-doc"


def feishu_api_base_url() -> str:
    return os.environ.get("FEISHU_BASE_URL", "https://open.feishu.cn/open-apis").rstrip("/")


def feishu_openapi_config() -> dict:
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    return {
        "appId": app_id,
        "appSecret": app_secret,
        "baseUrl": feishu_api_base_url(),
        "configured": bool(app_id and app_secret),
    }


def feishu_openapi_health() -> dict:
    config = feishu_openapi_config()
    missing = []
    if not config["appId"]:
        missing.append("FEISHU_APP_ID")
    if not config["appSecret"]:
        missing.append("FEISHU_APP_SECRET")
    return {
        "ok": config["configured"],
        "configured": config["configured"],
        "baseUrl": config["baseUrl"],
        "missing": missing,
        "error": "" if config["configured"] else "未配置飞书 OpenAPI 应用凭证。",
    }


def friendly_feishu_openapi_error(message: str, target: str = "") -> str:
    text = str(message or "").strip()
    if re.search(r"Access denied", text, flags=re.I) and re.search(r"docx:document|document", text, flags=re.I):
        return (
            "飞书 OpenAPI 已连通，但当前应用没有读取这个文档的权限。"
            "请在飞书开放平台开通并发布 docx:document:readonly 权限，"
            "并确认该文档已授权给应用或对应用可读。"
        )
    if re.search(r"Access denied", text, flags=re.I) and re.search(r"media|drive|download", text, flags=re.I):
        return (
            "飞书正文已读取，但图片下载权限不足。"
            "请开通并发布 docs:document.media:download 或 drive:drive:readonly 权限。"
        )
    if target == "image" and re.search(r"permission|forbidden|403|Access denied", text, flags=re.I):
        return (
            "飞书图片下载失败：当前应用缺少图片下载权限。"
            "请开通 docs:document.media:download 或 drive:drive:readonly。"
        )
    return text or "飞书 OpenAPI 请求失败。"


def feishu_openapi_request(path: str, method: str = "GET", body: dict | None = None, token: str = "", timeout: int = 30) -> dict:
    url = f"{feishu_api_base_url()}{path}"
    data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(detail)
            detail = payload.get("msg") or payload.get("message") or detail
        except Exception:
            pass
        raise RuntimeError(friendly_feishu_openapi_error(detail)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"飞书 OpenAPI 网络请求失败：{exc.reason}") from exc
    if payload.get("code", 0) not in (0, None):
        message = payload.get("msg") or payload.get("message") or json.dumps(payload, ensure_ascii=False)
        raise RuntimeError(friendly_feishu_openapi_error(message))
    return payload


def get_feishu_tenant_access_token() -> str:
    config = feishu_openapi_config()
    if not config["configured"]:
        raise RuntimeError("请先配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET。")
    data = feishu_openapi_request(
        "/auth/v3/tenant_access_token/internal",
        method="POST",
        body={"app_id": config["appId"], "app_secret": config["appSecret"]},
    )
    token = data.get("tenant_access_token") or (data.get("data") or {}).get("tenant_access_token")
    if not token:
        raise RuntimeError("飞书 OpenAPI 授权失败：没有拿到 tenant_access_token。")
    return token


def image_extension(content_type: str, body: bytes = b"") -> str:
    if body.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return ".webp"
    if body.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    lowered = (content_type or "").lower()
    if "png" in lowered:
        return ".png"
    if "webp" in lowered:
        return ".webp"
    if "gif" in lowered:
        return ".gif"
    return ".jpg"


def download_feishu_media_openapi(token: str, out_dir: Path, tenant_token: str) -> str | None:
    if not token:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_token = re.sub(r"[^A-Za-z0-9_-]+", "", token)[:42] or "image"
    existing = sorted(out_dir.glob(f"{safe_token}.*"))
    if existing:
        return existing[0].relative_to(ROOT).as_posix()
    url = f"{feishu_api_base_url()}/drive/v1/medias/{quote(token)}/download"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {tenant_token}"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            content_type = response.headers.get("Content-Type", "image/jpeg")
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(detail)
            detail = payload.get("msg") or payload.get("message") or detail
        except Exception:
            pass
        raise RuntimeError(friendly_feishu_openapi_error(detail, target="image")) from exc
    ext = image_extension(content_type, body)
    path = out_dir / f"{safe_token}{ext}"
    path.write_bytes(body)
    return path.relative_to(ROOT).as_posix()


def cli_text(result: subprocess.CompletedProcess[str] | None) -> str:
    if result is None:
        return ""
    return "\n".join(part for part in (result.stdout, result.stderr) if part).strip()


def normalize_lark_error(text: str) -> str:
    if "deprecated" in text.lower() and "api-version v2" in text.lower():
        return "当前 lark-cli / lark-doc skill 仍在使用旧版 v1 API。请先运行 lark-cli update，然后重新启动本项目。"
    return text


def parse_json_from_cli(output: str | None) -> dict:
    output = (output or "").strip()
    decoder = json.JSONDecoder()
    last_error = None
    for index, char in enumerate(output):
        if char not in "{[":
            continue
        try:
            data, _ = decoder.raw_decode(output[index:])
            return data
        except json.JSONDecodeError as exc:
            last_error = exc
    if last_error:
        preview = output[:1200].strip()
        raise RuntimeError(f"lark-cli 返回的 JSON 无法解析：{last_error.msg}。输出片段：{preview}") from last_error
    raise RuntimeError(output.strip() or "lark-cli 没有返回 JSON。")


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
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env={**os.environ, "NO_COLOR": "1"},
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
        encoding="utf-8",
        errors="replace",
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


def localize_feishu_html_images(html: str, doc: str) -> str:
    out_dir = ROOT / "output" / "_feishu_media" / feishu_doc_id(doc)

    def repl(match: re.Match) -> str:
        attrs = match.group(1)
        src_match = re.search(r'\bsrc="([^"]+)"', attrs)
        token = src_match.group(1) if src_match else ""
        media_path = download_feishu_media(token, out_dir) if token and not token.startswith(("http://", "https://", "data:")) else None
        if media_path:
            attrs = re.sub(r'\ssrc="[^"]*"', "", attrs)
            attrs = re.sub(r'\sdata-local-src="[^"]*"', "", attrs)
            return f'<img{attrs} data-local-src="{sanitize_attr_value(media_path)}" src=""/>'
        href_match = re.search(r'\bhref="([^"]+)"', attrs)
        if href_match and (not src_match or not src_match.group(1).startswith(("http://", "https://", "data:"))):
            attrs = re.sub(r'\ssrc="[^"]*"', f' src="{sanitize_attr_value(href_match.group(1))}"', attrs)
        return f"<img{attrs}/>"

    return re.sub(r"<img\b([^>]*)/?>", repl, html or "", flags=re.I)


def clean_inline_text(text: str) -> str:
    text = re.sub(r"\s+", " ", unescape(text or "")).strip()
    return text.replace("[", "\\[").replace("]", "\\]") or "飞书图片"


def is_generic_image_label(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    return (
        not value
        or value in {"飞书图片", "图片", "image"}
        or bool(re.search(r"\.(png|jpe?g|webp|gif|bmp|svg)$", value, flags=re.I))
    )


def block_id(block: dict) -> str:
    return str(block.get("block_id") or block.get("blockId") or block.get("id") or "")


def block_children(block: dict) -> list[str]:
    children = block.get("children") or block.get("children_ids") or block.get("childrenIds") or []
    return [str(child) for child in children if child]


def block_type_name(block: dict) -> str:
    for key in (
        "heading1", "heading2", "heading3", "heading4", "heading5", "heading6", "heading7", "heading8", "heading9",
        "bullet", "ordered", "quote", "callout", "code", "image", "table", "file",
        "grid", "column", "grid_column", "gridColumn", "view", "text", "divider", "todo", "quote_container", "quoteContainer",
    ):
        if key in block and block.get(key) is not None:
            if key == "quoteContainer":
                return "quote_container"
            return "grid_column" if key == "gridColumn" else key
    try:
        block_type = int(block.get("block_type") or block.get("blockType") or 0)
    except (TypeError, ValueError):
        block_type = 0
    by_type = {
        1: "page",
        2: "text",
        3: "heading1",
        4: "heading2",
        5: "heading3",
        6: "heading4",
        7: "heading5",
        8: "heading6",
        9: "heading7",
        10: "heading8",
        11: "heading9",
        12: "bullet",
        13: "ordered",
        14: "code",
        15: "quote",
        17: "todo",
        19: "callout",
        22: "divider",
        23: "file",
        24: "grid",
        25: "grid_column",
        27: "image",
        31: "table",
        32: "table_cell",
        33: "view",
        34: "quote_container",
    }
    return by_type.get(block_type, "")


def block_carrier(block: dict) -> dict:
    type_name = block_type_name(block)
    carrier = block.get(type_name) if type_name else None
    if not carrier and type_name == "grid_column":
        carrier = block.get("gridColumn") or block.get("grid_column") or block.get("column")
    return carrier if isinstance(carrier, dict) else block


def markdown_text(value: str) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\n", " ")


def element_to_markdown(element: dict) -> str:
    run = (
        element.get("text_run")
        or element.get("textRun")
        or element.get("mention_user")
        or element.get("mentionUser")
        or element.get("mention_doc")
        or element.get("mentionDoc")
        or element
    )
    content = markdown_text(run.get("content") or run.get("text") or element.get("content") or "")
    if not content:
        return ""
    style = (
        run.get("text_element_style")
        or run.get("textElementStyle")
        or element.get("text_element_style")
        or element.get("textElementStyle")
        or {}
    )
    link = style.get("link") or {}
    href = link.get("url") or link.get("href") or ""
    if href:
        content = f"[{content}]({href})"
    if style.get("bold"):
        content = f"**{content}**"
    if style.get("italic"):
        content = f"*{content}*"
    if style.get("strikethrough"):
        content = f"~~{content}~~"
    if style.get("inline_code") or style.get("inlineCode"):
        content = f"`{content}`"
    return content


def rich_text_from_block(block: dict) -> str:
    carrier = block_carrier(block)
    elements = carrier.get("elements") or carrier.get("text_elements") or carrier.get("textElements") or []
    if elements:
        return "".join(element_to_markdown(element) for element in elements).strip()
    for key in ("content", "text", "title", "name"):
        if isinstance(carrier.get(key), str):
            return markdown_text(carrier.get(key)).strip()
        if isinstance(block.get(key), str):
            return markdown_text(block.get(key)).strip()
    return ""


def rich_text_from_value(value) -> str:
    if isinstance(value, str):
        return markdown_text(value).strip()
    if isinstance(value, list):
        return "".join(element_to_markdown(element) for element in value if isinstance(element, dict)).strip()
    if isinstance(value, dict):
        elements = value.get("elements") or value.get("text_elements") or value.get("textElements") or []
        if elements:
            return "".join(element_to_markdown(element) for element in elements).strip()
        for key in ("content", "text", "title", "name"):
            if isinstance(value.get(key), str):
                return markdown_text(value.get(key)).strip()
    return ""


def plain_text_from_block(block: dict) -> str:
    return re.sub(r"[*_`~]+", "", rich_text_from_block(block)).strip()


def image_token_from_block(block: dict) -> str:
    image = block.get("image") if isinstance(block.get("image"), dict) else block
    return str(
        image.get("token")
        or image.get("file_token")
        or image.get("fileToken")
        or image.get("media_token")
        or image.get("mediaToken")
        or ""
    )


def image_caption_from_block(block: dict) -> str:
    image = block.get("image") if isinstance(block.get("image"), dict) else block
    for key in ("caption", "description", "alt", "title"):
        text = rich_text_from_value(image.get(key))
        if text:
            return text
    text = rich_text_from_block(block)
    return text if text and not re.search(r"\.(png|jpe?g|webp|gif|bmp|svg)$", text, flags=re.I) else ""


def image_markdown(alt: str, src: str | None) -> str:
    caption = "" if is_generic_image_label(alt) else clean_inline_text(alt or "").strip()
    label = caption or "飞书图片"
    if not src:
        return "> 飞书图片暂时无法下载"
    parts = [f"![{label}]({src})"]
    if caption:
        parts.append(caption)
    return join_markdown_parts(*parts)


def build_block_tree(blocks: list[dict]) -> dict:
    by_id = {block_id(block): block for block in blocks if block_id(block)}
    child_ids = {child_id for block in blocks for child_id in block_children(block)}
    page_children = [
        by_id[child_id]
        for block in blocks
        if block_type_name(block) == "page"
        for child_id in block_children(block)
        if child_id in by_id
    ]
    parentless = [
        block for block in blocks
        if block_type_name(block) != "page" and block_id(block) and block_id(block) not in child_ids
    ]
    return {"byId": by_id, "roots": page_children or parentless or blocks, "visited": set()}


def join_markdown_parts(*parts: str) -> str:
    return "\n\n".join(str(part or "").strip() for part in parts if str(part or "").strip())


def child_blocks(block: dict, context: dict) -> list[dict]:
    return [context["byId"][child_id] for child_id in block_children(block) if child_id in context["byId"]]


def children_to_markdown(block: dict, context: dict) -> str:
    return join_markdown_parts(*(block_to_markdown(child, context) for child in child_blocks(block, context)))


def blockquote_markdown(markdown: str) -> str:
    return "\n".join(f"> {line}" for line in str(markdown or "").splitlines() if line.strip()).strip()


def markdown_table_from_rows(rows: list[list[str]]) -> str:
    if not rows or not isinstance(rows, list) or not isinstance(rows[0], list):
        return ""
    normalized = [
        [markdown_text(cell.get("text") if isinstance(cell, dict) else cell).strip().replace("|", "\\|") for cell in row]
        for row in rows
    ]
    head, *body = normalized
    col_count = max(len(head), *(len(row) for row in body)) if body else len(head)
    if not col_count:
        return ""
    head = head + [""] * (col_count - len(head))
    return "\n".join([
        f"| {' | '.join(head)} |",
        f"| {' | '.join('---' for _ in head)} |",
        *(f"| {' | '.join(row + [''] * (col_count - len(row)))} |" for row in body),
    ])


def table_markdown(block: dict) -> str:
    table = block.get("table") or {}
    rows = table.get("rows") or table.get("cells") or []
    return markdown_table_from_rows(rows)


def table_cell_position(cell: dict, fallback_index: int, col_count: int) -> tuple[int, int]:
    carrier = block_carrier(cell)
    row = carrier.get("row_index") or carrier.get("rowIndex") or carrier.get("row") or carrier.get("row_idx")
    col = carrier.get("column_index") or carrier.get("columnIndex") or carrier.get("column") or carrier.get("col") or carrier.get("col_idx")
    try:
        row_index = max(0, int(row))
    except (TypeError, ValueError):
        row_index = fallback_index // max(1, col_count)
    try:
        col_index = max(0, int(col))
    except (TypeError, ValueError):
        col_index = fallback_index % max(1, col_count)
    return row_index, col_index


def table_block_markdown(block: dict, context: dict) -> str:
    markdown = table_markdown(block)
    if markdown:
        return markdown
    cells = child_blocks(block, context)
    if not cells:
        return ""
    carrier = block_carrier(block)
    col_count = (
        carrier.get("column_size")
        or carrier.get("columnSize")
        or carrier.get("columns")
        or carrier.get("col_count")
        or carrier.get("colCount")
    )
    try:
        col_count = max(1, int(col_count))
    except (TypeError, ValueError):
        col_count = max(1, int(len(cells) ** 0.5))
    rows: list[list[str]] = []
    for index, cell in enumerate(cells):
        context["visited"].add(block_id(cell))
        row_index, col_index = table_cell_position(cell, index, col_count)
        while len(rows) <= row_index:
            rows.append([])
        while len(rows[row_index]) <= col_index:
            rows[row_index].append("")
        cell_text = rich_text_from_block(cell) or children_to_markdown(cell, context)
        rows[row_index][col_index] = cell_text
    return markdown_table_from_rows(rows)


def file_markdown(block: dict) -> str:
    file = block.get("file") or {}
    name = str(file.get("name") or file.get("file_name") or file.get("fileName") or "").strip()
    return f"飞书附件：{name}" if name else ""


def ordered_value_from_block(block: dict, context: dict) -> int:
    carrier = block_carrier(block)
    explicit = (
        carrier.get("seq")
        or carrier.get("sequence")
        or carrier.get("index")
        or carrier.get("number")
        or block.get("seq")
    )
    try:
        value = int(explicit)
        if value > 0:
            if context.get("last_block_type") == "ordered" and value != 1:
                value = max(context.get("ordered_next", 1), value)
            context["ordered_next"] = value + 1
            context["last_block_type"] = "ordered"
            return value
    except (TypeError, ValueError):
        pass
    value = context.get("ordered_next", 1) if context.get("last_block_type") == "ordered" else 1
    context["ordered_next"] = value + 1
    context["last_block_type"] = "ordered"
    return value


def mark_non_ordered_block(context: dict, type_name: str) -> None:
    if type_name.startswith("heading") or type_name == "divider":
        context["last_block_type"] = type_name or ""
        context["ordered_next"] = 1


def collect_grid_column_images(block: dict, context: dict) -> list[dict]:
    current_id = block_id(block)
    if current_id:
        context["visited"].add(current_id)
    images = []
    if block_type_name(block) == "image":
        token = image_token_from_block(block)
        path = download_feishu_media_openapi(token, context["outDir"], context["token"]) if token else None
        if path:
            images.append({"src": path, "alt": image_caption_from_block(block) or "飞书图片"})
    for child in child_blocks(block, context):
        images.extend(collect_grid_column_images(child, context))
    return images


def grid_to_markdown(block: dict, context: dict) -> str:
    columns = []
    for child in child_blocks(block, context):
        type_name = block_type_name(child)
        if type_name not in ("column", "grid_column"):
            continue
        carrier = block_carrier(child)
        width = carrier.get("width_ratio") or carrier.get("widthRatio") or carrier.get("width") or "0.5"
        try:
            width_value = float(width)
            width = str(width_value / 100 if width_value > 1 else width_value)
        except (TypeError, ValueError):
            width = "0.5"
        images = collect_grid_column_images(child, context)
        if images:
            columns.append({"width": str(width), "images": images})
    if len(columns) >= 2:
        payload = json.dumps(columns, ensure_ascii=False, separators=(",", ":"))
        rendered_children = children_to_markdown(block, context)
        if re.sub(r"!\[[^\]]*\]\([^)]+\)", "", rendered_children).strip():
            return join_markdown_parts(f"<!-- feishu-grid:{payload} -->", rendered_children)
        return f"<!-- feishu-grid:{payload} -->"
    return children_to_markdown(block, context)


def block_to_markdown(block: dict, context: dict) -> str:
    current_id = block_id(block)
    if current_id and current_id in context["visited"]:
        return ""
    if current_id:
        context["visited"].add(current_id)
    type_name = block_type_name(block)
    text = rich_text_from_block(block)
    if type_name == "grid":
        mark_non_ordered_block(context, type_name)
        return grid_to_markdown(block, context)
    if type_name == "table":
        mark_non_ordered_block(context, type_name)
        return table_block_markdown(block, context)
    children = children_to_markdown(block, context)
    if type_name in ("page", "view", "column", "grid_column"):
        return children
    if type_name.startswith("heading"):
        mark_non_ordered_block(context, type_name)
        level = min(int(type_name.replace("heading", "") or "2"), 4)
        return join_markdown_parts(f"{'#' * level} {text}".strip(), children)
    if type_name == "bullet":
        mark_non_ordered_block(context, type_name)
        return join_markdown_parts(f"- {text}".strip(), children)
    if type_name == "ordered":
        marker = ordered_value_from_block(block, context)
        return join_markdown_parts(f"{marker}. {text}".strip(), children)
    if type_name == "todo":
        mark_non_ordered_block(context, type_name)
        return join_markdown_parts(f"- [ ] {text}".strip(), children)
    if type_name == "quote":
        mark_non_ordered_block(context, type_name)
        return join_markdown_parts(blockquote_markdown(text), children)
    if type_name == "quote_container":
        mark_non_ordered_block(context, type_name)
        return blockquote_markdown(children or text)
    if type_name == "callout":
        mark_non_ordered_block(context, type_name)
        content = children or text
        return f"> {content}" if content else ""
    if type_name == "divider":
        mark_non_ordered_block(context, type_name)
        return "---"
    if type_name == "code":
        mark_non_ordered_block(context, type_name)
        return join_markdown_parts(f"```\n{plain_text_from_block(block)}\n```", children)
    if type_name == "image":
        mark_non_ordered_block(context, type_name)
        token = image_token_from_block(block)
        media_path = download_feishu_media_openapi(token, context["outDir"], context["token"]) if token else None
        if not media_path:
            return join_markdown_parts(f"> 图片下载失败：{token}", children)
        return join_markdown_parts(image_markdown(image_caption_from_block(block), media_path), children)
    if type_name == "file":
        mark_non_ordered_block(context, type_name)
        return join_markdown_parts(file_markdown(block), children)
    mark_non_ordered_block(context, type_name)
    return join_markdown_parts(text, children)


def feishu_blocks_to_markdown(blocks: list[dict], tenant_token: str, doc_id: str) -> str:
    context = {
        **build_block_tree(blocks),
        "token": tenant_token,
        "outDir": ROOT / "output" / "_feishu_media" / doc_id,
        "ordered_next": 1,
        "last_block_type": "",
    }
    parts = [block_to_markdown(block, context) for block in context["roots"]]
    for block in blocks:
        current_id = block_id(block)
        if current_id and current_id in context["visited"]:
            continue
        if block_type_name(block) == "page":
            continue
        parts.append(block_to_markdown(block, context))
    return join_markdown_parts(*parts)


class FeishuHtmlMarkdownParser(HTMLParser):
    def __init__(self, doc: str):
        super().__init__(convert_charrefs=True)
        self.out_dir = ROOT / "output" / "_feishu_media" / feishu_doc_id(doc)
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.link_stack: list[str] = []
        self.ordered_stack: list[int] = []
        self.grid_stack: list[list[dict]] = []
        self.current_grid_column: dict | None = None
        self.quote_stack: list[list[str]] = []
        self.table_stack: list[dict] = []
        self.code_depth = 0
        self.next_ordered_value = 1
        self.last_block_kind = ""

    def target_parts(self) -> list[str]:
        if self.table_stack and self.table_stack[-1].get("current_cell") is not None:
            return self.table_stack[-1]["current_cell"]
        if self.quote_stack:
            return self.quote_stack[-1]
        return self.parts

    def text(self) -> str:
        text = "".join(self.parts)
        text = unescape(text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def append(self, value: str) -> None:
        if value:
            self.target_parts().append(value)

    def ensure_block(self) -> None:
        current = "".join(self.target_parts())
        if current and not current.endswith("\n\n"):
            self.append("\n" if current.endswith("\n") else "\n\n")

    def remove_from_stack(self, tag: str) -> None:
        if tag in self.stack:
            self.stack.remove(tag)

    def append_media(self, src: str, label: str = "飞书视频", media_type: str = "video") -> None:
        src = (src or "").strip()
        if not src:
            return
        item = {"src": src, "alt": clean_inline_text(label), "type": media_type}
        if self.current_grid_column is not None:
            self.current_grid_column["images"].append(item)
            return
        self.ensure_block()
        self.append(f"![{item['alt']}]({src})")
        self.ensure_block()
        self.mark_non_ordered("media")

    def append_column_caption(self, text: str) -> None:
        if not str(text or "").strip():
            return
        caption = clean_inline_text(text)
        if caption and self.current_grid_column is not None:
            self.current_grid_column["caption_parts"].append(caption)

    def mark_non_ordered(self, kind: str) -> None:
        if not self.ordered_stack and (kind == "title" or re.match(r"^h[1-6]$", kind)):
            self.last_block_kind = kind
            self.next_ordered_value = 1

    def finish_table_cell(self) -> None:
        if not self.table_stack:
            return
        table = self.table_stack[-1]
        cell_parts = table.get("current_cell")
        if cell_parts is None:
            return
        cell_text = re.sub(r"\s+", " ", unescape("".join(cell_parts))).strip()
        table.setdefault("current_row", []).append(cell_text)
        table["current_cell"] = None

    def finish_table_row(self) -> None:
        if not self.table_stack:
            return
        table = self.table_stack[-1]
        row = table.get("current_row")
        if row:
            table.setdefault("rows", []).append(row)
        table["current_row"] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        self.stack.append(tag)
        if tag == "table":
            self.ensure_block()
            self.table_stack.append({"rows": [], "current_row": None, "current_cell": None})
            self.mark_non_ordered("table")
            return
        if tag == "tr" and self.table_stack:
            self.table_stack[-1]["current_row"] = []
            return
        if tag in ("td", "th") and self.table_stack:
            self.table_stack[-1]["current_cell"] = []
            return
        if tag == "blockquote":
            self.ensure_block()
            self.quote_stack.append([])
            self.mark_non_ordered("quote")
            return
        if tag == "cite":
            self.ensure_block()
            self.quote_stack.append([])
            self.append("引用：")
            title = attrs_dict.get("title") or attrs_dict.get("name") or ""
            href = attrs_dict.get("href") or attrs_dict.get("url") or ""
            if title:
                self.append(f"[{clean_inline_text(title)}]({href})" if href else clean_inline_text(title))
            return
        if tag in ("video", "source"):
            self.append_media(
                attrs_dict.get("src") or attrs_dict.get("href") or "",
                attrs_dict.get("title") or attrs_dict.get("name") or attrs_dict.get("alt") or "飞书视频",
            )
            return
        if tag == "figcaption":
            self.ensure_block()
            self.mark_non_ordered(tag)
            return
        if tag in ("title", "p", "div"):
            self.ensure_block()
            self.mark_non_ordered(tag)
            if tag == "title":
                self.append("# ")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.ensure_block()
            self.mark_non_ordered(tag)
            level = min(int(tag[1]), 3)
            self.append("#" * level + " ")
        elif tag == "br":
            self.append("\n")
        elif tag in ("strong", "b"):
            self.append("**")
        elif tag in ("em", "i"):
            self.append("*")
        elif tag == "pre":
            self.ensure_block()
            lang = attrs_dict.get("lang") or attrs_dict.get("data-lang") or ""
            self.append(f"```{lang}\n")
        elif tag == "code" and "pre" not in self.stack[:-1]:
            self.code_depth += 1
            self.append("`")
        elif tag == "ol":
            explicit_start = attrs_dict.get("start") or ""
            if explicit_start.isdigit():
                start = int(explicit_start)
            elif self.last_block_kind == "ordered":
                start = self.next_ordered_value
            else:
                start = 1
            self.ordered_stack.append(start)
        elif tag == "grid":
            self.ensure_block()
            self.grid_stack.append([])
        elif tag == "column":
            if self.grid_stack:
                self.current_grid_column = {"width": attrs_dict.get("width-ratio", "0.5"), "images": [], "caption_parts": []}
        elif tag == "li":
            self.ensure_block()
            if self.ordered_stack:
                value = attrs_dict.get("value") or attrs_dict.get("seq") or ""
                if value.isdigit():
                    marker = int(value)
                    if self.last_block_kind == "ordered" and marker != 1:
                        marker = max(self.ordered_stack[-1], marker)
                else:
                    marker = self.ordered_stack[-1]
                self.ordered_stack[-1] = marker + 1
                self.next_ordered_value = marker + 1
                self.append(f"{marker}. ")
            else:
                self.mark_non_ordered("bullet")
                self.append("- ")
        elif tag == "a":
            self.link_stack.append(attrs_dict.get("href", ""))
            self.append("[")
        elif tag == "img":
            src = attrs_dict.get("src", "").strip()
            href = attrs_dict.get("href", "").strip()
            name = attrs_dict.get("caption") or attrs_dict.get("name") or attrs_dict.get("alt") or "飞书图片"
            media_path = download_feishu_media(src, self.out_dir) if src and not src.startswith(("http://", "https://", "data:")) else None
            image_src = media_path or href or src
            if self.current_grid_column is not None:
                self.current_grid_column["images"].append({"src": image_src, "alt": clean_inline_text(name)})
                return
            self.ensure_block()
            self.append(f"![{clean_inline_text(name)}]({image_src})" if image_src else "> 飞书图片暂时无法下载")
            self.ensure_block()
            self.mark_non_ordered("image")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("td", "th"):
            self.finish_table_cell()
            self.remove_from_stack(tag)
            return
        if tag == "tr":
            self.finish_table_row()
            self.remove_from_stack(tag)
            return
        if tag == "table" and self.table_stack:
            table = self.table_stack.pop()
            markdown = markdown_table_from_rows(table.get("rows") or [])
            if markdown:
                self.ensure_block()
                self.append(markdown)
                self.ensure_block()
            self.remove_from_stack(tag)
            return
        if tag in ("blockquote", "cite") and self.quote_stack:
            content = re.sub(r"\n{3,}", "\n\n", "".join(self.quote_stack.pop())).strip()
            markdown = blockquote_markdown(content)
            if markdown:
                self.ensure_block()
                self.append(markdown)
                self.ensure_block()
            self.remove_from_stack(tag)
            return
        if tag in ("title", "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self.ensure_block()
            if tag == "li" and self.ordered_stack:
                self.last_block_kind = "ordered"
        elif tag in ("strong", "b"):
            self.append("**")
        elif tag in ("em", "i"):
            self.append("*")
        elif tag == "pre":
            self.append("\n```\n\n")
        elif tag == "code" and self.code_depth:
            self.code_depth -= 1
            self.append("`")
        elif tag == "a":
            href = self.link_stack.pop() if self.link_stack else ""
            self.append(f"]({href})" if href else "]")
        elif tag == "ol" and self.ordered_stack:
            self.ordered_stack.pop()
        elif tag == "column" and self.current_grid_column is not None:
            caption = clean_inline_text(" ".join(self.current_grid_column.get("caption_parts") or []))
            if caption:
                for image in self.current_grid_column.get("images") or []:
                    if is_generic_image_label(image.get("alt")):
                        image["alt"] = caption
            if self.grid_stack:
                self.grid_stack[-1].append(self.current_grid_column)
            self.current_grid_column = None
        elif tag == "grid" and self.grid_stack:
            columns = self.grid_stack.pop()
            payload = json.dumps(columns, ensure_ascii=False, separators=(",", ":"))
            self.ensure_block()
            self.append(f"<!-- feishu-grid:{payload} -->")
            self.ensure_block()
        self.remove_from_stack(tag)

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self.current_grid_column is not None:
            if "img" not in self.stack and "video" not in self.stack and "source" not in self.stack:
                self.append_column_caption(data)
            return
        if self.code_depth or "pre" in self.stack:
            self.append(data.replace("<br/>", "\n"))
            return
        text = data.replace("\ufeff", "")
        if text.strip():
            self.append(re.sub(r"\s+", " ", text))


def feishu_html_to_markdown(html: str, doc: str) -> str:
    parser = FeishuHtmlMarkdownParser(doc)
    parser.feed(html)
    parser.close()
    return parser.text()


def extract_feishu_markdown(payload: dict, doc: str) -> str:
    markdown = payload.get("markdown") or ""
    document = payload.get("document") or {}
    content = document.get("content") or ""
    title = (payload.get("title") or document.get("title") or "").strip()
    if not markdown and content:
        if re.search(r"</?(title|p|h[1-6]|img|pre|ul|ol|li|table|blockquote)\b", content, flags=re.I):
            markdown = feishu_html_to_markdown(content, doc)
        else:
            markdown = content
    if not markdown:
        raise RuntimeError("飞书返回为空，可能没有文档权限或文档格式暂不支持。")
    if title and not re.search(r"^\s*#\s+", markdown, flags=re.MULTILINE):
        markdown = f"# {title}\n\n{markdown}"
    return replace_feishu_images(markdown, doc)


def extract_feishu_document(payload: dict, doc: str) -> dict:
    document = payload.get("document") or {}
    content = document.get("content") or ""
    markdown = extract_feishu_markdown(payload, doc)
    return {"markdown": markdown, "html": ""}


def fetch_feishu_document_metadata_openapi(doc_id: str, tenant_token: str) -> dict:
    try:
        data = feishu_openapi_request(f"/docx/v1/documents/{quote(doc_id)}", token=tenant_token)
        payload = data.get("data") or {}
        return payload.get("document") or payload
    except Exception:
        return {}


def fetch_feishu_blocks_openapi(doc_id: str, tenant_token: str) -> list[dict]:
    blocks: list[dict] = []
    page_token = ""
    while True:
        query = {"page_size": "500"}
        if page_token:
            query["page_token"] = page_token
        data = feishu_openapi_request(
            f"/docx/v1/documents/{quote(doc_id)}/blocks?{urlencode(query)}",
            token=tenant_token,
            timeout=60,
        )
        payload = data.get("data") or {}
        blocks.extend(payload.get("items") or payload.get("blocks") or [])
        page_token = payload.get("page_token") or payload.get("next_page_token") or ""
        if not page_token or not (payload.get("has_more") or payload.get("hasMore")):
            break
    return blocks


def fetch_feishu_raw_content_openapi(doc_id: str, tenant_token: str) -> str:
    try:
        data = feishu_openapi_request(f"/docx/v1/documents/{quote(doc_id)}/raw_content", token=tenant_token)
    except Exception:
        return ""
    payload = data.get("data") or {}
    return str(payload.get("content") or payload.get("raw_content") or payload.get("rawContent") or "").strip()


def clean_feishu_title(value: str) -> str:
    return re.sub(r"[#*_`]+", "", str(value or "")).strip() or "飞书导入文章"


def has_useful_feishu_content(markdown: str, title: str) -> bool:
    content = re.sub(r"\s+", " ", markdown or "").strip()
    return bool(content and content != clean_feishu_title(title))


def fetch_feishu_document_openapi(doc: str) -> dict:
    doc_id = feishu_doc_id(doc)
    tenant_token = get_feishu_tenant_access_token()
    document = fetch_feishu_document_metadata_openapi(doc_id, tenant_token)
    blocks = fetch_feishu_blocks_openapi(doc_id, tenant_token)
    title = clean_feishu_title(
        document.get("title")
        or document.get("name")
        or next((rich_text_from_block(block) for block in blocks if rich_text_from_block(block)), "")
    )
    markdown = feishu_blocks_to_markdown(blocks, tenant_token, doc_id).strip()
    if not markdown:
        markdown = fetch_feishu_raw_content_openapi(doc_id, tenant_token)
    if not has_useful_feishu_content(markdown, title):
        raise RuntimeError("没有从飞书文档读取到有效正文。请确认应用有文档读取权限，并且该文档已授权给应用或设置为公开可读。")
    if title and not re.search(r"^\s*#\s+", markdown, flags=re.MULTILINE):
        markdown = f"# {title}\n\n{markdown}"
    return {"markdown": markdown.strip(), "html": "", "source": "feishuOpenApi", "documentId": doc_id}


def fetch_feishu_markdown(doc: str) -> str:
    return fetch_feishu_document(doc)["markdown"]


def fetch_feishu_document_lark_cli(doc: str) -> dict:
    health = lark_cli_health()
    if not health.get("ok"):
        raise RuntimeError(health.get("error") or "飞书导入环境未就绪，请先检查 lark-cli。")
    commands = [
        ["docs", "+fetch", "--api-version", "v2", "--doc", doc.strip(), "--format", "json"],
        ["docs", "+fetch", "--api-version", "v2", "--doc", doc.strip(), "--doc-format", "markdown", "--format", "json"],
        ["docs", "+fetch", "--doc", doc.strip(), "--format", "json"],
    ]
    errors: list[str] = []
    result = None
    for command in commands:
        result = run_lark_cli(command, timeout=90)
        if result.returncode == 0:
            break
        errors.append(normalize_lark_error(cli_text(result) or "lark-cli docs +fetch 执行失败。"))
    if result is None:
        raise RuntimeError("lark-cli docs +fetch 未执行。")
    if result.returncode != 0:
        detail = "\n\n".join(error.strip() for error in errors if error.strip())
        raise RuntimeError(detail.strip())
    data = parse_json_from_cli(cli_text(result))
    if not data.get("ok"):
        raise RuntimeError(json.dumps(data.get("error", data), ensure_ascii=False))
    result_payload = extract_feishu_document(data["data"], doc)
    result_payload["source"] = "larkCli"
    return result_payload


def fetch_feishu_document(doc: str) -> dict:
    if not doc.strip():
        raise RuntimeError("请提供飞书文档链接。")
    errors: list[str] = []
    if feishu_openapi_config()["configured"]:
        try:
            return fetch_feishu_document_openapi(doc.strip())
        except Exception as exc:
            errors.append(f"OpenAPI 导入失败：{exc}")
    try:
        return fetch_feishu_document_lark_cli(doc.strip())
    except Exception as exc:
        errors.append(f"lark-cli 导入失败：{exc}")
    raise RuntimeError("\n\n".join(errors) or "飞书导入失败。")


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
            self.send_json(
                200,
                {
                    "ok": True,
                    "larkCli": lark_cli_health(),
                    "feishuOpenApi": feishu_openapi_health(),
                    "r2": r2_health(),
                },
            )
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
                    self.send_json(200, fetch_feishu_document(doc))
                except Exception as exc:
                    self.send_json(
                        500,
                        {
                            "error": str(exc),
                            "diagnostics": {
                                "larkCli": lark_cli_health(),
                                "feishuOpenApi": feishu_openapi_health(),
                            },
                        },
                    )
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

            account = payload.get("account", md2wechat.DEFAULT_ACCOUNT)
            html = payload.get("html", "")
            if html.strip():
                self.send_json(200, rich_content_html(html, account))
                return
            markdown = payload.get("markdown", "")
            if not markdown.strip():
                self.send_json(400, {"error": "请先粘贴 Markdown 正文"})
                return
            preserve_paragraphs = bool(payload.get("preserveParagraphs"))
            self.send_json(200, convert_markdown(markdown, account, preserve_paragraphs=preserve_paragraphs))
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
