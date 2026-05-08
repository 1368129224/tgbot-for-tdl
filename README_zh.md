<h1 align="center">telegram bot for tdl</h1>

<p align="center">
一个基于 <a href="https://github.com/iyear/tdl">tdl</a> 的 Telegram 下载机器人。
</p>

<p align="center">
<a href="README.md">English</a> | 简体中文
</p>

## 截图

<figure style="display: flex; justify-content: space-between;">
  <img src="img/screenrecord.gif" alt="Screenshot" width="886">
</figure>

## 特性

- 根据选择的 tag 将文件下载到不同子目录。
- 支持一条消息包含多条链接。
- 单线程下载（保持历史行为，避免带宽/限流问题）。

## 依赖

- Python 3.10+
- Telegram bot token
- 已安装 `tdl`（默认路径 `/usr/local/bin/tdl`），或者在配置里设置 `tdl_path`

## 本地快速开始

```bash
# 安装 uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync

# 第一次运行会生成默认配置文件并退出
uv run python app.py

# 编辑配置
nano tdl_bot_config.toml

# 再次运行
uv run python app.py
```

## 配置说明（`tdl_bot_config.toml`）

常用字段：

- `bot_token`：机器人 token
- `download_path`：下载根目录
- `tags`：按钮里的 tag 列表
- `proxy_url`：可选（bot 与 tdl 都会使用）
- `tdl_path`：可选（默认 `/usr/local/bin/tdl`）
- `tdl_extra_args`：可选，追加到 tdl 命令末尾的参数

## Docker

项目提供 Dockerfile，会在构建时下载固定版本的 `tdl`。

```bash
docker build -t tdl-bot .

mkdir -p downloads

# 第一次可以在宿主机先生成配置文件
python app.py

docker run -d --name tdl-bot \
  -v "$(pwd)/tdl_bot_config.toml:/app/tdl_bot_config.toml:ro" \
  -v "$(pwd)/downloads:/downloads" \
  --restart unless-stopped \
  tdl-bot
```

或使用 docker compose：

```bash
docker compose up -d --build
```

## 排错

- 如果第一次运行立刻退出：可能是生成了默认配置文件并退出。编辑 `tdl_bot_config.toml` 后再运行。
- 下载失败：检查 tdl 是否可用、链接是否正确。

## 协议

AGPL-3.0
