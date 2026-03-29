"""
Casino Bot — aiogram 3.x + aiosqlite
Render: https://dmitriy-45jd.onrender.com
"""

import asyncio
import logging
import os
import time
import random
import json
from pathlib import Path
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton,
    LabeledPrice, PreCheckoutQuery, CallbackQuery
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage

import database as db

# ══════════════════════════════════════════
BOT_TOKEN  = "8686326767:AAFheVAG5rhSjpQHaAJClR-axeuBbM0Zni8"
ADMIN_IDS  = [1840233118]
WEBAPP_URL = "https://dmitriy-45jd.onrender.com"
ADMIN_URL  = "https://dmitriy-45jd.onrender.com/admin"
PORT       = int(os.environ.get("PORT", 8080))
COMMISSION_PCT = 5      # 5% комиссия с выигрыша в GTA-рулетке
GTA_MIN_PLAYERS = 2     # минимум игроков для старта
GTA_SPIN_DELAY  = 15    # секунд ожидания ставок перед спином
# ══════════════════════════════════════════

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# Активные GTA-лобби ожидающие таймер
gta_timers: dict[int, asyncio.Task] = {}


# ══════════════════════════════════════════
#  /start
# ══════════════════════════════════════════
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    text_parts = message.text.split(maxsplit=1)

    # Создаём/обновляем пользователя
    u = await db.ensure_user(user.id, user.username or "", user.first_name or "")

    # Реферальная система: +10 монет реферреру
    if len(text_parts) > 1 and text_parts[1].startswith("ref_"):
        try:
            ref_id = int(text_parts[1].split("_")[1])
            if ref_id != user.id:
                ref_user = await db.get_user(ref_id)
                if ref_user:
                    new_bal = await db.add_to_balance(ref_id, 10)
                    await db.add_history(ref_id, "ref", 10, f"Реферал: {user.first_name}")
                    try:
                        await bot.send_message(
                            ref_id,
                            f"🎉 По вашей реферальной ссылке зарегистрировался "
                            f"<b>{user.first_name}</b>!\n"
                            f"💰 +10 монет → баланс: <b>{new_bal}</b>",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
        except (ValueError, IndexError):
            pass

    kb_reply = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🎰 Казино", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )
    kb_inline = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎰 Открыть Казино", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])

    await message.answer(
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        f"🎰 <b>Casino</b> — крути рулетку и выигрывай!\n\n"
        f"💰 Ваш баланс: <b>{u['balance']}</b> монет",
        reply_markup=kb_reply,
        parse_mode="HTML"
    )
    await message.answer("Или нажмите:", reply_markup=kb_inline)


# ══════════════════════════════════════════
#  /admin — только для администраторов
# ══════════════════════════════════════════
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return  # тихо игнорируем

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🛠 Открыть админ-панель",
            web_app=WebAppInfo(url=ADMIN_URL)
        )
    ]])
    await message.answer(
        "🛠 <b>Админ-панель</b>\nУправление пользователями:",
        reply_markup=kb,
        parse_mode="HTML"
    )


# ══════════════════════════════════════════
#  ОПЛАТА ЗВЁЗДАМИ (пополнение баланса)
# ══════════════════════════════════════════
@dp.message(Command("buy"))
async def cmd_buy(message: Message):
    """Пример: /buy 100  — купить 100 монет за 100 звёзд"""
    parts = message.text.split()
    amount = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 50
    amount = max(10, min(amount, 10000))

    await bot.send_invoice(
        chat_id=message.chat.id,
        title=f"💰 {amount} монет",
        description=f"Пополнение баланса на {amount} монет в Casino",
        payload=f"coins_{message.from_user.id}_{amount}",
        currency="XTR",           # Telegram Stars
        prices=[LabeledPrice(label=f"{amount} монет", amount=amount)],
    )


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    parts = payload.split("_")
    if parts[0] == "coins" and len(parts) == 3:
        uid    = int(parts[1])
        amount = int(parts[2])
        new_bal = await db.add_to_balance(uid, amount)
        await db.add_history(uid, "deposit", amount, "Пополнение через Stars")
        await message.answer(
            f"✅ Оплата прошла!\n"
            f"💰 +{amount} монет → баланс: <b>{new_bal}</b>",
            parse_mode="HTML"
        )


