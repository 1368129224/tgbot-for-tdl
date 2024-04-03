import re
import os
import sys
import math
import asyncio
import logging
import logging.handlers
import subprocess
import tomlkit
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import filters, MessageHandler, ApplicationBuilder, ContextTypes, \
                        CommandHandler, CallbackQueryHandler

# global
CFG_PATH = 'tdl_bot_config.toml'
RE_STR = r'\x1b\[[0-9;]*[a-zA-Z]'
KEYBOARD_MAX_ROW_LEN = 6
KEYBOARD_MAX_COL_LEN = 4
KEYBOARD_MAX_ONE_PAGE_LEN = KEYBOARD_MAX_ROW_LEN * KEYBOARD_MAX_COL_LEN

g_config = {
    "debug": "False",
    "bot_token": "123456789:abcdefghijk",
    "download_path": "/path/to/save/download/media",
    "proxy_url": "httpx://USERNAME:PASSWORD@PROXY_HOST:PROXY_PORT",
    "tags": ['dog', 'cat']
}


# enable python-telegram-bot logging
logging.basicConfig(
    style="{",
    format="{asctime} {levelname:<8} {funcName}:{lineno} {message}",
    datefmt="%m-%d %H:%M:%S",
    level=logging.INFO
)

# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
formatter = logging.Formatter(
    style="{",
    fmt="{asctime} {levelname:<8} {funcName}:{lineno} {message}",
    datefmt="%m-%d %H:%M:%S"
)

file_handler = logging.handlers.RotatingFileHandler(
    filename='tdl_bot.log',maxBytes=1 * 1024 * 1024, backupCount=3,
    encoding='utf-8')
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)
logger.addHandler(file_handler)


def get_config():
    if not os.path.isfile(CFG_PATH):
        logger.info("Config file not found, generating default config.")
        generate_config()
        sys.exit()
    with open(CFG_PATH, 'r', encoding='utf-8') as f:
        config = tomlkit.loads(f.read())
    g_config["debug"] = config["debug"]
    g_config["bot_token"] = config["bot_token"]
    g_config["download_path"] = config["download_path"]
    g_config["proxy_url"] = config["proxy_url"]
    g_config["tags"] = config["tags"]
    logger.debug(
        f"config: \n\
          * debug: {g_config['debug']}\n\
          * download_path: {g_config['download_path']}\n\
          * proxy_url: {g_config['proxy_url']}\n\
          * tags: {g_config['tags']}")

def generate_config():
    doc = tomlkit.document()
    doc.add(tomlkit.comment("*** TDL telegram bot ***"))
    doc.add(tomlkit.comment("TDL: https://github.com/iyear/tdl"))
    doc.add(tomlkit.nl())
    doc.add("debug", g_config["debug"])
    doc.add("bot_token", g_config["bot_token"])
    doc.add("download_path", g_config["download_path"])
    doc.add("proxy_url", g_config["proxy_url"])
    doc.add(tomlkit.nl())
    doc.add(tomlkit.comment(
        "To use socks proxy, need to install extra python package:"))
    doc.add(tomlkit.comment("pip install python-telegram-bot[socks]"))
    doc.add(tomlkit.comment("and set socks proxy:"))
    doc.add(tomlkit.comment("proxy_url = \"socks5://user:pass@host:port\""))
    doc.add(tomlkit.nl())
    doc.add("tags", g_config["tags"])
    with open(CFG_PATH, 'w', encoding='utf-8') as f:
        tomlkit.dump(doc, f)
    logger.info(f"The default configuration {CFG_PATH} is generated.")
    sys.exit()


class Keyborad():
    def __init__(self, tags, msg_id) -> None:
        self.tags = tags
        self.msg_id = msg_id
        self.tags_len = len(tags)
        self.is_single_page = self.tags_len <= KEYBOARD_MAX_ONE_PAGE_LEN
        self.keyboard = []
        self.get_keyboard()

    def multiple_navigator(self):
        return [InlineKeyboardButton("prev", callback_data=f"prev#{str(self.msg_id)}"),
                InlineKeyboardButton("cancel", callback_data=f"cancel#{str(self.msg_id)}"),
                InlineKeyboardButton("next", callback_data=f"next#{str(self.msg_id)}")]
    def single_navigator(self):
        return [InlineKeyboardButton("cancel", callback_data=f"cancel#{str(self.msg_id)}")]

    def button(self, text, callback_data):
        return InlineKeyboardButton(text=text, callback_data=f"{callback_data}#{self.msg_id}")

    def get_keyboard(self):
        row = []
        page = []
        if self.is_single_page:
            for i in range(self.tags_len):
                row.append(self.button(self.tags[i], self.tags[i]))
                if len(row) == KEYBOARD_MAX_ROW_LEN:
                    page.append(row)
                    logger.debug(f"row: {row}, page: {page}")
                    row = []
                if i == self.tags_len - 1:
                    page.append(row)
                    logger.debug(f"page: {page}")
                    page.append(self.single_navigator())
                    self.keyboard.append(page)
        else:
            for i in range(self.tags_len):
                row.append(self.button(self.tags[i], self.tags[i]))
                if len(row) == KEYBOARD_MAX_ROW_LEN:
                    page.append(row)
                    logger.debug(f"row: {row}, page: {page}")
                    row = []
                if len(page) == KEYBOARD_MAX_COL_LEN:
                    logger.debug(f"page: {page}")
                    page.append(self.multiple_navigator())
                    self.keyboard.append(page)
                    page = []
                if i == self.tags_len - 1:
                    page.append(row)
                    page.append(self.multiple_navigator())
                    self.keyboard.append(page)


