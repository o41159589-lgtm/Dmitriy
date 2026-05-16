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
            INSERT OR IGNORE INTO settings(key,value) VALUES ('euro_luck_coeff','1.0');
            INSERT OR IGNORE INTO settings(key,value) VALUES ('mines_luck_coeff','1.0');
            INSERT OR IGNORE INTO settings(key,value) VALUES ('tower_luck_coeff','1.0');
            INSERT OR IGNORE INTO settings(key,value) VALUES ('mines_max_mult','25.0');
            INSERT OR IGNORE INTO settings(key,value) VALUES ('tower_max_floors','10');
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
        except Exception:
            pass
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

        total_revenue = (gta_commission
                         + (euro_losses - euro_wins)
                         + (mines_losses - mines_wins)
                         + (tower_losses - tower_wins))

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

async def set_banned(uid: int, banned: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, uid))
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