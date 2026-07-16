import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from . import config

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id      INTEGER PRIMARY KEY,
    first_name TEXT,
    username   TEXT,
    status     TEXT NOT NULL DEFAULT 'active',   -- active | inactive | kicked
    joined_at  TEXT,
    kicked_at  TEXT
);
CREATE TABLE IF NOT EXISTS prompts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    text     TEXT NOT NULL,
    source   TEXT DEFAULT 'library',
    used_on  TEXT,
    added_by INTEGER,
    added_at TEXT
);
CREATE TABLE IF NOT EXISTS days (
    date             TEXT PRIMARY KEY,
    prompt_id        INTEGER,
    prompt_sent_at   TEXT,
    reminder_sent_at TEXT,
    collage_sent_at  TEXT,
    skipped          INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS photos (
    date         TEXT NOT NULL,
    tg_id        INTEGER NOT NULL,
    file_path    TEXT NOT NULL,
    submitted_at TEXT,
    PRIMARY KEY (date, tg_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ratings (
    date     TEXT NOT NULL,
    tg_id    INTEGER NOT NULL,
    value    TEXT NOT NULL,               -- fire | like | meh
    rated_at TEXT,
    PRIMARY KEY (date, tg_id)
);
CREATE TABLE IF NOT EXISTS collage_messages (
    date       TEXT NOT NULL,
    tg_id      INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (date, tg_id)
);
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id      INTEGER NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS suggestions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id      INTEGER NOT NULL,
    text       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | dismissed
    created_at TEXT
);
"""


def init(path: Path | str | None = None) -> None:
    global _conn
    path = Path(path) if path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock, _conn:
        _conn.executescript(SCHEMA)
        # english is the primary prompt text; text_ru is the optional translation
        pcols = {r["name"] for r in _conn.execute("PRAGMA table_info(prompts)")}
        if "text_ru" not in pcols:
            if "text_en" in pcols:
                _conn.execute("ALTER TABLE prompts RENAME COLUMN text_en TO text_ru")
            else:
                _conn.execute("ALTER TABLE prompts ADD COLUMN text_ru TEXT")
        migrations = {
            "users": [("lang", "TEXT")],
            "photos": [("excluded", "INTEGER NOT NULL DEFAULT 0")],
            "days": [
                ("moderation_sent_at", "TEXT"),
                ("final_reminder_sent_at", "TEXT"),
            ],
        }
        for table, columns in migrations.items():
            existing = {
                r["name"] for r in _conn.execute(f"PRAGMA table_info({table})")
            }
            for name, decl in columns:
                if name not in existing:
                    _conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _now() -> str:
    return datetime.now(config.TZ).isoformat(timespec="seconds")


def _exec(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    assert _conn is not None, "db.init() was not called"
    with _lock, _conn:
        return _conn.execute(sql, params)


# --- settings ---------------------------------------------------------------

def get_setting(key: str) -> str:
    row = _exec("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row:
        return row["value"]
    return config.DEFAULT_SETTINGS[key]


def set_setting(key: str, value: str) -> None:
    _exec(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# --- users ------------------------------------------------------------------

def upsert_user(tg_id: int, first_name: str, username: str | None) -> bool:
    """Register or reactivate a user. Returns True if the user is new."""
    existing = get_user(tg_id)
    if existing is None:
        _exec(
            "INSERT INTO users(tg_id, first_name, username, status, joined_at) "
            "VALUES(?, ?, ?, 'active', ?)",
            (tg_id, first_name, username, _now()),
        )
        return True
    if existing["status"] != "kicked":
        _exec(
            "UPDATE users SET first_name=?, username=?, status='active' WHERE tg_id=?",
            (first_name, username, tg_id),
        )
    return False


def get_user(tg_id: int) -> sqlite3.Row | None:
    return _exec("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()


def get_user_by_username(username: str) -> sqlite3.Row | None:
    return _exec(
        "SELECT * FROM users WHERE lower(username)=lower(?)", (username.lstrip("@"),)
    ).fetchone()


def set_user_lang(tg_id: int, lang: str) -> None:
    _exec("UPDATE users SET lang=? WHERE tg_id=?", (lang, tg_id))


def get_user_lang(tg_id: int) -> str | None:
    row = get_user(tg_id)
    return row["lang"] if row else None


def set_user_status(tg_id: int, status: str) -> None:
    kicked_at = _now() if status == "kicked" else None
    _exec(
        "UPDATE users SET status=?, kicked_at=? WHERE tg_id=?",
        (status, kicked_at, tg_id),
    )


def list_users() -> list[sqlite3.Row]:
    return _exec("SELECT * FROM users ORDER BY joined_at").fetchall()


def active_user_ids() -> list[int]:
    rows = _exec("SELECT tg_id FROM users WHERE status='active'").fetchall()
    return [r["tg_id"] for r in rows]


# --- prompts ----------------------------------------------------------------

def add_prompt(
    text: str, added_by: int, text_ru: str | None = None, source: str = "library"
) -> int:
    cur = _exec(
        "INSERT INTO prompts(text, text_ru, source, added_by, added_at) "
        "VALUES(?, ?, ?, ?, ?)",
        (text.strip(), text_ru.strip() if text_ru else None, source, added_by, _now()),
    )
    return cur.lastrowid


def set_prompt_ru(prompt_id: int, text_ru: str | None) -> bool:
    cur = _exec(
        "UPDATE prompts SET text_ru=? WHERE id=?",
        (text_ru.strip() if text_ru else None, prompt_id),
    )
    return cur.rowcount > 0


def list_prompts() -> list[sqlite3.Row]:
    return _exec("SELECT * FROM prompts ORDER BY id").fetchall()


def delete_prompt(prompt_id: int) -> bool:
    cur = _exec("DELETE FROM prompts WHERE id=?", (prompt_id,))
    return cur.rowcount > 0


def count_unused_prompts() -> int:
    return _exec(
        "SELECT COUNT(*) AS n FROM prompts WHERE used_on IS NULL"
    ).fetchone()["n"]


def pick_prompt() -> sqlite3.Row | None:
    """Next unused prompt in queue (list) order, or None if the queue is
    exhausted. Sequential: lowest id among the not-yet-used prompts."""
    return _exec(
        "SELECT * FROM prompts WHERE used_on IS NULL ORDER BY id LIMIT 1"
    ).fetchone()


def replace_prompt_queue(
    parsed: list[tuple[str, str | None]], added_by: int
) -> tuple[int, int]:
    """Make `parsed` (ordered (en, ru) lines) the new prompt queue: drop the
    current unused queue and insert these in order, but keep every already-used
    prompt as history (matched by text, so it is never re-queued). Returns
    (queued, kept_used)."""
    assert _conn is not None, "db.init() was not called"
    now = _now()
    with _lock, _conn:
        used = {
            r["text"].strip().casefold()
            for r in _conn.execute(
                "SELECT text FROM prompts WHERE used_on IS NOT NULL"
            )
        }
        _conn.execute("DELETE FROM prompts WHERE used_on IS NULL")
        queued = 0
        for en, ru in parsed:
            if en.strip().casefold() in used:
                continue  # already used — keep it struck, don't re-queue
            _conn.execute(
                "INSERT INTO prompts(text, text_ru, source, added_by, added_at) "
                "VALUES(?, ?, 'upload', ?, ?)",
                (en.strip(), ru.strip() if ru else None, added_by, now),
            )
            queued += 1
    return queued, len(used)


def mark_prompt_used(prompt_id: int, date: str) -> None:
    _exec("UPDATE prompts SET used_on=? WHERE id=?", (date, prompt_id))


# --- days -------------------------------------------------------------------

def get_day(date: str) -> sqlite3.Row | None:
    return _exec("SELECT * FROM days WHERE date=?", (date,)).fetchone()


def ensure_day(date: str) -> None:
    _exec("INSERT OR IGNORE INTO days(date) VALUES(?)", (date,))


def create_day(date: str, prompt_id: int) -> None:
    ensure_day(date)
    _exec(
        "UPDATE days SET prompt_id=?, prompt_sent_at=? WHERE date=?",
        (prompt_id, _now(), date),
    )


def set_day_field(date: str, field: str, value) -> None:
    assert field in {
        "reminder_sent_at",
        "final_reminder_sent_at",
        "moderation_sent_at",
        "collage_sent_at",
        "skipped",
    }
    ensure_day(date)
    _exec(f"UPDATE days SET {field}=? WHERE date=?", (value, date))


def get_prompt(prompt_id: int) -> sqlite3.Row | None:
    return _exec("SELECT * FROM prompts WHERE id=?", (prompt_id,)).fetchone()


# --- photos -----------------------------------------------------------------

def upsert_photo(date: str, tg_id: int, file_path: str) -> bool:
    """Store/replace a submission. Returns True if it replaced an earlier one."""
    replaced = (
        _exec(
            "SELECT 1 FROM photos WHERE date=? AND tg_id=?", (date, tg_id)
        ).fetchone()
        is not None
    )
    _exec(
        "INSERT INTO photos(date, tg_id, file_path, submitted_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(date, tg_id) DO UPDATE SET file_path=excluded.file_path, "
        "submitted_at=excluded.submitted_at",
        (date, tg_id, file_path, _now()),
    )
    return replaced


def photos_for(date: str, include_excluded: bool = False) -> list[sqlite3.Row]:
    """Day's submissions in stable submission order (used for moderation
    numbering, so the order must not depend on exclusion flags)."""
    sql = "SELECT * FROM photos WHERE date=?"
    if not include_excluded:
        sql += " AND excluded=0"
    sql += " ORDER BY submitted_at, tg_id"
    return _exec(sql, (date,)).fetchall()


def set_photo_excluded(date: str, tg_id: int, excluded: bool) -> None:
    _exec(
        "UPDATE photos SET excluded=? WHERE date=? AND tg_id=?",
        (1 if excluded else 0, date, tg_id),
    )


def submitter_ids(date: str) -> list[int]:
    return [r["tg_id"] for r in photos_for(date)]


# --- ratings ----------------------------------------------------------------

def set_rating(date: str, tg_id: int, value: str) -> bool:
    """Store/replace a user's collage rating. Returns False if it was already
    this value (so callers can skip re-editing keyboards)."""
    row = _exec(
        "SELECT value FROM ratings WHERE date=? AND tg_id=?", (date, tg_id)
    ).fetchone()
    if row and row["value"] == value:
        return False
    _exec(
        "INSERT INTO ratings(date, tg_id, value, rated_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(date, tg_id) DO UPDATE SET value=excluded.value, "
        "rated_at=excluded.rated_at",
        (date, tg_id, value, _now()),
    )
    return True


def rating_counts(date: str) -> dict[str, int]:
    rows = _exec(
        "SELECT value, COUNT(*) AS n FROM ratings WHERE date=? GROUP BY value",
        (date,),
    ).fetchall()
    return {r["value"]: r["n"] for r in rows}


def rating_counts_total() -> dict[str, int]:
    rows = _exec(
        "SELECT value, COUNT(*) AS n FROM ratings GROUP BY value"
    ).fetchall()
    return {r["value"]: r["n"] for r in rows}


def add_collage_message(date: str, tg_id: int, message_id: int) -> None:
    _exec(
        "INSERT INTO collage_messages(date, tg_id, message_id) VALUES(?, ?, ?) "
        "ON CONFLICT(date, tg_id) DO UPDATE SET message_id=excluded.message_id",
        (date, tg_id, message_id),
    )


def collage_messages_for(date: str) -> list[sqlite3.Row]:
    return _exec(
        "SELECT * FROM collage_messages WHERE date=?", (date,)
    ).fetchall()


# --- feedback & suggestions ---------------------------------------------------

def add_feedback(tg_id: int, text: str) -> int:
    cur = _exec(
        "INSERT INTO feedback(tg_id, text, created_at) VALUES(?, ?, ?)",
        (tg_id, text.strip(), _now()),
    )
    return cur.lastrowid


def add_suggestion(tg_id: int, text: str) -> int:
    cur = _exec(
        "INSERT INTO suggestions(tg_id, text, created_at) VALUES(?, ?, ?)",
        (tg_id, text.strip(), _now()),
    )
    return cur.lastrowid


def get_suggestion(sid: int) -> sqlite3.Row | None:
    return _exec("SELECT * FROM suggestions WHERE id=?", (sid,)).fetchone()


def set_suggestion_status(sid: int, status: str) -> bool:
    cur = _exec("UPDATE suggestions SET status=? WHERE id=?", (status, sid))
    return cur.rowcount > 0


def pending_suggestions() -> list[sqlite3.Row]:
    return _exec(
        "SELECT * FROM suggestions WHERE status='pending' ORDER BY id"
    ).fetchall()


# --- participation stats ------------------------------------------------------

def collage_dates() -> list[str]:
    """Dates whose collage actually went out, ascending."""
    rows = _exec(
        "SELECT date FROM days WHERE collage_sent_at IS NOT NULL "
        "AND skipped=0 ORDER BY date"
    ).fetchall()
    return [r["date"] for r in rows]


def participation() -> dict[int, set[str]]:
    """tg_id -> set of dates with a non-excluded submission."""
    rows = _exec("SELECT date, tg_id FROM photos WHERE excluded=0").fetchall()
    out: dict[int, set[str]] = {}
    for r in rows:
        out.setdefault(r["tg_id"], set()).add(r["date"])
    return out
