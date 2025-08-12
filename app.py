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

# Constants
CFG_PATH = 'tdl_bot_config.toml'
RE_STR = r'\x1b\[[0-9;]*[a-zA-Z]'
PROGRESS_INTERVAL = 10
KEYBOARD_MAX_ROW_LEN = 6
KEYBOARD_MAX_COL_LEN = 4
KEYBOARD_MAX_ONE_PAGE_LEN = KEYBOARD_MAX_ROW_LEN * KEYBOARD_MAX_COL_LEN

class BotConfig:
    def __init__(self):
        self._config_path = CFG_PATH
        self._defaults = {
            "debug": False,
            "enable_ipv6": False,
            "bot_token": "",
            "download_path": "",
            "proxy_url": None,
            "tags": []
        }
        self._config = self._load_or_create_config()
        self._validate_config()

    def _load_or_create_config(self):
        if not os.path.isfile(self._config_path):
            self._generate_default_config()
            return None
        
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                return tomlkit.loads(f.read())
        except (IOError, OSError) as e:
            raise ValueError(f"Failed to read config file: {e}")
        except tomlkit.exceptions.TOMLKitError as e:
            raise ValueError(f"Invalid TOML format in config file: {e}")

    def _generate_default_config(self):
        doc = tomlkit.document()
        doc.add(tomlkit.comment("*** TDL telegram bot ***"))
        doc.add(tomlkit.comment("TDL: https://github.com/iyear/tdl"))
        doc.add(tomlkit.nl())
        doc.add("debug", tomlkit.item(self._defaults["debug"]))
        doc.add("enable_ipv6", tomlkit.item(self._defaults["enable_ipv6"]))
        doc.add("bot_token", tomlkit.item(self._defaults["bot_token"]))
        doc.add("download_path", tomlkit.item(self._defaults["download_path"]))
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("This proxy will be used for both telegram bot and tdl"))
        doc.add(tomlkit.comment("If you don't need proxy, please remove the proxy_url keyword"))
        doc.add("proxy_url", tomlkit.item(self._defaults["proxy_url"]))
        doc.add(tomlkit.nl())
        doc.add(tomlkit.comment("To use socks proxy, need to install extra python package:"))
        doc.add(tomlkit.comment("pip install python-telegram-bot[socks]"))
        doc.add(tomlkit.comment("and set socks proxy:"))
        doc.add(tomlkit.comment("proxy_url = \"socks5://user:pass@host:port\""))
        doc.add(tomlkit.nl())
        doc.add("tags", tomlkit.item(self._defaults["tags"]))
        try:
            with open(self._config_path, 'w', encoding='utf-8') as f:
                tomlkit.dump(doc, f)
            logging.info(f"Generated default config at {self._config_path}")
            sys.exit()
        except (IOError, OSError) as e:
            raise ValueError(f"Failed to write config file: {e}")

    def _validate_config(self):
        if not self._config.get("bot_token") or not self._config.get("bot_token").strip():
            raise ValueError("Bot token is required and cannot be empty")
        
        download_path = self._config.get("download_path")
        if not download_path or not download_path.strip():
            raise ValueError("Download path is required and cannot be empty")

        if not os.path.exists(download_path):
            try:
                os.makedirs(download_path, exist_ok=True)
            except OSError as e:
                raise ValueError(f"Cannot create download path {download_path}: {e}")

    @property
    def debug(self):
        return str(self._config.get("debug", self._defaults["debug"]))

    @property
    def enable_ipv6(self):
        return str(self._config.get("enable_ipv6", self._defaults["enable_ipv6"]))

    @property
    def bot_token(self):
        return self._config.get("bot_token", self._defaults["bot_token"])

    @property
    def download_path(self):
        return self._config.get("download_path", self._defaults["download_path"])

    @property
    def proxy_url(self):
        return self._config.get("proxy_url", self._defaults["proxy_url"])

    @property
    def tags(self):
        return self._config.get("tags", self._defaults["tags"])

config = BotConfig()

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


class TagBtn():
    def __init__(self, link):
        self.tag_len = len(config.tags)
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
            row.append(self.button(config.tags[i], config.tags[i]))
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
        self.path = os.path.join(config.download_path, tag)
        self.proxy_url = config.proxy_url

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
    if config.debug == "True":
        logger.setLevel(logging.DEBUG)
    if config.enable_ipv6 == "False":
        socket.AF_INET6 = False
    if config.proxy_url is not None:
        asyncio_helper.proxy = config.proxy_url
    logger.info(f"logging level: {logger.getEffectiveLevel()}")

    bot = AsyncTeleBot(config.bot_token)

    @bot.message_handler(commands=['help', 'start'])
    async def start_help(message):
        text = """Supported command:\n/help to display help message.\n/show_config to display bot config.\n\nHow to use:\nSend message link to bot and select the tag, the download will be performed automatically."""
        await bot.reply_to(message, text)
    
    @bot.message_handler(commands=['show_config'])
    async def show_config(message):
        text = f"debug: {config.debug}\nenable_ipv6: {config.enable_ipv6}\ndownload_path: {config.download_path}\nproxy_url: {config.proxy_url}\ntags: {config.tags}"
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
        if cb in config.tags:
            dltask = DownloadTask(link, cb)
            await bot.answer_callback_query(call.id)
            msg = await bot.edit_message_text(f"{link}\nWill be downloaded into: {dltask.path}", chat_id=call.message.chat.id, message_id=call.message.id)
            worker = Worker(dltask, msg)
            await asyncio.gather(worker.call_tdl(bot))

    asyncio.run(bot.polling())
