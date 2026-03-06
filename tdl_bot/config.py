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

    # New options (backward compatible)
    tdl_path: str = "/usr/local/bin/tdl"
    tdl_extra_args: str = ""  # raw extra args appended at end


def generate_default_config(path: str = CFG_PATH) -> None:
    """Generate a default config file and exit.

    Mirrors old behavior: if config does not exist, create it and stop.
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

    # New (optional)
    doc.add(tomlkit.comment("Optional: path to tdl binary"))
    doc.add("tdl_path", tomlkit.item("/usr/local/bin/tdl"))
    doc.add(tomlkit.comment("Optional: extra args appended to tdl command (string)"))
    doc.add("tdl_extra_args", tomlkit.item(""))

    with open(path, "w", encoding="utf-8") as f:
        tomlkit.dump(doc, f)


def load_config(path: str = CFG_PATH) -> BotConfig:
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

    cfg = BotConfig(
        debug=bool(data.get("debug", False)),
        enable_ipv6=bool(data.get("enable_ipv6", False)),
        bot_token=str(data.get("bot_token", "") or ""),
        download_path=str(data.get("download_path", "") or ""),
        proxy_url=data.get("proxy_url", None),
        tags=list(data.get("tags", []) or []),
        tdl_path=str(data.get("tdl_path", "/usr/local/bin/tdl") or "/usr/local/bin/tdl"),
        tdl_extra_args=str(data.get("tdl_extra_args", "") or ""),
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

    # Create tag subfolders lazily; no need to pre-create here.
