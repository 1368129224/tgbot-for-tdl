"""程序入口（包内）。

职责：
- 加载配置
- 初始化日志
- 构建 bot
- 初始化并发控制
- 启动 polling
"""

import asyncio

from .config import load_config
from .logging_setup import setup_logging
from .bot import BotContext, build_bot, run_polling


def main() -> None:
    # 1) 读取配置（若不存在则生成默认配置并退出）
    cfg = load_config()

    # 2) 初始化日志
    logger = setup_logging(cfg.debug)
    logger.info("logging level: %s", logger.getEffectiveLevel())

    # 3) 构建 Telegram bot
    bot = build_bot(cfg, logger)
    ctx = BotContext(cfg=cfg, bot=bot, logger=logger)

    # 4) 并发控制：默认 1，可由配置 bot.max_concurrency 调整
    from .bot import Worker

    Worker.semaphore = asyncio.Semaphore(int(cfg.bot_max_concurrency))

    # 5) 启动 polling（阻塞）
    asyncio.run(run_polling(ctx))


if __name__ == "__main__":
    main()
