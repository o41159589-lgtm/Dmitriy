"""
Casino Bot — aiogram 3.x + aiosqlite  /  TopLuck Casino
"""
import asyncio, time, logging, os, random
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
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
import database as db

BOT_TOKEN       = "8686326767:AAFheVAG5rhSjpQHaAJClR-axeuBbM0Zni8"
ADMIN_IDS       = [1840233118, 5709138319]
WEBAPP_URL      = "https://dmitriy-45jd.onrender.com"
ADMIN_URL       = "https://dmitriy-45jd.onrender.com/admin"
PORT            = int(os.environ.get("PORT", 8080))
GTA_MIN_PLAYERS = 2
GTA_SPIN_DELAY  = 15

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
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

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    u = await db.ensure_user(user.id, user.username or "", user.first_name or "")
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
                    except Exception: pass
        except (ValueError, IndexError): pass
    if len(parts) > 1 and parts[1].startswith("gift_request"):
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id,
                    f"📦 Пользователь <b>{user.first_name}</b> (ID: <code>{user.id}</code>) написал боту по заявке на подарок.",
                    parse_mode="HTML")
            except Exception: pass
    kb_reply = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🎰 Казино", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True)
    kb_inline = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎰 Открыть TopLuck", web_app=WebAppInfo(url=WEBAPP_URL))]])
    await message.answer(
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        f"🍀 <b>TopLuck Casino</b> — крути рулетку и выигрывай!\n\n"
        f"💰 Ваш баланс: <b>{u['balance']}</b> монет",
        reply_markup=kb_reply, parse_mode="HTML")
    await message.answer("Нажми кнопку ниже:", reply_markup=kb_inline)

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛠 Открыть админ-панель", web_app=WebAppInfo(url=ADMIN_URL))]])
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=kb, parse_mode="HTML")

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(F.successful_payment)
async def on_payment(message: Message):
    pl = message.successful_payment.invoice_payload
    parts = pl.split("_")
    if parts[0] == "coins" and len(parts) == 3:
        uid, amount = int(parts[1]), int(parts[2])
        nb = await db.add_to_balance(uid, amount)
        await db.add_history(uid, "deposit", amount, "Пополнение через Stars")
        await message.answer(f"✅ Оплата прошла!\n💰 +{amount} монет → баланс: <b>{nb}</b>", parse_mode="HTML")

# ── HTTP API ──
async def api_user(req: web.Request):
    uid = int(req.match_info["uid"])
    u = await db.get_user(uid)
    if not u: return web.json_response({"error":"not found"}, status=404)
    return web.json_response(u)

async def api_ensure_user(req: web.Request):
    data = await req.json()
    uid = int(data.get("user_id", 0))
    if not uid: return web.json_response({"error":"no uid"}, status=400)
    u = await db.ensure_user(uid, str(data.get("username","")), str(data.get("first_name","")))
    return web.json_response(u)

async def api_history(req: web.Request):
    uid = int(req.match_info["uid"])
    return web.json_response(await db.get_history(uid))

async def api_invoice(req: web.Request):
    uid    = int(req.rel_url.query.get("uid", 0))
    amount = max(10, min(int(req.rel_url.query.get("amount", 50)), 10000))
    if not uid: return web.json_response({"error":"no uid"}, status=400)
    try:
        await bot.send_invoice(chat_id=uid, title=f"💰 {amount} монет",
            description=f"Пополнение баланса на {amount} монет",
            payload=f"coins_{uid}_{amount}", currency="XTR",
            prices=[LabeledPrice(label=f"{amount} монет", amount=amount)])
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def api_get_gifts(req: web.Request):
    try:
        result = await bot.get_available_gifts()
        gifts_list = []
        for gift in result.gifts:
            gifts_list.append({
                "id": gift.id,
                "emoji": gift.sticker.emoji if gift.sticker else "🎁",
                "star_count": gift.star_count,
                "total_count": gift.total_count,
                "remaining_count": gift.remaining_count,
                "is_limited": gift.total_count is not None,
            })
        return web.json_response({"gifts": gifts_list})
    except Exception as e:
        logger.error(f"get_available_gifts: {e}")
        return web.json_response({"error": str(e), "gifts": []}, status=500)

