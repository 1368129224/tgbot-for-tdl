import os
import sys
import logging
from dataclasses import dataclass, field
from typing import Optional, List

import tomlkit

from .constants import CFG_PATH


@dataclass
class BotConfig:
    debug: bool = False
    enable_ipv6: bool = False
    bot_token: str = ""
    download_path: str = ""
    proxy_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    # Execution / concurrency
    bot_max_concurrency: int = 1  # bot-level concurrent download tasks

    # tdl binary
    tdl_path: str = "/usr/local/bin/tdl"

    # tdl global flags (defaults keep consistent with tdl defaults where possible)
    tdl_limit: int = 1
    tdl_threads: int = 4
    tdl_delay: str = "0s"
    tdl_reconnect_timeout: str = "0"  # keep legacy behavior (0=infinite) unless changed

    # Download flags (defaults: keep consistent with tdl defaults)
    download_group: bool = False
    download_skip_same: bool = False
    download_rewrite_ext: bool = False
    download_desc: bool = False
    download_takeout: bool = False
    download_include: List[str] = field(default_factory=list)
    download_exclude: List[str] = field(default_factory=list)
    download_template: str = ""  # empty means tdl default
    download_serve: bool = False  # placeholder

    # Upload placeholder (not implemented yet)
    upload_enabled: bool = False
    upload_to_chat: str = ""
    upload_to_topic: str = ""
    upload_caption_template: str = ""
    upload_include: List[str] = field(default_factory=list)
    upload_exclude: List[str] = field(default_factory=list)


def generate_default_config(path: str = CFG_PATH) -> None:
    """Generate a default config file and exit.

    Mirrors old behavior: if config does not exist, create it and stop.
    Defaults for download flags keep consistent with tdl defaults.
    """
    doc = tomlkit.document()
    doc.add(tomlkit.comment("*** TDL telegram bot ***"))
    doc.add(tomlkit.comment("TDL: https://github.com/iyear/tdl"))
    doc.add(tomlkit.nl())

    doc.add("debug", tomlkit.item(False))
    doc.add("enable_ipv6", tomlkit.item(False))
    doc.add("bot_token", tomlkit.item(""))
    doc.add("download_path", tomlkit.item(""))
    doc.add(tomlkit.nl())

    doc.add(tomlkit.comment("This proxy will be used for both telegram bot and tdl"))
    doc.add(tomlkit.comment("If you don't need proxy, please remove the proxy_url keyword"))
    doc.add("proxy_url", tomlkit.item(None))
    doc.add(tomlkit.nl())

    doc.add(tomlkit.comment("Tags used as download subfolders"))
    doc.add("tags", tomlkit.item([]))
    doc.add(tomlkit.nl())

    bot = tomlkit.table()
    bot.add(tomlkit.comment("Bot-level options"))
    bot.add("max_concurrency", 1)
    doc.add("bot", bot)
    doc.add(tomlkit.nl())

    tdl = tomlkit.table()
    tdl.add(tomlkit.comment("tdl binary and global flags"))
    tdl.add("path", "/usr/local/bin/tdl")
    tdl.add("limit", 1)
    tdl.add("threads", 4)
    tdl.add("delay", "0s")
    tdl.add(tomlkit.comment("0 means infinite backoff (legacy behavior). tdl default is 5m"))
    tdl.add("reconnect_timeout", "0")
    doc.add("tdl", tdl)
    doc.add(tomlkit.nl())

    dl = tomlkit.table()
    dl.add(tomlkit.comment("Download flags (defaults keep consistent with tdl)"))
    dl.add("group", False)
    dl.add("skip_same", False)
    dl.add("rewrite_ext", False)
    dl.add("desc", False)
    dl.add("takeout", False)
    dl.add("include", [])
    dl.add("exclude", [])
    dl.add(tomlkit.comment("Empty means use tdl default template"))
    dl.add("template", "")
    dl.add(tomlkit.comment("Placeholder: serve mode (not enabled by default)"))
    dl.add("serve", False)
    doc.add("download", dl)
    doc.add(tomlkit.nl())

    up = tomlkit.table()
    up.add(tomlkit.comment("Upload placeholder (not implemented yet)"))
    up.add("enabled", False)
    up.add("to_chat", "")
    up.add("to_topic", "")
    up.add("caption_template", "")
    up.add("include", [])
    up.add("exclude", [])
    doc.add("upload", up)

    with open(path, "w", encoding="utf-8") as f:
        tomlkit.dump(doc, f)


