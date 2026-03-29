"""
Casino Bot — aiogram 3.x + aiosqlite
Render: https://dmitriy-45jd.onrender.com
"""
import asyncio, logging, os, random, time
from pathlib import Path
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.storage.memory import MemoryStorage
import database as db

# ════════════════════════════════════════
BOT_TOKEN  = "8686326767:AAFheVAG5rhSjpQHaAJClR-axeuBbM0Zni8"
ADMIN_IDS  = [1840233118]
WEBAPP_URL      = "https://dmitriy-45jd.onrender.com"
ADMIN_URL       = "https://dmitriy-45jd.onrender.com/admin"
PORT            = int(os.environ.get("PORT", 8080))
GTA_MIN_PLAYERS = 2
GTA_SPIN_DELAY  = 15   # секунд
# ════════════════════════════════════════

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())
gta_timers: dict[int, asyncio.Task] = {}

ROULETTE_NUMBERS = [
    (0,"green"),(32,"red"),(15,"black"),(19,"red"),(4,"black"),(21,"red"),
    (2,"black"),(25,"red"),(17,"black"),(34,"red"),(6,"black"),(27,"red"),
    (13,"black"),(36,"red"),(11,"black"),(30,"red"),(8,"black"),(23,"red"),
    (10,"black"),(5,"red"),(24,"black"),(16,"red"),(33,"black"),(1,"red"),
    (20,"black"),(14,"red"),(31,"black"),(9,"red"),(22,"black"),(18,"red"),
    (29,"black"),(7,"red"),(28,"black"),(12,"red"),(35,"black"),(3,"red"),(26,"black")
]

# ════════════════════════════════════════
#  BOT HANDLERS
# ════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    # Регистрируем / обновляем пользователя в БД
    u = await db.ensure_user(user.id, user.username or "", user.first_name or "")

    # Реферальная система
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            ref_id = int(parts[1].split("_")[1])
            if ref_id != user.id:
                ref_u = await db.get_user(ref_id)
                if ref_u:
                    nb = await db.add_to_balance(ref_id, 10)
                    await db.add_history(ref_id, "ref", 10, f"Реферал: {user.first_name}")
                    try:
                        await bot.send_message(ref_id,
                            f"🎉 По вашей ссылке зарегистрировался <b>{user.first_name}</b>!\n"
                            f"💰 +10 монет → баланс: <b>{nb}</b>", parse_mode="HTML")
                    except Exception:
                        pass
        except (ValueError, IndexError):
            pass

    kb_reply = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🎰 Казино", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True)
    kb_inline = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎰 Открыть Казино", web_app=WebAppInfo(url=WEBAPP_URL))]])

    await message.answer(
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        f"🎰 <b>Casino</b> — крути рулетку и выигрывай!\n\n"
        f"💰 Ваш баланс: <b>{u['balance']}</b> монет",
        reply_markup=kb_reply, parse_mode="HTML")
    await message.answer("Или нажмите:", reply_markup=kb_inline)


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛠 Открыть админ-панель", web_app=WebAppInfo(url=ADMIN_URL))]])
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=kb, parse_mode="HTML")


# ── Пополнение через Stars ──
# Mini App вызывает /api/invoice?uid=XXX&amount=YYY
# Бот отправляет инвойс пользователю в личку

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def on_payment(message: Message):
    pl = message.successful_payment.invoice_payload
    parts = pl.split("_")
    if parts[0] == "coins" and len(parts) == 3:
        uid    = int(parts[1])
        amount = int(parts[2])
        nb = await db.add_to_balance(uid, amount)
        await db.add_history(uid, "deposit", amount, "Пополнение через Stars")
        await message.answer(
            f"✅ Оплата прошла!\n💰 +{amount} монет → баланс: <b>{nb}</b>",
            parse_mode="HTML")

# ════════════════════════════════════════
#  HTTP API
# ════════════════════════════════════════

async def api_user(req: web.Request):
    uid = int(req.match_info["uid"])
    u = await db.get_user(uid)
    if not u:
        return web.json_response({"error":"not found"}, status=404)
    return web.json_response(u)

async def api_history(req: web.Request):
    uid = int(req.match_info["uid"])
    h = await db.get_history(uid)
    return web.json_response(h)

