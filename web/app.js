const accountMeta = {
  "西羊石AI视频": {
    note: "主号模板：真诚、有经验感、创业者视角。适合热点实测、教程、行业观察和创业故事。",
  },
  "羊羊AI视频": {
    note: "羊羊模板：蓝色科技感、直接清爽、实操导向。适合训练营、团队共用和 AI 视频教程。",
  },
  "西羊石AI短剧": {
    note: "短剧号模板：专业、实操、案例驱动。强调角色资产、制作流程和可复用 SOP。",
  },
  "小石的AI智能体工坊": {
    note: "工坊模板：技术极客、程序员精确感，理性中带温度。适合 AI Agent、编程和技术创业思考。",
  },
};

const el = {
  shell: document.querySelector(".shell"),
  controls: document.querySelector("#controls"),
  sidebarToggle: document.querySelector("#sidebarToggle"),
  account: document.querySelector("#account"),
  navCompose: document.querySelector("#navCompose"),
  navSettings: document.querySelector("#navSettings"),
  composeArea: document.querySelector("#composeArea"),
  settingsBox: document.querySelector("#settingsBox"),
  headerTemplate: document.querySelector("#headerTemplate"),
  footerTemplate: document.querySelector("#footerTemplate"),
  saveSettings: document.querySelector("#saveSettings"),
  resetSettings: document.querySelector("#resetSettings"),
  accountNote: document.querySelector("#accountNote"),
  activeAccount: document.querySelector("#activeAccount"),
  articleTitle: document.querySelector("#articleTitle"),
  markdownMode: document.querySelector("#markdownMode"),
  richMode: document.querySelector("#richMode"),
  markdownPane: document.querySelector("#markdownPane"),
  richPane: document.querySelector("#richPane"),
  feishuUrl: document.querySelector("#feishuUrl"),
  importFeishu: document.querySelector("#importFeishu"),
  importStatus: document.querySelector("#importStatus"),
  markdown: document.querySelector("#markdown"),
  richPaste: document.querySelector("#richPaste"),
  preview: document.querySelector("#preview"),
  status: document.querySelector("#status"),
  convert: document.querySelector("#convert"),
  copyRich: document.querySelector("#copyRich"),
  copyZhihu: document.querySelector("#copyZhihu"),
  copyHtml: document.querySelector("#copyHtml"),
  copyMarkdown: document.querySelector("#copyMarkdown"),
  exportCard: document.querySelector("#exportCard"),
  cardPreview: document.querySelector("#cardPreview"),
  loadSample: document.querySelector("#loadSample"),
  coverTitle: document.querySelector("#coverTitle"),
  coverText: document.querySelector("#coverText"),
  visualHammer: document.querySelector("#visualHammer"),
  makeCoverPrompt: document.querySelector("#makeCoverPrompt"),
  generateCover: document.querySelector("#generateCover"),
  coverPrompt: document.querySelector("#coverPrompt"),
  coverPreview: document.querySelector("#coverPreview"),
};

let lastContentHtml = "";
let inputMode = "markdown";
let lastMarkdown = "";
let lastRichHtml = "";
let coverTextTouched = false;
let workbenchSettings = { accounts: {} };
let activeSection = "compose";
let sidebarCollapsed = window.localStorage.getItem("wechatLayoutSidebarCollapsed") === "true";
const richPlaceholderText = el.richPaste.textContent.trim();

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function escapeMarkdown(text) {
  return text.replace(/\[/g, "\\[").replace(/\]/g, "\\]");
}

function normalizeText(text) {
  return (text || "").replace(/\u00a0/g, " ").replace(/[ \t]+\n/g, "\n").trim();
}

function textOf(node) {
  return normalizeText(node.textContent || "");
}

