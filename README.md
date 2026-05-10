<h1 align="center">telegram bot for tdl</h1>

<p align="center">
A Telegram bot for downloading files via <a href="https://github.com/iyear/tdl">tdl</a>.
</p>

<p align="center">
English | <a href="README_zh.md">简体中文</a>
</p>

## Screenshot

<figure style="display: flex; justify-content: space-between;">
  <img src="img/screenrecord.gif" alt="Screenshot" width="886">
</figure>

## Features

- Download files into different subfolders based on the selected tag.
- Supports multiple message links in a single message.
- Single-thread download (legacy behavior; avoids Telegram rate / bandwidth issues).

## Requirements

- Python 3.10+
- A Telegram bot token
- `tdl` installed (default path `/usr/local/bin/tdl`) or configure `tdl_path` in `tdl_bot_config.toml`

## Quick start (local)

```bash
# install uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync

# first run will generate a default config and exit
uv run python app.py

# edit config
nano tdl_bot_config.toml

# run
uv run python app.py
```

## Configuration (`tdl_bot_config.toml`)

Key options:

- `bot_token`: Telegram bot token
- `download_path`: base download directory
- `tags`: tag list shown as buttons
- `proxy_url`: optional (used for both bot and tdl)
- `tdl_path`: optional (default `/usr/local/bin/tdl`)
- `tdl_extra_args`: optional extra args appended to the tdl command

## Docker

Pre-built image: `ghcr.io/1368129224/tgbot-for-tdl:main`

### Option 1: Login on host, then run in container

```bash
# login tdl on host first (session saved to ~/.tdl/)
tdl login

# create folders and copy config
mkdir -p downloads
cp docker-compose.yml.example docker-compose.yml

# run with docker compose (mounts ~/.tdl into container)
docker compose up -d --build
```

### Option 2: Login inside the container

```bash
mkdir -p downloads
cp docker-compose.yml.example docker-compose.yml
docker compose up -d --build

# exec into container to login interactively
docker exec -it tdl-bot tdl login
```

### Manual docker run

```bash
docker run -d --name tdl-bot \
  --network host \
  -v "$(pwd)/tdl_bot_config.toml:/app/tdl_bot_config.toml:ro" \
  -v "$(pwd)/downloads:/downloads" \
  -v "$HOME/.tdl:/root/.tdl" \
  --restart unless-stopped \
  tdl-bot
```

The `~/.tdl` mount shares the host's tdl login session with the container.

## Troubleshooting

- If the bot exits immediately on first run: it probably generated a default config and exited. Edit `tdl_bot_config.toml` and run again.
- If downloads fail: verify `tdl` exists in container/host and that the link is valid.

## License

AGPL-3.0