class Downloader():
    def __init__(self, url, msg_id, proxy_url, base_path="") -> None:
        self.current_page = 0
        self.last_page = math.ceil(len(g_config["tags"]) / KEYBOARD_MAX_ONE_PAGE_LEN)
        self.url = url
        self.msg_id = msg_id
        self.proxy_url = proxy_url
        self.base_path = base_path
        self.keyboard = Keyborad(g_config["tags"], self.msg_id).keyboard
        logger.debug(f"self.keyboard: {self.keyboard}")

    async def tdl(self):
        return subprocess.Popen(
            ["/usr/local/bin/tdl", "dl", "-u", f"{self.url}", "--proxy", f"{self.proxy_url}",
             "-d", f"{self.base_path}"],
             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    async def download(self):
        if os.path.exists(self.base_path) is False:
            try:
                os.mkdir(self.base_path)
                logger.debug(f"The directory {self.base_path} has been created.")
            except FileExistsError:
                logger.debug(f"The directory {self.base_path} already exists.")
                return (False, "create directory failed")
        proc = await asyncio.create_subprocess_shell(
            f"/usr/local/bin/tdl dl -u {self.url} --proxy {self.proxy_url} -d {self.base_path}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        result = await asyncio.gather(proc.wait(), proc.stdout.read())
        output = result[1].decode()
        output = re.sub(RE_STR, '', output)
        output = output.split('\n')[-2]
        logger.debug(f"proc.returncode: {proc.returncode}, output: [{output}]")
        if proc.returncode != 0:
            return (False, output)
        return (True, output)


async def show_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"debug: {g_config['debug']}\ndownload_path: {g_config['download_path']}\n\
        proxy_url: {g_config['proxy_url']}\ntags: {g_config['tags']}")

async def video_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = str(update.message.message_id)
    downloader = Downloader(update.message.text, msg_id, g_config["proxy_url"])
    logger.info(f"msg_id: {msg_id} download: {downloader.url}")

    reply_markup = InlineKeyboardMarkup(
        downloader.keyboard[downloader.current_page])
    if downloader.url.startswith("https://t.me/"):
        logger.debug(f"create downloader, msg_id: {msg_id}")
        context.user_data[msg_id] = downloader
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="select tag: ", reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="URL check failed")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=downloader.url)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        logger.error("update.callback_query is None.")
        return
    query = update.callback_query
    choose_data = query.data.split("#")[0]
    msg_id = query.data.split("#")[1]
    logger.debug(f"msg_id: {msg_id}, downloader obj: {context.user_data[msg_id]}")
    downloader = context.user_data.get(msg_id, None)
    if downloader is None:
        logger.error(f"downloader not found, msg_id: {msg_id}")
        await query.answer()
        await query.edit_message_text(text=f"downloader not found, msg_id: {msg_id}")
        return
    if choose_data in ["cancel", "prev", "next"]:
        if choose_data == "cancel":
            logger.info(f"download canceled: {downloader.url}")
            await query.answer()
            await query.edit_message_text(text="canceled")
        elif choose_data == "prev":
            if downloader.current_page == 0:
                await query.answer()
                return
            downloader.current_page -= 1
            reply_markup = InlineKeyboardMarkup(
                downloader.keyboard[downloader.current_page])
            await query.answer()
            await query.edit_message_text(text="select tag:", reply_markup=reply_markup)
        elif choose_data == "next":
            if downloader.current_page == downloader.last_page:
                await query.answer()
                return
            downloader.current_page += 1
            reply_markup = InlineKeyboardMarkup(
                downloader.keyboard[downloader.current_page])
            await query.answer()
            await query.edit_message_text(text="select tag:", reply_markup=reply_markup)
        return
    sub_path = "/" + choose_data
    full_path = g_config["download_path"] + sub_path
    downloader.base_path = full_path
    await query.answer()
    await query.edit_message_text(text=f"file will be download into: {full_path}")
    logger.debug(
        f"download url: {downloader.url}, path: {full_path}, proxy_url: {downloader.proxy_url}")
    result = await asyncio.gather(downloader.download())
    logger.debug(f"result:\n[{result}]")
    tmp_msg = result[0][1].replace("\n", '')
    tmp_msg = re.sub(RE_STR, '', tmp_msg)
    if result[0][0] is False:
        msg = f"download failed: \n{tmp_msg}"
        logger.warning(f"download failed: {tmp_msg}")
    else:
        context.user_data.pop(msg_id, None)
        msg = f"download succeed: \n{tmp_msg}"
        logger.info(f"download succeed: {tmp_msg}")
    logger.debug(f"reply msg:\n[{msg}]")
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=msg, reply_to_message_id=downloader.msg_id)


if __name__ == '__main__':
    get_config()
    if g_config["debug"] == "True":
        logger.setLevel(logging.DEBUG)
    logger.info(f"logging level: {logger.getEffectiveLevel()}")

    application = ApplicationBuilder().connect_timeout(3).token(g_config["bot_token"]).proxy(
        g_config["proxy_url"]).get_updates_proxy(g_config["proxy_url"]).build()

    application.add_handler(CommandHandler("show_config", show_config))
    application.add_handler(MessageHandler(
        filters.TEXT & (~filters.COMMAND), video_link, block=False))
    application.add_handler(CallbackQueryHandler(button, block=False))

    application.run_polling(allowed_updates=Update.ALL_TYPES)
