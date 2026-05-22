#!/usr/bin/env python3
"""
Markdown → 微信公众号 HTML 转换器

用法：
    python3 scripts/md2wechat.py "output/文章标题.md"
    python3 scripts/md2wechat.py "output/文章标题.md" --account 羊羊AI视频
    python3 scripts/md2wechat.py "output/文章标题.md" --open  # 转换后自动在浏览器中打开

输出：
    output/文章标题.html  （可直接复制粘贴到公众号编辑器）

排版规范（从西羊石AI视频公众号真实文章逆向工程）：
    - 正文：15px, line-height 2em, margin-bottom 16px, color #1f2329
    - 小标题：16.5px, bold, 左侧紫色竖线 4px solid #7112​97
    - 加粗：**黑色加粗**，***紫色加粗***（整句重要内容）
    - 句号换行：每个句号/问号/叹号后自动换行独立成段（碎片化阅读优化）
    - 图片占位：带灰色提示框
    - 分割线：细线 + 间距
    - 顶部：品牌动图
    - 底部：编辑署名 + 一键三连 + 推荐阅读
"""

import re
import sys
import os
import argparse
import webbrowser
from datetime import datetime
from pathlib import Path

# ── 账号配色方案 ──────────────────────────────
ACCOUNT_THEMES = {
    "西羊石AI视频": {
        "primary": "rgb(113, 18, 151)",     # 紫色
        "primary_light": "rgb(166, 91, 203)",
        "primary_bg": "rgb(246, 243, 246)",
        "accent": "rgb(214, 168, 65)",       # 金色
        "author": "小石学长",
    },
    "羊羊AI视频": {
        "primary": "rgb(0, 122, 255)",       # 蓝色
        "primary_light": "rgb(34, 153, 255)",
        "primary_bg": "rgb(235, 246, 255)",
        "accent": "rgb(0, 209, 255)",
        "author": "羊羊",
        "paragraph_font_size": "17px",
        "paragraph_margin": "16px 0 0",
        "preserve_paragraphs_default": True,
        "h2_font_size": "22px",
        "image_margin": "16px 0 0",
    },
    "西堂AI创业": {
        "primary": "rgb(113, 18, 151)",
        "primary_light": "rgb(166, 91, 203)",
        "primary_bg": "rgb(246, 243, 246)",
        "accent": "rgb(214, 168, 65)",
        "author": "西堂",
    },
    "西羊石AI短剧": {
        "primary": "rgb(113, 18, 151)",
        "primary_light": "rgb(166, 91, 203)",
        "primary_bg": "rgb(246, 243, 246)",
        "accent": "rgb(214, 168, 65)",
        "author": "小石学长",
    },
    "小石的AI智能体工坊": {
        "primary": "rgb(210, 80, 30)",       # 橙红（匹配小石学长头像风格）
        "primary_light": "rgb(230, 120, 60)",
        "primary_bg": "rgb(255, 245, 238)",
        "accent": "rgb(214, 168, 65)",
        "author": "小石学长",
    },
}

DEFAULT_ACCOUNT = "西羊石AI视频"

# ── 顶部动图 URL ─────────────────────────────
HEADER_GIF = "https://mmbiz.qpic.cn/sz_mmbiz_gif/0jbau7U0eUuqo6uRgZB9bq4Vq1XIhvt9TibTuJLdden8sGpqmm9ic4mH9KKbdrtj2naR2h5BLjgjnDsiabFtCjFcQ/640?wx_fmt=gif&from=appmsg"

DEFAULT_RECOMMENDED = [
    ("字节Seedance2.0 更新，AI 变天了！", "https://mp.weixin.qq.com/s?__biz=Mzk0NDU5MTk3OA==&mid=2247537958&idx=1&sn=a8743ce2e171ba2b88a94fca7e875c9f&scene=21#wechat_redirect"),
    ("第一批不找工作的年轻人，靠AI半年赚几十万", "https://mp.weixin.qq.com/s?__biz=Mzk0NDU5MTk3OA==&mid=2247529966&idx=1&sn=8526b93cfe8a4421977c0d03b9aa0496&scene=21#wechat_redirect"),
    ("AI漫剧这么火，却没人讲透实操？这篇万字复盘，手把手带你复刻", "https://mp.weixin.qq.com/s?__biz=Mzk0NDU5MTk3OA==&mid=2247537425&idx=1&sn=a05b3df8c953490cced7038cc8c3bb2a&scene=21#wechat_redirect"),
    ("2026复盘：00后第一批创业者已经秃了", "https://mp.weixin.qq.com/s?__biz=Mzk0NDU5MTk3OA==&mid=2247537512&idx=1&sn=4743a422adb3a547f50c66c24244b55a&scene=21#wechat_redirect"),
]


