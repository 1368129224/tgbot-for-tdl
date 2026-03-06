"""Telegram Bot 逻辑层。

本模块负责：
- 解析用户消息中的 Telegram 链接
- 生成按钮（tag 选择、失败重试）
- 调用 tdl 执行下载，并把进度/结果反馈给用户

设计原则：
- bot 只负责“编排与反馈”，实际下载能力尽量交给 tdl
- 默认行为尽量保守（并发默认 1），避免资源争抢/限流
"""

import asyncio
import os
import socket
from dataclasses import dataclass

from telebot import asyncio_helper
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from telebot.async_telebot import AsyncTeleBot

from .config import BotConfig
from .constants import PROGRESS_INTERVAL, KEYBOARD_MAX_ROW_LEN
from .tdl import DownloadTask, build_download_args, parse_progress, parse_done


@dataclass
class BotContext:
    """运行上下文：配置 + bot 实例 + logger。"""

    cfg: BotConfig
    bot: AsyncTeleBot
    logger: any


class TagButtons:
    """tag 选择按钮。

    callback_data 形式：
    - "<tag>#<link>" 或 "cancel#<link>"
    """

    def __init__(self, tags: list[str], link: str):
        self.tags = tags
        self.link = link

    def _btn(self, text: str, callback_data: str) -> InlineKeyboardButton:
        # 通过 # 把 link 带回 callback 里，便于后续定位任务
        return InlineKeyboardButton(text=text, callback_data=f"{callback_data}#{self.link}")

    def build(self) -> InlineKeyboardMarkup:
        """构建 tag 键盘。"""
        markup = InlineKeyboardMarkup()
        markup.row_width = KEYBOARD_MAX_ROW_LEN
        row: list[InlineKeyboardButton] = []

        for i, tag in enumerate(self.tags):
            row.append(self._btn(tag, tag))
            if len(row) == KEYBOARD_MAX_ROW_LEN:
                markup.add(*row)
                row = []

            # 最后一行收尾：补齐最后一排，再追加 cancel
            if i == len(self.tags) - 1:
                if row:
                    markup.add(*row)
                markup.add(self._btn("cancel", "cancel"))

        return markup


class RetryButtons:
    """下载失败后的重试/取消按钮。"""

    def __init__(self, link: str, tag: str):
        self.link = link
        self.tag = tag

    def build(self) -> InlineKeyboardMarkup:
        # retry 的 callback_data 需要携带 tag
        markup = InlineKeyboardMarkup()
        markup.row_width = 2
        markup.add(
            InlineKeyboardButton(text="retry", callback_data=f"retry|{self.tag}#{self.link}"),
            InlineKeyboardButton(text="cancel", callback_data=f"cancel#{self.link}"),
        )
        return markup