async def api_gift_buy(req: web.Request):
    data         = await req.json()
    uid          = int(data.get("user_id", 0))
    gift_id      = str(data.get("gift_id", ""))
    star_count   = int(data.get("star_count", 0))
    source       = str(data.get("source", "bot"))
    recipient_id = int(data.get("recipient_id", uid))
    anonymous    = bool(data.get("anonymous", False))
    message_text = data.get("message")
    sender_name  = data.get("sender_name", "Аноним")
    gift_name    = str(data.get("gift_name", "Подарок"))
    gift_emoji   = str(data.get("gift_emoji", "🎁"))

    if not uid: return web.json_response({"error":"no uid"}, status=400)
    u = await db.get_user(uid)
    if not u: return web.json_response({"error":"user not found"}, status=404)
    price = star_count
    if price <= 0: return web.json_response({"error":"invalid price"}, status=400)
    if u["balance"] < price:
        return web.json_response({"error":"Недостаточно монет на балансе!"}, status=400)

    if source == "bot" and gift_id:
        caption = None
        if message_text and message_text != "auto":
            caption = message_text[:255]
        elif not anonymous and sender_name:
            caption = f"От {sender_name} 🎁"
        try:
            await bot.send_gift(user_id=recipient_id, gift_id=gift_id, text=caption)
        except TelegramForbiddenError:
            return web.json_response({"error":"❌ Пользователь заблокировал бота. Монеты не списаны."}, status=400)
        except TelegramBadRequest as e:
            s = str(e).lower()
            if "not enough stars" in s or "insufficient" in s or "STARGIFT_USAGE_LIMITED" in str(e):
                return web.json_response({"error":"⚠️ У бота недостаточно звёзд для этого подарка. Монеты не списаны."}, status=400)
            if "gift_id_invalid" in s or "invalid gift" in s:
                return web.json_response({"error":"❌ Этот подарок больше недоступен в Telegram. Монеты не списаны."}, status=400)
            return web.json_response({"error":f"❌ Ошибка: {str(e)}"}, status=400)
        except Exception as e:
            return web.json_response({"error":f"❌ Ошибка отправки: {str(e)}"}, status=500)
        new_bal = await db.add_to_balance(uid, -price)
        await db.add_history(uid, "gift_sent", price, f"Подарок → {recipient_id}: {gift_emoji} (⭐{price})")
        if recipient_id != uid:
            await db.add_history(recipient_id, "gift_received", 0, f"Подарок от {'Аноним' if anonymous else sender_name}")
        return web.json_response({"ok":True,"new_balance":new_bal})
    else:
        # Owner gift
        if recipient_id != uid:
            try:
                await bot.send_chat_action(chat_id=recipient_id, action="typing")
            except TelegramForbiddenError:
                return web.json_response({"error":"❌ Получатель заблокировал бота. Монеты не списаны."}, status=400)
            except Exception: pass
        new_bal = await db.add_to_balance(uid, -price)
        await db.add_history(uid, "gift_sent", price, f"Заявка владельцу: {gift_emoji} {gift_name} (⭐{price})")
        sender_info = "Аноним 🎭" if anonymous else f"{sender_name} (ID: {uid})"
        admin_msg = (
            f"📦 <b>Заявка на подарок от владельца</b>\n\n"
            f"👤 Покупатель: <b>{sender_info}</b>\n"
            f"🎁 Подарок: {gift_emoji} <b>{gift_name}</b>\n"
            f"⭐ Стоимость: {price} монет\n"
            f"📩 Получатель ID: <code>{recipient_id}</code>\n"
            + (f"💬 Подпись: <i>{message_text}</i>\n" if message_text and message_text != "auto" else "")
            + f"\n⚠️ Выдайте подарок вручную."
        )
        for admin_id in ADMIN_IDS:
            try: await bot.send_message(admin_id, admin_msg, parse_mode="HTML")
            except Exception as e: logger.warning(f"Admin notify: {e}")
        try:
            await bot.send_message(uid,
                f"📨 <b>Заявка принята!</b>\n\nВы заказали: {gift_emoji} <b>{gift_name}</b> ({price} ⭐)\n"
                f"Владелец получил уведомление и скоро свяжется с вами.\n\n"
                f"💬 Напишите боту, чтобы владелец увидел ваш запрос!",
                parse_mode="HTML")
        except Exception as e: logger.warning(f"Buyer notify: {e}")
        return web.json_response({"ok":True,"new_balance":new_bal})

