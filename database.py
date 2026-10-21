"""database.py — SQLite через aiosqlite.
Баланс хранится как TEXT, в Python — int произвольной длины (бесконечность).
"""
import aiosqlite, time, os, json, asyncio
from contextlib import asynccontextmanager

DB_PATH = os.environ.get("DB_PATH", "casino.db")


# ── BIG INT helpers (баланс = TEXT, в Python = бесконечный int) ──────────
def _to_int(v, default: int = 0) -> int:
    """Безопасно приводит значение к int произвольной длины."""
    if v is None or v == "":
        return default
    try:
        if isinstance(v, float):
            if not (v == v) or v in (float("inf"), float("-inf")):
                return default
            v = int(v)
        else:
            v = int(v)
    except (TypeError, ValueError, OverflowError):
        return default
    return v


def _clamp(v: int) -> int:
    """Только нижняя граница: баланс не может быть < 0.
    Сверху — бесконечность."""
    return v if v >= 0 else 0


# ── ОБЩЕЕ СОЕДИНЕНИЕ + WAL ───────────────────────────────────────────────
_db: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()
_init_lock = asyncio.Lock()


async def _get_conn() -> aiosqlite.Connection:
    """Одно общее соединение на весь процесс. WAL + busy_timeout."""
    global _db
    if _db is None:
        async with _init_lock:
            if _db is None:
                conn = await aiosqlite.connect(DB_PATH, timeout=30.0)
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await conn.execute("PRAGMA busy_timeout=30000")
                await conn.execute("PRAGMA foreign_keys=ON")
                await conn.commit()
                _db = conn
    return _db


@asynccontextmanager
async def _conn():
    """Контекст: НЕ закрывает общее соединение. Без блокировки — для чтений."""
    db = await _get_conn()
    yield db


@asynccontextmanager
async def _tx():
    """Контекст с asyncio.Lock — для read-modify-write операций."""
    db = await _get_conn()
    async with _db_lock:
        yield db


