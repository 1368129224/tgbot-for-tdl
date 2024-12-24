import os
import re
import sys
import socket
import asyncio
import logging
import logging.handlers
import tomlkit

from telebot import asyncio_helper
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from telebot.async_telebot import AsyncTeleBot

# global
CFG_PATH = 'tdl_bot_config.toml'
RE_STR = r'\x1b\[[0-9;]*[a-zA-Z]'
PROGRESS_INTERVAL = 10
KEYBOARD_MAX_ROW_LEN = 6
KEYBOARD_MAX_COL_LEN = 4
KEYBOARD_MAX_ONE_PAGE_LEN = KEYBOARD_MAX_ROW_LEN * KEYBOARD_MAX_COL_LEN

g_config = {
    "debug": "False",
    "enable_ipv6": "False",
    "bot_token": "123456789:abcdefghijk",
    "download_path": "/path/to/save/download/media",
    "proxy_url": "httpx://USERNAME:PASSWORD@PROXY_HOST:PROXY_PORT",
    "tags": ['dog', 'cat']
}

logging.basicConfig(
    style="{",
    format="{asctime} {levelname:<8} {funcName}:{lineno} {message}",
    datefmt="%m-%d %H:%M:%S",
    level=logging.DEBUG
)

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
    g_config["enable_ipv6"] = config["enable_ipv6"]
    g_config["bot_token"] = config["bot_token"]
    g_config["download_path"] = config["download_path"]
    g_config["proxy_url"] = config.get("proxy_url", None)
    g_config["tags"] = config["tags"]
    logger.debug(
        f"""
* debug: {g_config['debug']}
* enable_ipv6: {g_config['enable_ipv6']}
* download_path: {g_config['download_path']}
* proxy_url: {g_config['proxy_url']}
* tags: {g_config['tags']}""")

def generate_config():
    doc = tomlkit.document()
    doc.add(tomlkit.comment("*** TDL telegram bot ***"))
    doc.add(tomlkit.comment("TDL: https://github.com/iyear/tdl"))
    doc.add(tomlkit.nl())
    doc.add("debug", g_config["debug"])
    doc.add("enable_ipv6", g_config["enable_ipv6"])
    doc.add("bot_token", g_config["bot_token"])
    doc.add("download_path", g_config["download_path"])
    doc.add(tomlkit.nl())
    doc.add(tomlkit.comment("This proxy will be used for both telegram bot and tdl"))
    doc.add(tomlkit.comment("If you don't need proxy, please remove the proxy_url keyword"))
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


class TagBtn():
    def __init__(self, link):
        self.tag_len = len(g_config["tags"])
        self.link = link
        self.retry_markup = None

    def button(self, text, callback_data):
        return InlineKeyboardButton(text=text, callback_data=callback_data + "#" + self.link)

    def get_retry_btns(self):
        markup = InlineKeyboardMarkup()
        markup.row_width = 2
        markup.add(self.button("retry", "retry"), self.button("cancel", "cancel"))
        self.retry_markup = markup

    def get_btns(self):
        markup = InlineKeyboardMarkup()
        markup.row_width = KEYBOARD_MAX_ROW_LEN
        row = []

        for i in range(self.tag_len):
            row.append(self.button(g_config["tags"][i], g_config["tags"][i]))
            if len(row) == KEYBOARD_MAX_ROW_LEN:
                markup.add(*row)
                row = []
            if i == self.tag_len - 1:
                markup.add(*row)
                markup.add(self.button("cancel", "cancel"))

        return markup

class DownloadTask():
    def __init__(self, link, tag):
        self.link = link
        self.tag = tag
        self.path = g_config["download_path"] + "/" + self.tag
        self.proxy_url = g_config["proxy_url"]