async def api_invoice(req: web.Request):
    """Mini App запрашивает отправку инвойса пользователю"""
    uid    = int(req.rel_url.query.get("uid", 0))
    amount = int(req.rel_url.query.get("amount", 50))
    amount = max(10, min(amount, 10000))
    if not uid:
        return web.json_response({"error":"no uid"}, status=400)
    try:
        await bot.send_invoice(
            chat_id=uid,
            title=f"💰 {amount} монет",
            description=f"Пополнение баланса на {amount} монет",
            payload=f"coins_{uid}_{amount}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{amount} монет", amount=amount)])
        return web.json_response({"ok": True})
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def api_spin(req: web.Request):
    data = await req.json()
    uid      = int(data.get("user_id", 0))
    bet_amt  = int(data.get("bet", 0))
    bet_type = data.get("bet_type", "")

    u = await db.get_user(uid)
    if not u:
        return web.json_response({"error":"user not found"}, status=404)
    if bet_amt <= 0 or bet_amt > u["balance"]:
        return web.json_response({"error":"invalid bet"}, status=400)

    luck = await db.get_luck(uid)

    def check(n, c, bt):
        if bt=="red":    return c=="red"
        if bt=="black":  return c=="black"
        if bt=="green":  return c=="green"
        if bt=="even":   return n!=0 and n%2==0
        if bt=="odd":    return n%2==1
        if bt=="low":    return 1<=n<=18
        if bt=="high":   return 19<=n<=36
        if bt=="dozen1": return 1<=n<=12
        if bt=="dozen2": return 13<=n<=24
        return False

    if luck == -1:
        rn, rc = random.choice(ROULETTE_NUMBERS)
    else:
        will_win = random.randint(0,99) < luck
        wins  = [(n,c) for n,c in ROULETTE_NUMBERS if check(n,c,bet_type)]
        loses = [(n,c) for n,c in ROULETTE_NUMBERS if not check(n,c,bet_type)]
        if will_win and wins:
            rn,rc = random.choice(wins)
        elif loses:
            rn,rc = random.choice(loses)
        else:
            rn,rc = random.choice(ROULETTE_NUMBERS)

    MULT = {"red":2,"black":2,"green":14,"even":2,"odd":2,"low":2,"high":2,"dozen1":3,"dozen2":3}
    won  = check(rn, rc, bet_type)
    mult = MULT.get(bet_type, 2)
    ridx = next(i for i,(n,c) in enumerate(ROULETTE_NUMBERS) if n==rn and c==rc)

    if won:
        gain    = bet_amt * mult
        new_bal = await db.add_to_balance(uid, gain - bet_amt)
        await db.add_history(uid, "win", gain, f"Европ. рулетка: {rn} {rc}, ×{mult}")
        await db.update_spin_stats(uid, True, gain, 0)
    else:
        new_bal = await db.add_to_balance(uid, -bet_amt)
        await db.add_history(uid, "lose", bet_amt, f"Европ. рулетка: {rn} {rc}")
        await db.update_spin_stats(uid, False, 0, bet_amt)

    return web.json_response({
        "result_n": rn, "result_c": rc, "result_index": ridx,
        "won": won, "gain": gain if won else 0, "new_balance": new_bal
    })

async def api_gta_lobby(req: web.Request):
    lobby = await db.get_open_lobby()
    if not lobby:
        lid = await db.create_lobby()
        lobby = await db.get_lobby(lid)
    bets = await db.get_lobby_bets(lobby["id"])
    return web.json_response({"lobby": lobby, "bets": bets})

async def api_gta_bet(req: web.Request):
    data   = await req.json()
    uid    = int(data.get("user_id", 0))
    amount = int(data.get("amount", 0))

    u = await db.get_user(uid)
    if not u:
        return web.json_response({"error":"user not found"}, status=404)
    if amount <= 0 or amount > u["balance"]:
        return web.json_response({"error":"invalid amount"}, status=400)

    lobby = await db.get_open_lobby()
    if not lobby:
        lid = await db.create_lobby()
        lobby = await db.get_lobby(lid)
    if lobby["status"] != "open":
        return web.json_response({"error":"lobby not open"}, status=400)

    await db.add_to_balance(uid, -amount)
    await db.place_gta_bet(lobby["id"], uid, amount)
    await db.add_history(uid, "lose", amount, f"GTA ставка #{lobby['id']}")

    bets = await db.get_lobby_bets(lobby["id"])
    unique = len({b["user_id"] for b in bets})
    if unique >= GTA_MIN_PLAYERS and lobby["id"] not in gta_timers:
        task = asyncio.create_task(_gta_spin_delayed(lobby["id"]))
        gta_timers[lobby["id"]] = task

    nb = (await db.get_user(uid))["balance"]
    return web.json_response({"success":True,"new_balance":nb,"lobby_id":lobby["id"],
        "players":unique,"pot":(await db.get_lobby(lobby["id"]))["pot"]})

async def api_gta_status(req: web.Request):
    lid = int(req.match_info["lid"])
    lobby = await db.get_lobby(lid)
    if not lobby:
        return web.json_response({"error":"not found"}, status=404)
    bets = await db.get_lobby_bets(lid)
    return web.json_response({"lobby":lobby,"bets":bets})

async def _gta_spin_delayed(lid: int):
    await asyncio.sleep(GTA_SPIN_DELAY)
    await _gta_run(lid)
    gta_timers.pop(lid, None)

