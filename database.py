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
        """)
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