# ══════════════════════════════════════════
#  API — endpoints для Mini App
# ══════════════════════════════════════════

async def api_get_user(request: web.Request) -> web.Response:
    uid = int(request.match_info["uid"])
    u = await db.get_user(uid)
    if not u:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(u)

async def api_get_history(request: web.Request) -> web.Response:
    uid = int(request.match_info["uid"])
    hist = await db.get_history(uid, 100)
    return web.json_response(hist)

async def api_spin_european(request: web.Request) -> web.Response:
    """Европейская рулетка"""
    data = await request.json()
    uid      = int(data.get("user_id", 0))
    bet_amt  = int(data.get("bet", 0))
    bet_type = data.get("bet_type", "")

    u = await db.get_user(uid)
    if not u:
        return web.json_response({"error": "user not found"}, status=404)
    if bet_amt <= 0 or bet_amt > u["balance"]:
        return web.json_response({"error": "invalid bet"}, status=400)

    NUMBERS = [
        (0,"green"),(32,"red"),(15,"black"),(19,"red"),(4,"black"),(21,"red"),
        (2,"black"),(25,"red"),(17,"black"),(34,"red"),(6,"black"),(27,"red"),
        (13,"black"),(36,"red"),(11,"black"),(30,"red"),(8,"black"),(23,"red"),
        (10,"black"),(5,"red"),(24,"black"),(16,"red"),(33,"black"),(1,"red"),
        (20,"black"),(14,"red"),(31,"black"),(9,"red"),(22,"black"),(18,"red"),
        (29,"black"),(7,"red"),(28,"black"),(12,"red"),(35,"black"),(3,"red"),(26,"black")
    ]

    # Подкрут шансов
    luck = await db.get_luck(uid)
    if luck == -1:
        result_n, result_c = random.choice(NUMBERS)
    else:
        # luck_pct = вероятность выиграть (0–100)
        will_win = random.randint(0, 99) < luck
        def check_win(n, c, bt):
            if bt == "red":    return c == "red"
            if bt == "black":  return c == "black"
            if bt == "green":  return c == "green"
            if bt == "even":   return n != 0 and n % 2 == 0
            if bt == "odd":    return n % 2 == 1
            if bt == "low":    return 1 <= n <= 18
            if bt == "high":   return 19 <= n <= 36
            if bt == "dozen1": return 1 <= n <= 12
            if bt == "dozen2": return 13 <= n <= 24
            return False

        winning_nums  = [(n, c) for n, c in NUMBERS if check_win(n, c, bet_type)]
        losing_nums   = [(n, c) for n, c in NUMBERS if not check_win(n, c, bet_type)]
        if will_win and winning_nums:
            result_n, result_c = random.choice(winning_nums)
        elif losing_nums:
            result_n, result_c = random.choice(losing_nums)
        else:
            result_n, result_c = random.choice(NUMBERS)

    # Расчёт выигрыша
    MULTIPLIERS = {"red":2,"black":2,"green":14,"even":2,"odd":2,
                   "low":2,"high":2,"dozen1":3,"dozen2":3}

    def is_win(n, c, bt):
        if bt == "red":    return c == "red"
        if bt == "black":  return c == "black"
        if bt == "green":  return c == "green"
        if bt == "even":   return n != 0 and n % 2 == 0
        if bt == "odd":    return n % 2 == 1
        if bt == "low":    return 1 <= n <= 18
        if bt == "high":   return 19 <= n <= 36
        if bt == "dozen1": return 1 <= n <= 12
        if bt == "dozen2": return 13 <= n <= 24
        return False

    won = is_win(result_n, result_c, bet_type)
    mult = MULTIPLIERS.get(bet_type, 2)

    if won:
        gain = bet_amt * mult
        new_bal = await db.add_to_balance(uid, gain - bet_amt)
        await db.add_history(uid, "win", gain,
            f"Европ. рулетка: {result_n} {result_c}, ставка {bet_amt}×{mult}")
        await db.update_spin_stats(uid, True, gain, 0)
    else:
        await db.add_to_balance(uid, -bet_amt)
        new_bal = (await db.get_user(uid))["balance"]
        await db.add_history(uid, "lose", bet_amt,
            f"Европ. рулетка: {result_n} {result_c}, ставка {bet_amt}")
        await db.update_spin_stats(uid, False, 0, bet_amt)

    return web.json_response({
        "result_n": result_n, "result_c": result_c,
        "won": won, "gain": gain if won else 0,
        "new_balance": new_bal,
        "result_index": next(i for i,(n,c) in enumerate(NUMBERS) if n==result_n and c==result_c)
    })


