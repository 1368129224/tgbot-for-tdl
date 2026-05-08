# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Telegram bot front-end for the [tdl](https://github.com/iyear/tdl) CLI tool. Users send `t.me/...` links, pick a "tag" (subfolder), and the bot downloads files via `tdl` subprocess with live progress updates in chat.

## Commands

```bash
# Run locally (uv manages the virtualenv automatically)
uv sync
uv run python app.py

# Lint (CI runs this on Python 3.11 and 3.12)
uv run pylint $(git ls-files '*.py')

# Syntax check
uv run python -m py_compile app.py tdl_bot/*.py

# Docker
docker compose up -d --build
```

There is no test suite.

## Architecture

`app.py` is a thin wrapper calling `tdl_bot.main:main()`. All logic lives in the `tdl_bot/` package:

- **`config.py`** — `BotConfig` dataclass; `load_config()` reads TOML with both legacy flat keys and structured `[bot]/[tdl]/[download]` sections. Config path overridable via `TDL_BOT_CONFIG` env var.
- **`main.py`** — Loads config, sets up logging, builds bot, starts polling.
- **`bot.py`** — Core logic: `BotContext` (holds config + semaphore), `Worker` (download executor), `extract_links()` (regex parser), inline keyboard handlers (`TagButtons`, `RetryButtons`).
- **`tdl.py`** — `DownloadTask` dataclass, `build_download_args()` (constructs `tdl download` argv from config), output parsers (`parse_progress`, `parse_done`, `summarize_error`).
- **`constants.py`** — Config path, ANSI regex, progress interval, keyboard layout constants.
- **`logging_setup.py`** — Console + rotating file handler (`tdl_bot.log`, 1MB, 3 backups).

**Data flow**: User message → `extract_links()` → tag button keyboard → user clicks tag → `Worker` acquires semaphore → spawns `tdl` via `asyncio.create_subprocess_exec` → parses stdout for progress/errors → updates Telegram message → retry keyboard on failure.

## Key Technical Details

- Uses `pyTelegramBotAPI` (imported as `telebot`) with async polling.
- Downloads are concurrency-limited via `asyncio.Semaphore` (default 1, configured as `bot.max_concurrency`).
- `tdl` binary must be installed separately (pinned to v0.16.0 in Docker).
- Progress updates are throttled by `PROGRESS_INTERVAL` to avoid Telegram rate limits.
- The `[upload]` config section exists but is not yet implemented.
