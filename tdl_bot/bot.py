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
from .tdl import DownloadTask, build_tdl_command, parse_progress, parse_done


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
    # Legacy behavior: single-thread downloads
    lock = asyncio.Lock()

    def __init__(self, ctx: BotContext, task: DownloadTask, msg):
        self.ctx = ctx
        self.task = task
        self.msg = msg

    async def call_tdl(self) -> None:
        async with Worker.lock:
            os.makedirs(self.task.path, exist_ok=True)

            cmd = build_tdl_command(
                tdl_path=self.ctx.cfg.tdl_path,
                task=self.task,
                extra_args=self.ctx.cfg.tdl_extra_args,
            )
            self.ctx.logger.info("Run tdl: %s", cmd)

            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            i = 0
            j = 0
            if not proc.stdout:
                self.ctx.logger.error("create_subprocess_shell() returned no stdout")
                return

            while True:
                line_b = await proc.stdout.readline()
                if not line_b:
                    break
                line = line_b.decode(errors="replace")

                i += 1
                done = parse_done(line)
                if done:
                    self.ctx.logger.info("Link: %s", self.task.link)
                    self.ctx.logger.info("Download done: %s", done)
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
                    self.ctx.logger.debug("Downloading: %s %s", process, speed)
                except Exception as e:
                    self.ctx.logger.error("stdout: %s\nerror: %s", line, e)

            await proc.wait()
            self.ctx.logger.info("Download returncode %s", proc.returncode)


def extract_links(text: str) -> list[str]:
    if not text:
        return []
    # Keep legacy behavior: split by whitespace; accept t.me links
    links: list[str] = []
    for token in text.split():
        if token.startswith("https://t.me/"):
            links.append(token)
    return links


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
            f"tdl_path: {ctx.cfg.tdl_path}\n"
            f"tdl_extra_args: {ctx.cfg.tdl_extra_args}"
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
