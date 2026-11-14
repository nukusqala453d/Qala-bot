import asyncio
import json
import logging
import os

from aiogram import Bot, Dispatcher, F
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

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def nick(u):
    if u.username:
        return "@" + u.username
    return u.full_name + " (ID: " + str(u.id) + ")"


def keyboard():
    rows = [
        [InlineKeyboardButton(text=name, callback_data="t:" + code)]
        for code, name in TYPES.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("Sálem! 🏠 Qanday úy qurasız?", reply_markup=keyboard())


@dp.callback_query(F.data.startswith("t:"))
async def choose(c: CallbackQuery):
    code = c.data[2:]
    if code not in TYPES:
        await c.answer()
        return
    u = c.from_user
    row = json.dumps({"n": u.username or u.full_name, "t": code}, ensure_ascii=False)
    text = "🏠 Jańa úy\n👤 " + nick(u) + "\n🏡 " + TYPES[code] + "\n\n" + row
    await bot.send_message(OWNER_ID, text)
    await c.message.edit_text(
        "✅ Qabıl etildi!\n🏡 " + TYPES[code] + "\n\n"
        "Úyińiz tez arada saytqa qosıladı.\n"
        "📷 Fotońızdı jibere alasız (májbúriy emes)."
    )
    await c.answer()


@dp.message(F.photo)
async def photo(m: Message):
    await bot.send_photo(
        OWNER_ID,
        m.photo[-1].file_id,
        caption="📷 Foto: " + nick(m.from_user),
    )
    await m.answer("📷 Foto qabıl etildi!")


@dp.message()
async def other(m: Message):
    await m.answer("Úy tańlaw ushın /start basıń 🏠")


async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