def parse_markdown(md_text: str) -> dict:
    """解析 Markdown 文章，提取标题、正文、推荐阅读"""
    lines = md_text.strip().split('\n')

    title = ""
    body_lines = []
    recommended = []
    author_line = ""
    in_recommended = False
    in_code_block = False
    preserve_paragraphs = False

    for line in lines:
        # 跟踪代码块状态
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            body_lines.append(line)
            continue

        if in_code_block:
            body_lines.append(line)
            continue

        # 提取 h1 标题
        if line.startswith('# ') and not title:
            title = line[2:].strip()
            continue

        if line.strip() == '<!-- sentence-split: off -->':
            preserve_paragraphs = True
            continue

        # 提取推荐阅读
        if '**推荐阅读' in line or '推荐阅读' in line.replace('*', ''):
            in_recommended = True
            continue

        if in_recommended and line.startswith('- '):
            recommended.append(line[2:].strip())
            continue

        # 提取作者行
        if '作者' in line and '编辑' in line and '|' in line:
            author_line = line.strip()
            continue

        # 跳过固定尾部
        if '一键三连' in line or '觉得有收获' in line:
            continue

        # 跳过孤立的 ---
        if line.strip() == '---':
            body_lines.append('---')
            continue

        if not in_recommended:
            body_lines.append(line)

    return {
        "title": title,
        "body": '\n'.join(body_lines).strip(),
        "recommended": recommended,
        "author_line": author_line,
        "preserve_paragraphs": preserve_paragraphs,
    }