function isBoldNode(node) {
  if (node.nodeType !== Node.ELEMENT_NODE) return false;
  const tag = node.tagName.toLowerCase();
  if (tag === "strong" || tag === "b") return true;
  const fontWeight = String(node.style?.fontWeight || "").toLowerCase();
  if (fontWeight === "bold" || Number(fontWeight) >= 600) return true;
  const style = String(node.getAttribute("style") || "").toLowerCase();
  return /font-weight\s*:\s*(bold|[6-9]00)/.test(style);
}

function inlineToMarkdown(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    return (node.textContent || "").replace(/\u00a0/g, " ");
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return "";
  }

  const tag = node.tagName.toLowerCase();
  if (tag === "br") {
    return "\n";
  }
  if (tag === "img") {
    const src = node.getAttribute("src") || node.getAttribute("data-src") || node.getAttribute("data-original") || "";
    if (!src) return "";
    return `![${escapeMarkdown(node.getAttribute("alt") || "图片")}](${src})`;
  }

  const content = Array.from(node.childNodes).map(inlineToMarkdown).join("");
  if (!content.trim()) return "";
  if (tag === "code") return `\`${content}\``;
  if (isBoldNode(node)) {
    const leading = content.match(/^\s*/)?.[0] || "";
    const trailing = content.match(/\s*$/)?.[0] || "";
    return `${leading}**${content.trim()}**${trailing}`;
  }
  return content;
}

function tableToMarkdown(table) {
  const rows = Array.from(table.querySelectorAll("tr"))
    .map((row) => Array.from(row.querySelectorAll("th,td")).map((cell) => inlineToMarkdown(cell).trim().replace(/\|/g, "\\|")))
    .filter((row) => row.length);
  if (!rows.length) {
    return "";
  }
  const width = Math.max(...rows.map((row) => row.length));
  const normalized = rows.map((row) => [...row, ...Array(width - row.length).fill("")]);
  const header = normalized[0];
  const body = normalized.slice(1);
  const firstDomRow = table.querySelector("tr");
  const firstCells = firstDomRow ? Array.from(firstDomRow.querySelectorAll("th,td")) : [];
  const alignments = Array.from({ length: width }, (_, index) => {
    const cell = firstCells[index];
    const styleAlign = (cell?.style?.textAlign || "").toLowerCase();
    const attrAlign = (cell?.getAttribute("align") || "").toLowerCase();
    const align = styleAlign || attrAlign;
    if (align === "center" || align === "-webkit-center") return ":---:";
    if (align === "right" || align === "end") return "---:";
    return "---";
  });
  return [
    `| ${header.join(" | ")} |`,
    `| ${alignments.join(" | ")} |`,
    ...body.map((row) => `| ${row.join(" | ")} |`),
  ].join("\n");
}

function blockToMarkdown(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    return textOf(node);
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return "";
  }

  const tag = node.tagName.toLowerCase();
  if (tag === "br") {
    return "";
  }
  if (tag === "img") {
    const src = node.getAttribute("src") || node.getAttribute("data-src") || node.getAttribute("data-original") || "";
    if (!src) {
      return "";
    }
    return `![${escapeMarkdown(node.getAttribute("alt") || "图片")}](${src})`;
  }
  if (/^h[1-6]$/.test(tag)) {
    const level = Math.min(Number(tag.slice(1)), 3);
    return `${"#".repeat(level)} ${inlineToMarkdown(node).trim()}`;
  }
  if (tag === "table") {
    return tableToMarkdown(node);
  }
  if (tag === "pre") {
    return `\`\`\`\n${node.textContent.trim()}\n\`\`\``;
  }
  if (tag === "blockquote") {
    return inlineToMarkdown(node).trim()
      .split("\n")
      .map((line) => `> ${line.trim()}`)
      .join("\n");
  }
  if (tag === "ul" || tag === "ol") {
    const start = Number(node.getAttribute("start") || "1") || 1;
    return Array.from(node.children)
      .filter((child) => child.tagName && child.tagName.toLowerCase() === "li")
      .map((child, index) => {
        const explicitValue = Number(child.getAttribute("value"));
        const value = Number.isFinite(explicitValue) && explicitValue > 0 ? explicitValue : start + index;
        const marker = tag === "ol" ? `${value}.` : "-";
        return `${marker} ${inlineToMarkdown(child).trim()}`;
      })
      .join("\n");
  }

  if (isBoldNode(node)) {
    return inlineToMarkdown(node).trim();
  }

  if (isInlineElement(node)) {
    return inlineToMarkdown(node).trim();
  }

  if (node.childNodes && node.childNodes.length) {
    if (!hasBlockChildren(node)) {
      return inlineToMarkdown(node).trim();
    }
    const parts = Array.from(node.childNodes)
      .map(blockToMarkdown)
      .map((part) => part.trim())
      .filter(Boolean);
    if (parts.length) {
      return parts.join("\n\n");
    }
  }

  const text = textOf(node);
  return text || "";
}

