import asyncio
import html
import json
import logging
import os
import re
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ---------------- SOZLAMALAR ----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "SIZIN_BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "123456789"))  # Ozinizdin Telegram ID-nizdi jazin
CARD_NUMBER = os.environ.get("CARD_NUMBER", "9860350149518655")
DB_PATH = os.environ.get("DB_PATH", "bot_database.db")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

esc = html.escape


# ---------------- BAZA (SQLite) ----------------
def conn_():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = conn_()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            instagram TEXT,
            has_house INTEGER DEFAULT 0,
            house_type TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            order_type TEXT,
            details TEXT,
            amount INTEGER,
            screenshot_id TEXT,
            status TEXT DEFAULT 'pending',
            sent_otchet INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            meta TEXT
        )
    """)
    try:  # eski bazada meta bagani joq bolsa qosamiz
        cur.execute("ALTER TABLE orders ADD COLUMN meta TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


init_db()


def db_get_user(user_id):
    conn = conn_()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()
    conn.close()
    return user


def db_save_user(user_id, username, full_name, instagram):
    conn = conn_()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (user_id, username, full_name, instagram)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            instagram=excluded.instagram,
            username=excluded.username,
            full_name=excluded.full_name
    """, (user_id, username, full_name, instagram))
    conn.commit()
    conn.close()


def db_update_house_status(user_id, house_type):
    conn = conn_()
    cur = conn.cursor()
    cur.execute("UPDATE users SET has_house = 1, house_type = ? WHERE user_id = ?", (house_type, user_id))
    conn.commit()
    conn.close()


def db_add_order(user_id, order_type, details, amount, screenshot_id, meta=None):
    conn = conn_()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders (user_id, order_type, details, amount, screenshot_id, meta)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, order_type, details, amount, screenshot_id,
          json.dumps(meta, ensure_ascii=False) if meta else None))
    conn.commit()
    order_id = cur.lastrowid
    conn.close()
    return order_id


def db_update_order_status(order_id, status):
    """Tek 'pending' buyirtpani ozgertedi. Aldin islengen bolsa None qaytaradi."""
    conn = conn_()
    cur = conn.cursor()
    cur.execute("SELECT user_id, order_type, details, meta, status FROM orders WHERE id = ?", (order_id,))
    row = cur.fetchone()
    if not row or row[4] != "pending":
        conn.close()
        return None
    cur.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()
    meta = json.loads(row[3]) if row[3] else {}
    return row[0], row[1], row[2], meta


