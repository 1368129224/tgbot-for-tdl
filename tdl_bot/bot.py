"""Telegram Bot 逻辑层。

本模块负责：
- 解析用户消息中的 Telegram 链接
- 生成按钮（tag 选择、失败重试、下载取消）
- 调用 tdl 执行下载，并把进度/结果反馈给用户

设计原则：
- bot 只负责"编排与反馈"，实际下载能力尽量交给 tdl
- 默认行为尽量保守（并发默认 1），避免资源争抢/限流
"""

import asyncio
import os
import socket
import time
from dataclasses import dataclass

from telebot import asyncio_helper
from telebot.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telebot.async_telebot import AsyncTeleBot

from .config import BotConfig, save_config
from .constants import (
    PROGRESS_INTERVAL,
    KEYBOARD_MAX_ROW_LEN,
    KEYBOARD_MAX_ONE_PAGE_LEN,
)
from .tdl import DownloadTask, build_download_args, parse_progress, parse_done

# 跟踪活跃下载任务，key 为 "{chat_id}_{msg_id}"
_active_workers: dict[str, "Worker"] = {}

# 排队中的任务计数
_pending_count: int = 0

# 配置编辑状态: chat_id -> 正在编辑的字段名
_config_edit_state: dict[int, str] = {}


def _elapsed_str(start: float) -> str:
    """格式化已用时间为 mm:ss 或 HH:MM:SS。"""
    secs = int(time.time() - start)
    if secs < 3600:
        return f"{secs // 60:02d}:{secs % 60:02d}"
    return f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"


@dataclass
class BotContext:
    """运行上下文：配置 + bot 实例 + logger。"""

    cfg: BotConfig
    bot: AsyncTeleBot
    logger: any