function isInlineElement(node) {
  if (node.nodeType !== Node.ELEMENT_NODE) return false;
  return new Set([
    "a",
    "abbr",
    "b",
    "code",
    "em",
    "i",
    "label",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "u",
  ]).has(node.tagName.toLowerCase());
}

function isBlockElement(node) {
  if (node.nodeType !== Node.ELEMENT_NODE) return false;
  return new Set([
    "article",
    "aside",
    "blockquote",
    "div",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
  ]).has(node.tagName.toLowerCase());
}

function hasBlockChildren(node) {
  return Array.from(node.childNodes).some(isBlockElement);
}

function mergeTextParts(parts) {
  const merged = [];
  for (const part of parts) {
    const prev = merged[merged.length - 1] || "";
    const beforePrev = merged[merged.length - 2] || "";
    const partIsImage = part.startsWith("![");
    const prevIsImage = prev.startsWith("![");
    const beforePrevIsImage = beforePrev.startsWith("![");
    const prevIsHeading = /^#{1,3}\s/.test(prev);
    const partIsBlock = partIsImage || /^#{1,3}\s/.test(part) || part.startsWith("| ") || part.startsWith("```") || part.startsWith("> ");
    const prevLooksLikeCaption = beforePrevIsImage && prev.length <= 36 && !/[。！？；;]/.test(prev);
    if (merged.length && !partIsBlock && !prevIsImage && !prevIsHeading && !prevLooksLikeCaption && prev.length + part.length < 120) {
      merged[merged.length - 1] = `${prev}${prev.endsWith("，") || prev.endsWith("。") ? "" : " "}${part}`;
    } else {
      merged.push(part);
    }
  }
  return merged;
}

function richHtmlToMarkdown(container) {
  const blocks = [];
  let inlineBuffer = [];

  const flushInlineBuffer = () => {
    const markdown = inlineBuffer.map(inlineToMarkdown).join("").trim();
    if (markdown) blocks.push(markdown);
    inlineBuffer = [];
  };

  for (const node of Array.from(container.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE || isInlineElement(node)) {
      inlineBuffer.push(node);
      continue;
    }
    flushInlineBuffer();
    const markdown = blockToMarkdown(node).trim();
    if (markdown) blocks.push(markdown);
  }
  flushInlineBuffer();

  return blocks.join("\n\n");
}

function currentMarkdown() {
  if (inputMode === "rich") {
    return richHtmlToMarkdown(el.richPaste).trim();
  }
  return lastMarkdown || el.markdown.value.trim();
}

function currentRichHtml() {
  if (inputMode !== "rich") {
    return "";
  }
  const text = el.richPaste.textContent.trim();
  if (!text || text === richPlaceholderText) {
    return "";
  }
  return el.richPaste.innerHTML.trim();
}

