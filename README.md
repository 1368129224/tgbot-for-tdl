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
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# first run will generate a default config and exit
python app.py

# edit config
nano tdl_bot_config.toml

# run
python app.py
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

This repo includes a Dockerfile that downloads a pinned `tdl` release.

```bash
docker build -t tdl-bot .

# create folders
mkdir -p downloads

# first time: create config locally (or copy from template)
python app.py

# run
docker run -d --name tdl-bot \
  -v "$(pwd)/tdl_bot_config.toml:/app/tdl_bot_config.toml:ro" \
  -v "$(pwd)/downloads:/downloads" \
  --restart unless-stopped \
  tdl-bot
```

Or use docker compose:

```bash
docker compose up -d --build
```

## Troubleshooting

- If the bot exits immediately on first run: it probably generated a default config and exited. Edit `tdl_bot_config.toml` and run again.
- If downloads fail: verify `tdl` exists in container/host and that the link is valid.

## License

AGPL-3.0
