"""database.py — SQLite через aiosqlite"""
import aiosqlite, time, os

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
        """)
        # Migration: add banned column if missing
        try:
            await db.execute('ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0')
        except Exception:
            pass
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

# ── HISTORY ──
async def add_history(uid: int, type_: str, amount: int, detail=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO history (user_id,type,amount,detail,created_at) VALUES (?,?,?,?,?)",
            (uid, type_, amount, detail, time.time()))
        await db.commit()

async def get_history(uid: int, limit=100):
    async with aiosqlite.connect(DB_PATH) as db:
        return await _rows(db,
            "SELECT * FROM history WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (uid, limit))

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

        return {
            "gta_commission": gta_commission,
            "euro_losses":    euro_losses,
            "euro_wins":      euro_wins,
            "euro_profit":    euro_losses - euro_wins,
            "deposits":       deposits,
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
# ── BAN ──
async def is_banned(uid: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT banned FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
            return bool(row[0]) if row else False

async def set_banned(uid: int, banned: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, uid))
        await db.commit()