async def api_spin(req: web.Request):
    data = await req.json()
    uid, bet_amt, bet_type = int(data.get("user_id",0)), int(data.get("bet",0)), data.get("bet_type","")
    u = await db.get_user(uid)
    if not u: return web.json_response({"error":"user not found"}, status=404)
    if bet_amt <= 0 or bet_amt > u["balance"]: return web.json_response({"error":"invalid bet"}, status=400)
    luck, global_k = await db.get_luck(uid), await db.get_global_luck_coeff()
    def check(n,c,bt):
        if bt=="red": return c=="red"
        if bt=="black": return c=="black"
        if bt=="green": return c=="green"
        if bt=="even": return n!=0 and n%2==0
        if bt=="odd": return n%2==1
        if bt=="low": return 1<=n<=18
        if bt=="high": return 19<=n<=36
        if bt=="dozen1": return 1<=n<=12
        if bt=="dozen2": return 13<=n<=24
        return False

    wins  = [(n,co) for n,co in ROULETTE_NUMBERS if check(n,co,bet_type)]
    loses = [(n,co) for n,co in ROULETTE_NUMBERS if not check(n,co,bet_type)]

    # ── luck=100: guaranteed win (always) ──
    if luck == 100:
        rn, rc = random.choice(wins) if wins else random.choice(ROULETTE_NUMBERS)
    # ── luck=0: guaranteed loss (always) ──
    elif luck == 0:
        rn, rc = random.choice(loses) if loses else random.choice(ROULETTE_NUMBERS)
    elif luck == -1:
        # Auto: global_k scales win probability
        if global_k >= 1.0 or random.random() < global_k:
            rn, rc = random.choice(ROULETTE_NUMBERS)
        else:
            rn, rc = random.choice(loses) if loses else random.choice(ROULETTE_NUMBERS)
    else:
        # Personal luck 1–99 scaled by global_k
        effective = min(100, int(luck * global_k))
        will_win = random.randint(0, 99) < effective
        if will_win and wins: rn, rc = random.choice(wins)
        elif loses:           rn, rc = random.choice(loses)
        else:                 rn, rc = random.choice(ROULETTE_NUMBERS)
    MULT = {"red":2,"black":2,"green":14,"even":2,"odd":2,"low":2,"high":2,"dozen1":3,"dozen2":3}
    won  = check(rn, rc, bet_type)
    mult = MULT.get(bet_type, 2)
    ridx = next(i for i,(n,c) in enumerate(ROULETTE_NUMBERS) if n==rn and c==rc)
    gain = 0
    if won:
        gain = bet_amt * mult
        new_bal = await db.add_to_balance(uid, gain - bet_amt)
        await db.add_history(uid, "win", gain, f"Европ. рулетка: {rn} {rc}, x{mult}")
        await db.update_spin_stats(uid, True, gain, 0)
        try:
            ico = "🟢" if rc=="green" else "🔴" if rc=="red" else "⚫"
            await bot.send_message(uid,
                f"🎉 <b>Выигрыш в Европейской рулетке!</b>\n{ico} Выпало: <b>{rn}</b> · x{mult}\n"
                f"💰 +<b>{gain}</b> монет · Баланс: <b>{new_bal}</b>", parse_mode="HTML")
        except Exception: pass
    else:
        new_bal = await db.add_to_balance(uid, -bet_amt)
        await db.add_history(uid, "lose", bet_amt, f"Европ. рулетка: {rn} {rc}")
        await db.update_spin_stats(uid, False, 0, bet_amt)
    return web.json_response({"result_n":rn,"result_c":rc,"result_index":ridx,"won":won,"gain":gain,"new_balance":new_bal})

async def _enrich_bets(bets):
    enriched = []
    for b in bets:
        u = await db.get_user(b["user_id"])
        name = (u.get("first_name") or u.get("username") or f"ID{b['user_id']}") if u else f"ID{b['user_id']}"
        enriched.append({**b, "player_name": name})
    return enriched

async def api_gta_lobby(req: web.Request):
    lobby = await db.get_open_lobby()
    if not lobby:
        lid = await db.create_lobby(); lobby = await db.get_lobby(lid)
    bets = await _enrich_bets(await db.get_lobby_bets(lobby["id"]))
    return web.json_response({"lobby": lobby, "bets": bets})

async def api_gta_bet(req: web.Request):
    data = await req.json()
    uid, amount = int(data.get("user_id",0)), int(data.get("amount",0))
    u = await db.get_user(uid)
    if not u: return web.json_response({"error":"user not found"}, status=404)
    if amount <= 0 or amount > u["balance"]: return web.json_response({"error":"invalid amount"}, status=400)
    lobby = await db.get_open_lobby()
    if not lobby:
        lid = await db.create_lobby(); lobby = await db.get_lobby(lid)
    if lobby["status"] != "open": return web.json_response({"error":"lobby not open"}, status=400)
    await db.add_to_balance(uid, -amount)
    await db.place_gta_bet(lobby["id"], uid, amount)
    await db.add_history(uid, "lose", amount, f"GTA ставка #{lobby['id']}")
    bets = await db.get_lobby_bets(lobby["id"])
    unique = len({b["user_id"] for b in bets})
    lid = lobby["id"]
    new_deadline = time.time() + GTA_SPIN_DELAY
    await db.set_lobby_deadline(lid, new_deadline)
    if unique >= GTA_MIN_PLAYERS:
        if lid in gta_timers: gta_timers[lid].cancel()
        gta_timers[lid] = asyncio.create_task(_gta_spin_delayed(lid))
    nb = (await db.get_user(uid))["balance"]
    updated_lobby = await db.get_lobby(lid)
    return web.json_response({"success":True,"new_balance":nb,"lobby_id":lid,"players":unique,"pot":updated_lobby["pot"],"deadline":new_deadline})

