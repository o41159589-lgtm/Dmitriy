"""
Casino Telegram Bot — aiogram 3.x
Хостинг: Render (https://dmitriy-45jd.onrender.com)
Запуск: python bot.py
"""

import asyncio
import logging
import time
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage

# ══════════════════════════════════════════
#  CONFIG  —  замените нужные строки
# ══════════════════════════════════════════
BOT_TOKEN  = "8726291672:AAEbVmk2LG4H2hOQTughIIKxoVMXCwD3TJM"   # ← токен бота
ADMIN_IDS  = [1840233118]                                           # ← ваш Telegram ID
WEBAPP_URL = "https://dmitriy-45jd.onrender.com"                  # ← URL Mini App
PORT       = 8080                                                  # порт для Render
# ══════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ── Хранилище (в памяти; для продакшна замените на Redis/PostgreSQL) ──
user_balances: dict[int, int]   = {}
user_history:  dict[int, list]  = {}

def get_balance(uid: int) -> int:
    return user_balances.get(uid, 100)          # стартовый баланс 100

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
    args = message.text.split(maxsplit=1)

    # Реферальная система
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_id = args[1].split("_")[1]
        logger.info(f"User {user.id} пришёл по рефералке от {ref_id}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🎰 Открыть Казино",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    ]])

    await message.answer(
        f"🎰 Добро пожаловать, <b>{user.first_name}</b>!\n\n"
        f"💰 Ваш баланс: <b>{get_balance(user.id)}</b> монет\n\n"
        f"Нажмите кнопку ниже, чтобы открыть казино:",
        reply_markup=kb,
        parse_mode="HTML"
    )


# ══════════════════════════════════════════
#  /balance
# ══════════════════════════════════════════
@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    await message.answer(
        f"💰 Ваш баланс: <b>{get_balance(message.from_user.id)}</b> монет",
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
        await message.answer(
            "⚠️ Монеты начислены, но уведомить пользователя не удалось "
            "(возможно, он ещё не запускал бота)."
        )


# ══════════════════════════════════════════
#  HTTP-сервер для Render (keep-alive)
# ══════════════════════════════════════════
async def health(request):
    return web.Response(text="OK — Casino Bot is running")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"HTTP server running on port {PORT}")


# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════
async def main():
    await start_web_server()
    logger.info("Bot polling started...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())