class Worker:
    """下载任务执行器。

    - 默认串行（semaphore=1）
    - 支持通过配置调整 bot 级并发
    """

    semaphore: asyncio.Semaphore | None = None

    def __init__(self, ctx: BotContext, task: DownloadTask, msg):
        import uuid

        self.ctx = ctx
        self.task = task
        self.msg = msg
        # 用短 task_id 方便在日志里定位单次任务
        self.task_id = uuid.uuid4().hex[:8]

    def _pfx(self) -> str:
        """统一的日志前缀，方便 grep。"""
        return f"task={self.task_id} link={self.task.link} tag={self.task.tag}"

    async def call_tdl(self) -> None:
        """调用 tdl 执行下载，并将进度/结果反馈给用户。

        约束：
        - 下载失败需要把错误原因（摘要）发给用户
        - 提供 retry 按钮
        """

        sem = Worker.semaphore or asyncio.Semaphore(1)
        async with sem:
            # 确保目标目录存在
            os.makedirs(self.task.path, exist_ok=True)

            # 由结构化配置生成 tdl 参数（argv），避免 shell 转义问题
            args = build_download_args(
                task=self.task,
                debug=bool(self.ctx.cfg.debug),
                proxy_url=self.ctx.cfg.proxy_url,
                reconnect_timeout=str(self.ctx.cfg.tdl_reconnect_timeout),
                limit=int(self.ctx.cfg.tdl_limit),
                threads=int(self.ctx.cfg.tdl_threads),
                delay=str(self.ctx.cfg.tdl_delay),
                group=bool(self.ctx.cfg.download_group),
                skip_same=bool(self.ctx.cfg.download_skip_same),
                rewrite_ext=bool(self.ctx.cfg.download_rewrite_ext),
                desc=bool(self.ctx.cfg.download_desc),
                takeout=bool(self.ctx.cfg.download_takeout),
                include=list(self.ctx.cfg.download_include),
                exclude=list(self.ctx.cfg.download_exclude),
                template=str(self.ctx.cfg.download_template),
                serve=bool(self.ctx.cfg.download_serve),
            )

            self.ctx.logger.info(
                "%s Run tdl: %s %s",
                self._pfx(),
                self.ctx.cfg.tdl_path,
                " ".join(args),
            )

            # 直接 exec，不走 shell
            proc = await asyncio.create_subprocess_exec(
                self.ctx.cfg.tdl_path,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            # i/j 用于节流（避免过于频繁 edit_message 导致风控/限流）
            i = 0
            j = 0

            # 保存最近输出用于错误摘要
            last_lines: list[str] = []

            if not proc.stdout:
                # 极小概率：子进程没有 stdout
                self.ctx.logger.error("%s subprocess has no stdout", self._pfx())
                await self.ctx.bot.edit_message_text(
                    f"{self.task.link} tag: {self.task.tag}\nFailed: no stdout from subprocess",
                    chat_id=self.msg.chat.id,
                    message_id=self.msg.id,
                    reply_markup=RetryButtons(self.task.link, self.task.tag).build(),
                )
                return

            while True:
                line_b = await proc.stdout.readline()
                if not line_b:
                    break

                line = line_b.decode(errors="replace")

                # 保留一小段 tail，用于失败时给用户一个可读的原因
                last_lines.append(line)
                if len(last_lines) > 30:
                    last_lines = last_lines[-30:]

                i += 1

                # 1) 完成判断（tdl 输出里包含 done!）
                done = parse_done(line)
                if done:
                    self.ctx.logger.info("%s Download done: %s", self._pfx(), done)
                    await self.ctx.bot.edit_message_text(
                        f"{self.task.link} tag: {self.task.tag}\nDownlaod {done}",
                        chat_id=self.msg.chat.id,
                        message_id=self.msg.id,
                    )
                    continue

                # 2) 进度解析（非每行都能解析，解析不到就跳过）
                if i >= 10:
                    i = 0

                progress = parse_progress(line)
                if not progress:
                    continue

                process, speed = progress
                try:
                    if j >= PROGRESS_INTERVAL:
                        await self.ctx.bot.edit_message_text(
                            f"{self.task.link} tag: {self.task.tag}\nDownloading: {process} {speed}",
                            chat_id=self.msg.chat.id,
                            message_id=self.msg.id,
                        )
                        j = 0
                    else:
                        j += 1

                    self.ctx.logger.debug("%s Downloading: %s %s", self._pfx(), process, speed)
                except Exception as e:
                    # edit_message 可能因为消息过旧/权限等失败，这里只记录不终止任务
                    self.ctx.logger.error("%s edit_message failed: %s", self._pfx(), e)

            await proc.wait()
            rc = proc.returncode
            self.ctx.logger.info("%s Download returncode %s", self._pfx(), rc)

            # 失败：把原因摘要发给用户，并提供重试按钮
            if rc and rc != 0:
                from .tdl import summarize_error

                summary = summarize_error(last_lines)
                await self.ctx.bot.edit_message_text(
                    f"{self.task.link} tag: {self.task.tag}\nFailed (rc={rc}): {summary}",
                    chat_id=self.msg.chat.id,
                    message_id=self.msg.id,
                    reply_markup=RetryButtons(self.task.link, self.task.tag).build(),
                )


def extract_links(text: str) -> list[str]:
    """从用户文本中提取 Telegram 消息链接。

    改进点（相较于简单 split）：
    - 基于正则提取（允许用户随意换行/夹杂文字）
    - 去掉常见的尾随标点
    - 去重（保序）
    """

    import re

    if not text:
        return []

    candidates = re.findall(r"https://t\.me/\S+", text)

    def normalize(url: str) -> str:
        # 用户粘贴时经常带上句号/右括号等，做一下清理
        return url.rstrip(".,;:!?)\"']>")

    seen: set[str] = set()
    out: list[str] = []
    for u in candidates:
        u = normalize(u)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def build_bot(cfg: BotConfig, logger) -> AsyncTeleBot:
    """根据配置构建 Telegram bot 实例。"""

    # 兼容旧逻辑：禁用 IPv6（best-effort，部分平台无效）
    if not cfg.enable_ipv6:
        socket.AF_INET6 = False

    # 设置 telebot 的全局代理（如果配置了）
    if cfg.proxy_url:
        asyncio_helper.proxy = cfg.proxy_url

    return AsyncTeleBot(cfg.bot_token)


def register_handlers(ctx: BotContext) -> None:
    """注册消息处理器与回调处理器。"""

    bot = ctx.bot

    @bot.message_handler(commands=["help", "start"])
    async def start_help(message):
        text = (
            "Supported command:\n"
            "/help to display help message.\n"
            "/show_config to display bot config.\n\n"
            "How to use:\n"
            "Send message link to bot and select the tag, the download will be performed automatically."
        )
        await bot.reply_to(message, text)

    @bot.message_handler(commands=["show_config"])
    async def show_config(message):
        # 打印当前配置（方便排障）
        text = (
            f"debug: {ctx.cfg.debug}\n"
            f"enable_ipv6: {ctx.cfg.enable_ipv6}\n"
            f"download_path: {ctx.cfg.download_path}\n"
            f"proxy_url: {ctx.cfg.proxy_url}\n"
            f"tags: {ctx.cfg.tags}\n"
            f"bot.max_concurrency: {ctx.cfg.bot_max_concurrency}\n"
            f"tdl.path: {ctx.cfg.tdl_path}\n"
            f"tdl.limit: {ctx.cfg.tdl_limit}\n"
            f"tdl.threads: {ctx.cfg.tdl_threads}\n"
            f"tdl.delay: {ctx.cfg.tdl_delay}\n"
            f"tdl.reconnect_timeout: {ctx.cfg.tdl_reconnect_timeout}\n"
            f"download.group: {ctx.cfg.download_group}\n"
            f"download.skip_same: {ctx.cfg.download_skip_same}\n"
            f"download.rewrite_ext: {ctx.cfg.download_rewrite_ext}\n"
            f"download.include: {ctx.cfg.download_include}\n"
            f"download.exclude: {ctx.cfg.download_exclude}\n"
            f"download.template: {ctx.cfg.download_template}\n"
            f"download.takeout: {ctx.cfg.download_takeout}\n"
            f"download.desc: {ctx.cfg.download_desc}\n"
            f"download.serve: {ctx.cfg.download_serve}\n"
            f"upload.enabled: {ctx.cfg.upload_enabled}"
        )
        await bot.send_message(message.chat.id, text)

    @bot.message_handler(func=lambda message: True)
    async def split_links(message):
        # 一条消息可能包含多个 link，因此逐条回复
        for link in extract_links(message.text):
            btns = TagButtons(ctx.cfg.tags, link)
            await bot.reply_to(message, text=f"{link}\nchoose tag: ", reply_markup=btns.build())

    @bot.callback_query_handler(func=lambda call: True)
    async def callback_query(call):
        # callback_data 格式统一为 "<action>#<link>"
        cb, link = call.data.split("#", 1)

        if cb == "cancel":
            await bot.answer_callback_query(call.id)
            await bot.reply_to(call.message, text="Canceled")
            return

        # retry 格式：retry|<tag>#<link>
        if cb.startswith("retry|"):
            tag = cb.split("|", 1)[1]
            if tag in ctx.cfg.tags:
                await bot.answer_callback_query(call.id)

                path = os.path.join(ctx.cfg.download_path, tag)
                dltask = DownloadTask(link=link, tag=tag, path=path, proxy_url=ctx.cfg.proxy_url)

                msg = await bot.edit_message_text(
                    f"{link}\nWill be downloaded into: {dltask.path}",
                    chat_id=call.message.chat.id,
                    message_id=call.message.id,
                )

                worker = Worker(ctx, dltask, msg)
                await asyncio.gather(worker.call_tdl())
            else:
                await bot.answer_callback_query(call.id)
                await bot.reply_to(call.message, text=f"Unknown tag: {tag}")
            return

        # tag 下载
        if cb in ctx.cfg.tags:
            path = os.path.join(ctx.cfg.download_path, cb)
            dltask = DownloadTask(link=link, tag=cb, path=path, proxy_url=ctx.cfg.proxy_url)

            await bot.answer_callback_query(call.id)
            msg = await bot.edit_message_text(
                f"{link}\nWill be downloaded into: {dltask.path}",
                chat_id=call.message.chat.id,
                message_id=call.message.id,
            )

            worker = Worker(ctx, dltask, msg)
            await asyncio.gather(worker.call_tdl())


async def run_polling(ctx: BotContext) -> None:
    """启动 polling（阻塞运行）。"""
    register_handlers(ctx)
    await ctx.bot.polling()