def md_to_html_body(md_body: str, theme: dict, preserve_paragraphs: bool = False) -> str:
    """将 Markdown 正文转为微信格式 HTML"""
    primary = theme["primary"]
    preserve_paragraphs = preserve_paragraphs or bool(theme.get("preserve_paragraphs_default"))
    lines = md_body.split('\n')
    html_parts = []
    in_code_block = False
    code_lines = []
    code_lang = ""

    i = 0
    while i < len(lines):
        line = lines[i]

        # ── 代码块 ────────────────────────────
        if line.strip().startswith('```'):
            if not in_code_block:
                in_code_block = True
                code_lines = []
                code_lang = line.strip()[3:].strip()
                i += 1
                continue
            else:
                in_code_block = False
                code_html = '<br/>'.join(escape_html(line) or '&nbsp;' for line in code_lines)
                raw_label = (code_lang or '').strip()
                generic_labels = {'', 'text', 'plain', 'plaintext', 'plain text'}
                code_label = '' if raw_label.lower() in generic_labels else escape_html(raw_label)
                label_html = (
                    f'<span style="display: inline-block; margin-left: 10px; font-size: 13px; '
                    f'color: rgb(190, 198, 210); font-family: Menlo, Monaco, Consolas, monospace; '
                    f'line-height: 34px; letter-spacing: 0; vertical-align: top;">{code_label}</span>'
                    if code_label
                    else ''
                )
                html_parts.append(
                    f'<section style="margin: 18px 0 22px 0; border-radius: 8px; overflow: hidden; '
                    f'background-color: rgb(36, 42, 51); border: 1px solid rgb(47, 55, 66); '
                    f'box-shadow: rgba(20, 28, 38, 0.18) 0 8px 22px;">'
                    f'<section style="height: 34px; padding: 0 16px; background-color: rgb(36, 42, 51); '
                    f'box-sizing: border-box; font-size: 0; line-height: 34px; white-space: nowrap;">'
                    f'<span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; '
                    f'background-color: rgb(255, 95, 87); margin-right: 8px; vertical-align: middle;"></span>'
                    f'<span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; '
                    f'background-color: rgb(255, 189, 46); margin-right: 8px; vertical-align: middle;"></span>'
                    f'<span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; '
                    f'background-color: rgb(40, 201, 64); vertical-align: middle;"></span>'
                    f'{label_html}'
                    f'</section>'
                    f'<section style="padding: 14px 18px 18px 18px; background-color: rgb(36, 42, 51); '
                    f'font-size: 13px; line-height: 1.9; color: rgb(238, 242, 247); '
                    f'font-family: Menlo, Monaco, Consolas, monospace; word-break: break-word;">'
                    f'{code_html}</section></section>'
                )
                i += 1
                continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        stripped = line.strip()

        # ── 空行 ─────────────────────────────
        if not stripped:
            i += 1
            continue

        # ── HTML 注释（如 <!-- digest: ... -->）────
        if stripped.startswith('<!--') and stripped.endswith('-->'):
            i += 1
            continue

        # ── 分割线（正文中不渲染，只保留 footer 模板中的）────
        if stripped == '---':
            i += 1
            continue

        # ── h1 一级标题（文章标题之外的正文大章节）────────
        if stripped.startswith('# '):
            heading_text = format_inline(stripped[2:].strip(), theme)
            primary_bg = theme.get('primary_bg', 'rgb(243, 240, 250)')
            accent = theme.get('accent', 'rgb(214, 168, 65)')
            html_parts.append(
                f'<section style="margin: 38px 0 20px 0; text-align: center;">'
                f'<section style="display: inline-block; padding: 4px 0 7px 0; '
                f'border-bottom: 3px solid {accent};">'
                f'<section style="display: inline-block; padding: 7px 16px; '
                f'background-color: {primary_bg}; border-radius: 4px; '
                f'font-weight: bold; font-size: 18px; color: rgb(31, 35, 41); '
                f'line-height: 1.45; font-family: PingFang SC, system-ui, -apple-system, sans-serif;">'
                f'{heading_text}</section></section></section>'
            )
            i += 1
            continue

        # ── h2 标题 ───────────────────────────
        if stripped.startswith('## '):
            heading_text = format_inline(stripped[3:].strip(), theme)
            h2_font_size = theme.get("h2_font_size", "16.5px")
            html_parts.append(
                f'<h3 style="margin: 35px 0 16px 0; padding: 0 0 0 8px; '
                f'font-weight: bold; font-size: {h2_font_size}; color: rgb(63, 63, 63); '
                f'border-left: 4px solid {primary}; line-height: 1.2; '
                f'font-family: PingFang SC, system-ui, -apple-system, sans-serif;">'
                f'{heading_text}</h3>'
            )
            i += 1
            continue

        # ── h3 标题（作为加粗段落处理）────────
        if stripped.startswith('### '):
            heading_text = format_inline(stripped[4:].strip(), theme)
            html_parts.append(make_paragraph(f'<strong>{heading_text}</strong>', preserve_paragraphs=preserve_paragraphs))
            i += 1
            continue

        # ── 提示框 > [!NOTE/TIP/WARNING] ────────
        admonition_match = re.match(r'^>\s*\[!(NOTE|TIP|WARNING|IMPORTANT)\]\s*(.*)', stripped)
        if admonition_match:
            ad_type = admonition_match.group(1)
            first_line = admonition_match.group(2).strip()
            # 收集多行提示框内容
            ad_lines = []
            if first_line:
                ad_lines.append(first_line)
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if nxt.startswith('> ') and not re.match(r'^>\s*\[!', nxt):
                    ad_lines.append(nxt[2:].strip())
                    i += 1
                elif nxt == '>':
                    ad_lines.append('')
                    i += 1
                else:
                    break
            ad_content = '<br/>'.join(format_inline(l, theme) for l in ad_lines if l)
            # 不同类型使用不同配色
            if ad_type in ('NOTE', 'TIP'):
                border_color = primary
                bg_color = theme.get('primary_bg', 'rgb(243, 240, 250)')
                label = '提示' if ad_type == 'TIP' else '说明'
            elif ad_type == 'WARNING':
                border_color = 'rgb(214, 168, 65)'
                bg_color = 'rgb(255, 251, 235)'
                label = '注意'
            else:  # IMPORTANT
                border_color = 'rgb(200, 50, 50)'
                bg_color = 'rgb(255, 245, 245)'
                label = '重要'
            html_parts.append(
                f'<section style="margin: 16px 0; padding: 12px 16px; '
                f'border-left: 3px solid {border_color}; '
                f'background-color: {bg_color}; border-radius: 4px; '
                f'font-size: 14px; line-height: 1.8; color: rgb(63, 63, 63);">'
                f'<span style="font-weight: bold; color: {border_color}; '
                f'font-size: 13px;">{label}</span><br/>'
                f'{ad_content}</section>'
            )
            continue

        # ── 引用块 ────────────────────────────
        if stripped.startswith('> '):
            quote_text = format_inline(stripped[2:].strip(), theme)
            html_parts.append(
                f'<blockquote style="margin: 16px 0; padding: 12px 16px; '
                f'border-left: 3px solid rgb(219, 219, 219); '
                f'color: rgb(136, 136, 136); font-size: 14px; line-height: 1.8;">'
                f'{quote_text}</blockquote>'
            )
            i += 1
            continue

        # ── Markdown 表格 ────────────────────
        if '|' in stripped and i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            if re.match(r'^\|[\s\-:|]+\|$', next_stripped):
                # 收集表格所有行
                table_rows = [stripped]
                table_rows.append(next_stripped)  # 分隔行
                j = i + 2
                while j < len(lines) and '|' in lines[j].strip():
                    table_rows.append(lines[j].strip())
                    j += 1
                # 解析
                def parse_row(row_str):
                    cells = [c.strip() for c in row_str.strip('|').split('|')]
                    return cells
                def parse_align(cell: str) -> str:
                    value = cell.strip()
                    if value.startswith(':') and value.endswith(':'):
                        return 'center'
                    if value.endswith(':'):
                        return 'right'
                    return 'left'
                header_cells = parse_row(table_rows[0])
                align_cells = parse_row(table_rows[1])
                alignments = [parse_align(cell) for cell in align_cells]
                data_rows = [parse_row(r) for r in table_rows[2:]]
                primary_bg = theme.get('primary_bg', 'rgb(243, 240, 250)')
                col_count = max(len(header_cells), len(alignments), *(len(row) for row in data_rows)) if data_rows else max(len(header_cells), len(alignments))
                header_cells = header_cells + [''] * (col_count - len(header_cells))
                alignments = alignments + ['left'] * (col_count - len(alignments))
                # 渲染 HTML table
                table_html = (
                    '<section style="margin: 16px 0; width: 100%; overflow-x: auto;">'
                    '<table style="width: 100%; table-layout: fixed; border-collapse: collapse; '
                    'font-size: 14px; line-height: 1.6;">'
                )
                # 表头
                table_html += '<tr>'
                for ci, cell in enumerate(header_cells):
                    cell_html = format_inline(cell, theme)
                    align = alignments[ci]
                    table_html += (
                        f'<th style="background-color: {primary_bg}; '
                        f'border: 1px solid rgb(224, 224, 224); padding: 9px 10px; '
                        f'font-weight: bold; text-align: {align}; color: rgb(51, 51, 51); '
                        f'word-break: break-word; overflow-wrap: anywhere; vertical-align: middle;">'
                        f'{cell_html}</th>'
                    )
                table_html += '</tr>'
                # 数据行
                for ri, row in enumerate(data_rows):
                    row = row + [''] * (col_count - len(row))
                    row_bg = 'rgb(250, 250, 250)' if ri % 2 == 1 else 'rgb(255, 255, 255)'
                    table_html += f'<tr style="background-color: {row_bg};">'
                    for ci, cell in enumerate(row):
                        cell_html = format_inline(cell, theme)
                        align = alignments[ci]
                        table_html += (
                            f'<td style="border: 1px solid rgb(224, 224, 224); '
                            f'padding: 9px 10px; color: rgb(31, 35, 41); text-align: {align}; '
                            f'word-break: break-word; overflow-wrap: anywhere; vertical-align: middle;">'
                            f'{cell_html}</td>'
                        )
                    table_html += '</tr>'
                table_html += '</table></section>'
                html_parts.append(table_html)
                i = j
                continue

        # ── 图片占位 [图片] ───────────────────
        if stripped == '[图片]':
            image_margin = theme.get("image_margin", "0 0 16px 0")
            html_parts.append(
                f'<section style="margin: {image_margin}; text-align: center;">'
                '<img data-placeholder="true" src="" style="display: inline-block; '
                'max-width: 100%; height: auto; border-radius: 12px; '
                'box-shadow: rgb(240, 240, 240) 0px 0px 0.5em 0px; '
                'background-color: transparent;"/>'
                '</section>'
            )
            i += 1
            continue

        # ── 连续列表 ──────────────────────────
        ordered_match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
        bullet_match = re.match(r'^[-*]\s+(.+)$', stripped)
        if ordered_match or bullet_match:
            is_ordered = bool(ordered_match)
            items = []
            j = i
            while j < len(lines):
                current = lines[j].strip()
                if is_ordered:
                    match = re.match(r'^\d+\.\s+(.+)$', current)
                else:
                    match = re.match(r'^[-*]\s+(.+)$', current)
                if not match:
                    break
                marker = re.match(r'^(\d+)\.\s+', current).group(1) if is_ordered else '•'
                items.append((marker, match.group(1).strip()))
                j += 1

            item_html = []
            item_font_size = theme.get("paragraph_font_size", "15px")
            for marker, item in items:
                marker_text = f'{marker}.' if is_ordered else marker
                item_html.append(
                    f'<section style="display: table; width: 100%; margin: 0 0 10px 0; '
                    f'font-size: {item_font_size}; line-height: 2em; color: rgb(31, 35, 41); '
                    f'font-family: PingFang SC, system-ui, -apple-system, BlinkMacSystemFont, '
                    f'Helvetica Neue, Arial, sans-serif;">'
                    f'<span style="display: table-cell; width: 30px; padding-right: 6px; '
                    f'font-weight: bold; color: {primary}; vertical-align: top;">{marker_text}</span>'
                    f'<span style="display: table-cell; vertical-align: top;">{format_inline(item, theme)}</span>'
                    f'</section>'
                )
            html_parts.append(
                f'<section style="margin: 12px 0 16px 0; padding: 0;">'
                f'{"".join(item_html)}</section>'
            )
            i = j
            continue

        # ── Markdown 图片 ![alt](path) ────────
        image_match = re.match(r'!\[(.*?)\]\((.+?)\)$', stripped)
        if image_match:
            alt_text = escape_html(image_match.group(1).strip() or 'image')
            image_src = image_match.group(2).strip()
            if is_video_src(image_src):
                html_parts.append(make_video_placeholder(alt_text, image_src, theme))
                i += 1
                continue
            caption = ""
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if is_image_caption(next_line):
                    caption = next_line
            image_style = (
                'display: inline-block; max-width: 100%; height: auto; '
                'border-radius: 12px; box-shadow: rgb(240, 240, 240) 0px 0px 0.5em 0px; '
                'background-color: transparent;'
            )
            image_margin = theme.get("image_margin", "0 0 16px 0")
            caption_html = ""
            if caption:
                caption_html = (
                    f'<p style="margin: 6px 0 16px 0; text-align: center; '
                    f'font-size: 13px; line-height: 1.55; color: rgb(115, 119, 125); '
                    f'font-family: PingFang SC, system-ui, -apple-system, sans-serif;">'
                    f'{format_inline(caption, theme)}</p>'
                )
            if re.match(r'^(https?://|data:image/)', image_src):
                html_parts.append(
                    f'<section style="margin: {image_margin}; text-align: center;">'
                    f'<img src="{escape_attr(image_src)}" style="{image_style}" alt="{alt_text}"/>'
                    f'{caption_html}'
                    '</section>'
                )
            else:
                html_parts.append(
                    f'<section style="margin: {image_margin}; text-align: center;">'
                    f'<img data-local-src="{escape_attr(image_src)}" src="" style="{image_style}" alt="{alt_text}"/>'
                    f'{caption_html}'
                    '</section>'
                )
            i += 2 if caption else 1
            continue

        # ── 视频链接占位 ─────────────────────
        if is_video_src(stripped):
            html_parts.append(make_video_placeholder("视频", stripped, theme))
            i += 1
            continue

        # ── 有序/无序列表项 ───────────────────
        if stripped.startswith('- ') or stripped.startswith('* '):
            html_parts.append(make_paragraph(f'· {stripped[2:].strip()}', indent=True, theme=theme, preserve_paragraphs=preserve_paragraphs))
            i += 1
            continue

        m = re.match(r'^(\d+)\.\s+(.+)', stripped)
        if m:
            num, text = m.group(1), m.group(2)
            html_parts.append(make_paragraph(f'{num}. {text}', indent=True, theme=theme, preserve_paragraphs=preserve_paragraphs))
            i += 1
            continue

        # ── 普通段落 ──────────────────────────
        html_parts.append(make_paragraph(stripped, theme=theme, preserve_paragraphs=preserve_paragraphs))
        i += 1

    return ''.join(html_parts)


