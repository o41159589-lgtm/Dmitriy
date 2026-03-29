"""
Casino Telegram Bot — aiogram 3.x
Сервер раздаёт Mini App HTML по корневому URL.
Хостинг: Render (https://dmitriy-45jd.onrender.com)
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage

# ══════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════
BOT_TOKEN  = "8726291672:AAHuDez_PMbrmAFymPDvOwQseZOeE73YJWU"
ADMIN_IDS  = [1840233118]                          # ← замените на ваш Telegram ID
WEBAPP_URL = "https://dmitriy-45jd.onrender.com"
PORT       = int(os.environ.get("PORT", 8080))
# ══════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ── Хранилище балансов (in-memory) ──
user_balances: dict[int, int]  = {}
user_history:  dict[int, list] = {}

def get_balance(uid: int) -> int:
    return user_balances.get(uid, 100)

def add_balance(uid: int, amount: int) -> int:
    user_balances[uid] = get_balance(uid) + amount
    user_history.setdefault(uid, []).insert(0, {
        "type": "add", "amount": amount, "ts": time.time()
    })
    return user_balances[uid]


# ══════════════════════════════════════════
#  /start
# ══════════════════════════════════════════
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user

    # Реферальная система
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_id = args[1].split("_")[1]
        logger.info(f"User {user.id} пришёл по реф. от {ref_id}")

    # Inline-кнопка открытия Mini App
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🎰 Открыть Казино",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    ]])

    # Reply-кнопка (постоянная) тоже с Web App
    reply_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🎰 Казино", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )

    await message.answer(
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        f"🎰 <b>Casino Bot</b> — крути рулетку и выигрывай монеты!\n\n"
        f"💰 Твой баланс: <b>{get_balance(user.id)}</b> монет\n\n"
        f"Нажми кнопку ниже чтобы открыть казино 👇",
        reply_markup=reply_kb,
        parse_mode="HTML"
    )
    await message.answer(
        "Или используй эту кнопку:",
        reply_markup=inline_kb
    )


# ══════════════════════════════════════════
#  /balance
# ══════════════════════════════════════════
@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    bal = get_balance(message.from_user.id)
    await message.answer(
        f"💰 Ваш баланс: <b>{bal}</b> монет",
        parse_mode="HTML"
    )


# ══════════════════════════════════════════
#  /skill-creator <user_id> <amount>
# ══════════════════════════════════════════
@dp.message(F.text.regexp(r"^/skill[-_]creator"))
async def cmd_skill_creator(message: Message):
    caller = message.from_user.id

    if caller not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для этой команды.")
        return

    parts = message.text.split()
    if len(parts) != 3:
        await message.answer(
            "❌ Неверный формат.\n"
            "Использование: <code>/skill-creator &lt;user_id&gt; &lt;amount&gt;</code>\n"
            "Пример: <code>/skill-creator 123456789 500</code>",
            parse_mode="HTML"
        )
        return

    try:
        target_id = int(parts[1])
        amount    = int(parts[2])
    except ValueError:
        await message.answer("❌ user_id и amount должны быть целыми числами.")
        return

    if amount <= 0:
        await message.answer("❌ Сумма должна быть больше 0.")
        return

    new_balance = add_balance(target_id, amount)

    await message.answer(
        f"✅ <b>Готово!</b>\n"
        f"👤 Пользователь: <code>{target_id}</code>\n"
        f"💰 Начислено: <b>+{amount}</b> монет\n"
        f"📊 Новый баланс: <b>{new_balance}</b> монет",
        parse_mode="HTML"
    )

    try:
        await bot.send_message(
            chat_id=target_id,
            text=f"🎉 Вам начислено <b>{amount}</b> монет!\n"
                 f"💰 Ваш баланс: <b>{new_balance}</b> монет",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить {target_id}: {e}")
        await message.answer("⚠️ Монеты начислены, но пользователь не получил уведомление.")


# ══════════════════════════════════════════
#  HTTP-сервер — раздаёт Mini App HTML
# ══════════════════════════════════════════
HTML_FILE = Path(__file__).parent / "telegram_mini_app.html"

async def serve_miniapp(request):
    """Отдаём HTML файл Mini App по корневому URL"""
    if HTML_FILE.exists():
        content = HTML_FILE.read_text(encoding="utf-8")
        return web.Response(
            text=content,
            content_type="text/html",
            charset="utf-8"
        )
    return web.Response(text="Mini App not found", status=404)

async def health(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", serve_miniapp)          # ← главная страница = Mini App
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"HTTP server on port {PORT} | Mini App: {WEBAPP_URL}")


# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════
async def main():
    await start_web_server()
    logger.info("Bot polling started...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())