function setMode(mode) {
  inputMode = mode;
  const isMarkdown = mode === "markdown";
  el.markdownMode.classList.toggle("active", isMarkdown);
  el.richMode.classList.toggle("active", !isMarkdown);
  el.markdownPane.classList.toggle("active", isMarkdown);
  el.richPane.classList.toggle("active", !isMarkdown);
  setStatus(isMarkdown ? "粘贴 Markdown 后生成公众号排版。" : "从飞书复制正文，粘贴到富文本区后生成公众号排版。");
}

function renderPreview(html) {
  el.preview.innerHTML = html;
  el.preview.querySelectorAll("img[data-local-src]").forEach((image) => {
    const localPath = image.getAttribute("data-local-src");
    image.setAttribute("src", `/api/file?path=${encodeURIComponent(localPath)}`);
    image.dataset.previewSrc = "local";
  });
  el.preview.querySelectorAll('img[src=""], img:not([src])').forEach((image) => {
    if (!image.dataset.localSrc) {
      image.style.minHeight = "96px";
      image.style.background = "rgb(248, 248, 248)";
      image.style.border = "1px dashed rgb(220, 220, 220)";
    }
  });
}

function setStatus(message, isError = false) {
  el.status.textContent = message;
  el.status.style.color = isError ? "#a83232" : "#6e6a63";
}

function setImportStatus(message = "", state = "idle") {
  el.importStatus.textContent = message;
  el.importStatus.dataset.state = state;
}

function importErrorMessage(data, fallback = "飞书导入失败。") {
  const details = data?.diagnostics?.larkCli;
  if (details?.error) {
    return `${fallback}${details.error}`;
  }
  return data?.error || fallback;
}

function syncAccountNote() {
  const account = el.account.value;
  el.accountNote.textContent = accountMeta[account].note;
  el.activeAccount.textContent = account;
  syncThemeAccent(account);
  loadAccountTemplateFields();
}

function syncThemeAccent(account) {
  const accent = account === "羊羊AI视频" ? "#007aff" : account === "小石的AI智能体工坊" ? "#d2501e" : "#711297";
  document.documentElement.style.setProperty("--accent", accent);
}

function loadAccountTemplateFields() {
  const account = el.account.value;
  const settings = workbenchSettings.accounts?.[account] || {};
  el.headerTemplate.value = settings.header || "";
  el.footerTemplate.value = settings.footer || "";
}

function applySidebarState() {
  el.shell.classList.toggle("sidebar-collapsed", sidebarCollapsed);
  el.sidebarToggle.setAttribute("aria-expanded", String(!sidebarCollapsed));
  el.sidebarToggle.setAttribute("aria-label", sidebarCollapsed ? "展开侧边栏" : "收起侧边栏");
  el.sidebarToggle.title = sidebarCollapsed ? "展开侧边栏" : "收起侧边栏";
}

function setSidebarCollapsed(collapsed) {
  sidebarCollapsed = collapsed;
  window.localStorage.setItem("wechatLayoutSidebarCollapsed", String(sidebarCollapsed));
  applySidebarState();
}

async function loadSettings() {
  try {
    const response = await fetch("/api/settings");
    if (response.ok) {
      workbenchSettings = await response.json();
    }
  } catch (error) {
    workbenchSettings = { accounts: {} };
  }
  loadAccountTemplateFields();
}

async function checkImportEnvironment() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    if (!response.ok || !data.larkCli?.ok) {
      setImportStatus(`飞书导入环境未就绪：${data.larkCli?.error || "请检查 lark-cli 登录态。"}`, "error");
    }
  } catch (error) {
    setImportStatus("无法检查飞书导入环境：本地服务可能未启动。", "error");
  }
}

function setSection(section, expandSidebar = true) {
  activeSection = section === "settings" ? "settings" : "compose";
  if (expandSidebar && sidebarCollapsed) {
    setSidebarCollapsed(false);
  }
  const showSettings = activeSection === "settings";
  el.controls.dataset.section = activeSection;
  el.settingsBox.hidden = !showSettings;
  el.composeArea.hidden = showSettings;
  el.navCompose.classList.toggle("active", !showSettings);
  el.navSettings.classList.toggle("active", showSettings);
  setStatus(showSettings ? "这里可以按账号设置固定开头和结尾模板。" : "已回到排版工作台。");
}