async def api_gta_lobby(request: web.Request) -> web.Response:
    """Получить/создать открытое лобби"""
    lobby = await db.get_open_lobby()
    if not lobby:
        lid = await db.create_lobby()
        lobby = await db.get_lobby(lid)
    bets = await db.get_lobby_bets(lobby["id"])
    return web.json_response({"lobby": lobby, "bets": bets})


async def api_gta_bet(request: web.Request) -> web.Response:
    """Сделать ставку в GTA-лобби"""
    data = await request.json()
    uid    = int(data.get("user_id", 0))
    amount = int(data.get("amount", 0))

    u = await db.get_user(uid)
    if not u:
        return web.json_response({"error": "user not found"}, status=404)
    if amount <= 0 or amount > u["balance"]:
        return web.json_response({"error": "invalid amount"}, status=400)

    lobby = await db.get_open_lobby()
    if not lobby:
        lid = await db.create_lobby()
        lobby = await db.get_lobby(lid)

    if lobby["status"] != "open":
        return web.json_response({"error": "lobby not open"}, status=400)

    # Снимаем ставку с баланса
    await db.add_to_balance(uid, -amount)
    await db.place_gta_bet(lobby["id"], uid, amount)
    await db.add_history(uid, "lose", amount,
        f"GTA ставка в лобби #{lobby['id']}")

    # Проверяем, нужно ли запустить таймер спина
    bets = await db.get_lobby_bets(lobby["id"])
    unique_players = len({b["user_id"] for b in bets})

    if unique_players >= GTA_MIN_PLAYERS and lobby["id"] not in gta_timers:
        task = asyncio.create_task(gta_spin_after_delay(lobby["id"]))
        gta_timers[lobby["id"]] = task

    new_bal = (await db.get_user(uid))["balance"]
    return web.json_response({
        "success": True,
        "new_balance": new_bal,
        "lobby_id": lobby["id"],
        "players": unique_players,
        "pot": lobby["pot"] + amount
    })


async def api_gta_status(request: web.Request) -> web.Response:
    """Статус лобби для polling из Mini App"""
    lid = int(request.match_info.get("lid", 0))
    lobby = await db.get_lobby(lid)
    if not lobby:
        return web.json_response({"error": "not found"}, status=404)
    bets = await db.get_lobby_bets(lid)
    return web.json_response({"lobby": lobby, "bets": bets})


async def gta_spin_after_delay(lobby_id: int):
    """Ждём GTA_SPIN_DELAY секунд, потом крутим"""
    await asyncio.sleep(GTA_SPIN_DELAY)
    await run_gta_spin(lobby_id)
    gta_timers.pop(lobby_id, None)


async def run_gta_spin(lobby_id: int):
    lobby = await db.get_lobby(lobby_id)
    if not lobby or lobby["status"] != "open":
        return

    bets = await db.get_lobby_bets(lobby_id)
    if not bets:
        return

    await db.set_lobby_spinning(lobby_id)

    pot = lobby["pot"]
    total = sum(b["amount"] for b in bets)

    # Взвешенный случайный выбор победителя
    # Учитываем luck_pct каждого игрока
    weights = []
    for b in bets:
        luck = await db.get_luck(b["user_id"])
        base_weight = b["amount"] / total * 100
        if luck == -1:
            weights.append(base_weight)
        elif luck == 0:
            weights.append(0.01)   # почти невозможно
        elif luck == 100:
            weights.append(999999)
        else:
            weights.append(luck)

    winner_bet = random.choices(bets, weights=weights, k=1)[0]
    winner_id  = winner_bet["user_id"]

    # Комиссия с прогрессивной шкалой
    commission = _calc_commission(pot)
    payout = pot - commission

    await db.add_to_balance(winner_id, payout)
    await db.add_history(winner_id, "win", payout,
        f"GTA рулетка #{lobby_id}: банк {pot}, комиссия {commission}")
    await db.update_spin_stats(winner_id, True, payout, 0)

    # Обновляем проигравших (история уже записана при ставке)
    for b in bets:
        if b["user_id"] != winner_id:
            await db.update_spin_stats(b["user_id"], False, 0, b["amount"])

    await db.close_lobby(lobby_id, winner_id, commission)

    # Уведомление победителю
    try:
        winner = await db.get_user(winner_id)
        await bot.send_message(
            winner_id,
            f"🎉 <b>Вы выиграли в GTA-рулетке!</b>\n"
            f"💰 Банк: {pot} монет\n"
            f"🏦 Комиссия ({commission_pct(pot)}%): {commission} монет\n"
            f"✅ Выплата: <b>{payout}</b> монет\n"
            f"📊 Ваш баланс: <b>{winner['balance']}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить победителя {winner_id}: {e}")


