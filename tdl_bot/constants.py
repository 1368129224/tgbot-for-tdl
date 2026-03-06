CFG_PATH = "tdl_bot_config.toml"

# Regex for stripping ANSI escape sequences from tdl output
ANSI_ESCAPE_RE = r"\x1b\[[0-9;]*[a-zA-Z]"

PROGRESS_INTERVAL = 10

KEYBOARD_MAX_ROW_LEN = 6
KEYBOARD_MAX_COL_LEN = 4
KEYBOARD_MAX_ONE_PAGE_LEN = KEYBOARD_MAX_ROW_LEN * KEYBOARD_MAX_COL_LEN