async function saveAccountSettings() {
  const payload = {
    account: el.account.value,
    header: el.headerTemplate.value.trim(),
    footer: el.footerTemplate.value.trim(),
  };
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.error || "模板保存失败。", true);
    return;
  }
  workbenchSettings = data;
  setStatus("当前账号首尾模板已保存。重新生成预览后生效。");
  if (currentMarkdown()) {
    await convert();
  }
}

async function resetAccountSettings() {
  el.headerTemplate.value = "";
  el.footerTemplate.value = "";
  await saveAccountSettings();
}

async function convert() {
  const html = currentRichHtml();
  const markdown = inputMode === "rich" ? richHtmlToMarkdown(el.richPaste).trim() : el.markdown.value.trim();
  if (!markdown && !html) {
    setStatus(inputMode === "rich" ? "请先粘贴飞书富文本正文。" : "请先粘贴 Markdown 正文。", true);
    return;
  }

  setStatus("正在生成公众号排版...");
  lastMarkdown = markdown;
  lastRichHtml = html;
  const response = await fetch("/api/convert", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ markdown, html, account: el.account.value, preserveParagraphs: inputMode === "rich" }),
  });
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.error || "转换失败。", true);
    return;
  }

  lastContentHtml = data.contentHtml;
  el.articleTitle.textContent = data.title;
  if (!el.coverTitle.value.trim()) {
    el.coverTitle.value = data.title;
  }
  renderPreview(data.contentHtml);
  setStatus("已生成。发公众号请点右上角“复制到公众号”，Markdown/HTML 只是备用。");
}

async function loadSample() {
  setMode("markdown");
  setStatus("正在载入示例文章...");
  const response = await fetch(`/api/sample?account=${encodeURIComponent(el.account.value)}`);
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.error || "示例文章载入失败。", true);
    return;
  }
  el.markdown.value = data.markdown;
  await convert();
}

async function importFeishuDoc() {
  const docUrl = el.feishuUrl.value.trim();
  if (!docUrl) {
    setStatus("请先粘贴飞书 docx 链接。", true);
    return;
  }
  setMode("markdown");
  setStatus("正在从飞书导入文档...");
  setImportStatus("正在连接飞书并下载正文和图片，文档大时可能需要几十秒。", "loading");
  el.importFeishu.disabled = true;
  el.importFeishu.textContent = "导入中...";
  try {
    const response = await fetch("/api/import-feishu", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc: docUrl }),
    });
    const data = await response.json();
    if (!response.ok) {
      const message = importErrorMessage(data, "飞书导入失败：");
      setStatus(message, true);
      setImportStatus(message, "error");
      return;
    }
    el.markdown.value = data.markdown.includes("<!-- sentence-split: off -->")
      ? data.markdown
      : `<!-- sentence-split: off -->\n\n${data.markdown}`;
    if (data.html) {
      setMode("rich");
      el.richPaste.innerHTML = data.html;
      lastRichHtml = data.html;
    }
    await convert();
    setStatus("飞书文档已导入，图片已尽量下载成本地文件。现在可以直接复制公众号富文本。");
    setImportStatus("导入完成，正文已写入 Markdown 区并生成预览。", "success");
  } catch (error) {
    setStatus("飞书导入请求失败。请确认本地服务还在运行。", true);
    setImportStatus("请求失败：本地服务可能断开，或飞书接口超时。", "error");
  } finally {
    el.importFeishu.disabled = false;
    el.importFeishu.textContent = "导入";
  }
}