class TagButtons:
    """tag 选择按钮，支持分页。

    callback_data 形式：
    - "<tag>#<link>" 或 "cancel#<link>"
    - 分页: "page:<page_num>#<link>"
    """

    def __init__(self, tags: list[str], link: str, page: int = 0):
        self.tags = tags
        self.link = link
        self.page = page

    def _btn(self, text: str, callback_data: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=f"{callback_data}#{self.link}")

    def build(self) -> InlineKeyboardMarkup:
        """构建 tag 键盘，tags 超过一页时自动分页。"""
        markup = InlineKeyboardMarkup()
        markup.row_width = KEYBOARD_MAX_ROW_LEN

        page_size = KEYBOARD_MAX_ONE_PAGE_LEN
        total_pages = max(1, (len(self.tags) + page_size - 1) // page_size)
        page = max(0, min(self.page, total_pages - 1))
        start = page * KEYBOARD_MAX_ONE_PAGE_LEN
        end = min(start + KEYBOARD_MAX_ONE_PAGE_LEN, len(self.tags))
        page_tags = self.tags[start:end]

        row: list[InlineKeyboardButton] = []
        for tag in page_tags:
            row.append(self._btn(tag, tag))
            if len(row) == KEYBOARD_MAX_ROW_LEN:
                markup.add(*row)
                row = []
        if row:
            markup.add(*row)

        # 分页按钮
        if total_pages > 1:
            nav_row: list[InlineKeyboardButton] = []
            if page > 0:
                cb = f"page:{page - 1}#{self.link}"
                nav_row.append(
                    InlineKeyboardButton(text="< prev", callback_data=cb)
                )
            nav_row.append(
                InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")
            )
            if page < total_pages - 1:
                cb = f"page:{page + 1}#{self.link}"
                nav_row.append(
                    InlineKeyboardButton(text="next >", callback_data=cb)
                )
            markup.add(*nav_row)

        markup.add(self._btn("cancel", "cancel"))
        return markup


class RetryButtons:
    """下载失败后的重试/取消按钮。"""

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


class CancelDownloadButton:
    """下载中的取消按钮。"""

    def __init__(self, key: str):
        self.key = key

    def build(self) -> InlineKeyboardMarkup:
        markup = InlineKeyboardMarkup()
        cb = f"cancel_download#{self.key}"
        markup.add(InlineKeyboardButton(text="cancel download", callback_data=cb))
        return markup


class Worker:
    """下载任务执行器。

    - 默认串行（semaphore=1）
    - 支持通过配置调整 bot 级并发
    """

    semaphore: asyncio.Semaphore | None = None

    def __init__(self, ctx: BotContext, task: DownloadTask, msg, key: str):
        import uuid

        self.ctx = ctx
        self.task = task
        self.msg = msg
        self.key = key
        self.task_id = uuid.uuid4().hex[:8]
        self.start_time: float = 0.0
        self.proc: asyncio.subprocess.Process | None = None
        self.cancelled: bool = False

    def _pfx(self) -> str:
        return f"task={self.task_id} link={self.task.link} tag={self.task.tag}"

    async def call_tdl(self) -> None:
        """调用 tdl 执行下载，并将进度/结果反馈给用户。"""
        global _pending_count

        sem = Worker.semaphore or asyncio.Semaphore(1)

        _pending_count += 1
        queue_pos = _pending_count
        try:
            await self.ctx.bot.edit_message_text(
                f"{self.task.link} tag: {self.task.tag}\nQueued (#{queue_pos}), waiting...",
                chat_id=self.msg.chat.id,
                message_id=self.msg.id,
            )
        except Exception:
            pass

        try:
            async with sem:
                _pending_count = max(0, _pending_count - 1)
                self.start_time = time.time()

                # 注册到活跃任务
                _active_workers[self.key] = self

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

                self.ctx.logger.info(
                    "%s Run tdl: %s %s",
                    self._pfx(),
                    self.ctx.cfg.tdl_path,
                    " ".join(args),
                )

                proc = await asyncio.create_subprocess_exec(
                    self.ctx.cfg.tdl_path,
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                self.proc = proc

                # 更新为下载中状态
                elapsed = _elapsed_str(self.start_time)
                try:
                    dl_info = f"{self.task.link} tag: {self.task.tag}"
                    await self.ctx.bot.edit_message_text(
                        f"{dl_info}\nDownloading...\nElapsed: {elapsed}",
                        chat_id=self.msg.chat.id,
                        message_id=self.msg.id,
                        reply_markup=CancelDownloadButton(self.key).build(),
                    )
                except Exception:
                    pass

                j = 0
                last_lines: list[str] = []

                if not proc.stdout:
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
                    last_lines.append(line)
                    if len(last_lines) > 30:
                        last_lines = last_lines[-30:]

                    done = parse_done(line)
                    if done:
                        self.ctx.logger.info("%s Download done: %s", self._pfx(), done)
                        elapsed = _elapsed_str(self.start_time)
                        dl_info = f"{self.task.link} tag: {self.task.tag}"
                        await self.ctx.bot.edit_message_text(
                            f"{dl_info}\nDownload {done}\nElapsed: {elapsed}",
                            chat_id=self.msg.chat.id,
                            message_id=self.msg.id,
                        )
                        continue

                    progress = parse_progress(line)
                    if not progress:
                        continue

                    pct, speed = progress
                    try:
                        if j >= PROGRESS_INTERVAL:
                            elapsed = _elapsed_str(self.start_time)
                            await self.ctx.bot.edit_message_text(
                                f"{self.task.link} tag: {self.task.tag}\n"
                                f"Downloading: {pct} {speed}\n"
                                f"Elapsed: {elapsed}",
                                chat_id=self.msg.chat.id,
                                message_id=self.msg.id,
                                reply_markup=CancelDownloadButton(self.key).build(),
                            )
                            j = 0
                        else:
                            j += 1

                        self.ctx.logger.debug("%s Downloading: %s %s", self._pfx(), pct, speed)
                    except Exception as e:
                        self.ctx.logger.error("%s edit_message failed: %s", self._pfx(), e)

                await proc.wait()
                rc = proc.returncode
                self.ctx.logger.info("%s Download returncode %s", self._pfx(), rc)

                if self.cancelled:
                    return

                if rc and rc != 0:
                    self.ctx.logger.warning(
                        "%s Last output:\n%s",
                        self._pfx(),
                        "".join(last_lines[-10:]),
                    )

                if rc and rc != 0:
                    from .tdl import summarize_error

                    summary = summarize_error(last_lines)
                    await self.ctx.bot.edit_message_text(
                        f"{self.task.link} tag: {self.task.tag}\nFailed (rc={rc}): {summary}",
                        chat_id=self.msg.chat.id,
                        message_id=self.msg.id,
                        reply_markup=RetryButtons(self.task.link, self.task.tag).build(),
                    )
        finally:
            _active_workers.pop(self.key, None)

    async def cancel(self) -> None:
        """取消正在进行的下载。"""
        self.cancelled = True
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
            except ProcessLookupError:
                pass
        elapsed = _elapsed_str(self.start_time) if self.start_time else "00:00"
        try:
            await self.ctx.bot.edit_message_text(
                f"{self.task.link} tag: {self.task.tag}\nCancelled\nElapsed: {elapsed}",
                chat_id=self.msg.chat.id,
                message_id=self.msg.id,
            )
        except Exception:
            pass


def extract_links(text: str) -> list[str]:
    """从用户文本中提取 Telegram 消息链接。"""
    import re

    if not text:
        return []

    candidates = re.findall(r"https://t\.me/\S+", text)

    def normalize(url: str) -> str:
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
    if not cfg.enable_ipv6:
        socket.AF_INET6 = False

    if cfg.proxy_url:
        asyncio_helper.proxy = cfg.proxy_url

    return AsyncTeleBot(cfg.bot_token)


def register_handlers(ctx: BotContext) -> None:
    """注册消息处理器与回调处理器。"""
    bot = ctx.bot

    @bot.message_handler(commands=["help", "start"])
    async def start_help(message):
        text = (
            "Supported commands:\n"
            "/help — display help message\n"
            "/config — edit bot settings\n"
            "/status — show active downloads\n"
            "/show_config — display bot config\n\n"
            "How to use:\n"
            "Send message link(s) to bot and select a tag, "
            "the download will be performed automatically."
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

    def _config_text() -> str:
        proxy = ctx.cfg.proxy_url or "not set"
        ipv6 = "ON" if ctx.cfg.enable_ipv6 else "OFF"
        tags = ", ".join(ctx.cfg.tags) if ctx.cfg.tags else "none"
        return (
            f"Download path: {ctx.cfg.download_path}\n"
            f"Proxy: {proxy}\n"
            f"Tags: {tags}\n"
            f"IPv6: {ipv6}"
        )

    def _config_kb() -> InlineKeyboardMarkup:
        kb = InlineKeyboardMarkup()
        kb.row(
            InlineKeyboardButton("Edit Download Path", callback_data="cfg:download_path"),
            InlineKeyboardButton("Edit Proxy", callback_data="cfg:proxy_url"),
        )
        ipv6_label = "IPv6: ON" if ctx.cfg.enable_ipv6 else "IPv6: OFF"
        kb.row(
            InlineKeyboardButton("Edit Tags", callback_data="cfg:tags"),
            InlineKeyboardButton(ipv6_label, callback_data="cfg:ipv6"),
        )
        return kb

    @bot.message_handler(commands=["config"])
    async def config_cmd(message):
        _config_edit_state.pop(message.chat.id, None)
        await bot.send_message(
            message.chat.id,
            f"Current config:\n{_config_text()}",
            reply_markup=_config_kb(),
        )

    @bot.message_handler(commands=["status"])
    async def status(message):
        if not _active_workers:
            await bot.reply_to(message, "No active downloads.")
            return

        lines = ["Active downloads:"]
        for worker in _active_workers.values():
            elapsed = _elapsed_str(worker.start_time) if worker.start_time else "pending"
            lines.append(f"- {worker.task.link} tag: {worker.task.tag} ({elapsed})")
        await bot.reply_to(message, "\n".join(lines))

    @bot.message_handler(func=lambda m: m.chat.id in _config_edit_state)
    async def handle_config_input(message):
        field = _config_edit_state.pop(message.chat.id)
        val = (message.text or "").strip()

        if field == "download_path":
            if not val:
                await bot.reply_to(message, "Path cannot be empty. Cancelled.")
                return
            ctx.cfg.download_path = val
            os.makedirs(val, exist_ok=True)
            await bot.reply_to(message, f"Download path updated: {val}")

        elif field == "proxy_url":
            if val == "-":
                ctx.cfg.proxy_url = None
                await bot.reply_to(message, "Proxy cleared.")
            else:
                ctx.cfg.proxy_url = val if val else None
                await bot.reply_to(message, f"Proxy updated: {val or 'not set'}")

        elif field == "tags":
            new_tags = [t.strip() for t in val.split(",") if t.strip()]
            if not new_tags:
                await bot.reply_to(message, "Tags cannot be empty. Cancelled.")
                return
            ctx.cfg.tags = new_tags
            await bot.reply_to(message, f"Tags updated: {', '.join(new_tags)}")

        save_config(ctx.cfg)
        await bot.send_message(
            message.chat.id,
            f"Config saved.\n{_config_text()}",
            reply_markup=_config_kb(),
        )

    @bot.message_handler(func=lambda message: True)
    async def split_links(message):
        links = extract_links(message.text)
        if not links:
            await bot.reply_to(message, "No Telegram message links found. Send a t.me/... link.")
            return
        for link in links:
            btns = TagButtons(ctx.cfg.tags, link)
            await bot.reply_to(message, text=f"{link}\nchoose tag: ", reply_markup=btns.build())

    @bot.callback_query_handler(func=lambda call: True)
    async def callback_query(call):
        cb_data: str = call.data

        # noop
        if cb_data == "noop":
            await bot.answer_callback_query(call.id)
            return

        # 配置编辑按钮
        if cb_data.startswith("cfg:"):
            field = cb_data.split(":", 1)[1]

            if field == "ipv6":
                ctx.cfg.enable_ipv6 = not ctx.cfg.enable_ipv6
                save_config(ctx.cfg)
                await bot.answer_callback_query(
                    call.id, f"IPv6 {'enabled' if ctx.cfg.enable_ipv6 else 'disabled'}"
                )
                await bot.edit_message_text(
                    f"Current config:\n{_config_text()}",
                    chat_id=call.message.chat.id,
                    message_id=call.message.id,
                    reply_markup=_config_kb(),
                )
                return

            prompts = {
                "download_path": "Send new download path:",
                "proxy_url": "Send new proxy URL (or send '-' to clear):",
                "tags": "Send tags, comma-separated (e.g. music,video,doc):",
            }
            _config_edit_state[call.message.chat.id] = field
            await bot.answer_callback_query(call.id)
            await bot.send_message(call.message.chat.id, prompts.get(field, "Send new value:"))
            return

        # 取消正在进行的下载
        if cb_data.startswith("cancel_download#"):
            key = cb_data.split("#", 1)[1]
            worker = _active_workers.get(key)
            if worker:
                await bot.answer_callback_query(call.id, "Cancelling...")
                await worker.cancel()
            else:
                await bot.answer_callback_query(call.id, "Task not found or already finished")
            return

        # 分页切换
        if cb_data.startswith("page:"):
            rest = cb_data.split("#", 1)
            page_num = int(rest[0].split(":")[1])
            link = rest[1] if len(rest) > 1 else ""
            await bot.answer_callback_query(call.id)
            btns = TagButtons(ctx.cfg.tags, link, page=page_num)
            try:
                await bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.id,
                    reply_markup=btns.build(),
                )
            except Exception:
                pass
            return

        # 统一拆分: "<action>#<link>"
        cb, link = cb_data.split("#", 1)

        if cb == "cancel":
            await bot.answer_callback_query(call.id)
            await bot.reply_to(call.message, text="Canceled")
            return

        # retry 格式: retry|<tag>#<link>
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

                key = f"{msg.chat.id}_{msg.id}"
                worker = Worker(ctx, dltask, msg, key)
                await worker.call_tdl()
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

            key = f"{msg.chat.id}_{msg.id}"
            worker = Worker(ctx, dltask, msg, key)
            await worker.call_tdl()


async def run_polling(ctx: BotContext) -> None:
    """启动 polling（阻塞运行）。"""
    register_handlers(ctx)

    # 向 Telegram 注册命令菜单（用户输入 / 时可见）
    try:
        await ctx.bot.set_my_commands([
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Display help message"),
            BotCommand("config", "Edit bot settings"),
            BotCommand("status", "Show active downloads"),
            BotCommand("show_config", "Display bot config"),
        ])
    except Exception as e:
        ctx.logger.warning("Failed to set bot commands: %s", e)

    await ctx.bot.polling()
