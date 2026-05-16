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

```bash
python3 web/server.py 8765
```

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

## 账号首尾模板

页面侧边栏进入「账号与首尾模板」，按当前账号保存固定开头和结尾。配置保存在本地：

```text
config/workbench-settings.json
```

这个文件默认不提交，适合团队成员各自维护自己的本地配置。