async function imageToDataUrl(image) {
  const src = image.getAttribute("src") || "";
  if (!src || src.startsWith("data:image/")) {
    return src;
  }
  try {
    const response = await fetch(src);
    if (!response.ok) {
      return src;
    }
    const blob = await response.blob();
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  } catch (error) {
    return src;
  }
}

function absoluteUrl(src) {
  try {
    return new URL(src, window.location.href).href;
  } catch (error) {
    return src;
  }
}

function platformImageSrc(image) {
  const src = image.getAttribute("src") || "";
  if (!src || src.startsWith("data:image/")) {
    return src;
  }
  return absoluteUrl(src);
}

function isPublicImageSrc(src) {
  return /^https?:\/\//i.test(src) && !/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])/i.test(src);
}

function zhihuImagePlaceholder(image, index) {
  const localPath = image.getAttribute("data-local-src") || "";
  const alt = image.getAttribute("alt") || "图片";
  const fileName = localPath.split("/").pop() || alt;
  const label = `【图片 ${String(index + 1).padStart(2, "0")}：${fileName}】`;
  const hint = localPath ? `本地路径：${localPath}` : "请在知乎中用图片按钮重新上传这张图";
  const wrapper = document.createElement("p");
  wrapper.setAttribute(
    "style",
    "margin: 16px 0; padding: 10px 12px; border-left: 3px solid rgb(180, 180, 180); color: rgb(95, 99, 104); font-size: 14px; line-height: 1.7; background-color: rgb(248, 248, 248);"
  );
  wrapper.textContent = `${label} ${hint}`;
  return wrapper;
}

async function buildClipboardHtml({ imageMode = "data-url" } = {}) {
  const clone = el.preview.cloneNode(true);
  clone.removeAttribute("id");
  clone.removeAttribute("contenteditable");
  clone.querySelectorAll("img").forEach((image) => {
    image.removeAttribute("data-preview-src");
  });
  const sourceImages = Array.from(el.preview.querySelectorAll("img"));
  const cloneImages = Array.from(clone.querySelectorAll("img"));
  for (let i = 0; i < sourceImages.length; i += 1) {
    if (imageMode === "zhihu") {
      const publicSrc = platformImageSrc(sourceImages[i]);
      if (isPublicImageSrc(publicSrc)) {
        cloneImages[i].setAttribute("src", publicSrc);
      } else {
        cloneImages[i].replaceWith(zhihuImagePlaceholder(sourceImages[i], i));
      }
      continue;
    }
    const imageSrc = imageMode === "platform-url" ? platformImageSrc(sourceImages[i]) : await imageToDataUrl(sourceImages[i]);
    if (imageSrc) {
      cloneImages[i].setAttribute("src", imageSrc);
    }
  }
  return clone.innerHTML.trim();
}

async function writeHtmlToClipboard(html) {
  const copySource = document.createElement("div");
  copySource.style.position = "fixed";
  copySource.style.left = "-9999px";
  copySource.innerHTML = html;
  document.body.appendChild(copySource);
  const blobHtml = new Blob([html], { type: "text/html" });
  const blobText = new Blob([copySource.innerText], { type: "text/plain" });
  await navigator.clipboard.write([
    new ClipboardItem({
      "text/html": blobHtml,
      "text/plain": blobText,
    }),
  ]);
  copySource.remove();
}

function selectAndCopyHtml(html) {
  const copySource = document.createElement("div");
  copySource.style.position = "fixed";
  copySource.style.left = "-9999px";
  copySource.innerHTML = html;
  document.body.appendChild(copySource);
  const range = document.createRange();
  range.selectNodeContents(copySource);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  const copied = document.execCommand("copy");
  selection.removeAllRanges();
  copySource.remove();
  return copied;
}