def is_image_caption(text: str) -> bool:
    """判断图片后紧跟的一行是否像图注。"""
    if not text:
        return False
    if text.startswith(('#', '>', '-', '*', '|', '![', '<!--', '```')):
        return False
    if re.match(r'^\d+\.\s+', text):
        return False
    if len(text) > 36:
        return False
    if any(mark in text for mark in ['。', '！', '？', '；', ';']):
        return False
    return True


def is_video_src(src: str) -> bool:
    return bool(re.search(r'\.(mp4|mov|m4v|webm)(\?.*)?$', src.strip(), re.I))


def make_video_placeholder(label: str, src: str, theme: dict) -> str:
    primary = theme["primary"] if theme else "rgb(113, 18, 151)"
    src_html = escape_html(src)
    label_html = escape_html(label or "视频")
    return (
        f'<section style="margin: 18px 0; padding: 18px 16px; '
        f'border: 1px dashed {primary}; border-radius: 8px; '
        f'background-color: rgb(250, 248, 252); text-align: center;">'
        f'<p style="margin: 0 0 6px 0; font-size: 15px; font-weight: bold; '
        f'line-height: 1.7; color: {primary};">视频占位：{label_html}</p>'
        f'<p style="margin: 0; font-size: 12px; line-height: 1.6; color: rgb(115, 119, 125);">'
        f'粘贴到公众号后台后，请在这里插入/上传对应视频。<br/>来源：{src_html}</p>'
        f'</section>'
    )


