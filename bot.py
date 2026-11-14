import asyncio
import json
import logging
import os
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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


class Form(StatesGroup):
    nick = State()


def tg(u):
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
async def start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Form.nick)
    await m.answer("Sálem! 👋 Instagram nikińizdi jazıń (mısalı: @nikiniz)")


@dp.message(Form.nick, F.text)
async def get_nick(m: Message, state: FSMContext):
    n = m.text.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", n):
        await m.answer("❌ Nik duris emes. Tek Instagram nikińizdi jazıń (mısalı: @nikiniz)")
        return
    await state.update_data(nick=n)
    await state.set_state(None)
    await m.answer("Qanday úy qurasız?", reply_markup=keyboard())


@dp.callback_query(F.data.startswith("t:"))
async def choose(c: CallbackQuery, state: FSMContext):
    code = c.data[2:]
    data = await state.get_data()
    n = data.get("nick")
    if code not in TYPES or not n:
        await c.answer("/start basıń", show_alert=True)
        return
    row = json.dumps({"n": n, "t": code}, ensure_ascii=False)
    text = (
        "🏠 Jańa úy\n"
        "📸 Instagram: @" + n + "\n"
        "🏡 " + TYPES[code] + "\n"
        "👤 Telegram: " + tg(c.from_user) + "\n\n" + row
    )
    await bot.send_message(OWNER_ID, text)
    await c.message.edit_text(
        "✅ Qabıl etildi!\n"
        "📸 @" + n + "\n"
        "🏡 " + TYPES[code] + "\n\n"
        "Úyińiz tez arada saytqa qosıladı.\n"
        "📷 Fotońızdı jibere alasız (májbúriy emes)."
    )
    await c.answer()


@dp.message(F.photo)
async def photo(m: Message, state: FSMContext):
    data = await state.get_data()
    n = data.get("nick")
    who = "@" + n if n else tg(m.from_user)
    await bot.send_photo(
        OWNER_ID,
        m.photo[-1].file_id,
        caption="📷 Foto: " + who,
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
