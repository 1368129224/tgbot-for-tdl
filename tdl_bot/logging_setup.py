import logging
import logging.handlers


def setup_logging(debug: bool, log_file: str = "tdl_bot.log") -> logging.Logger:
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

    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=1 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)

    logger = logging.getLogger("tdl_bot")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.addHandler(file_handler)
    return logger
