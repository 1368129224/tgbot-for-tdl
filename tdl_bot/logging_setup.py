"""日志初始化。

- 控制台：basicConfig
- 文件：RotatingFileHandler，默认 tdl_bot.log，按 1MB 轮转，保留 3 份

说明：
- bot/tdl 输出会比较多，轮转可以避免日志无限增长。
"""

import logging
import logging.handlers


def setup_logging(debug: bool, log_file: str = "tdl_bot.log") -> logging.Logger:
    """创建并返回项目 logger。"""

    # basicConfig 主要影响 root logger（这里保留历史格式）
    logging.basicConfig(
        style="{",
        format="{asctime} {levelname:<8} {funcName}:{lineno} {message}",
        datefmt="%m-%d %H:%M:%S",
        level=logging.DEBUG if debug else logging.INFO,
    )

    formatter = logging.Formatter(
        style="{",
        fmt="{asctime} {levelname:<8} {funcName}:{lineno} {message}",
        datefmt="%m-%d %H:%M:%S",
    )

    # 轮转日志：避免文件过大
    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=1 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)

    # 使用独立命名空间的 logger，便于过滤
    logger = logging.getLogger("tdl_bot")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.addHandler(file_handler)
    return logger