def make_paragraph(content: str, indent: bool = False, theme: dict = None, preserve_paragraphs: bool = False) -> str:
    """生成标准微信正文段落 HTML

    公众号碎片化阅读优化：每个句号/问号/叹号后自动换行，每句话独立成段。
    当传入 theme 时，先分句再对每句应用 format_inline，避免 span 标签跨段落断裂。
    """
    padding = "padding-left: 1.5em; " if indent else ""
    paragraph_font_size = theme.get("paragraph_font_size", "15px") if theme else "15px"
    paragraph_margin = theme.get("paragraph_margin", "0 0 16px") if theme else "0 0 16px"
    p_style = (
        f'font-size: {paragraph_font_size}; line-height: 2em; '
        f'font-family: PingFang SC, system-ui, -apple-system, BlinkMacSystemFont, '
        f'Helvetica Neue, Hiragino Sans GB, Microsoft YaHei UI, Microsoft YaHei, '
        f'Arial, sans-serif; color: rgb(31, 35, 41); '
        f'margin: {paragraph_margin}; word-break: break-all; {padding}'
        f'min-height: 20px;'
    )

    # 先分句（在原始 Markdown 文本上拆分，不含 HTML 标签）
    sentences = [content] if preserve_paragraphs else split_sentences(content)

    # 对每句单独应用 format_inline（如果传入了 theme），确保 span 不跨段落
    if theme:
        sentences = [format_inline(s, theme) for s in sentences]

    if len(sentences) <= 1:
        s = sentences[0] if sentences else content
        if theme:
            s = format_inline(s, theme) if not sentences else s
        return f'<p style="{p_style}">{s}</p>'

    return ''.join(
        f'<p style="{p_style}">{s.strip()}</p>'
        for s in sentences if s.strip()
    )