class Worker():
    lock = asyncio.Lock()

    def __init__(self, task, msg):
        self.task = task
        self.msg = msg

    async def call_tdl(self, bot):
        async with Worker.lock:
            proc = await asyncio.create_subprocess_shell(
                f"/usr/local/bin/tdl --debug dl -u {self.task.link} --proxy {self.task.proxy_url} -d {self.task.path} --reconnect-timeout 0",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            i = 0
            j = 0
            while True:
                if not proc.stdout:
                    logger.error(f'Call create_subprocess_shell() failed!')
                    break
                line = await proc.stdout.readline()
                line = line.decode()
                if line:
                    i = i + 1
                    if i == 10 or "done!" in line:
                        i = 0
                        line = re.sub(RE_STR, '', line)
                        if "done!" in line:
                            logger.info(f'Link: {self.task.link}')
                            logger.info(f'Download {line.split("...")[-1].strip()}')
                            await bot.edit_message_text(f'{self.task.link} tag: {self.task.tag}\nDownlaod {line.split("...")[-1].strip()}', chat_id=self.msg.chat.id, message_id=self.msg.id)
                        try:
                            if not line.startswith("CPU") and not line.startswith("[") and not line.startswith("All") and line != '':
                                process = line.split('...')[1].split()[0]
                                speed = line.split("...")[-1].split(";")[-1].strip().rstrip("]")
                                if j == PROGRESS_INTERVAL:
                                    await bot.edit_message_text(f'{self.task.link} tag: {self.task.tag}\nDownloading: {process + " " + speed}', chat_id=self.msg.chat.id, message_id=self.msg.id)
                                    j = 0
                                else:
                                    j = j + 1
                                logger.debug(f'Downloading: {process + " " + speed}')
                        except Exception as e:
                            logger.error(f'stdout: {line}\nerror: {e}')
                else:
                    break
            await proc.wait()
            logger.info(f'Download returncode {proc.returncode}')
        if proc.stderr:
            line = await proc.stderr.readline()
            line = line.decode()
            if line:
                logger.warning(f'Download stderr: {line}')
        if proc.stdout:
            line = await proc.stdout.readline()
            line = line.decode()
            if line:
                logger.warning(f'Download stdout: {line}')


if __name__ == "__main__":
    get_config()
    if g_config["debug"] == "True":
        logger.setLevel(logging.DEBUG)
    if g_config["enable_ipv6"] == "False":
        socket.AF_INET6 = False
    if g_config["proxy_url"] is not None:
        asyncio_helper.proxy = g_config["proxy_url"]
    logger.info(f"logging level: {logger.getEffectiveLevel()}")

    bot = AsyncTeleBot(g_config["bot_token"])

    @bot.message_handler(commands=['help', 'start'])
    async def start_help(message):
        text = """Supported command:\n/help to display help message.\n/show_config to display bot config.\n\nHow to use:\nSend message link to bot and select the tag, the download will be performed automatically."""
        await bot.reply_to(message, text)
    
    @bot.message_handler(commands=['show_config'])
    async def show_config(message):
        text = f"debug: {g_config.get('debug')}\nenable_ipv6: {g_config.get('enable_ipv6')}download_path: {g_config.get('download_path')}\nproxy_url: {g_config.get('proxy_url', None)}\ntags: {g_config.get('tags', None)}"
        await bot.send_message(message.chat.id, text)

    @bot.message_handler(func=lambda message: True)
    async def split_links(message):
        msgs = message.text.split()
        for link in msgs:
            if link.startswith("https://t.me/"):
                btns = TagBtn(link)
                msg = await bot.reply_to(message, text=f"{link}\nchoose tag: ", reply_markup=btns.get_btns())

    @bot.callback_query_handler(func=lambda call: True)
    async def callback_query(call):
        cb, link = call.data.split("#")
        if cb == "cancel":
            await bot.answer_callback_query(call.id)
            await bot.reply_to(call.message, text=f"Canceled")
        if cb in g_config["tags"]:
            dltask = DownloadTask(link, cb)
            await bot.answer_callback_query(call.id)
            msg = await bot.edit_message_text(f"{link}\nWill be downloaded into: {dltask.path}", chat_id=call.message.chat.id, message_id=call.message.id)
            worker = Worker(dltask, msg)
            await asyncio.gather(worker.call_tdl(bot))

    asyncio.run(bot.polling())
