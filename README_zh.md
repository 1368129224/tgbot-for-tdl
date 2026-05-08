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

`tdl` 使用 Telegram 客户端会话下载文件，首次使用需要登录。有两种方式：

### 方式一：在宿主机登录，再启动容器

```bash
# 在宿主机登录 tdl（会话保存到 ~/.tdl/）
tdl login

# 创建目录
mkdir -p downloads tdl-data

# 把宿主机的会话拷贝到项目目录
cp -r ~/.tdl/* tdl-data/

# 使用 docker compose 启动
docker compose up -d --build
```

### 方式二：在容器内登录

```bash
mkdir -p downloads tdl-data
docker compose up -d --build

# 进入容器执行登录（交互式输入验证码）
docker exec -it tdl-bot tdl login

# 会话持久化在 ./tdl-data（挂载为 /root/.tdl）
```

会话数据通过 `tdl-data` 目录挂载，容器重建后无需重新登录。

### 手动 docker run

```bash
docker run -d --name tdl-bot \
  -v "$(pwd)/tdl_bot_config.toml:/app/tdl_bot_config.toml:ro" \
  -v "$(pwd)/downloads:/downloads" \
  -v "$(pwd)/tdl-data:/root/.tdl" \
  --restart unless-stopped \
  tdl-bot
```

## 排错

- 如果第一次运行立刻退出：可能是生成了默认配置文件并退出。编辑 `tdl_bot_config.toml` 后再运行。
- 下载失败：检查 tdl 是否可用、链接是否正确。

## 协议

AGPL-3.0
