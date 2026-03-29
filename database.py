"""
database.py — асинхронная обёртка над SQLite (aiosqlite)
Хранит: пользователей, историю транзакций, лобби GTA-рулетки
"""

import aiosqlite
import time
import os

DB_PATH = os.environ.get("DB_PATH", "casino.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT    DEFAULT '',
                first_name  TEXT    DEFAULT '',
                balance     INTEGER DEFAULT 10,
                luck_pct    INTEGER DEFAULT -1,   -- -1 = честная игра, 0–100 = подкрут
                spins       INTEGER DEFAULT 0,
                wins        INTEGER DEFAULT 0,
                total_won   INTEGER DEFAULT 0,
                total_lost  INTEGER DEFAULT 0,
                created_at  REAL    DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                type        TEXT    NOT NULL,   -- 'win','lose','add','sub','deposit','ref'
                amount      INTEGER NOT NULL,
                detail      TEXT    DEFAULT '',
                created_at  REAL    DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS gta_lobbies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                status      TEXT    DEFAULT 'open',   -- open / spinning / done
                winner_id   INTEGER DEFAULT NULL,
                pot         INTEGER DEFAULT 0,
                commission  INTEGER DEFAULT 0,
                created_at  REAL    DEFAULT 0,
                closed_at   REAL    DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS gta_bets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lobby_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                amount      INTEGER NOT NULL,
                created_at  REAL    DEFAULT 0
            );
        """)
        await db.commit()


# ── USERS ──────────────────────────────────────────

async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def ensure_user(user_id: int, username: str = "", first_name: str = "") -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO users
               (user_id, username, first_name, balance, created_at)
               VALUES (?,?,?,10,?)""",
            (user_id, username or "", first_name or "", time.time())
        )
        # Обновляем имя при каждом входе
        await db.execute(
            "UPDATE users SET username=?, first_name=? WHERE user_id=?",
            (username or "", first_name or "", user_id)
        )
        await db.commit()
    return await get_user(user_id)

async def get_all_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY balance DESC"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def set_balance(user_id: int, new_balance: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance=? WHERE user_id=?",
            (max(0, new_balance), user_id)
        )
        await db.commit()

async def add_to_balance(user_id: int, delta: int) -> int:
    """Добавляет/вычитает монеты. Возвращает новый баланс."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT balance FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            current = row[0] if row else 0
        new_bal = max(0, current + delta)
        await db.execute(
            "UPDATE users SET balance=? WHERE user_id=?", (new_bal, user_id)
        )
        await db.commit()
        return new_bal

async def set_luck(user_id: int, luck_pct: int):
    """luck_pct: -1 = честно, 0–100 = фиксированный шанс выиграть"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET luck_pct=? WHERE user_id=?", (luck_pct, user_id)
        )
        await db.commit()

async def get_luck(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT luck_pct FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else -1

async def update_spin_stats(user_id: int, won: bool, delta_won: int, delta_lost: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE users SET
               spins=spins+1,
               wins=wins+?,
               total_won=total_won+?,
               total_lost=total_lost+?
               WHERE user_id=?""",
            (1 if won else 0, delta_won, delta_lost, user_id)
        )
        await db.commit()


# ── HISTORY ────────────────────────────────────────

async def add_history(user_id: int, type_: str, amount: int, detail: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO history (user_id,type,amount,detail,created_at) VALUES (?,?,?,?,?)",
            (user_id, type_, amount, detail, time.time())
        )
        await db.commit()

async def get_history(user_id: int, limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM history WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ── GTA LOBBIES ────────────────────────────────────

async def create_lobby() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO gta_lobbies (status,created_at) VALUES ('open',?)",
            (time.time(),)
        )
        await db.commit()
        return cur.lastrowid

async def get_open_lobby() -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM gta_lobbies WHERE status='open' ORDER BY id DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def get_lobby(lobby_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM gta_lobbies WHERE id=?", (lobby_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def get_lobby_bets(lobby_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM gta_bets WHERE lobby_id=? ORDER BY amount DESC",
            (lobby_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

async def place_gta_bet(lobby_id: int, user_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        # Если уже ставил — добавляем к его ставке
        async with db.execute(
            "SELECT id, amount FROM gta_bets WHERE lobby_id=? AND user_id=?",
            (lobby_id, user_id)
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            await db.execute(
                "UPDATE gta_bets SET amount=amount+? WHERE id=?",
                (amount, existing[0])
            )
        else:
            await db.execute(
                "INSERT INTO gta_bets (lobby_id,user_id,amount,created_at) VALUES (?,?,?,?)",
                (lobby_id, user_id, amount, time.time())
            )
        await db.execute(
            "UPDATE gta_lobbies SET pot=pot+? WHERE id=?", (amount, lobby_id)
        )
        await db.commit()

async def close_lobby(lobby_id: int, winner_id: int, commission: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE gta_lobbies SET
               status='done', winner_id=?, commission=?, closed_at=?
               WHERE id=?""",
            (winner_id, commission, time.time(), lobby_id)
        )
        await db.commit()

async def set_lobby_spinning(lobby_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE gta_lobbies SET status='spinning' WHERE id=?", (lobby_id,)
        )
        await db.commit()