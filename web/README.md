# 西羊石公众号排版工作台

把 Markdown / 飞书文档转成可直接粘贴到微信公众号编辑器的富文本预览页。

支持账号：

- 西羊石AI视频
- 羊羊AI视频（蓝色主题）
- 西羊石AI短剧
- 小石的AI智能体工坊

页面侧边栏的「账号与首尾模板」可以按账号设置固定开头和结尾。留空时使用默认开头和默认结尾。

## 本地 Python 启动

推荐在仓库根目录运行：

```bash
./scripts/start-local.sh 8765
```

脚本会自动重启端口、写日志，并在 macOS 上用 `screen` 保持后台服务。

也可以前台运行：

```bash
python3 web/server.py 8765
```

打开：

```text
http://127.0.0.1:8765
```

## Docker 启动

在本仓库根目录运行：

```bash
docker compose -f web/docker-compose.yml up --build
```

打开：

```text
http://127.0.0.1:8765
```

Docker 会把当前仓库目录挂载到容器 `/app`，所以本地修改 `scripts/md2wechat.py`、`config/workbench-settings.json`、`output/` 文章和图片后，刷新网页即可使用最新内容。

Docker 镜像内置 Node.js 和 `lark-cli`。飞书链接导入还需要宿主机先登录：

```bash
lark-cli auth login
```

然后 compose 会把 `~/.lark-cli` 挂载到容器里。Windows 可手动指定：

```powershell
$env:LARK_CLI_CONFIG_DIR="C:\Users\你的用户名\.lark-cli"
docker compose -f web/docker-compose.yml up --build
```

如果要直接生成封面，需要在环境里提供：

```bash
OPENAI_API_KEY=你的 key
```

## 飞书导入依赖

飞书链接导入不是浏览器直接抓网页，而是本地 Python 服务调用 `lark-cli`：

```bash
lark-cli docs +fetch --doc "<飞书链接>" --format json
```

如果 Windows 出现 `[WinError 2] 系统找不到指定的文件`，就是 Python 找不到 `lark-cli` 可执行文件。先检查：

```powershell
lark-cli --version
lark-cli update
lark-cli doctor
lark-cli auth status
```

缺命令时安装：

```powershell
npm install -g @larksuite/cli
```

命令存在但没登录时运行：

```powershell
lark-cli auth login
```

如果提示 `docs +fetch is using the v1 API`，运行：

```powershell
lark-cli update
```

线上网站如果要像 `xysaiai.cn/admin/imports/feishu` 那样导入，应改成服务端飞书 OpenAPI 模式：服务端保存飞书应用凭证，下载文档内容和图片，再把图片保存到本站存储。这样访问者不需要本机安装 `lark-cli`。
