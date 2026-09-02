"""database.py — SQLite через aiosqlite"""
import aiosqlite, time, os, json

DB_PATH = os.environ.get("DB_PATH", "casino.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                balance    INTEGER DEFAULT 10,
                luck_pct   INTEGER DEFAULT -1,
                spins      INTEGER DEFAULT 0,
                wins       INTEGER DEFAULT 0,
                total_won  INTEGER DEFAULT 0,
                total_lost INTEGER DEFAULT 0,
                banned     INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                type       TEXT NOT NULL,
                amount     INTEGER NOT NULL,
                detail     TEXT DEFAULT '',
                created_at REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS nft_gallery (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                sticker_file_id TEXT NOT NULL,
                file_unique_id TEXT DEFAULT '',
                is_video      INTEGER DEFAULT 0,
                is_animated   INTEGER DEFAULT 0,
                source        TEXT DEFAULT 'manual',
                added_by      INTEGER DEFAULT 0,
                created_at    REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS glogs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                thread      INTEGER NOT NULL,
                category    TEXT NOT NULL,
                text        TEXT NOT NULL,
                created_at  REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS gta_lobbies (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                status     TEXT DEFAULT 'open',
                winner_id  INTEGER DEFAULT NULL,
                pot        INTEGER DEFAULT 0,
                commission INTEGER DEFAULT 0,
                deadline   REAL DEFAULT 0,
                created_at REAL DEFAULT 0,
                closed_at  REAL DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS gta_bets (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                lobby_id   INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                amount     INTEGER NOT NULL,
                created_at REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT DEFAULT ''
            );
            INSERT OR IGNORE INTO settings(key,value) VALUES ('global_luck_coeff','1.0');
            INSERT OR IGNORE INTO settings(key,value) VALUES ('euro_luck_coeff','1.0');
            INSERT OR IGNORE INTO settings(key,value) VALUES ('mines_luck_coeff','1.0');
            INSERT OR IGNORE INTO settings(key,value) VALUES ('tower_luck_coeff','1.0');
            INSERT OR IGNORE INTO settings(key,value) VALUES ('mines_max_mult','25.0');
            INSERT OR IGNORE INTO settings(key,value) VALUES ('tower_max_floors','10');
            INSERT OR IGNORE INTO settings(key,value) VALUES ('blackjack_luck_coeff','1.0');
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                type        TEXT NOT NULL,
                title       TEXT NOT NULL,
                description TEXT DEFAULT '',
                reward      INTEGER NOT NULL,
                target      TEXT DEFAULT '',
                target_count INTEGER DEFAULT 1,
                active      INTEGER DEFAULT 1,
                created_at  REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS user_tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                task_id     INTEGER NOT NULL,
                completed_at REAL DEFAULT 0,
                UNIQUE(user_id, task_id)
            );
            CREATE TABLE IF NOT EXISTS promo_codes (
                code        TEXT PRIMARY KEY,
                reward      INTEGER DEFAULT 0,
                uses_left   INTEGER DEFAULT NULL,
                expires_at  REAL    DEFAULT NULL,
                total_activations INTEGER DEFAULT 0,
                created_at  REAL    DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS promo_activations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                code            TEXT    NOT NULL,
                user_id         INTEGER NOT NULL,
                amount_received INTEGER NOT NULL,
                activated_at    REAL    DEFAULT 0,
                UNIQUE(code, user_id)
            );
        """)
        # Migration: add banned column if missing
        try:
            await db.execute('ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0')
        except Exception: pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT DEFAULT ''")
        except Exception: pass
        try:
            await db.execute("ALTER TABLE nft_gallery ADD COLUMN file_unique_id TEXT DEFAULT ''")
        except Exception: pass
        try:
            await db.execute("ALTER TABLE nft_gallery ADD COLUMN source TEXT DEFAULT 'manual'")
        except Exception: pass
        try:
            await db.execute('ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL')
        except Exception: pass
        try:
            await db.execute('ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0')
        except Exception: pass
        try:
            await db.execute('ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 0')
        except Exception: pass
        # Migration: add new settings rows if missing (for existing DBs)
        for key, default in [
            ('euro_luck_coeff',  '1.0'),
            ('mines_luck_coeff', '1.0'),
        ]:
            await db.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, default))
        await db.commit()

async def _row(db, sql, params=()):
    db.row_factory = aiosqlite.Row
    async with db.execute(sql, params) as cur:
        r = await cur.fetchone()
        return dict(r) if r else None

async def _rows(db, sql, params=()):
    db.row_factory = aiosqlite.Row
    async with db.execute(sql, params) as cur:
        return [dict(r) for r in await cur.fetchall()]

# ── USERS ──
async def get_user(uid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        return await _row(db, "SELECT * FROM users WHERE user_id=?", (uid,))

async def ensure_user(uid: int, username="", first_name=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id,username,first_name,balance,created_at) VALUES (?,?,?,10,?)",
            (uid, username, first_name, time.time()))
        await db.execute(
            "UPDATE users SET username=?,first_name=? WHERE user_id=?",
            (username, first_name, uid))
        await db.commit()
    return await get_user(uid)

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        return await _rows(db, "SELECT * FROM users ORDER BY balance DESC")

async def get_all_users_by_join():
    async with aiosqlite.connect(DB_PATH) as db:
        return await _rows(db, "SELECT * FROM users ORDER BY created_at ASC")

async def set_balance(uid: int, val: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=? WHERE user_id=?", (max(0,val), uid))
        await db.commit()

async def add_to_balance(uid: int, delta: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
            cur_bal = row[0] if row else 0
        new_bal = max(0, cur_bal + delta)
        await db.execute("UPDATE users SET balance=? WHERE user_id=?", (new_bal, uid))
        await db.commit()
        return new_bal

async def set_luck(uid: int, luck: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET luck_pct=? WHERE user_id=?", (luck, uid))
        await db.commit()

async def get_luck(uid: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT luck_pct FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else -1

async def update_spin_stats(uid: int, won: bool, won_amt: int, lost_amt: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET spins=spins+1,wins=wins+?,total_won=total_won+?,total_lost=total_lost+? WHERE user_id=?",
            (1 if won else 0, won_amt, lost_amt, uid))
        await db.commit()

# ── GROUP LOGS (in-panel copy of the Telegram log group, category = topic name) ──
async def add_glog(thread: int, category: str, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO glogs (thread,category,text,created_at) VALUES (?,?,?,?)",
            (thread, category, text, time.time()))
        await db.commit()

async def get_glogs(category: str = None, limit: int = 300):
    async with aiosqlite.connect(DB_PATH) as db:
        if category and category != "all":
            return await _rows(db,
                "SELECT * FROM glogs WHERE category=? ORDER BY created_at DESC LIMIT ?",
                (category, limit))
        return await _rows(db,
            "SELECT * FROM glogs ORDER BY created_at DESC LIMIT ?", (limit,))

async def get_glog_counts():
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await _rows(db, "SELECT category, COUNT(*) as c FROM glogs GROUP BY category", ())
        return {r["category"]: r["c"] for r in rows}

# ── NFT GALLERY (real unique-gift stickers — manually forwarded, or synced from a sticker pack) ──
async def add_nft(name: str, sticker_file_id: str, is_video: bool, is_animated: bool, added_by: int,
                   file_unique_id: str = "", source: str = "manual"):
    async with aiosqlite.connect(DB_PATH) as db:
        # Skip if this exact sticker (by stable file_unique_id) is already in the gallery
        if file_unique_id:
            async with db.execute("SELECT id FROM nft_gallery WHERE file_unique_id=?", (file_unique_id,)) as cur:
                if await cur.fetchone():
                    return False
        await db.execute(
            "INSERT INTO nft_gallery (name,sticker_file_id,file_unique_id,is_video,is_animated,source,added_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (name, sticker_file_id, file_unique_id, 1 if is_video else 0, 1 if is_animated else 0, source, added_by, time.time()))
        await db.commit()
        return True

async def get_nfts():
    async with aiosqlite.connect(DB_PATH) as db:
        return await _rows(db, "SELECT * FROM nft_gallery ORDER BY created_at DESC", ())

async def delete_nft(nft_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM nft_gallery WHERE id=?", (nft_id,))
        await db.commit()

async def clear_nfts_by_source(source: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM nft_gallery WHERE source=?", (source,))
        await db.commit()

# ── HISTORY ──
async def add_history(uid: int, type_: str, amount: int, detail=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO history (user_id,type,amount,detail,created_at) VALUES (?,?,?,?,?)",
            (uid, type_, amount, detail, time.time()))
        await db.commit()

async def get_history(uid: int, limit=None):
    async with aiosqlite.connect(DB_PATH) as db:
        if limit:
            return await _rows(db,
                "SELECT * FROM history WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (uid, limit))
        return await _rows(db,
            "SELECT * FROM history WHERE user_id=? ORDER BY created_at DESC",
            (uid,))

# ── GTA LOBBIES ──
async def create_lobby() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT INTO gta_lobbies (status,created_at) VALUES ('open',?)", (time.time(),))
        await db.commit()
        return cur.lastrowid

async def get_open_lobby():
    async with aiosqlite.connect(DB_PATH) as db:
        return await _row(db, "SELECT * FROM gta_lobbies WHERE status='open' ORDER BY id DESC LIMIT 1")

async def get_lobby(lid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        return await _row(db, "SELECT * FROM gta_lobbies WHERE id=?", (lid,))

async def get_lobby_bets(lid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        return await _rows(db, "SELECT * FROM gta_bets WHERE lobby_id=? ORDER BY amount DESC", (lid,))

async def place_gta_bet(lid: int, uid: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id,amount FROM gta_bets WHERE lobby_id=? AND user_id=?", (lid, uid)) as cur:
            ex = await cur.fetchone()
        if ex:
            await db.execute("UPDATE gta_bets SET amount=amount+? WHERE id=?", (amount, ex[0]))
        else:
            await db.execute("INSERT INTO gta_bets (lobby_id,user_id,amount,created_at) VALUES (?,?,?,?)",
                (lid, uid, amount, time.time()))
        await db.execute("UPDATE gta_lobbies SET pot=pot+? WHERE id=?", (amount, lid))
        await db.commit()

async def set_lobby_deadline(lid: int, deadline: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE gta_lobbies SET deadline=? WHERE id=?", (deadline, lid))
        await db.commit()

async def set_lobby_spinning(lid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE gta_lobbies SET status='spinning' WHERE id=?", (lid,))
        await db.commit()

async def close_lobby(lid: int, winner_id: int, commission: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE gta_lobbies SET status='done',winner_id=?,commission=?,closed_at=? WHERE id=?",
            (winner_id, commission, time.time(), lid))
        await db.commit()

async def get_revenue(from_ts: float = 0, to_ts: float = 9999999999):
    """Доходность казино за период: комиссии GTA + проигрыши в европейской"""
    async with aiosqlite.connect(DB_PATH) as db_conn:
        # GTA комиссии
        async with db_conn.execute(
            "SELECT COALESCE(SUM(commission),0) FROM gta_lobbies WHERE status='done' AND closed_at>=? AND closed_at<=?",
            (from_ts, to_ts)
        ) as cur:
            gta_commission = (await cur.fetchone())[0] or 0

        # Проигрыши в европейской (тип 'lose' в истории)
        async with db_conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM history WHERE type='lose' AND created_at>=? AND created_at<=?",
            (from_ts, to_ts)
        ) as cur:
            euro_losses = (await cur.fetchone())[0] or 0

        # Выигрыши (выплаты) в европейской
        async with db_conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM history WHERE type='win' AND detail LIKE '%Европ%' AND created_at>=? AND created_at<=?",
            (from_ts, to_ts)
        ) as cur:
            euro_wins = (await cur.fetchone())[0] or 0

        # Пополнения (deposits)
        async with db_conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM history WHERE type='deposit' AND created_at>=? AND created_at<=?",
            (from_ts, to_ts)
        ) as cur:
            deposits = (await cur.fetchone())[0] or 0

        # Итого доход казино
        total_revenue = gta_commission + (euro_losses - euro_wins)

        # Мины — проигрыши и выигрыши
        async with db_conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM history WHERE type='lose' AND detail LIKE '%Мины%' AND created_at>=? AND created_at<=?",
            (from_ts, to_ts)
        ) as cur:
            mines_losses = (await cur.fetchone())[0] or 0
        async with db_conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM history WHERE type='win' AND detail LIKE '%Мины%' AND created_at>=? AND created_at<=?",
            (from_ts, to_ts)
        ) as cur:
            mines_wins = (await cur.fetchone())[0] or 0

        # Башня — проигрыши и выигрыши
        async with db_conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM history WHERE type='lose' AND detail LIKE '%Башня%' AND created_at>=? AND created_at<=?",
            (from_ts, to_ts)
        ) as cur:
            tower_losses = (await cur.fetchone())[0] or 0
        async with db_conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM history WHERE type='win' AND detail LIKE '%Башня%' AND created_at>=? AND created_at<=?",
            (from_ts, to_ts)
        ) as cur:
            tower_wins = (await cur.fetchone())[0] or 0

        # Выводы подарков (реальные деньги, потраченные казино на подарки игрокам)
        async with db_conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM history WHERE type='gift_sent' AND created_at>=? AND created_at<=?",
            (from_ts, to_ts)
        ) as cur:
            withdrawals = (await cur.fetchone())[0] or 0

        # Реальный доход казино = сколько купили монет за звёзды − сколько выплатили подарками за звёзды.
        # (Внутриигровые выигрыши/проигрыши виртуальные и не считаются доходом, пока не выведены подарком.)
        total_revenue = deposits - withdrawals

        return {
            "gta_commission": gta_commission,
            "euro_losses":    euro_losses,
            "euro_wins":      euro_wins,
            "euro_profit":    euro_losses - euro_wins,
            "mines_losses":   mines_losses,
            "mines_wins":     mines_wins,
            "mines_profit":   mines_losses - mines_wins,
            "tower_losses":   tower_losses,
            "tower_wins":     tower_wins,
            "tower_profit":   tower_losses - tower_wins,
            "deposits":       deposits,
            "withdrawals":    withdrawals,
            "total_revenue":  total_revenue,
            "from_ts": from_ts,
            "to_ts":   to_ts,
        }

async def get_global_luck_coeff() -> float:
    """Глобальный коэф. удачи: 1.0 = без изменений, 0.5 = вдвое меньше шансов, 0 = никто не выигрывает"""
    async with aiosqlite.connect(DB_PATH) as db_conn:
        async with db_conn.execute("SELECT value FROM settings WHERE key='global_luck_coeff'") as cur:
            row = await cur.fetchone()
            try: return float(row[0]) if row else 1.0
            except: return 1.0

async def set_global_luck_coeff(coeff: float):
    coeff = max(0.0, min(2.0, coeff))
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('global_luck_coeff',?)",
            (str(coeff),))
        await db_conn.commit()

async def get_tower_luck_coeff() -> float:
    async with aiosqlite.connect(DB_PATH) as db_conn:
        async with db_conn.execute("SELECT value FROM settings WHERE key='tower_luck_coeff'") as cur:
            row = await cur.fetchone()
            try: return float(row[0]) if row else 1.0
            except: return 1.0

async def set_tower_luck_coeff(coeff: float):
    coeff = max(0.0, min(2.0, coeff))
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('tower_luck_coeff',?)",
            (str(coeff),))
        await db_conn.commit()
# ── BAN ──
async def is_banned(uid: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT banned FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
            return bool(row[0]) if row else False

async def get_ban_reason(uid: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT ban_reason FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
            return (row[0] or "") if row else ""

async def set_banned(uid: int, banned: bool, reason: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET banned=?, ban_reason=? WHERE user_id=?",
                          (1 if banned else 0, reason if banned else "", uid))
        await db.commit()
async def get_mines_max_mult() -> float:
    async with aiosqlite.connect(DB_PATH) as db_conn:
        async with db_conn.execute("SELECT value FROM settings WHERE key='mines_max_mult'") as cur:
            row = await cur.fetchone()
            try: return float(row[0]) if row else 25.0
            except: return 25.0

async def set_mines_max_mult(val: float):
    val = max(1.0, min(1000.0, val))
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('mines_max_mult',?)", (str(val),))
        await db_conn.commit()

async def get_tower_max_floors() -> int:
    async with aiosqlite.connect(DB_PATH) as db_conn:
        async with db_conn.execute("SELECT value FROM settings WHERE key='tower_max_floors'") as cur:
            row = await cur.fetchone()
            try: return int(row[0]) if row else 10
            except: return 10

async def set_tower_max_floors(val: int):
    val = max(1, min(50, val))
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('tower_max_floors',?)", (str(val),))
        await db_conn.commit()

# ── EURO LUCK ──
async def get_euro_luck_coeff() -> float:
    async with aiosqlite.connect(DB_PATH) as db_conn:
        async with db_conn.execute("SELECT value FROM settings WHERE key='euro_luck_coeff'") as cur:
            row = await cur.fetchone()
            try: return float(row[0]) if row else 1.0
            except: return 1.0

async def set_euro_luck_coeff(coeff: float):
    coeff = max(0.0, min(2.0, coeff))
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('euro_luck_coeff',?)", (str(coeff),))
        await db_conn.commit()

# ── MINES LUCK ──
async def get_mines_luck_coeff() -> float:
    async with aiosqlite.connect(DB_PATH) as db_conn:
        async with db_conn.execute("SELECT value FROM settings WHERE key='mines_luck_coeff'") as cur:
            row = await cur.fetchone()
            try: return float(row[0]) if row else 1.0
            except: return 1.0

async def set_mines_luck_coeff(coeff: float):
    coeff = max(0.0, min(2.0, coeff))
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('mines_luck_coeff',?)", (str(coeff),))
        await db_conn.commit()

# ── BLACKJACK LUCK ──
async def get_blackjack_luck_coeff() -> float:
    async with aiosqlite.connect(DB_PATH) as db_conn:
        async with db_conn.execute("SELECT value FROM settings WHERE key='blackjack_luck_coeff'") as cur:
            row = await cur.fetchone()
            try: return float(row[0]) if row else 1.0
            except: return 1.0

async def set_blackjack_luck_coeff(coeff: float):
    coeff = max(0.0, min(2.0, coeff))
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('blackjack_luck_coeff',?)", (str(coeff),))
        await db_conn.commit()

# ── PLINKO MULTIPLIERS (15 slots, center-symmetric ladder) ──
DEFAULT_PLINKO_MULTS = [20,10,5,2.5,2,1.5,1.2,0,1.2,1.5,2,2.5,5,10,20]

async def get_plinko_mults() -> list:
    async with aiosqlite.connect(DB_PATH) as db_conn:
        async with db_conn.execute("SELECT value FROM settings WHERE key='plinko_mults'") as cur:
            row = await cur.fetchone()
            if not row: return list(DEFAULT_PLINKO_MULTS)
            try:
                vals = json.loads(row[0])
                if isinstance(vals, list) and len(vals) == 15:
                    return [float(v) for v in vals]
            except Exception:
                pass
            return list(DEFAULT_PLINKO_MULTS)

async def set_plinko_mults(vals: list):
    vals = [max(0.0, min(1000.0, float(v))) for v in vals][:15]
    while len(vals) < 15:
        vals.append(0.0)
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('plinko_mults',?)", (json.dumps(vals),))
        await db_conn.commit()

# ── PROMO CODES ──
async def get_promo(code: str):
    async with aiosqlite.connect(DB_PATH) as db_conn:
        return await _row(db_conn, "SELECT * FROM promo_codes WHERE code=?", (code,))

async def get_all_promos():
    async with aiosqlite.connect(DB_PATH) as db_conn:
        return await _rows(db_conn,
            "SELECT * FROM promo_codes ORDER BY created_at DESC")

async def create_promo(code: str, reward: int, uses_left, expires_at):
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "INSERT INTO promo_codes(code,reward,uses_left,expires_at,total_activations,created_at)"
            " VALUES(?,?,?,?,0,?)",
            (code, reward, uses_left, expires_at, time.time()))
        await db_conn.commit()

async def update_promo(code: str, **fields):
    if not fields: return
    parts = ", ".join(f"{k}=?" for k in fields)
    vals  = list(fields.values()) + [code]
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            f"UPDATE promo_codes SET {parts} WHERE code=?", vals)
        await db_conn.commit()

async def delete_promo(code: str):
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute("DELETE FROM promo_codes WHERE code=?", (code,))
        await db_conn.execute("DELETE FROM promo_activations WHERE code=?", (code,))
        await db_conn.commit()

async def has_activated_promo(uid: int, code: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db_conn:
        async with db_conn.execute(
            "SELECT id FROM promo_activations WHERE code=? AND user_id=?", (code, uid)
        ) as cur:
            return (await cur.fetchone()) is not None

async def activate_promo(uid: int, code: str, reward: int):
    """Record activation and decrement uses_left (if not unlimited)."""
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "INSERT OR IGNORE INTO promo_activations(code,user_id,amount_received,activated_at)"
            " VALUES(?,?,?,?)",
            (code, uid, reward, time.time()))
        await db_conn.execute(
            "UPDATE promo_codes SET total_activations=total_activations+1,"
            " uses_left=CASE WHEN uses_left IS NOT NULL THEN uses_left-1 ELSE NULL END"
            " WHERE code=?", (code,))
        await db_conn.commit()

async def get_promo_activations(code: str):
    async with aiosqlite.connect(DB_PATH) as db_conn:
        return await _rows(db_conn,
            "SELECT * FROM promo_activations WHERE code=? ORDER BY activated_at DESC", (code,))
# ── XP / LEVELS ──
def xp_for_level(level: int) -> int:
    """XP required to REACH this level from 0. Progressive like Telegram."""
    return level * (level + 1) * 50  # L1=100, L2=300, L3=600, L4=1000...

def calc_level(xp: int) -> int:
    """Return level for given XP amount."""
    lvl = 0
    while xp_for_level(lvl + 1) <= xp:
        lvl += 1
    return lvl

async def add_xp(uid: int, xp_gain: int):
    """Add XP and update level if changed."""
    if xp_gain <= 0: return
    async with aiosqlite.connect(DB_PATH) as db_conn:
        db_conn.row_factory = aiosqlite.Row
        async with db_conn.execute("SELECT xp, level FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row: return
        new_xp  = (row['xp'] or 0) + xp_gain
        new_lvl = calc_level(new_xp)
        await db_conn.execute(
            "UPDATE users SET xp=?, level=? WHERE user_id=?",
            (new_xp, new_lvl, uid))
        await db_conn.commit()
        return new_lvl

async def set_level(uid: int, level: int):
    xp = xp_for_level(level)
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "UPDATE users SET level=?, xp=? WHERE user_id=?", (level, xp, uid))
        await db_conn.commit()

# ── REFERRER ──
async def set_referrer(uid: int, referrer_id: int):
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "UPDATE users SET referrer_id=? WHERE user_id=? AND referrer_id IS NULL",
            (referrer_id, uid))
        await db_conn.commit()

async def get_referrer(uid: int):
    async with aiosqlite.connect(DB_PATH) as db_conn:
        db_conn.row_factory = aiosqlite.Row
        async with db_conn.execute(
            "SELECT referrer_id FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
            return row['referrer_id'] if row else None

# ── TASKS ──
async def get_tasks(active_only=True):
    async with aiosqlite.connect(DB_PATH) as db_conn:
        sql = "SELECT * FROM tasks"
        if active_only: sql += " WHERE active=1"
        sql += " ORDER BY created_at DESC"
        return await _rows(db_conn, sql)

async def get_task(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db_conn:
        return await _row(db_conn, "SELECT * FROM tasks WHERE id=?", (task_id,))

async def create_task(type_: str, title: str, description: str, reward: int, target: str, target_count: int):
    async with aiosqlite.connect(DB_PATH) as db_conn:
        cur = await db_conn.execute(
            "INSERT INTO tasks(type,title,description,reward,target,target_count,active,created_at)"
            " VALUES(?,?,?,?,?,?,1,?)",
            (type_, title, description, reward, target, target_count, time.time()))
        await db_conn.commit()
        return cur.lastrowid

async def update_task(task_id: int, **fields):
    if not fields: return
    parts = ", ".join(f"{k}=?" for k in fields)
    vals  = list(fields.values()) + [task_id]
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(f"UPDATE tasks SET {parts} WHERE id=?", vals)
        await db_conn.commit()

async def delete_task(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        await db_conn.execute("DELETE FROM user_tasks WHERE task_id=?", (task_id,))
        await db_conn.commit()

async def get_user_tasks(uid: int):
    """Return list of task_ids completed by this user."""
    async with aiosqlite.connect(DB_PATH) as db_conn:
        rows = await _rows(db_conn,
            "SELECT task_id FROM user_tasks WHERE user_id=?", (uid,))
        return [r['task_id'] for r in rows]

async def complete_task(uid: int, task_id: int) -> bool:
    """Mark task as completed. Returns True if newly completed."""
    async with aiosqlite.connect(DB_PATH) as db_conn:
        try:
            await db_conn.execute(
                "INSERT INTO user_tasks(user_id,task_id,completed_at) VALUES(?,?,?)",
                (uid, task_id, time.time()))
            await db_conn.commit()
            return True
        except Exception:
            return False

async def get_tower_max_mult() -> float:
    async with aiosqlite.connect(DB_PATH) as db_conn:
        async with db_conn.execute("SELECT value FROM settings WHERE key='tower_max_mult'") as cur:
            row = await cur.fetchone()
            try: return float(row[0]) if row else 5.0
            except: return 5.0

async def set_tower_max_mult(val: float):
    val = max(1.1, min(100.0, val))
    async with aiosqlite.connect(DB_PATH) as db_conn:
        await db_conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES('tower_max_mult',?)", (str(val),))
        await db_conn.commit()