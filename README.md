# WeChat Layout Workbench

一个本地微信公众号排版工作台。支持 Markdown、飞书文档链接、飞书富文本粘贴，生成可直接粘贴到微信公众号后台的富文本。

## 功能

- 多账号模板：西羊石AI视频、羊羊AI视频、西羊石AI短剧、小石的AI智能体工坊
- 羊羊AI视频蓝色主题
- 飞书链接导入，尽量下载文档图片到本地
- 复制公众号富文本，不需要再用壹伴转 HTML
- 自定义账号开头和结尾模板
- Mac Terminal 风格代码块
- 表格对齐、换行和溢出保护
- 2.35:1 公众号封面提示词和可选 OpenAI 图片生成
- 长图卡片导出

## 本地启动

推荐用脚本启动，会自动清理旧端口、拉起独立后台会话并做 HTTP 检查：

```bash
./scripts/start-local.sh 8765
```

打开：

```text
http://127.0.0.1:8765
```

也可以直接前台启动：

```bash
python3 web/server.py 8765
```

前台启动时不要关闭这个终端窗口。

打开：

```text
http://127.0.0.1:8765
```

## Docker 启动

```bash
docker compose -f web/docker-compose.yml up --build
```

打开：

```text
http://127.0.0.1:8765
```

## 可选环境变量

```bash
OPENAI_API_KEY=你的 key
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_IMAGE_SIZE=1584x672
OPENAI_IMAGE_QUALITY=high
```

## 飞书导入

飞书链接导入依赖本机可用的 `lark-cli` 登录态。没有 `lark-cli` 时仍可使用 Markdown 或飞书富文本粘贴模式。

导入原理：

1. 浏览器把飞书链接发给本地服务的 `/api/import-feishu`。
2. 本地 Python 服务调用 `lark-cli docs +fetch --doc <链接> --format json`。
3. `lark-cli` 使用本机飞书登录态读取文档，返回 Markdown 和图片 token。
4. 本地服务再调用 `lark-cli docs +media-download` 下载图片到 `output/_feishu_media/`。
5. 页面把 Markdown 转成公众号可复制富文本。

如果 Windows 显示 `[WinError 2] 系统找不到指定的文件`，通常是本机没有安装 `lark-cli`，或者 `lark-cli` 没有加入 PATH。先在 PowerShell 里检查：

```powershell
lark-cli --version
lark-cli doctor
lark-cli auth status
```

如果第一条就提示找不到命令，先安装并重新打开 PowerShell：

```powershell
npm install -g @larksuite/cli
```

如果命令存在但 `doctor` 或 `auth status` 不通过，执行：

```powershell
lark-cli auth login
```

## 账号首尾模板

页面侧边栏进入「账号与首尾模板」，按当前账号保存固定开头和结尾。配置保存在本地：

```text
config/workbench-settings.json
```

这个文件默认不提交，适合团队成员各自维护自己的本地配置。