def split_sentences(text: str) -> list:
    """按中文句号/问号/叹号拆分文本，保留标点在前一句末尾。

    智能处理：不拆分引号内、代码标签内的句号。
    """
    # 先保护 HTML 标签和引号内容，避免内部句号被拆分
    protected = {}
    counter = [0]

    def protect(match):
        key = f'\x00PROT{counter[0]}\x00'
        protected[key] = match.group(0)
        counter[0] += 1
        return key

    # 保护 Markdown/飞书加粗标记内容，避免内部句号被拆分
    safe = re.sub(r'\*\*\*(.+?)\*\*\*', protect, text)
    safe = re.sub(r'\*\*(.+?)\*\*', protect, safe)
    safe = re.sub(r'__(.+?)__', protect, safe)
    safe = re.sub(r'<(?:strong|b)\b[^>]*>.*?</(?:strong|b)>', protect, safe, flags=re.I | re.S)
    safe = re.sub(
        r'<span\b(?=[^>]*font-weight\s*:\s*(?:bold|[6-9]00))[^>]*>.*?</span>',
        protect,
        safe,
        flags=re.I | re.S,
    )
    # 保护 HTML 标签
    safe = re.sub(r'<[^>]+>', protect, safe)
    # 保护中文引号内容
    safe = re.sub(r'[""「」].*?[""「」]', protect, safe)

    # 按句末标点拆分
    parts = re.split(r'([。！？])', safe)

    # 重新组合：标点跟前一句
    sentences = []
    i = 0
    while i < len(parts):
        s = parts[i]
        if i + 1 < len(parts) and re.match(r'^[。！？]$', parts[i + 1]):
            s += parts[i + 1]
            i += 2
        else:
            i += 1
        if s.strip():
            sentences.append(s)

    # 还原被保护的内容
    result = []
    for s in sentences:
        for key, val in protected.items():
            s = s.replace(key, val)
        result.append(s)

    return result


def normalize_feishu_bold_html(text: str) -> str:
    """将飞书/富文本常见粗体 HTML 归一成当前微信行内样式。"""
    text = re.sub(
        r'<(?:strong|b)\b[^>]*>(.*?)</(?:strong|b)>',
        r'<span style="font-weight: bold;">\1</span>',
        text,
        flags=re.I | re.S,
    )
    text = re.sub(
        r'<span\b(?=[^>]*font-weight\s*:\s*(?:bold|[6-9]00))[^>]*>(.*?)</span>',
        r'<span style="font-weight: bold;">\1</span>',
        text,
        flags=re.I | re.S,
    )
    return text


def protect_inline_code(text: str) -> tuple[str, dict]:
    """临时保护行内代码，避免代码里的星号/下划线被当成强调。"""
    protected = {}

    def protect(match):
        key = f'\x00CODE{len(protected)}\x00'
        protected[key] = (
            '<code style="font-size: 13px; padding: 2px 6px; '
            'background-color: rgb(246, 246, 246); border-radius: 3px; '
            'font-family: Menlo, Monaco, Consolas, monospace; '
            f'color: rgb(51, 51, 51);">{match.group(1)}</code>'
        )
        return key

    return re.sub(r'`([^`]+)`', protect, text), protected