def _calc_commission(pot: int) -> int:
    """Прогрессивная комиссия: 3% до 500, 5% до 2000, 8% выше"""
    if pot <= 500:
        pct = 3
    elif pot <= 2000:
        pct = 5
    else:
        pct = 8
    return max(1, round(pot * pct / 100))

def commission_pct(pot: int) -> int:
    if pot <= 500: return 3
    if pot <= 2000: return 5
    return 8


# ══════════════════════════════════════════
#  ADMIN API
# ══════════════════════════════════════════

async def api_admin_users(request: web.Request) -> web.Response:
    if not _check_admin(request):
        return web.json_response({"error": "forbidden"}, status=403)
    users = await db.get_all_users()
    return web.json_response(users)

async def api_admin_set_balance(request: web.Request) -> web.Response:
    if not _check_admin(request):
        return web.json_response({"error": "forbidden"}, status=403)
    data = await request.json()
    uid = int(data["user_id"])
    new_bal = int(data["balance"])
    await db.set_balance(uid, new_bal)
    old = data.get("old_balance", 0)
    delta = new_bal - old
    await db.add_history(uid, "add" if delta > 0 else "sub", abs(delta),
        f"Изменено администратором")
    return web.json_response({"success": True, "balance": new_bal})

async def api_admin_set_luck(request: web.Request) -> web.Response:
    if not _check_admin(request):
        return web.json_response({"error": "forbidden"}, status=403)
    data = await request.json()
    uid  = int(data["user_id"])
    luck = int(data["luck"])   # -1 или 0–100
    await db.set_luck(uid, luck)
    return web.json_response({"success": True})

def _check_admin(request: web.Request) -> bool:
    key = request.headers.get("X-Admin-Key", "")
    return key == BOT_TOKEN   # используем токен бота как секрет


# ══════════════════════════════════════════
#  HTML сервер
# ══════════════════════════════════════════
BASE_DIR = Path(__file__).parent

async def serve_miniapp(request: web.Request) -> web.Response:
    f = BASE_DIR / "telegram_mini_app.html"
    if f.exists():
        return web.Response(text=f.read_text("utf-8"),
                            content_type="text/html", charset="utf-8")
    return web.Response(text="Not found", status=404)

async def serve_admin(request: web.Request) -> web.Response:
    f = BASE_DIR / "admin_panel.html"
    if f.exists():
        return web.Response(text=f.read_text("utf-8"),
                            content_type="text/html", charset="utf-8")
    return web.Response(text="Not found", status=404)

async def health(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/",                    serve_miniapp)
    app.router.add_get("/admin",               serve_admin)
    app.router.add_get("/health",              health)
    # User API
    app.router.add_get ("/api/user/{uid}",     api_get_user)
    app.router.add_get ("/api/history/{uid}",  api_get_history)
    app.router.add_post("/api/spin/european",  api_spin_european)
    app.router.add_get ("/api/gta/lobby",      api_gta_lobby)
    app.router.add_post("/api/gta/bet",        api_gta_bet)
    app.router.add_get ("/api/gta/status/{lid}", api_gta_status)
    # Admin API
    app.router.add_get ("/api/admin/users",         api_admin_users)
    app.router.add_post("/api/admin/set_balance",   api_admin_set_balance)
    app.router.add_post("/api/admin/set_luck",      api_admin_set_luck)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info(f"HTTP on :{PORT}")


# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════
async def main():
    await db.init_db()
    await start_web_server()
    logger.info("Polling started")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())