def db_get_unreported_orders():
    conn = conn_()
    cur = conn.cursor()
    cur.execute("""
        SELECT o.id, o.user_id, u.instagram, o.order_type, o.details, o.amount, o.created_at
        FROM orders o
        JOIN users u ON o.user_id = u.user_id
        WHERE o.status = 'approved' AND o.sent_otchet = 0
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def db_mark_orders_reported(order_ids):
    if not order_ids:
        return
    conn = conn_()
    cur = conn.cursor()
    cur.executemany("UPDATE orders SET sent_otchet = 1 WHERE id = ?", [(oid,) for oid in order_ids])
    conn.commit()
    conn.close()


def db_export_site():
    """Tastiqlangan buyirtpalardan sayt JSON-in jasaydi."""
    conn = conn_()
    cur = conn.cursor()
    cur.execute("""
        SELECT o.user_id, u.instagram, o.meta
        FROM orders o JOIN users u ON o.user_id = u.user_id
        WHERE o.status = 'approved' AND o.meta IS NOT NULL
        ORDER BY o.id
    """)
    rows = cur.fetchall()
    conn.close()

    houses, shops, cars = {}, [], []
    for uid, ig, meta in rows:
        m = json.loads(meta)
        if "car" in m:
            cars.append({"n": ig, "k": m["car"]})
        elif m.get("t") == "m":
            shops.append({"n": ig, "t": "m", "d": m.get("d", "")})
        else:
            houses[uid] = {"n": ig, **m}  # keyingi uy aldingisin almastiradi (upgrade)
    homes = list(houses.values()) + shops
    return {"lvl": min(4, len(homes) // 200), "homes": homes, "cars": cars}


# ---------------- MOSHINALAR (100 - 1000 so'm) ----------------
CARS = {
    "c1": {"name": "Chevrolet Spark", "price": 100},
    "c2": {"name": "UzAuto Damas", "price": 150},
    "c3": {"name": "Chevrolet Cobalt", "price": 250},
    "c4": {"name": "Chevrolet Gentra", "price": 350},
    "c5": {"name": "Chevrolet Tracker", "price": 500},
    "c6": {"name": "Chevrolet Equinox", "price": 650},
    "c7": {"name": "BMW M5 F90", "price": 800},
    "c8": {"name": "Mercedes-Benz G63 (Gelik)", "price": 900},
    "c9": {"name": "Porsche 911 Turbo S", "price": 950},
    "c10": {"name": "Lamborghini Urus", "price": 1000},
}

TYPES_FREE = {"y": "Qara úy", "h": "Ápiwayı úy"}


# ---------------- FSM ----------------
class Form(StatesGroup):
    nick = State()
    custom_house_floors = State()
    custom_house_desc = State()
    custom_house_pay = State()
    business_desc = State()
    business_pay = State()
    upgrade_pay = State()
    car_pay = State()


# ---------------- YORDAMSHI ----------------
def tg_link(u):
    if u.username:
        return "@" + esc(u.username)
    return esc(u.full_name) + f" (ID: {u.id})"


def main_menu_kb(is_owner=False):
    rows = [
        [InlineKeyboardButton(text="🏠 Bepul úy qosıw (1 márte)", callback_data="menu:free_house")],
        [InlineKeyboardButton(text="🏗 Óz dizaynındaǵı úy (1000s + etajı 500s)", callback_data="menu:custom_house")],
        [InlineKeyboardButton(text="🏢 Biznes / Sawda orayı (5000 so'm)", callback_data="menu:business")],
        [InlineKeyboardButton(text="🔄 Úydi ózgertiw / Katta úyge ótiw", callback_data="menu:upgrade")],
        [InlineKeyboardButton(text="🚗 Moshina satıp alıw", callback_data="menu:cars")],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton(text="📊 Otchet alıw", callback_data="menu:otchet")])
        rows.append([InlineKeyboardButton(text="📦 Sayt JSON (export)", callback_data="menu:export")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def approve_kb(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tastiqlaw", callback_data=f"approve:{order_id}"),
        InlineKeyboardButton(text="❌ Biykarlaw", callback_data=f"reject:{order_id}"),
    ]])


async def send_to_owner(screenshot_id, caption, order_id):
    await bot.send_photo(OWNER_ID, screenshot_id, caption=caption, reply_markup=approve_kb(order_id))


async def send_export(target: Message):
    data = json.dumps(db_export_site(), ensure_ascii=False)
    await target.answer_document(
        BufferedInputFile(data.encode("utf-8"), filename="site.json"),
        caption="📦 Sayt JSON. Usı fayldıń mazmunın saytqa jiberiń.",
    )


# ---------------- START / NIK ----------------
@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    user = db_get_user(m.from_user.id)
    if user and user[3]:
        await m.answer(
            f"Sálem, @{esc(user[3])}! Xosh kelibsiz! 🌟\nTómendegi xizmetlerden birin tańlań:",
            reply_markup=main_menu_kb(m.from_user.id == OWNER_ID),
        )
    else:
        await state.set_state(Form.nick)
        await m.answer("Sálem! 👋 Instagram nikińizdi jazıń (mısalı: @nikiniz)")


@dp.message(Form.nick, F.text)
async def get_nick(m: Message, state: FSMContext):
    n = m.text.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", n):
        await m.answer("❌ Nik duris emes. Tek Instagram nikińizdi jazıń (mısalı: @nikiniz)")
        return

    db_save_user(m.from_user.id, m.from_user.username, m.from_user.full_name, n)
    await state.clear()

    if m.from_user.id == OWNER_ID:
        await m.answer("👑 Assalawma áleykum, Xojayın! Sizge Otchet hám Export sisteması qosıldı.",
                       reply_markup=main_menu_kb(True))
    else:
        await m.answer("✅ Instagram nikińiz saqlandı! Xizmetlerden birin tańlań:",
                       reply_markup=main_menu_kb(False))


@dp.message(Command("export"))
async def export_cmd(m: Message):
    if m.from_user.id == OWNER_ID:
        await send_export(m)


# ---------------- MENYU ----------------
@dp.callback_query(F.data.startswith("menu:"))
async def menu_handler(c: CallbackQuery, state: FSMContext):
    action = c.data.split(":")[1]
    user_id = c.from_user.id
    user = db_get_user(user_id)
    is_owner = user_id == OWNER_ID

    if not user or not user[3]:
        await c.answer("Aldın /start basın hám Instagram nikińizdi kórsetiń!", show_alert=True)
        return

    await state.clear()

    if action == "free_house":
        if user[4] == 1:
            await c.answer("❌ Hárbir telegram akkauntnan tek 1 úy qosıw múmkin!", show_alert=True)
            return
        rows = [[InlineKeyboardButton(text=name, callback_data=f"free:{code}")] for code, name in TYPES_FREE.items()]
        await c.message.edit_text("🏡 Bepul úy túrin tańlań:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    elif action == "custom_house":
        await state.set_state(Form.custom_house_floors)
        await c.message.edit_text(
            "🏗 <b>Óz dizaynıńızdaǵı úy qurıw</b>\n"
            "Baza narx: 1000 so'm + hár bir etajı 500 so'm (maksimal 50 qavat).\n\n"
            "Qansha etajlı bolıwın san menen jazıń (mısalı: 3):"
        )

    elif action == "business":
        await state.set_state(Form.business_desc)
        await c.message.edit_text(
            "🏢 <b>Biznes / Sawda orayın ashıw</b>\n"
            "Xizmet narxı: <b>5000 so'm</b>.\n\n"
            "Sawda orayınıń atın jazıń (maksimum 16 háripke shekem, saytta jazıw bolıp kórinedi):"
        )

    elif action == "upgrade":
        if user[4] == 0:
            await c.answer("Sizde házircha bepul úy joq. Aldın bepul úy alıń!", show_alert=True)
            return
        await state.set_state(Form.upgrade_pay)
        await c.message.edit_text(
            "🔄 <b>Úydi ózgertiw / Katta úyge ótiw</b>\n"
            "Narxı: <b>3000 so'm</b>\n"
            f"Tólem ushın karta: <code>{CARD_NUMBER}</code>\n"
            "Puldi ótkergennen soń, tólemdi tastiqlawshı <b>skrinshot</b> jiberiń:"
        )

    elif action == "cars":
        rows = [[InlineKeyboardButton(text=f"{v['name']} — {v['price']} so'm", callback_data=f"car:{k}")]
                for k, v in CARS.items()]
        rows.append([InlineKeyboardButton(text="🔙 Artqa", callback_data="menu:back")])
        await c.message.edit_text("🚗 Satıp alıw múmkin bolǵan moshinalar:\nBirin tańlań:",
                                  reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    elif action == "otchet":
        if not is_owner:
            await c.answer("Bul bólim tek Xojayın ushın!", show_alert=True)
            return
        unreported = db_get_unreported_orders()
        if not unreported:
            await c.message.edit_text("📭 Otchetqa kiritilmegen jańa tastiqlanǵan buyırtpa joq.",
                                      reply_markup=main_menu_kb(True))
            await c.answer()
            return
        text = "📊 <b>JAŃA OTCHET:</b>\n\n"
        ids = []
        for oid, uid, ig, o_type, details, amt, created in unreported:
            ids.append(oid)
            text += (f"🆔 {oid} | 📸 @{esc(ig)}\n📌 {esc(o_type)}\n📝 {esc(str(details))}\n"
                     f"💰 {amt} so'm\n📅 {created}\n-------------------\n")
        db_mark_orders_reported(ids)
        for i in range(0, len(text), 3800):  # Telegram limiti 4096
            await c.message.answer(text[i:i + 3800])
        await c.message.answer("Menyu:", reply_markup=main_menu_kb(True))

    elif action == "export":
        if not is_owner:
            await c.answer("Bul bólim tek Xojayın ushın!", show_alert=True)
            return
        await send_export(c.message)

    elif action == "back":
        await c.message.edit_text("Bas menyu:", reply_markup=main_menu_kb(is_owner))

    await c.answer()


# ---------------- BEPUL UY ----------------
@dp.callback_query(F.data.startswith("free:"))
async def choose_free_house(c: CallbackQuery):
    code = c.data.split(":")[1]
    user_id = c.from_user.id
    user = db_get_user(user_id)

    if code not in TYPES_FREE:
        await c.answer("Qátelik", show_alert=True)
        return
    if user[4] == 1:
        await c.answer("❌ Bir akkauntqa tek 1 úy qosıw múmkin!", show_alert=True)
        return

    house_name = TYPES_FREE[code]
    db_update_house_status(user_id, house_name)
    order_id = db_add_order(user_id, f"Bepul úy ({house_name})", f"Instagram: @{user[3]}", 0, "none", {"t": code})
    db_update_order_status(order_id, "approved")

    try:
        await bot.send_message(
            OWNER_ID,
            f"🏠 Jańa bepul úy\n📸 Instagram: @{esc(user[3])}\n🏡 {house_name}\n👤 Telegram: {tg_link(c.from_user)}",
        )
    except Exception:
        pass

    await c.message.edit_text(
        f"✅ Qabıl etildi!\n📸 @{esc(user[3])}\n🏡 {house_name}\n\n"
        "Úyińiz saytqa qosılıwǵa jiberildi!"
    )
    await c.answer()


# ---------------- OZ DIZAYNDAGI UY ----------------
@dp.message(Form.custom_house_floors, F.text)
async def custom_house_floors_handler(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        await m.answer("❌ Tek san jazıń (mısalı: 2, 3, 5):")
        return
    floors = int(m.text.strip())
    if floors < 1 or floors > 50:
        await m.answer("❌ Etaj sanı 1 den 50 aralıǵında bolıwı kerek. Qaytadan jazıń:")
        return

    price = 1000 + floors * 500
    await state.update_data(floors=floors, price=price)
    await state.set_state(Form.custom_house_desc)
    await m.answer(
        f"🏗 Etajlar sanı: {floors}\n"
        f"💳 Jemi narx: <b>{price} so'm</b> (1000 + {floors}×500).\n\n"
        "Endi úy haqqında qısqasha maǵlıwmat jazıń (mısalı: reńi, stili):"
    )


@dp.message(Form.custom_house_desc)
async def custom_house_desc_handler(m: Message, state: FSMContext):
    desc = (m.text or m.caption or "Súwret boyınsha dizayn")[:200]
    await state.update_data(desc=desc)
    await state.set_state(Form.custom_house_pay)
    data = await state.get_data()
    await m.answer(
        f"💳 Tólem kartası: <code>{CARD_NUMBER}</code>\n"
        f"💰 Ótkeriw kerek bolǵan summa: <b>{data['price']} so'm</b>\n\n"
        "Puldi ótkergennen soń, tólemdi tastiqlawshı <b>skrinshot</b> jiberiń:"
    )


@dp.message(Form.custom_house_pay, F.photo)
async def custom_house_pay_handler(m: Message, state: FSMContext):
    data = await state.get_data()
    user = db_get_user(m.from_user.id)
    shot = m.photo[-1].file_id

    order_id = db_add_order(
        m.from_user.id, "Dizayn úy",
        f"Etaj: {data['floors']}, Descr: {data['desc']}",
        data["price"], shot,
        {"t": "c", "f": data["floors"], "d": data["desc"][:40]},
    )
    await state.clear()
    await m.answer("✅ Buyırtpa qabıl etildi! Xojayın tastiqlawın kútiń.")
    await send_to_owner(shot, (
        f"🔔 <b>Jańa Dizayn Úy Buyırtpası!</b>\n"
        f"🆔 Order ID: {order_id}\n"
        f"👤 {tg_link(m.from_user)} (@{esc(user[3])})\n"
        f"🏗 Etaj: {data['floors']} | 💰 {data['price']} so'm\n"
        f"📝 {esc(data['desc'])}"
    ), order_id)


# ---------------- BIZNES ----------------
@dp.message(Form.business_desc, F.text)
async def business_desc_handler(m: Message, state: FSMContext):
    await state.update_data(desc=m.text.strip()[:16])
    await state.set_state(Form.business_pay)
    await m.answer(
        "🏢 Biznes / Sawda orayı narxı: <b>5000 so'm</b>.\n"
        f"Karta: <code>{CARD_NUMBER}</code>\n"
        "Puldi ótkergennen soń <b>skrinshot</b> jiberiń:"
    )


@dp.message(Form.business_pay, F.photo)
async def business_pay_handler(m: Message, state: FSMContext):
    data = await state.get_data()
    user = db_get_user(m.from_user.id)
    shot = m.photo[-1].file_id

    order_id = db_add_order(m.from_user.id, "Biznes / Sawda orayı", data["desc"], 5000, shot,
                            {"t": "m", "d": data["desc"]})
    await state.clear()
    await m.answer("✅ Biznes buyırtpası qabıl etildi! Xojayın tekseredi.")
    await send_to_owner(shot, (
        f"🔔 <b>Jańa Biznes / Sawda orayı!</b>\n"
        f"🆔 Order ID: {order_id}\n"
        f"👤 {tg_link(m.from_user)} (@{esc(user[3])})\n"
        f"💰 5000 so'm\n"
        f"📝 {esc(data['desc'])}"
    ), order_id)


# ---------------- UYDI OZGERTIW ----------------
@dp.message(Form.upgrade_pay, F.photo)
async def upgrade_pay_handler(m: Message, state: FSMContext):
    user = db_get_user(m.from_user.id)
    shot = m.photo[-1].file_id
    price = 3000

    order_id = db_add_order(m.from_user.id, "Úydi ózgertiw (Katta úy)",
                            "Eski úy ornına katta úy", price, shot, {"t": "g"})
    await state.clear()
    await m.answer("✅ Sorawıńız jiberildi! Xojayın tastiqlawın kútiń.")
    await send_to_owner(shot, (
        f"🔔 <b>Úydi Ózgertiw / Katta Úy!</b>\n"
        f"🆔 Order ID: {order_id}\n"
        f"👤 {tg_link(m.from_user)} (@{esc(user[3])})\n"
        f"💰 {price} so'm"
    ), order_id)


# ---------------- MOSHINA ----------------
@dp.callback_query(F.data.startswith("car:"))
async def choose_car(c: CallbackQuery, state: FSMContext):
    key = c.data.split(":")[1]
    if key not in CARS:
        await c.answer("Moshina tabılmadı", show_alert=True)
        return
    car = CARS[key]
    await state.update_data(car_name=car["name"], car_price=car["price"], car_key=key)
    await state.set_state(Form.car_pay)
    await c.message.edit_text(
        f"🚗 Tańlanǵan moshina: <b>{car['name']}</b>\n"
        f"💰 Narx: <b>{car['price']} so'm</b>\n\n"
        f"💳 Tólem kartası: <code>{CARD_NUMBER}</code>\n"
        "Puldi ótkergennen soń tastiqlawshı <b>skrinshot</b> jiberiń:"
    )
    await c.answer()


@dp.message(Form.car_pay, F.photo)
async def car_pay_handler(m: Message, state: FSMContext):
    data = await state.get_data()
    user = db_get_user(m.from_user.id)
    shot = m.photo[-1].file_id

    order_id = db_add_order(m.from_user.id, f"Moshina ({data['car_name']})", data["car_name"],
                            data["car_price"], shot, {"car": data["car_key"]})
    await state.clear()
    await m.answer("✅ Moshina buyırtpası qabıl etildi! Xojayın tekseredi.")
    await send_to_owner(shot, (
        f"🔔 <b>Moshina Satıp Alıw!</b>\n"
        f"🆔 Order ID: {order_id}\n"
        f"👤 {tg_link(m.from_user)} (@{esc(user[3])})\n"
        f"🚗 {data['car_name']}\n"
        f"💰 {data['car_price']} so'm"
    ), order_id)


# ---------------- ADMIN: TASTIQLAW / BIYKARLAW ----------------
@dp.callback_query(F.data.startswith(("approve:", "reject:")))
async def admin_action(c: CallbackQuery):
    if c.from_user.id != OWNER_ID:
        await c.answer("Bul buyrıq tek xojayın ushın!", show_alert=True)
        return

    action, oid = c.data.split(":")
    order_id = int(oid)
    approve = action == "approve"

    res = db_update_order_status(order_id, "approved" if approve else "rejected")
    if not res:
        await c.answer("Bul buyırtpa aldın islengen.", show_alert=True)
        return

    u_id, o_type, _details, meta = res
    if approve and meta.get("t") in ("c", "g"):
        db_update_house_status(u_id, o_type)

    try:
        if approve:
            await bot.send_message(u_id, f"✅ Sizdiń '{esc(o_type)}' buyırtpańız tastiqlandı! 🎉\n"
                                         "Bir neshe waqıttan soń saytta kórinedi.")
        else:
            await bot.send_message(u_id, f"❌ Sizdiń '{esc(o_type)}' buyırtpańız biykarlandı.")
    except Exception:
        pass

    mark = "✅ TASTIQLANDI" if approve else "❌ BIYKARLANDI"
    await c.message.edit_caption(caption=(c.message.html_text or "") + f"\n\n<b>STATUS: {mark}</b>")
    await c.answer("Tayar!")


# ---------------- QALǴAN XABARLAR ----------------
@dp.message()
async def other(m: Message):
    user = db_get_user(m.from_user.id)
    if not user or not user[3]:
        await m.answer("Sálem! 👋 Aldın /start basıń.")
        return
    await m.answer("Xizmet tańlaw ushın menyudan paydalanıń 🏠",
                   reply_markup=main_menu_kb(m.from_user.id == OWNER_ID))


async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