async def api_gta_status(req: web.Request):
    lid = int(req.match_info["lid"])
    lobby = await db.get_lobby(lid)
    if not lobby: return web.json_response({"error":"not found"}, status=404)
    bets = await _enrich_bets(await db.get_lobby_bets(lid))
    return web.json_response({"lobby":lobby,"bets":bets})

async def _gta_spin_delayed(lid):
    await asyncio.sleep(GTA_SPIN_DELAY)
    await _gta_run(lid)
    gta_timers.pop(lid, None)

async def _gta_run(lid):
    lobby = await db.get_lobby(lid)
    if not lobby or lobby["status"] != "open": return
    bets = await db.get_lobby_bets(lid)
    if not bets: return
    await db.set_lobby_spinning(lid)
    pot, total = lobby["pot"], sum(b["amount"] for b in bets)
    global_k = await db.get_global_luck_coeff()

    # Fetch luck for every player
    luck_map = {}
    for b in bets:
        luck_map[b["user_id"]] = await db.get_luck(b["user_id"])

    # ── Luck=100 players always win; luck=0 players always lose ──
    # Group unique players by their max bet entry
    player_bets = {}  # user_id → bet row (use last/only entry)
    for b in bets:
        if b["user_id"] not in player_bets:
            player_bets[b["user_id"]] = b
        else:
            # accumulate amount for weight purposes
            player_bets[b["user_id"]] = {**player_bets[b["user_id"]],
                "amount": player_bets[b["user_id"]]["amount"] + b["amount"]}

    lucky100 = [uid for uid, lk in luck_map.items() if lk == 100]
    unlucky0 = {uid for uid, lk in luck_map.items() if lk == 0}

    # All participants excluding guaranteed losers
    eligible = [b for b in player_bets.values() if b["user_id"] not in unlucky0]
    if not eligible:
        # Everyone has luck=0 — pick by pure bet weight from all
        eligible = list(player_bets.values())

    if lucky100:
        # Among lucky=100 players who are eligible, do a fair weighted draw
        lucky_eligible = [b for b in eligible if b["user_id"] in set(lucky100)]
        if lucky_eligible:
            # Fair draw among them weighted by their bet amount
            amounts = [b["amount"] for b in lucky_eligible]
            winner_row = random.choices(lucky_eligible, weights=amounts, k=1)[0]
        else:
            # lucky100 players all have luck=0 override (contradictory) — fall through
            lucky_eligible = eligible
            amounts = [b["amount"] for b in lucky_eligible]
            winner_row = random.choices(lucky_eligible, weights=amounts, k=1)[0]
    else:
        # Normal weighted draw respecting global_k
        weights = []
        for b in eligible:
            lk = luck_map[b["user_id"]]
            base = b["amount"] / total * 100
            if lk == -1:
                w = base * (0.3 + global_k * 0.7)
            else:
                ep = max(lk * global_k, 0.1)
                w = base * (ep / 50.0)
            weights.append(max(0.001, w))
        winner_row = random.choices(eligible, weights=weights, k=1)[0]

    wid = winner_row["user_id"]

    def _comm(p):
        if p<=500: return max(1,round(p*3/100))
        if p<=2000: return max(1,round(p*5/100))
        return max(1,round(p*8/100))

    commission = _comm(pot)
    payout = pot - commission
    await db.add_to_balance(wid, payout)
    await db.add_history(wid,"win",payout,f"GTA #{lid}: банк {pot}, комиссия {commission}")
    await db.update_spin_stats(wid, True, payout, 0)
    for b in bets:
        if b["user_id"] != wid: await db.update_spin_stats(b["user_id"], False, 0, b["amount"])
    await db.close_lobby(lid, wid, commission)
    try:
        wu = await db.get_user(wid)
        pct = 3 if pot<=500 else 5 if pot<=2000 else 8
        await bot.send_message(wid,
            f"🎉 <b>Вы выиграли в GTA-рулетке!</b>\n💰 Банк: {pot} · Комиссия {pct}%: {commission}\n"
            f"✅ Выплата: <b>{payout}</b> монет\n📊 Баланс: <b>{wu['balance']}</b>", parse_mode="HTML")
    except Exception as e: logger.warning(f"GTA notify: {e}")