async def _gta_run(lid: int):
    lobby = await db.get_lobby(lid)
    if not lobby or lobby["status"] != "open":
        return
    bets = await db.get_lobby_bets(lid)
    if not bets:
        return
    await db.set_lobby_spinning(lid)

    pot   = lobby["pot"]
    total = sum(b["amount"] for b in bets)
    weights = []
    for b in bets:
        luck = await db.get_luck(b["user_id"])
        base = b["amount"] / total * 100
        if luck == -1:   weights.append(base)
        elif luck == 0:  weights.append(0.01)
        elif luck == 100:weights.append(999999)
        else:            weights.append(float(luck))

    winner = random.choices(bets, weights=weights, k=1)[0]
    wid    = winner["user_id"]

    def _comm(p):
        if p<=500:  return max(1,round(p*3/100))
        if p<=2000: return max(1,round(p*5/100))
        return max(1,round(p*8/100))

    commission = _comm(pot)
    payout     = pot - commission
    await db.add_to_balance(wid, payout)
    await db.add_history(wid,"win",payout,f"GTA #{lid}: банк {pot}, комиссия {commission}")
    await db.update_spin_stats(wid, True, payout, 0)
    for b in bets:
        if b["user_id"] != wid:
            await db.update_spin_stats(b["user_id"], False, 0, b["amount"])
    await db.close_lobby(lid, wid, commission)
    try:
        wu = await db.get_user(wid)
        pct = 3 if pot<=500 else 5 if pot<=2000 else 8
        await bot.send_message(wid,
            f"🎉 <b>Вы выиграли в GTA-рулетке!</b>\n"
            f"💰 Банк: {pot} · Комиссия {pct}%: {commission}\n"
            f"✅ Выплата: <b>{payout}</b> монет\n"
            f"📊 Баланс: <b>{wu['balance']}</b>", parse_mode="HTML")
    except Exception as e:
        logger.warning(f"GTA notify error: {e}")

# ── Admin API ──
def _is_admin(req: web.Request):
    # Проверка по токену бота ИЛИ по uid администратора
    key = req.headers.get("X-Admin-Key", "")
    uid_hdr = req.headers.get("X-Admin-Uid", "")
    try:
        return key == BOT_TOKEN or int(uid_hdr) in ADMIN_IDS
    except ValueError:
        return False

async def api_admin_users(req: web.Request):
    if not _is_admin(req):
        return web.json_response({"error":"forbidden"}, status=403)
    return web.json_response(await db.get_all_users())

async def api_admin_set_balance(req: web.Request):
    if not _is_admin(req):
        return web.json_response({"error":"forbidden"}, status=403)
    data = await req.json()
    uid, new_bal = int(data["user_id"]), int(data["balance"])
    old = int(data.get("old_balance", 0))
    await db.set_balance(uid, new_bal)
    delta = new_bal - old
    await db.add_history(uid, "add" if delta>=0 else "sub", abs(delta), "Изменено администратором")
    return web.json_response({"success":True,"balance":new_bal})

async def api_admin_set_luck(req: web.Request):
    if not _is_admin(req):
        return web.json_response({"error":"forbidden"}, status=403)
    data = await req.json()
    await db.set_luck(int(data["user_id"]), int(data["luck"]))
    return web.json_response({"success":True})

# ── Static ──
BASE = Path(__file__).parent

async def serve(f: str):
    p = BASE / f
    if p.exists():
        return web.Response(text=p.read_text("utf-8"), content_type="text/html", charset="utf-8")
    return web.Response(text="Not found", status=404)

async def serve_app(req):   return await serve("telegram_mini_app.html")
async def serve_admin(req): return await serve("admin_panel.html")
async def health(req):      return web.Response(text="OK")

async def start_web():
    app = web.Application()
    app.router.add_get("/",        serve_app)
    app.router.add_get("/admin",   serve_admin)
    app.router.add_get("/health",  health)
    app.router.add_get("/api/user/{uid}",          api_user)
    app.router.add_get("/api/history/{uid}",       api_history)
    app.router.add_get("/api/invoice",             api_invoice)
    app.router.add_post("/api/spin",               api_spin)
    app.router.add_get("/api/gta/lobby",           api_gta_lobby)
    app.router.add_post("/api/gta/bet",            api_gta_bet)
    app.router.add_get("/api/gta/status/{lid}",    api_gta_status)
    app.router.add_get("/api/admin/users",         api_admin_users)
    app.router.add_post("/api/admin/set_balance",  api_admin_set_balance)
    app.router.add_post("/api/admin/set_luck",     api_admin_set_luck)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner,"0.0.0.0",PORT).start()
    logger.info(f"HTTP :{PORT}")

async def main():
    await db.init_db()
    await start_web()
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())