def load_config(path: str = CFG_PATH) -> BotConfig:
    # Allow overriding config path in container/managed environments
    path = os.environ.get("TDL_BOT_CONFIG", path)

    if not os.path.isfile(path):
        # preserve legacy behavior
        generate_default_config(path)
        logging.getLogger(__name__).info("Generated default config at %s", path)
        sys.exit(0)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = tomlkit.loads(f.read())
    except (IOError, OSError) as e:
        raise ValueError(f"Failed to read config file: {e}")
    except tomlkit.exceptions.TOMLKitError as e:
        raise ValueError(f"Invalid TOML format in config file: {e}")

    # Backward compatibility: allow both new tables and legacy flat keys
    bot_tbl = data.get("bot", {}) or {}
    tdl_tbl = data.get("tdl", {}) or {}
    dl_tbl = data.get("download", {}) or {}
    up_tbl = data.get("upload", {}) or {}

    def _list(v):
        return list(v or [])

    cfg = BotConfig(
        debug=bool(data.get("debug", False)),
        enable_ipv6=bool(data.get("enable_ipv6", False)),
        bot_token=str(data.get("bot_token", "") or ""),
        download_path=str(data.get("download_path", "") or ""),
        proxy_url=data.get("proxy_url", None),
        tags=_list(data.get("tags", [])),

        bot_max_concurrency=int(bot_tbl.get("max_concurrency", 1) or 1),

        tdl_path=str(tdl_tbl.get("path", data.get("tdl_path", "/usr/local/bin/tdl")) or "/usr/local/bin/tdl"),
        tdl_limit=int(tdl_tbl.get("limit", 1) or 1),
        tdl_threads=int(tdl_tbl.get("threads", 4) or 4),
        tdl_delay=str(tdl_tbl.get("delay", "0s") or "0s"),
        tdl_reconnect_timeout=str(tdl_tbl.get("reconnect_timeout", "0") or "0"),

        download_group=bool(dl_tbl.get("group", False)),
        download_skip_same=bool(dl_tbl.get("skip_same", False)),
        download_rewrite_ext=bool(dl_tbl.get("rewrite_ext", False)),
        download_desc=bool(dl_tbl.get("desc", False)),
        download_takeout=bool(dl_tbl.get("takeout", False)),
        download_include=_list(dl_tbl.get("include", [])),
        download_exclude=_list(dl_tbl.get("exclude", [])),
        download_template=str(dl_tbl.get("template", "") or ""),
        download_serve=bool(dl_tbl.get("serve", False)),

        upload_enabled=bool(up_tbl.get("enabled", False)),
        upload_to_chat=str(up_tbl.get("to_chat", "") or ""),
        upload_to_topic=str(up_tbl.get("to_topic", "") or ""),
        upload_caption_template=str(up_tbl.get("caption_template", "") or ""),
        upload_include=_list(up_tbl.get("include", [])),
        upload_exclude=_list(up_tbl.get("exclude", [])),
    )

    validate_config(cfg)
    return cfg


def validate_config(cfg: BotConfig) -> None:
    if not cfg.bot_token.strip():
        raise ValueError("Bot token is required and cannot be empty")

    if not cfg.download_path.strip():
        raise ValueError("Download path is required and cannot be empty")

    if not os.path.exists(cfg.download_path):
        os.makedirs(cfg.download_path, exist_ok=True)

    if not isinstance(cfg.tags, list) or not cfg.tags:
        raise ValueError("tags must be a non-empty list")

    if cfg.bot_max_concurrency < 1:
        raise ValueError("bot.max_concurrency must be >= 1")

    if cfg.tdl_limit < 1:
        raise ValueError("tdl.limit must be >= 1")

    if cfg.tdl_threads < 1:
        raise ValueError("tdl.threads must be >= 1")

    # Create tag subfolders lazily; no need to pre-create here.