def _is_admin(req):
    try: return req.headers.get("X-Admin-Key","") == BOT_TOKEN or int(req.headers.get("X-Admin-Uid","0")) in ADMIN_IDS
    except: return False

async def api_admin_get_global_luck(req):
    if not _is_admin(req): return web.json_response({"error":"forbidden"}, status=403)
    return web.json_response({"coeff": await db.get_global_luck_coeff()})

async def api_admin_set_global_luck(req):
    if not _is_admin(req): return web.json_response({"error":"forbidden"}, status=403)
    data = await req.json(); coeff = float(data.get("coeff",1.0))
    await db.set_global_luck_coeff(coeff); return web.json_response({"ok":True,"coeff":coeff})

async def api_admin_revenue(req):
    if not _is_admin(req): return web.json_response({"error":"forbidden"}, status=403)
    from_ts = float(req.rel_url.query.get("from",0)); to_ts = float(req.rel_url.query.get("to",9999999999))
    return web.json_response(await db.get_revenue(from_ts, to_ts))

async def api_admin_users(req):
    if not _is_admin(req): return web.json_response({"error":"forbidden"}, status=403)
    return web.json_response(await db.get_all_users_by_join())

async def api_admin_set_balance(req):
    if not _is_admin(req): return web.json_response({"error":"forbidden"}, status=403)
    data = await req.json(); uid, new_bal = int(data["user_id"]), int(data["balance"])
    old = int(data.get("old_balance",0)); await db.set_balance(uid, new_bal)
    if new_bal - old > 0: await db.add_history(uid, "deposit", new_bal-old, "Пополнение администратором")
    return web.json_response({"success":True,"balance":new_bal})

async def api_admin_set_luck(req):
    if not _is_admin(req): return web.json_response({"error":"forbidden"}, status=403)
    data = await req.json(); await db.set_luck(int(data["user_id"]), int(data["luck"]))
    return web.json_response({"success":True})

BASE = Path(__file__).parent

async def serve_html(f):
    p = BASE / f
    if p.exists(): return web.Response(text=p.read_text("utf-8"), content_type="text/html", charset="utf-8")
    return web.Response(text="Not found", status=404)

async def serve_app(req):   return await serve_html("index.html")
async def serve_admin(req): return await serve_html("admin_panel.html")
async def health(req):      return web.Response(text="OK")

async def serve_static(req):
    filename = req.match_info.get("filename","")
    if ".." in filename: return web.Response(text="Forbidden", status=403)
    p = BASE / filename
    if not p.exists(): return web.Response(text="Not found", status=404)
    ext = p.suffix.lower()
    ct = {".css":"text/css",".png":"image/png",".jpg":"image/jpeg",".js":"application/javascript",
          ".svg":"image/svg+xml",".html":"text/html"}.get(ext,"application/octet-stream")
    if ext in (".html",".css",".js"):
        return web.Response(text=p.read_text("utf-8"), content_type=ct, charset="utf-8")
    return web.Response(body=p.read_bytes(), content_type=ct)

async def start_web():
    app = web.Application()
    app.router.add_get("/", serve_app)
    app.router.add_get("/admin", serve_admin)
    app.router.add_get("/health", health)
    app.router.add_post("/api/ensure_user",        api_ensure_user)
    app.router.add_get ("/api/user/{uid}",         api_user)
    app.router.add_get ("/api/history/{uid}",      api_history)
    app.router.add_get ("/api/invoice",            api_invoice)
    app.router.add_get ("/api/gifts",              api_get_gifts)
    app.router.add_post("/api/spin",               api_spin)
    app.router.add_get ("/api/gta/lobby",          api_gta_lobby)
    app.router.add_post("/api/gta/bet",            api_gta_bet)
    app.router.add_get ("/api/gta/status/{lid}",   api_gta_status)
    app.router.add_post("/api/gift/buy",           api_gift_buy)
    app.router.add_get ("/api/admin/users",        api_admin_users)
    app.router.add_post("/api/admin/set_balance",  api_admin_set_balance)
    app.router.add_post("/api/admin/set_luck",     api_admin_set_luck)
    app.router.add_get ("/api/admin/revenue",      api_admin_revenue)
    app.router.add_get ("/api/admin/global_luck",  api_admin_get_global_luck)
    app.router.add_post("/api/admin/global_luck",  api_admin_set_global_luck)
    app.router.add_get("/{filename:.+}", serve_static)
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