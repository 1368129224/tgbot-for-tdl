"""常量定义。

集中管理一些“散落在代码中会很难维护”的魔法数字与固定字符串。
"""

# 默认配置文件路径（相对当前工作目录）
CFG_PATH = "tdl_bot_config.toml"

# 用于剥离 tdl 输出中的 ANSI 颜色控制符
ANSI_ESCAPE_RE = r"\x1b\[[0-9;]*[a-zA-Z]"

# 进度刷新节流：每多少次解析到进度后才更新一次 Telegram 消息
PROGRESS_INTERVAL = 10

# 按钮布局
KEYBOARD_MAX_ROW_LEN = 6
KEYBOARD_MAX_COL_LEN = 4
KEYBOARD_MAX_ONE_PAGE_LEN = KEYBOARD_MAX_ROW_LEN * KEYBOARD_MAX_COL_LEN
