import asyncio
import html
import json
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

TYPES = {"y": "Qara úy", "h": "Apiwayı úy", "b": "Ekewi de"}

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


def nick(u) -> str:
    if u.username:
        return "@" + u.username
    return f'<a href="tg://user?id={u.id}">{html.escape(u.full_name)}
