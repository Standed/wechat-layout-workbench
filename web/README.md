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

如果要直接生成封面，需要在环境里提供：

```bash
OPENAI_API_KEY=你的 key
```
