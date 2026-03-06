import asyncio
import os
import socket
from dataclasses import dataclass
from typing import Optional

from telebot import asyncio_helper
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from telebot.async_telebot import AsyncTeleBot

from .config import BotConfig
from .constants import (
    PROGRESS_INTERVAL,
    KEYBOARD_MAX_ROW_LEN,
)
from .tdl import DownloadTask, build_download_args, parse_progress, parse_done


@dataclass
class BotContext:
    cfg: BotConfig
    bot: AsyncTeleBot
    logger: any


class TagButtons:
    def __init__(self, tags: list[str], link: str):
        self.tags = tags
        self.link = link

    def _btn(self, text: str, callback_data: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=f"{callback_data}#{self.link}")


class RetryButtons:
    def __init__(self, link: str, tag: str):
        self.link = link
        self.tag = tag

    def build(self) -> InlineKeyboardMarkup:
        markup = InlineKeyboardMarkup()
        markup.row_width = 2
        markup.add(
            InlineKeyboardButton(text="retry", callback_data=f"retry|{self.tag}#{self.link}"),
            InlineKeyboardButton(text="cancel", callback_data=f"cancel#{self.link}"),
        )
        return markup

    def build(self) -> InlineKeyboardMarkup:
        markup = InlineKeyboardMarkup()
        markup.row_width = KEYBOARD_MAX_ROW_LEN
        row: list[InlineKeyboardButton] = []

        for i, tag in enumerate(self.tags):
            row.append(self._btn(tag, tag))
            if len(row) == KEYBOARD_MAX_ROW_LEN:
                markup.add(*row)
                row = []
            if i == len(self.tags) - 1:
                if row:
                    markup.add(*row)
                markup.add(self._btn("cancel", "cancel"))

        return markup


class Worker:
    # Default: single-thread downloads, but configurable via semaphore
    semaphore: asyncio.Semaphore | None = None

    def __init__(self, ctx: BotContext, task: DownloadTask, msg):
        import uuid

        self.ctx = ctx
        self.task = task
        self.msg = msg
        self.task_id = uuid.uuid4().hex[:8]

    def _pfx(self) -> str:
        return f"task={self.task_id} link={self.task.link} tag={self.task.tag}"

    async def call_tdl(self) -> None:
        """Run a tdl download and provide progress + final result to user.

        Requirements:
        - if download fails, send error cause to user + provide retry button
        """
        sem = Worker.semaphore or asyncio.Semaphore(1)
        async with sem:
            os.makedirs(self.task.path, exist_ok=True)

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
            self.ctx.logger.info("%s Run tdl: %s %s", self._pfx(), self.ctx.cfg.tdl_path, " ".join(args))

            proc = await asyncio.create_subprocess_exec(
                self.ctx.cfg.tdl_path,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            i = 0
            j = 0
            last_lines: list[str] = []

            if not proc.stdout:
                self.ctx.logger.error("%s create_subprocess_shell() returned no stdout", self._pfx())
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

                # keep a small tail for error reporting
                last_lines.append(line)
                if len(last_lines) > 30:
                    last_lines = last_lines[-30:]

                i += 1
                done = parse_done(line)
                if done:
                    self.ctx.logger.info("%s Download done: %s", self._pfx(), done)
                    await self.ctx.bot.edit_message_text(
                        f"{self.task.link} tag: {self.task.tag}\nDownlaod {done}",
                        chat_id=self.msg.chat.id,
                        message_id=self.msg.id,
                    )
                    continue

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
                    self.ctx.logger.error("%s stdout: %s\nerror: %s", self._pfx(), line, e)

            await proc.wait()
            rc = proc.returncode
            self.ctx.logger.info("%s Download returncode %s", self._pfx(), rc)

            if rc and rc != 0:
                # best-effort error summary for user
                from .tdl import summarize_error

                summary = summarize_error(last_lines)
                await self.ctx.bot.edit_message_text(
                    f"{self.task.link} tag: {self.task.tag}\nFailed (rc={rc}): {summary}",
                    chat_id=self.msg.chat.id,
                    message_id=self.msg.id,
                    reply_markup=RetryButtons(self.task.link, self.task.tag).build(),
                )
                return


def extract_links(text: str) -> list[str]:
    """Extract Telegram message links from free-form text.

    Improvements over legacy split():
    - regex-based extraction
    - strips common trailing punctuation
    - de-duplicates while preserving order
    """
    import re

    if not text:
        return []

    candidates = re.findall(r"https://t\.me/\S+", text)

    def normalize(url: str) -> str:
        # Strip trailing punctuation that users often paste with
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
    if not cfg.enable_ipv6:
        # preserve legacy behavior (best-effort)
        socket.AF_INET6 = False

    if cfg.proxy_url:
        asyncio_helper.proxy = cfg.proxy_url

    return AsyncTeleBot(cfg.bot_token)


def register_handlers(ctx: BotContext) -> None:
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
        for link in extract_links(message.text):
            btns = TagButtons(ctx.cfg.tags, link)
            await bot.reply_to(message, text=f"{link}\nchoose tag: ", reply_markup=btns.build())

    @bot.callback_query_handler(func=lambda call: True)
    async def callback_query(call):
        cb, link = call.data.split("#", 1)

        if cb == "cancel":
            await bot.answer_callback_query(call.id)
            await bot.reply_to(call.message, text="Canceled")
            return

        # Retry button encodes tag as: retry|<tag>#<link>
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

        if cb in ctx.cfg.tags:
            # build task
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
    register_handlers(ctx)
    await ctx.bot.polling()