async function copyRichText() {
  if (!lastContentHtml.trim() && !el.preview.innerHTML.trim()) {
    setStatus("还没有可复制的排版内容。", true);
    return;
  }

  try {
    const html = await buildClipboardHtml({ imageMode: "data-url" });
    await writeHtmlToClipboard(html);
    setStatus("公众号富文本已复制。现在直接粘贴到微信公众号编辑器，不需要再进壹伴转 HTML。");
  } catch (error) {
    const range = document.createRange();
    range.selectNodeContents(el.preview);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    document.execCommand("copy");
    setStatus("已选中并复制预览区；如果浏览器拦截，请按 Cmd+C 再粘贴到公众号。");
  }
}

async function copyZhihuRichText() {
  const richHtml = currentRichHtml();
  if (richHtml) {
    try {
      await writeHtmlToClipboard(richHtml);
      setStatus("知乎版已复制飞书原始富文本。现在粘贴到知乎，图片/GIF 会尽量沿用飞书剪贴板格式。");
      return;
    } catch (error) {
      if (selectAndCopyHtml(richHtml)) {
        setStatus("知乎版已用兼容方式复制飞书原始富文本。现在粘贴到知乎。");
        return;
      }
    }
  }
  if (!lastContentHtml.trim() && !el.preview.innerHTML.trim()) {
    setStatus("还没有可复制的排版内容。", true);
    return;
  }
  const html = await buildClipboardHtml({ imageMode: "zhihu" });
  try {
    await writeHtmlToClipboard(html);
    setStatus("知乎版已复制。本地图片已转成占位提示，请在知乎里用图片按钮按占位上传原图/GIF。");
  } catch (error) {
    if (selectAndCopyHtml(html)) {
      setStatus("知乎版已用兼容方式复制。本地图片已转成占位提示，请在知乎里用图片按钮上传原图/GIF。");
      return;
    }
    setStatus("知乎版复制失败。请确认浏览器允许剪贴板权限，或先点预览区后手动 Cmd+C。", true);
  }
}

async function copyHtml() {
  const html = lastContentHtml || el.preview.innerHTML.trim();
  if (!html) {
    setStatus("还没有可复制的 HTML。", true);
    return;
  }
  await navigator.clipboard.writeText(html);
  setStatus("HTML 已复制。");
}

async function copyConvertedMarkdown() {
  const markdown = currentMarkdown();
  if (!markdown) {
    setStatus("还没有可复制的 Markdown。", true);
    return;
  }
  await navigator.clipboard.writeText(markdown);
  setStatus("转换后的 Markdown 已复制。");
}

function getCoverPayload() {
  const articleText = currentMarkdown() || el.preview.innerText.trim();
  return {
    account: el.account.value,
    title: el.coverTitle.value.trim() || el.articleTitle.textContent.trim(),
    coverText: el.coverText.value.trim(),
    visualHammer: el.visualHammer.value.trim(),
    articleText,
  };
}

async function exportLongCard() {
  const markdown = currentMarkdown();
  if (!markdown) {
    setStatus("请先粘贴或导入正文，再导出长图卡片。", true);
    return;
  }
  setStatus("正在导出长图卡片...");
  el.exportCard.disabled = true;
  try {
    const response = await fetch("/api/export-card", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown, account: el.account.value }),
    });
    const data = await response.json();
    if (!response.ok) {
      setStatus(data.error || "长图卡片导出失败。", true);
      return;
    }
    el.cardPreview.classList.add("active");
    el.cardPreview.innerHTML = `<img src="${data.url}&t=${Date.now()}" alt="公众号长图卡片"><figcaption>${data.path}</figcaption>`;
    setStatus("长图卡片已导出，可以打开预览或拿去做朋友圈/社群分享。");
  } finally {
    el.exportCard.disabled = false;
  }
}

async function makeCoverPrompt() {
  const payload = getCoverPayload();
  if (!payload.title || payload.title === "未命名文章") {
    setStatus("请先生成文章预览，或者手动填写文章标题。", true);
    return;
  }
  setStatus("正在生成封面提示词...");
  const response = await fetch("/api/cover-prompt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    setStatus(data.error || "封面提示词生成失败。", true);
    return;
  }
  el.coverPrompt.value = data.prompt;
  if (!coverTextTouched || !el.coverText.value.trim()) {
    el.coverText.value = data.coverText;
    coverTextTouched = false;
  }
  setStatus("封面提示词已生成。可以复制给 Codex / GPT Image 使用。");
}

