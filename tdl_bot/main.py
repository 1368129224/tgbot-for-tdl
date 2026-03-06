import asyncio

from .config import load_config
from .logging_setup import setup_logging
from .bot import BotContext, build_bot, run_polling


def main() -> None:
    cfg = load_config()
    logger = setup_logging(cfg.debug)
    logger.info("logging level: %s", logger.getEffectiveLevel())

    bot = build_bot(cfg, logger)
    ctx = BotContext(cfg=cfg, bot=bot, logger=logger)

    asyncio.run(run_polling(ctx))


if __name__ == "__main__":
    main()