def restore_protected(text: str, protected: dict) -> str:
    for key, val in protected.items():
        text = text.replace(key, val)
    return text


def format_inline(text: str, theme: dict = None) -> str:
    """处理行内 Markdown/飞书格式：紫色加粗、黑色加粗、行内代码

    格式约定：
    - ***整句重要强调*** → 紫色加粗（用于整句非常重要的内容）
    - **普通强调** / __普通强调__ / 飞书粗体 HTML → 黑色加粗
    """
    primary = theme["primary"] if theme else "rgb(113, 18, 151)"
    text, protected_code = protect_inline_code(text)
    text = normalize_feishu_bold_html(text)

    # 紫色加粗 ***text***（三星号，必须在双星号之前处理）
    text = re.sub(
        r'\*\*\*(.+?)\*\*\*',
        rf'<span style="font-weight: bold; color: {primary};">\1</span>',
        text
    )
    # 黑色加粗 **text**
    text = re.sub(
        r'\*\*(.+?)\*\*',
        r'<span style="font-weight: bold;">\1</span>',
        text
    )
    # 黑色加粗 __text__（飞书/部分 Markdown 导出会用下划线）
    text = re.sub(
        r'__(.+?)__',
        r'<span style="font-weight: bold;">\1</span>',
        text
    )
    return restore_protected(text, protected_code)