async function generateCover() {
  const payload = getCoverPayload();
  if (!payload.title || payload.title === "未命名文章") {
    setStatus("请先生成文章预览，或者手动填写文章标题。", true);
    return;
  }
  setStatus("正在生成封面，可能需要一两分钟...");
  const response = await fetch("/api/generate-cover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    if (data.error) {
      el.coverPrompt.value = el.coverPrompt.value || "";
      await makeCoverPrompt();
      setStatus(data.error, true);
      return;
    }
    setStatus("封面生成失败。", true);
    return;
  }
  el.coverPrompt.value = data.prompt;
  el.coverPreview.classList.add("active");
  el.coverPreview.innerHTML = `<img src="${data.url}&t=${Date.now()}" alt="公众号封面"><figcaption>${data.path}</figcaption>`;
  setStatus("封面已生成并保存。");
}

el.account.addEventListener("change", () => {
  syncAccountNote();
  if (el.markdown.value.trim() || textOf(el.richPaste)) {
    convert();
  }
});
el.navCompose.addEventListener("click", () => setSection("compose"));
el.navSettings.addEventListener("click", () => setSection("settings"));
el.sidebarToggle.addEventListener("click", () => setSidebarCollapsed(!sidebarCollapsed));
el.saveSettings.addEventListener("click", saveAccountSettings);
el.resetSettings.addEventListener("click", resetAccountSettings);
el.markdownMode.addEventListener("click", () => setMode("markdown"));
el.richMode.addEventListener("click", () => setMode("rich"));
el.richPaste.addEventListener("focus", () => {
  if (el.richPaste.textContent.trim() === "从飞书文档复制正文后，粘贴到这里。") {
    el.richPaste.innerHTML = "";
  }
});
el.richPaste.addEventListener("paste", async (event) => {
  setMode("rich");
  const files = Array.from(event.clipboardData?.files || []).filter((file) => file.type.startsWith("image/"));
  if (!files.length) {
    window.setTimeout(() => {
      setStatus("已粘贴飞书富文本。点“生成预览”即可保留其中可访问的图片。");
    }, 0);
    return;
  }

  event.preventDefault();
  const html = event.clipboardData?.getData("text/html");
  const text = event.clipboardData?.getData("text/plain");
  if (html) {
    document.execCommand("insertHTML", false, html);
  } else if (text) {
    document.execCommand("insertText", false, text);
  }
  for (const file of files) {
    const dataUrl = await fileToDataUrl(file);
    document.execCommand("insertHTML", false, `<p><img src="${dataUrl}" alt="粘贴图片"></p>`);
  }
  setStatus("已接收剪贴板图片。点“生成预览”即可带图排版。");
});
el.convert.addEventListener("click", convert);
el.importFeishu.addEventListener("click", importFeishuDoc);
el.feishuUrl.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    importFeishuDoc();
  }
});
el.loadSample.addEventListener("click", loadSample);
el.copyRich.addEventListener("click", copyRichText);
el.copyZhihu.addEventListener("click", copyZhihuRichText);
el.copyHtml.addEventListener("click", copyHtml);
el.copyMarkdown.addEventListener("click", copyConvertedMarkdown);
el.exportCard.addEventListener("click", exportLongCard);
el.makeCoverPrompt.addEventListener("click", makeCoverPrompt);
el.generateCover.addEventListener("click", generateCover);
el.coverText.addEventListener("input", () => {
  coverTextTouched = true;
});

applySidebarState();
setSection(activeSection, false);
syncAccountNote();
setMode("markdown");
loadSettings();
checkImportEnvironment();
loadSample();