async def close_db():
    """Вызвать при остановке бота."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None


# ── INIT ─────────────────────────────────────────────────────────────────
async def init_db():
    db = await _get_conn()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            balance    TEXT DEFAULT '10',
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
    # Миграции колонок
    for stmt in [
        'ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0',
        "ALTER TABLE users ADD COLUMN ban_reason TEXT DEFAULT ''",
        "ALTER TABLE nft_gallery ADD COLUMN file_unique_id TEXT DEFAULT ''",
        "ALTER TABLE nft_gallery ADD COLUMN source TEXT DEFAULT 'manual'",
        'ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL',
        'ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0',
        'ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 0',
    ]:
        try:
            await db.execute(stmt)
        except Exception:
            pass

    # ── МИГРАЦИЯ: balance INTEGER -> TEXT ──────────────────────────────
    # Приводим все существующие балансы к строке, чтобы единообразно читать.
    try:
        await db.execute(
            "UPDATE users SET balance = CAST(balance AS TEXT) "
            "WHERE balance IS NOT NULL AND typeof(balance) != 'text'"
        )
    except Exception:
        pass

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


# ── USERS ────────────────────────────────────────────────────────────────
async def get_user(uid: int):
    db = await _get_conn()
    row = await _row(db, "SELECT * FROM users WHERE user_id=?", (uid,))
    if row and "balance" in row:
        row["balance"] = _to_int(row["balance"])
    return row


async def ensure_user(uid: int, username="", first_name=""):
    async with _tx() as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id,username,first_name,balance,created_at) "
            "VALUES (?,?,?,?,?)",
            (uid, username, first_name, "10", time.time()))
        await db.execute(
            "UPDATE users SET username=?,first_name=? WHERE user_id=?",
            (username, first_name, uid))
        await db.commit()
    return await get_user(uid)


async def get_all_users():
    db = await _get_conn()
    rows = await _rows(db, "SELECT * FROM users", ())
    for r in rows:
        r["balance"] = _to_int(r.get("balance"))
    rows.sort(key=lambda r: r["balance"], reverse=True)
    return rows


async def get_all_users_by_join():
    db = await _get_conn()
    rows = await _rows(db, "SELECT * FROM users ORDER BY created_at ASC", ())
    for r in rows:
        r["balance"] = _to_int(r.get("balance"))
    return rows


async def set_balance(uid: int, val):
    val = _clamp(_to_int(val))
    async with _tx() as db:
        await db.execute(
            "UPDATE users SET balance=? WHERE user_id=?",
            (str(val), uid))
        await db.commit()


async def add_to_balance(uid: int, delta) -> int:
    """Атомарный read-modify-write под локом. Без верхнего потолка."""
    delta = _to_int(delta)
    async with _tx() as db:
        async with db.execute(
            "SELECT balance FROM users WHERE user_id=?", (uid,)
        ) as cur:
            row = await cur.fetchone()
        cur_bal = _to_int(row[0]) if row else 0
        new_bal = _clamp(cur_bal + delta)
        await db.execute(
            "UPDATE users SET balance=? WHERE user_id=?",
            (str(new_bal), uid))
        await db.commit()
        return new_bal


async def try_debit(uid: int, amount) -> int | None:
    """Атомарно списывает amount. Возвращает новый баланс или None, если средств не хватает.
    Защищает от гонки «проверил баланс -> параллельные запросы -> ставка из воздуха»."""
    amount = _to_int(amount)
    if amount <= 0:
        return None
    async with _tx() as db:
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        cur_bal = _to_int(row[0])
        if cur_bal < amount:
            return None
        new_bal = cur_bal - amount
        await db.execute("UPDATE users SET balance=? WHERE user_id=?", (str(new_bal), uid))
        await db.commit()
        return new_bal


async def set_luck(uid: int, luck: int):
    async with _tx() as db:
        await db.execute("UPDATE users SET luck_pct=? WHERE user_id=?", (luck, uid))
        await db.commit()


async def get_luck(uid: int) -> int:
    db = await _get_conn()
    async with db.execute("SELECT luck_pct FROM users WHERE user_id=?", (uid,)) as cur:
        row = await cur.fetchone()
        return row[0] if row else -1


async def update_spin_stats(uid: int, won: bool, won_amt: int, lost_amt: int):
    async with _tx() as db:
        await db.execute(
            "UPDATE users SET spins=spins+1,wins=wins+?,total_won=total_won+?,total_lost=total_lost+? WHERE user_id=?",
            (1 if won else 0, won_amt, lost_amt, uid))
        await db.commit()


# ── GROUP LOGS ───────────────────────────────────────────────────────────
async def add_glog(thread: int, category: str, text: str):
    async with _tx() as db:
        await db.execute(
            "INSERT INTO glogs (thread,category,text,created_at) VALUES (?,?,?,?)",
            (thread, category, text, time.time()))
        await db.commit()


async def get_glogs(category: str = None, limit: int = 300):
    db = await _get_conn()
    if category and category != "all":
        return await _rows(db,
            "SELECT * FROM glogs WHERE category=? ORDER BY created_at DESC LIMIT ?",
            (category, limit))
    return await _rows(db,
        "SELECT * FROM glogs ORDER BY created_at DESC LIMIT ?", (limit,))


async def get_glog_counts():
    db = await _get_conn()
    rows = await _rows(db, "SELECT category, COUNT(*) as c FROM glogs GROUP BY category", ())
    return {r["category"]: r["c"] for r in rows}


# ── NFT GALLERY ──────────────────────────────────────────────────────────
async def add_nft(name: str, sticker_file_id: str, is_video: bool, is_animated: bool,
                   added_by: int, file_unique_id: str = "", source: str = "manual"):
    async with _tx() as db:
        if file_unique_id:
            async with db.execute(
                "SELECT id FROM nft_gallery WHERE file_unique_id=?", (file_unique_id,)
            ) as cur:
                if await cur.fetchone():
                    return False
        await db.execute(
            "INSERT INTO nft_gallery (name,sticker_file_id,file_unique_id,is_video,is_animated,source,added_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (name, sticker_file_id, file_unique_id,
             1 if is_video else 0, 1 if is_animated else 0, source, added_by, time.time()))
        await db.commit()
        return True


async def get_nfts():
    db = await _get_conn()
    return await _rows(db, "SELECT * FROM nft_gallery ORDER BY created_at DESC", ())


async def delete_nft(nft_id: int):
    async with _tx() as db:
        await db.execute("DELETE FROM nft_gallery WHERE id=?", (nft_id,))
        await db.commit()


async def clear_nfts_by_source(source: str):
    async with _tx() as db:
        await db.execute("DELETE FROM nft_gallery WHERE source=?", (source,))
        await db.commit()


# ── HISTORY ──────────────────────────────────────────────────────────────
async def add_history(uid: int, type_: str, amount: int, detail=""):
    async with _tx() as db:
        await db.execute(
            "INSERT INTO history (user_id,type,amount,detail,created_at) VALUES (?,?,?,?,?)",
            (uid, type_, amount, detail, time.time()))
        await db.commit()


async def get_history(uid: int, limit=None):
    db = await _get_conn()
    if limit:
        return await _rows(db,
            "SELECT * FROM history WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (uid, limit))
    return await _rows(db,
        "SELECT * FROM history WHERE user_id=? ORDER BY created_at DESC",
        (uid,))


# ── GTA LOBBIES ──────────────────────────────────────────────────────────
async def create_lobby() -> int:
    async with _tx() as db:
        cur = await db.execute(
            "INSERT INTO gta_lobbies (status,created_at) VALUES ('open',?)", (time.time(),))
        await db.commit()
        return cur.lastrowid


async def get_open_lobby():
    db = await _get_conn()
    return await _row(db, "SELECT * FROM gta_lobbies WHERE status='open' ORDER BY id DESC LIMIT 1")


async def get_lobby(lid: int):
    db = await _get_conn()
    return await _row(db, "SELECT * FROM gta_lobbies WHERE id=?", (lid,))


async def get_lobby_bets(lid: int):
    db = await _get_conn()
    return await _rows(db, "SELECT * FROM gta_bets WHERE lobby_id=? ORDER BY amount DESC", (lid,))


async def place_gta_bet(lid: int, uid: int, amount: int):
    async with _tx() as db:
        async with db.execute(
            "SELECT id,amount FROM gta_bets WHERE lobby_id=? AND user_id=?", (lid, uid)
        ) as cur:
            ex = await cur.fetchone()
        if ex:
            await db.execute("UPDATE gta_bets SET amount=amount+? WHERE id=?", (amount, ex[0]))
        else:
            await db.execute(
                "INSERT INTO gta_bets (lobby_id,user_id,amount,created_at) VALUES (?,?,?,?)",
                (lid, uid, amount, time.time()))
        await db.execute("UPDATE gta_lobbies SET pot=pot+? WHERE id=?", (amount, lid))
        await db.commit()


async def set_lobby_deadline(lid: int, deadline: float):
    async with _tx() as db:
        await db.execute("UPDATE gta_lobbies SET deadline=? WHERE id=?", (deadline, lid))
        await db.commit()


async def set_lobby_spinning(lid: int):
    async with _tx() as db:
        await db.execute("UPDATE gta_lobbies SET status='spinning' WHERE id=?", (lid,))
        await db.commit()


async def close_lobby(lid: int, winner_id: int, commission: int):
    async with _tx() as db:
        await db.execute(
            "UPDATE gta_lobbies SET status='done',winner_id=?,commission=?,closed_at=? WHERE id=?",
            (winner_id, commission, time.time(), lid))
        await db.commit()


async def get_revenue(from_ts: float = 0, to_ts: float = 9999999999):
    """Доходность казино за период. Считается в Python для больших чисел."""
    db = await _get_conn()

    async with db.execute(
        "SELECT COALESCE(SUM(commission),0) FROM gta_lobbies "
        "WHERE status='done' AND closed_at>=? AND closed_at<=?",
        (from_ts, to_ts)
    ) as cur:
        gta_commission = (await cur.fetchone())[0] or 0

    async with db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM history "
        "WHERE type='lose' AND created_at>=? AND created_at<=?",
        (from_ts, to_ts)
    ) as cur:
        euro_losses = (await cur.fetchone())[0] or 0

    async with db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM history "
        "WHERE type='win' AND detail LIKE '%Европ%' AND created_at>=? AND created_at<=?",
        (from_ts, to_ts)
    ) as cur:
        euro_wins = (await cur.fetchone())[0] or 0

    async with db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM history "
        "WHERE type='deposit' AND created_at>=? AND created_at<=?",
        (from_ts, to_ts)
    ) as cur:
        deposits = (await cur.fetchone())[0] or 0

    async with db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM history "
        "WHERE type='lose' AND detail LIKE '%Мины%' AND created_at>=? AND created_at<=?",
        (from_ts, to_ts)
    ) as cur:
        mines_losses = (await cur.fetchone())[0] or 0

    async with db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM history "
        "WHERE type='win' AND detail LIKE '%Мины%' AND created_at>=? AND created_at<=?",
        (from_ts, to_ts)
    ) as cur:
        mines_wins = (await cur.fetchone())[0] or 0

    async with db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM history "
        "WHERE type='lose' AND detail LIKE '%Башня%' AND created_at>=? AND created_at<=?",
        (from_ts, to_ts)
    ) as cur:
        tower_losses = (await cur.fetchone())[0] or 0

    async with db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM history "
        "WHERE type='win' AND detail LIKE '%Башня%' AND created_at>=? AND created_at<=?",
        (from_ts, to_ts)
    ) as cur:
        tower_wins = (await cur.fetchone())[0] or 0

    async with db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM history "
        "WHERE type='gift_sent' AND created_at>=? AND created_at<=?",
        (from_ts, to_ts)
    ) as cur:
        withdrawals = (await cur.fetchone())[0] or 0

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


# ── SETTINGS HELPERS ─────────────────────────────────────────────────────
async def _get_setting_float(key: str, default: float) -> float:
    db = await _get_conn()
    async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
        row = await cur.fetchone()
        try:
            return float(row[0]) if row else default
        except Exception:
            return default


async def _set_setting(key: str, value: str):
    async with _tx() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))
        await db.commit()


async def get_global_luck_coeff() -> float:
    return await _get_setting_float('global_luck_coeff', 1.0)


async def set_global_luck_coeff(coeff: float):
    coeff = max(0.0, min(2.0, coeff))
    await _set_setting('global_luck_coeff', str(coeff))


async def get_tower_luck_coeff() -> float:
    return await _get_setting_float('tower_luck_coeff', 1.0)


async def set_tower_luck_coeff(coeff: float):
    coeff = max(0.0, min(2.0, coeff))
    await _set_setting('tower_luck_coeff', str(coeff))


# ── BAN ──────────────────────────────────────────────────────────────────
async def is_banned(uid: int) -> bool:
    db = await _get_conn()
    async with db.execute("SELECT banned FROM users WHERE user_id=?", (uid,)) as cur:
        row = await cur.fetchone()
        return bool(row[0]) if row else False


async def get_ban_reason(uid: int) -> str:
    db = await _get_conn()
    async with db.execute("SELECT ban_reason FROM users WHERE user_id=?", (uid,)) as cur:
        row = await cur.fetchone()
        return (row[0] or "") if row else ""


async def set_banned(uid: int, banned: bool, reason: str = ""):
    async with _tx() as db:
        await db.execute(
            "UPDATE users SET banned=?, ban_reason=? WHERE user_id=?",
            (1 if banned else 0, reason if banned else "", uid))
        await db.commit()


async def get_mines_max_mult() -> float:
    return await _get_setting_float('mines_max_mult', 25.0)


async def set_mines_max_mult(val: float):
    val = max(1.0, min(1000.0, val))
    await _set_setting('mines_max_mult', str(val))


async def get_tower_max_floors() -> int:
    db = await _get_conn()
    async with db.execute("SELECT value FROM settings WHERE key='tower_max_floors'") as cur:
        row = await cur.fetchone()
        try:
            return int(row[0]) if row else 10
        except Exception:
            return 10


async def set_tower_max_floors(val: int):
    val = max(1, min(50, val))
    await _set_setting('tower_max_floors', str(val))


# ── EURO / MINES / BLACKJACK LUCK ────────────────────────────────────────
async def get_euro_luck_coeff() -> float:
    return await _get_setting_float('euro_luck_coeff', 1.0)


async def set_euro_luck_coeff(coeff: float):
    coeff = max(0.0, min(2.0, coeff))
    await _set_setting('euro_luck_coeff', str(coeff))


async def get_mines_luck_coeff() -> float:
    return await _get_setting_float('mines_luck_coeff', 1.0)


async def set_mines_luck_coeff(coeff: float):
    coeff = max(0.0, min(2.0, coeff))
    await _set_setting('mines_luck_coeff', str(coeff))


async def get_blackjack_luck_coeff() -> float:
    return await _get_setting_float('blackjack_luck_coeff', 1.0)


async def set_blackjack_luck_coeff(coeff: float):
    coeff = max(0.0, min(2.0, coeff))
    await _set_setting('blackjack_luck_coeff', str(coeff))


# ── PLINKO MULTIPLIERS ───────────────────────────────────────────────────
DEFAULT_PLINKO_MULTS = [20, 10, 5, 2.5, 2, 1.5, 1.2, 0, 1.2, 1.5, 2, 2.5, 5, 10, 20]


async def get_plinko_mults() -> list:
    db = await _get_conn()
    async with db.execute("SELECT value FROM settings WHERE key='plinko_mults'") as cur:
        row = await cur.fetchone()
        if not row:
            return list(DEFAULT_PLINKO_MULTS)
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
    await _set_setting('plinko_mults', json.dumps(vals))


# ── PROMO CODES ──────────────────────────────────────────────────────────
async def get_promo(code: str):
    db = await _get_conn()
    return await _row(db, "SELECT * FROM promo_codes WHERE code=?", (code,))


async def get_all_promos():
    db = await _get_conn()
    return await _rows(db, "SELECT * FROM promo_codes ORDER BY created_at DESC")


async def create_promo(code: str, reward: int, uses_left, expires_at):
    async with _tx() as db:
        await db.execute(
            "INSERT INTO promo_codes(code,reward,uses_left,expires_at,total_activations,created_at)"
            " VALUES(?,?,?,?,0,?)",
            (code, reward, uses_left, expires_at, time.time()))
        await db.commit()


async def update_promo(code: str, **fields):
    if not fields:
        return
    parts = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [code]
    async with _tx() as db:
        await db.execute(f"UPDATE promo_codes SET {parts} WHERE code=?", vals)
        await db.commit()


async def delete_promo(code: str):
    async with _tx() as db:
        await db.execute("DELETE FROM promo_codes WHERE code=?", (code,))
        await db.execute("DELETE FROM promo_activations WHERE code=?", (code,))
        await db.commit()


async def has_activated_promo(uid: int, code: str) -> bool:
    db = await _get_conn()
    async with db.execute(
        "SELECT id FROM promo_activations WHERE code=? AND user_id=?", (code, uid)
    ) as cur:
        return (await cur.fetchone()) is not None


async def activate_promo(uid: int, code: str, reward: int):
    async with _tx() as db:
        await db.execute(
            "INSERT OR IGNORE INTO promo_activations(code,user_id,amount_received,activated_at)"
            " VALUES(?,?,?,?)",
            (code, uid, reward, time.time()))
        await db.execute(
            "UPDATE promo_codes SET total_activations=total_activations+1,"
            " uses_left=CASE WHEN uses_left IS NOT NULL THEN uses_left-1 ELSE NULL END"
            " WHERE code=?", (code,))
        await db.commit()


async def get_promo_activations(code: str):
    db = await _get_conn()
    return await _rows(db,
        "SELECT * FROM promo_activations WHERE code=? ORDER BY activated_at DESC", (code,))


# ── XP / LEVELS ──────────────────────────────────────────────────────────
def xp_for_level(level: int) -> int:
    """XP required to REACH this level from 0. Progressive like Telegram."""
    return level * (level + 1) * 50


def calc_level(xp: int) -> int:
    """Return level for given XP amount."""
    lvl = 0
    while xp_for_level(lvl + 1) <= xp:
        lvl += 1
    return lvl


async def add_xp(uid: int, xp_gain: int):
    """Add XP and update level if changed."""
    if xp_gain <= 0:
        return
    async with _tx() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT xp, level FROM users WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        if not row:
            return
        new_xp = (row['xp'] or 0) + xp_gain
        new_lvl = calc_level(new_xp)
        await db.execute(
            "UPDATE users SET xp=?, level=? WHERE user_id=?",
            (new_xp, new_lvl, uid))
        await db.commit()
        return new_lvl


async def set_level(uid: int, level: int):
    xp = xp_for_level(level)
    async with _tx() as db:
        await db.execute(
            "UPDATE users SET level=?, xp=? WHERE user_id=?", (level, xp, uid))
        await db.commit()


# ── REFERRER ─────────────────────────────────────────────────────────────
async def set_referrer(uid: int, referrer_id: int):
    async with _tx() as db:
        await db.execute(
            "UPDATE users SET referrer_id=? WHERE user_id=? AND referrer_id IS NULL",
            (referrer_id, uid))
        await db.commit()


async def get_referrer(uid: int):
    db = await _get_conn()
    db.row_factory = aiosqlite.Row
    async with db.execute(
        "SELECT referrer_id FROM users WHERE user_id=?", (uid,)
    ) as cur:
        row = await cur.fetchone()
        return row['referrer_id'] if row else None


# ── TASKS ────────────────────────────────────────────────────────────────
async def get_tasks(active_only=True):
    db = await _get_conn()
    sql = "SELECT * FROM tasks"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY created_at DESC"
    return await _rows(db, sql)


async def get_task(task_id: int):
    db = await _get_conn()
    return await _row(db, "SELECT * FROM tasks WHERE id=?", (task_id,))


async def create_task(type_: str, title: str, description: str, reward: int,
                       target: str, target_count: int):
    async with _tx() as db:
        cur = await db.execute(
            "INSERT INTO tasks(type,title,description,reward,target,target_count,active,created_at)"
            " VALUES(?,?,?,?,?,?,1,?)",
            (type_, title, description, reward, target, target_count, time.time()))
        await db.commit()
        return cur.lastrowid


async def update_task(task_id: int, **fields):
    if not fields:
        return
    parts = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [task_id]
    async with _tx() as db:
        await db.execute(f"UPDATE tasks SET {parts} WHERE id=?", vals)
        await db.commit()


async def delete_task(task_id: int):
    async with _tx() as db:
        await db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        await db.execute("DELETE FROM user_tasks WHERE task_id=?", (task_id,))
        await db.commit()


async def get_user_tasks(uid: int):
    db = await _get_conn()
    rows = await _rows(db, "SELECT task_id FROM user_tasks WHERE user_id=?", (uid,))
    return [r['task_id'] for r in rows]


async def complete_task(uid: int, task_id: int) -> bool:
    async with _tx() as db:
        try:
            await db.execute(
                "INSERT INTO user_tasks(user_id,task_id,completed_at) VALUES(?,?,?)",
                (uid, task_id, time.time()))
            await db.commit()
            return True
        except Exception:
            return False


async def get_tower_max_mult() -> float:
    return await _get_setting_float('tower_max_mult', 5.0)


async def set_tower_max_mult(val: float):
    val = max(1.1, min(100.0, val))
    await _set_setting('tower_max_mult', str(val))


# ── MAINTENANCE / GAME SWITCHES ──────────────────────────────────────────
GAME_KEYS = ["european_roulette", "gta_roulette", "mines", "tower",
             "blackjack", "plinko", "rocket", "aviator"]


async def _get_setting_str(key: str, default: str = "") -> str:
    db = await _get_conn()
    async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
        row = await cur.fetchone()
        return str(row[0]) if row and row[0] is not None else default


async def get_site_status() -> dict:
    """{'maintenance': bool, 'message': str, 'disabled_games': [keys]}"""
    maint = (await _get_setting_str("maintenance", "0")) == "1"
    msg = await _get_setting_str("maintenance_msg", "")
    try:
        disabled = json.loads(await _get_setting_str("disabled_games", "[]"))
        if not isinstance(disabled, list):
            disabled = []
    except Exception:
        disabled = []
    return {"maintenance": maint, "message": msg,
            "disabled_games": [g for g in disabled if g in GAME_KEYS]}


async def set_site_status(maintenance=None, message=None, disabled_games=None):
    if maintenance is not None:
        await _set_setting("maintenance", "1" if maintenance else "0")
    if message is not None:
        await _set_setting("maintenance_msg", str(message)[:300])
    if disabled_games is not None:
        clean = [g for g in dict.fromkeys(disabled_games) if g in GAME_KEYS]
        await _set_setting("disabled_games", json.dumps(clean))


async def get_recent_activity(limit: int = 100) -> list:
    db = await _get_conn()
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """SELECT h.id, h.user_id, h.type, h.amount, h.detail, h.created_at,
                  u.first_name, u.username
           FROM history h LEFT JOIN users u ON u.user_id = h.user_id
           ORDER BY h.created_at DESC LIMIT ?""", (limit,)) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]