def escape_html(text: str) -> str:
    """转义 HTML 特殊字符"""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def escape_attr(text: str) -> str:
    """转义 HTML 属性中的特殊字符"""
    return (
        text.replace('&', '&amp;')
        .replace('"', '&quot;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )


def build_header(theme: dict) -> str:
    """生成固定顶部"""
    custom = theme.get("custom_header_html")
    if custom:
        return custom
    return (
        f'<section style="margin-bottom: 16px;">'
        f'<img src="{HEADER_GIF}" '
        f'style="max-width: 100%; display: inline-block; border-radius: 9px; '
        f'background-color: transparent; height: auto !important;"/>'
        f'</section>'
    )


def build_footer(theme: dict, author: str, recommended: list) -> str:
    """生成不含二维码引流图的公众号尾部。"""
    custom = theme.get("custom_footer_html")
    if custom:
        return custom
    primary_light = theme["primary_light"]
    primary_bg = theme.get("primary_bg", "rgb(246, 243, 246)")
    items = normalize_recommended(recommended) or DEFAULT_RECOMMENDED
    links_html = ''.join(
        f'<section style="margin: 0 0 10px 0; padding: 0; line-height: 1.55;">'
        f'<a class="normal_text_link" target="_blank" href="{escape_attr(url)}" '
        f'style="font-size: 13px; color: rgb(31, 35, 41); text-decoration: none;">'
        f'{escape_html(title)}</a></section>'
        for title, url in items[:4]
    )
    footer = (
        f'<section style="text-align: center; margin-top: 28px;">'
        f'<span style="font-size: 12px; color: rgb(0, 0, 0); font-weight: bold;">作者 | {author}</span>'
        f'</section>'
        f'<section style="line-height: 1em; margin-top: 16px; text-align: center;">'
        f'<span style="font-size: 12px; color: rgb(0, 0, 0); font-weight: bold;">编辑 | {author}</span>'
        f'</section>'
        f'<hr style="border-style: solid; border-width: 1px 0 0; '
        f'border-color: rgba(0,0,0,0.1); margin: 24px 0;"/>'
        f'<section style="text-align: center; margin: 0 0 20px 0;">'
        f'<span style="font-size: 15px; color: {primary_light}; font-weight: bold;">觉得有收获可以一键三连，转发给需要的小伙伴</span>'
        f'</section>'
        f'<section style="margin: 24px 0 12px 0; text-align: center;">'
        f'<span style="display: inline-block; padding: 0 6px 6px 6px; '
        f'border-bottom: 8px solid {primary_bg}; font-size: 15px; '
        f'line-height: 1; color: {primary_light}; font-weight: bold;">推荐阅读</span>'
        f'</section>'
        f'<section style="margin: 0 0 8px 0;">{links_html}</section>'
    )
    return footer


def normalize_recommended(recommended: list) -> list[tuple[str, str]]:
    items = []
    for raw in recommended:
        text = raw.strip()
        match = re.match(r'\[(.+?)\]\((https?://.+?)\)', text)
        if match:
            items.append((match.group(1).strip(), match.group(2).strip()))
        elif text:
            items.append((text, ""))
    return items


def build_full_html(parsed: dict, theme: dict) -> str:
    """组装完整的微信文章 HTML"""
    author = theme["author"]

    body_html = md_to_html_body(
        parsed["body"],
        theme,
        preserve_paragraphs=parsed.get("preserve_paragraphs", False),
    )
    header = build_header(theme)
    footer = build_footer(theme, author, parsed["recommended"])

    # 外层容器使用微信编辑器的标准样式
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape_html(parsed['title'])}</title>
<style>
  body {{
    max-width: 780px;
    margin: 0 auto;
    padding: 20px;
    background: #fff;
    font-family: "PingFang SC", system-ui, -apple-system, BlinkMacSystemFont,
                 "Helvetica Neue", "Hiragino Sans GB", "Microsoft YaHei",
                 Arial, sans-serif;
  }}
  /* 预览用，实际粘贴到微信时只用 #content 里的内容 */
  .preview-title {{
    font-size: 22px;
    font-weight: bold;
    color: #1f2329;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid #e7e7eb;
  }}
  .copy-hint {{
    background: #fffbe6;
    border: 1px solid #ffe58f;
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 20px;
    font-size: 14px;
    color: #8c6d1f;
  }}
</style>
</head>
<body>
<div class="copy-hint">
  复制提示：选中下方 #content 区域的所有内容，Ctrl+C 复制后直接粘贴到微信公众号编辑器。
</div>
<div class="preview-title">{escape_html(parsed['title'])}</div>
<div id="content">
<section style="font-size: 17px; line-height: 1.8; color: rgb(51, 51, 51);
  font-family: -apple-system, BlinkMacSystemFont, Helvetica Neue, PingFang SC,
  Hiragino Sans GB, Microsoft YaHei, Arial, sans-serif;
  word-break: break-word; margin-bottom: 16px;">
{header}{body_html}{footer}
</section>
</div>
</body>
</html>"""


def detect_account(md_text: str) -> str:
    """从文章末尾的作者行自动检测账号"""
    if '羊羊' in md_text and '小石' not in md_text.split('作者')[0] if '作者' in md_text else False:
        return "羊羊AI视频"
    if '西堂' in md_text and '作者 | 西堂' in md_text:
        return "西堂AI创业"
    return DEFAULT_ACCOUNT


def main():
    parser = argparse.ArgumentParser(description='Markdown → 微信公众号 HTML')
    parser.add_argument('input', help='Markdown 文件路径')
    parser.add_argument('--account', '-a', default=None,
                        help='目标公众号名称（自动检测或指定）')
    parser.add_argument('--open', '-o', action='store_true',
                        help='转换后在浏览器中打开预览')

    args = parser.parse_args()

    # 读取 Markdown
    input_path = Path(args.input)
    if not input_path.exists():
        # 尝试在 output/ 目录下找
        alt_path = Path('output') / input_path.name
        if alt_path.exists():
            input_path = alt_path
        else:
            print(f"错误：找不到文件 {args.input}")
            sys.exit(1)

    md_text = input_path.read_text(encoding='utf-8')

    # 解析
    parsed = parse_markdown(md_text)

    if not parsed['title']:
        print("警告：未找到 h1 标题，使用文件名作为标题")
        parsed['title'] = input_path.stem

    # 确定账号和主题
    account = args.account or detect_account(md_text)
    theme = ACCOUNT_THEMES.get(account, ACCOUNT_THEMES[DEFAULT_ACCOUNT])
    print(f"目标账号：{account}（作者：{theme['author']}）")

    # 转换
    html = build_full_html(parsed, theme)

    # 输出到对应的 html/ 目录（支持账号维度目录结构）
    # 如果输入路径是 output/{account}/md/xxx.md，输出到 output/{account}/html/
    # 如果是旧结构 output/md/xxx.md，输出到 output/html/
    if input_path.parent.name == 'md' and input_path.parent.parent.name != 'output':
        # 账号维度结构：output/{account}/md/ → output/{account}/html/
        html_dir = input_path.parent.parent / 'html'
    else:
        script_root = Path(__file__).parent.parent
        html_dir = script_root / 'output' / 'html'
    html_dir.mkdir(parents=True, exist_ok=True)

    date_prefix = datetime.now().strftime("%y%m%d")
    stem = input_path.stem
    # 避免重复加日期前缀
    if not re.match(r'^\d{6}-', stem):
        html_name = f"{date_prefix}-{stem}.html"
    else:
        html_name = f"{stem}.html"

    output_path = html_dir / html_name
    output_path.write_text(html, encoding='utf-8')
    print(f"已生成：{output_path}")

    if args.open:
        webbrowser.open(f'file://{output_path.absolute()}')
        print("已在浏览器中打开预览")


if __name__ == '__main__':
    main()
