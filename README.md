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

Docker 镜像会内置 `lark-cli`。如果要使用飞书链接导入，需要把宿主机的 `~/.lark-cli` 挂载进容器；默认 compose 已经做了这个映射：

```yaml
${LARK_CLI_CONFIG_DIR:-~/.lark-cli}:/root/.lark-cli
```

Windows 如果配置目录不在默认位置，可以设置：

```powershell
$env:LARK_CLI_CONFIG_DIR="C:\Users\你的用户名\.lark-cli"
docker compose -f web/docker-compose.yml up --build
```

## 可选环境变量

```bash
OPENAI_API_KEY=你的 key
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_IMAGE_SIZE=1584x672
OPENAI_IMAGE_QUALITY=high

# 飞书线上导入模式
FEISHU_APP_ID=飞书开放平台应用 app_id
FEISHU_APP_SECRET=飞书开放平台应用 app_secret
FEISHU_BASE_URL=https://open.feishu.cn/open-apis
```

## 飞书导入

飞书链接导入支持两种模式：

- 线上 OpenAPI 模式：服务端配置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 后，后端直接通过飞书 OpenAPI 读取文档和图片。访问者只需要粘贴链接，不需要本机安装 `lark-cli`。
- 本地 `lark-cli` 模式：未配置 OpenAPI 时，继续使用本机 `lark-cli` 登录态读取文档；适合个人本地使用。

系统会优先尝试 OpenAPI；如果 OpenAPI 未配置或读取失败，会回退到 `lark-cli`。两种模式都会先转成 Markdown，再走公众号排版渲染链路，避免飞书导入影响正文段距、小标题样式和图片网格样式。

OpenAPI 模式原理：

1. 浏览器把飞书链接发给本地服务的 `/api/import-feishu`。
2. 服务端用 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 获取 `tenant_access_token`。
3. 服务端读取 `/docx/v1/documents/{document_id}` 和 `/docx/v1/documents/{document_id}/blocks`。
4. 服务端把 block 树转成 Markdown，并通过 `/drive/v1/medias/{token}/download` 下载图片到 `output/_feishu_media/`。
5. 页面把 Markdown 转成公众号可复制富文本。

飞书开放平台应用至少需要开通并发布：

- `docx:document:readonly` 或对应云文档读取权限
- `docs:document.media:download` 或 `drive:drive:readonly`

注意：你个人能编辑文档，不代表开放平台应用能通过 API 读取文档。需要确认文档已授权给应用，或在组织权限范围内对应用可读。

本地 `lark-cli` 模式原理：

1. 浏览器把飞书链接发给本地服务的 `/api/import-feishu`。
2. 本地 Python 服务调用 `lark-cli docs +fetch --doc <链接> --format json`。
3. `lark-cli` 使用本机飞书登录态读取文档，返回 Markdown 和图片 token。
4. 本地服务再调用 `lark-cli docs +media-download` 下载图片到 `output/_feishu_media/`。
5. 页面把 Markdown 转成公众号可复制富文本。

如果 Windows 显示 `[WinError 2] 系统找不到指定的文件`，通常是本机没有安装 `lark-cli`，或者 `lark-cli` 没有加入 PATH。先在 PowerShell 里检查：

```powershell
lark-cli --version
lark-cli update
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

如果看到 `[deprecated] docs +fetch is using the v1 API`，说明本机 lark-doc skill 还是旧版，执行：

```powershell
lark-cli update
```

然后重新启动本项目。

Windows 推荐直接运行项目脚本，它会检查 Python、`lark-cli`、飞书登录态、端口和页面：

```powershell
.\scripts\start-local.ps1 -Port 8765
```

## 线上部署建议

适合团队线上版的路线：

- 内部团队用：先做“服务端飞书应用凭证”模式，限定只有自己团队可访问。
- 多用户 SaaS 用：再做 OAuth 用户授权模式，每个用户绑定自己的飞书身份。
- 图片存储：线上不要依赖飞书外链，建议保存到 Cloudflare R2、S3 或服务器本地静态目录。

## 账号首尾模板

页面侧边栏进入「账号与首尾模板」，按当前账号保存固定开头和结尾。配置保存在本地：

```text
config/workbench-settings.json
```

这个文件默认不提交，适合团队成员各自维护自己的本地配置。
