import sqlite3
import threading
from datetime import date as date_cls, datetime, timedelta
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
-- "Knock, knock": readers flip through the day's photos and knock on the one
-- whose story they want. One knock each, and moving it is allowed while the
-- window is open, hence the (date, tg_id) key rather than a row per tap.
CREATE TABLE IF NOT EXISTS knocks (
    date       TEXT NOT NULL,
    tg_id      INTEGER NOT NULL,   -- who knocked
    target_id  INTEGER NOT NULL,   -- whose photo they knocked on
    knocked_at TEXT,
    PRIMARY KEY (date, tg_id)
);
-- The mosaic arrangement, frozen at build time. The carousel walks the photos
-- in the order the collage reads, and that order must survive a rebuild or a
-- restart — recomputing it is how the image and the buttons drift apart.
CREATE TABLE IF NOT EXISTS collage_cells (
    date  TEXT NOT NULL,
    idx   INTEGER NOT NULL,
    tg_id INTEGER NOT NULL,
    PRIMARY KEY (date, idx)
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
-- Custom admin-authored 👍/👎 feedback polls. Each poll is a row here; votes
-- and the sent message copies reference it by id so several polls coexist.
CREATE TABLE IF NOT EXISTS polls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question    TEXT NOT NULL,               -- English (primary/fallback)
    question_ru TEXT,                         -- optional Russian
    status      TEXT NOT NULL DEFAULT 'open', -- open | closed
    created_by  INTEGER,
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS poll_votes (
    poll_id  INTEGER NOT NULL,
    tg_id    INTEGER NOT NULL,
    value    TEXT NOT NULL,               -- up | down
    voted_at TEXT,
    PRIMARY KEY (poll_id, tg_id)
);
CREATE TABLE IF NOT EXISTS poll_messages (
    poll_id    INTEGER NOT NULL,
    tg_id      INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (poll_id, tg_id)
);
-- "Story of the day": the admin asks the author of one past photo why they
-- chose it; the author's reply is captured here and later published (with their
-- name — this is opt-in deanonymization) to that day's submitters.
CREATE TABLE IF NOT EXISTS stories (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date           TEXT NOT NULL,        -- the submission day the photo is from
    tg_id          INTEGER NOT NULL,     -- the photo's author
    ask_message_id INTEGER,              -- the bot's ask message, for reply matching
    text           TEXT,                 -- the author's story (NULL until answered)
    text_ru        TEXT,                 -- optional RU version (admin-added translation)
    status         TEXT NOT NULL DEFAULT 'asked',  -- asked|answered|published|dismissed
    asked_at       TEXT,
    answered_at    TEXT,
    published_at   TEXT
);
-- One ❤️ per reader per story, toggled off by tapping again.
CREATE TABLE IF NOT EXISTS story_likes (
    story_id INTEGER NOT NULL,
    tg_id    INTEGER NOT NULL,
    liked_at TEXT,
    PRIMARY KEY (story_id, tg_id)
);
-- Collage proofing: a few trusted users see the collage before anyone else and
-- either wave it through (one 👍 publishes) or hold it for the admin. One row
-- per person asked per day; `value` stays NULL until they decide.
CREATE TABLE IF NOT EXISTS proof_asks (
    date       TEXT NOT NULL,
    tg_id      INTEGER NOT NULL,
    round_no   INTEGER NOT NULL,     -- 1 = first batch, 2+ = escalations
    message_id INTEGER,              -- the preview message, so it can be closed
    asked_at   TEXT,
    value      TEXT,                 -- approve | ban
    note       TEXT,                 -- optional free-text reason for a ban
    voted_at   TEXT,
    PRIMARY KEY (date, tg_id)
);
-- Every copy of a published story, so a tap can refresh the tally on all of them.
CREATE TABLE IF NOT EXISTS story_messages (
    story_id   INTEGER NOT NULL,
    tg_id      INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (story_id, tg_id)
);
-- The weekly card: one row per person who didn't miss a day that week. The card
-- is theirs first — it only reaches the group if they tap "share", which is what
-- `status` tracks. `file_id` is the card as Telegram stored it, so sharing costs
-- no second upload.
CREATE TABLE IF NOT EXISTS week_cards (
    week_end   TEXT NOT NULL,        -- last day of the window (ISO)
    tg_id      INTEGER NOT NULL,
    days       INTEGER NOT NULL,     -- collage days in the window = photos on the card
    streak     INTEGER NOT NULL,
    status     TEXT NOT NULL DEFAULT 'offered',  -- offered | shared | kept
    file_id    TEXT,
    offered_at TEXT,
    decided_at TEXT,
    PRIMARY KEY (week_end, tg_id)
);
-- One live ❤️ tally per shared week card. The card's owner is separate from
-- the reader so every public copy contributes to the same counter.
CREATE TABLE IF NOT EXISTS week_card_likes (
    week_end  TEXT NOT NULL,
    card_tg_id INTEGER NOT NULL,
    tg_id     INTEGER NOT NULL,
    liked_at  TEXT,
    PRIMARY KEY (week_end, card_tg_id, tg_id)
);
-- Every copy of a shared card, including the author's original, so a heart can
-- refresh the tally everywhere rather than only on the message that was tapped.
CREATE TABLE IF NOT EXISTS week_card_messages (
    week_end   TEXT NOT NULL,
    card_tg_id INTEGER NOT NULL,
    tg_id      INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    PRIMARY KEY (week_end, card_tg_id, tg_id)
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
            "users": [
                ("lang", "TEXT"),
                ("proofer", "INTEGER NOT NULL DEFAULT 0"),
                ("last_proofed_on", "TEXT"),
            ],
            # file_id: Telegram's own handle for the submitted photo. Re-sending
            # it in the knock carousel costs one tiny API call instead of an
            # upload, so a flip is instant.
            "photos": [
                ("excluded", "INTEGER NOT NULL DEFAULT 0"),
                ("file_id", "TEXT"),
            ],
            "days": [
                ("moderation_sent_at", "TEXT"),
                ("final_reminder_sent_at", "TEXT"),
                ("collage_nudges", "INTEGER NOT NULL DEFAULT 0"),
                ("preview_sent_at", "TEXT"),
                ("proof_asked_at", "TEXT"),
                ("proof_round", "INTEGER NOT NULL DEFAULT 0"),
                ("proof_result", "TEXT"),  # approved | held | exhausted
                # Set after the next day's knock window has been dealt with.
                # This makes the once-a-minute scheduler safe to retry.
                ("knock_resolved_at", "TEXT"),
            ],
            "stories": [("text_ru", "TEXT")],
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

def upsert_user(
    tg_id: int, first_name: str, username: str | None, new_status: str = "active"
) -> bool:
    """Register or reactivate a user. `new_status` is the status a brand-new row
    gets — the bot creates newcomers as 'pending' so an admin can wave them in,
    while scripts and seeds keep the plain 'active' default. Returns True if the
    user is new."""
    existing = get_user(tg_id)
    if existing is None:
        _exec(
            "INSERT INTO users(tg_id, first_name, username, status, joined_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (tg_id, first_name, username, new_status, _now()),
        )
        return True
    # Touching an existing row refreshes the name and revives whoever ran /stop.
    if existing["status"] == "pending":
        # Keep them behind the gate — otherwise any message would walk a
        # newcomer straight past it — but keep the name on the admin's card fresh.
        _exec(
            "UPDATE users SET first_name=?, username=? WHERE tg_id=?",
            (first_name, username, tg_id),
        )
    elif existing["status"] != "kicked":
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


def pending_users() -> list[sqlite3.Row]:
    """Newcomers waiting for an admin's ✅, longest wait first. They are not in
    active_user_ids(), so nothing the bot broadcasts reaches them meanwhile."""
    return _exec(
        "SELECT * FROM users WHERE status='pending' ORDER BY joined_at, tg_id"
    ).fetchall()


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
        "collage_nudges",
        "preview_sent_at",
        "proof_asked_at",
        "proof_round",
        "proof_result",
        "knock_resolved_at",
        "skipped",
    }
    ensure_day(date)
    _exec(f"UPDATE days SET {field}=? WHERE date=?", (value, date))


def get_prompt(prompt_id: int) -> sqlite3.Row | None:
    return _exec("SELECT * FROM prompts WHERE id=?", (prompt_id,)).fetchone()


# --- photos -----------------------------------------------------------------

def upsert_photo(
    date: str, tg_id: int, file_path: str, file_id: str | None = None
) -> bool:
    """Store/replace a submission. Returns True if it replaced an earlier one."""
    replaced = (
        _exec(
            "SELECT 1 FROM photos WHERE date=? AND tg_id=?", (date, tg_id)
        ).fetchone()
        is not None
    )
    _exec(
        "INSERT INTO photos(date, tg_id, file_path, submitted_at, file_id) "
        "VALUES(?, ?, ?, ?, ?) "
        "ON CONFLICT(date, tg_id) DO UPDATE SET file_path=excluded.file_path, "
        "submitted_at=excluded.submitted_at, file_id=excluded.file_id",
        (date, tg_id, file_path, _now(), file_id),
    )
    return replaced


def get_photo(date: str, tg_id: int) -> sqlite3.Row | None:
    return _exec(
        "SELECT * FROM photos WHERE date=? AND tg_id=?", (date, tg_id)
    ).fetchone()


def set_photo_file_id(date: str, tg_id: int, file_id: str) -> None:
    """Remember Telegram's handle for a photo we've just uploaded, so the next
    reader to reach it in the carousel gets it without another upload."""
    _exec(
        "UPDATE photos SET file_id=? WHERE date=? AND tg_id=?",
        (file_id, date, tg_id),
    )


# --- knocks ("knock, knock, who's there") ------------------------------------

def set_collage_cells(date: str, tg_ids: list[int]) -> None:
    """Freeze the mosaic order for a date (idx 0 = first tile the collage
    shows). Replaces any earlier arrangement, so a rebuilt collage re-registers
    rather than leaving the carousel pointing at the old layout."""
    _exec("DELETE FROM collage_cells WHERE date=?", (date,))
    for idx, tg_id in enumerate(tg_ids):
        _exec(
            "INSERT INTO collage_cells(date, idx, tg_id) VALUES(?, ?, ?)",
            (date, idx, tg_id),
        )


def collage_cells(date: str) -> list[int]:
    rows = _exec(
        "SELECT tg_id FROM collage_cells WHERE date=? ORDER BY idx", (date,)
    ).fetchall()
    return [r["tg_id"] for r in rows]


def set_knock(date: str, tg_id: int, target_id: int) -> None:
    """Record (or move) someone's single knock for the day."""
    _exec(
        "INSERT INTO knocks(date, tg_id, target_id, knocked_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(date, tg_id) DO UPDATE SET target_id=excluded.target_id, "
        "knocked_at=excluded.knocked_at",
        (date, tg_id, target_id, _now()),
    )


def get_knock(date: str, tg_id: int) -> int | None:
    row = _exec(
        "SELECT target_id FROM knocks WHERE date=? AND tg_id=?", (date, tg_id)
    ).fetchone()
    return row["target_id"] if row else None


def knock_tally(date: str) -> list[sqlite3.Row]:
    """Who got knocked on, most first. Ties break towards whoever reached that
    count earliest, so a shared top is still resolved by the room, not a coin."""
    return _exec(
        "SELECT target_id, COUNT(*) AS n, MAX(knocked_at) AS last_at "
        "FROM knocks WHERE date=? GROUP BY target_id "
        "ORDER BY n DESC, last_at ASC",
        (date,),
    ).fetchall()


def knockers_for(date: str, target_id: int) -> list[int]:
    rows = _exec(
        "SELECT tg_id FROM knocks WHERE date=? AND target_id=? ORDER BY knocked_at",
        (date, target_id),
    ).fetchall()
    return [r["tg_id"] for r in rows]


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


def delete_collage_messages(date: str) -> None:
    _exec("DELETE FROM collage_messages WHERE date=?", (date,))


def delete_ratings(date: str) -> None:
    _exec("DELETE FROM ratings WHERE date=?", (date,))


# --- collage proofing ---------------------------------------------------------

def set_proofer(tg_id: int, on: bool) -> None:
    _exec("UPDATE users SET proofer=? WHERE tg_id=?", (1 if on else 0, tg_id))


def list_proofers() -> list[sqlite3.Row]:
    """Everyone flagged as a proofer, whatever their status — for /proofers."""
    return _exec(
        "SELECT * FROM users WHERE proofer=1 ORDER BY first_name"
    ).fetchall()


def proofer_ids() -> list[int]:
    """Active proofers, whoever was asked longest ago first (never-asked lead),
    so the duty rotates instead of always landing on the same two people."""
    rows = _exec(
        "SELECT tg_id FROM users WHERE proofer=1 AND status='active' "
        "ORDER BY last_proofed_on IS NOT NULL, last_proofed_on, tg_id"
    ).fetchall()
    return [r["tg_id"] for r in rows]


def add_proof_ask(date: str, tg_id: int, round_no: int) -> None:
    """Put someone on the hook for a date. Asking is what advances the rotation,
    so last_proofed_on moves even when they never answer."""
    _exec(
        "INSERT INTO proof_asks(date, tg_id, round_no, asked_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(date, tg_id) DO NOTHING",
        (date, tg_id, round_no, _now()),
    )
    _exec("UPDATE users SET last_proofed_on=? WHERE tg_id=?", (date, tg_id))


def delete_proof_ask(date: str, tg_id: int) -> None:
    _exec("DELETE FROM proof_asks WHERE date=? AND tg_id=?", (date, tg_id))


def set_proof_message(date: str, tg_id: int, message_id: int | None) -> None:
    _exec(
        "UPDATE proof_asks SET message_id=? WHERE date=? AND tg_id=?",
        (message_id, date, tg_id),
    )


def get_proof_ask(date: str, tg_id: int) -> sqlite3.Row | None:
    return _exec(
        "SELECT * FROM proof_asks WHERE date=? AND tg_id=?", (date, tg_id)
    ).fetchone()


def proof_asks_for(date: str, round_no: int | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM proof_asks WHERE date=?"
    params: tuple = (date,)
    if round_no is not None:
        sql += " AND round_no=?"
        params += (round_no,)
    return _exec(sql + " ORDER BY round_no, asked_at", params).fetchall()


def set_proof_vote(date: str, tg_id: int, value: str) -> bool:
    """Record a decision. Returns False if that person already decided — votes
    are deliberately one-shot, unlike the collage ratings."""
    row = get_proof_ask(date, tg_id)
    if row is None or row["value"]:
        return False
    _exec(
        "UPDATE proof_asks SET value=?, voted_at=? WHERE date=? AND tg_id=?",
        (value, _now(), date, tg_id),
    )
    return True


def set_proof_note(date: str, tg_id: int, note: str) -> None:
    _exec(
        "UPDATE proof_asks SET note=? WHERE date=? AND tg_id=?",
        (note.strip(), date, tg_id),
    )


def proof_counts(date: str) -> dict[str, int]:
    rows = _exec(
        "SELECT value, COUNT(*) AS n FROM proof_asks WHERE date=? "
        "AND value IS NOT NULL GROUP BY value",
        (date,),
    ).fetchall()
    return {r["value"]: r["n"] for r in rows}


def proof_bans(date: str) -> list[sqlite3.Row]:
    return _exec(
        "SELECT * FROM proof_asks WHERE date=? AND value='ban' ORDER BY voted_at",
        (date,),
    ).fetchall()


# --- custom feedback polls --------------------------------------------------

def create_poll(question: str, question_ru: str | None, created_by: int) -> int:
    cur = _exec(
        "INSERT INTO polls(question, question_ru, created_by, created_at) "
        "VALUES(?, ?, ?, ?)",
        (question.strip(), question_ru.strip() if question_ru else None,
         created_by, _now()),
    )
    return cur.lastrowid


def get_poll(poll_id: int) -> sqlite3.Row | None:
    return _exec("SELECT * FROM polls WHERE id=?", (poll_id,)).fetchone()


def list_polls() -> list[sqlite3.Row]:
    return _exec("SELECT * FROM polls ORDER BY id DESC").fetchall()


def update_poll_question(poll_id: int, question: str, question_ru: str | None) -> bool:
    cur = _exec(
        "UPDATE polls SET question=?, question_ru=? WHERE id=?",
        (question.strip(), question_ru.strip() if question_ru else None, poll_id),
    )
    return cur.rowcount > 0


def set_poll_status(poll_id: int, status: str) -> None:
    _exec("UPDATE polls SET status=? WHERE id=?", (status, poll_id))


def set_poll_vote(poll_id: int, tg_id: int, value: str) -> bool:
    """Store/replace a user's vote. Returns False if it was already this value
    (so callers can skip re-editing keyboards)."""
    row = _exec(
        "SELECT value FROM poll_votes WHERE poll_id=? AND tg_id=?", (poll_id, tg_id)
    ).fetchone()
    if row and row["value"] == value:
        return False
    _exec(
        "INSERT INTO poll_votes(poll_id, tg_id, value, voted_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(poll_id, tg_id) DO UPDATE SET value=excluded.value, "
        "voted_at=excluded.voted_at",
        (poll_id, tg_id, value, _now()),
    )
    return True


def poll_counts(poll_id: int) -> dict[str, int]:
    rows = _exec(
        "SELECT value, COUNT(*) AS n FROM poll_votes WHERE poll_id=? GROUP BY value",
        (poll_id,),
    ).fetchall()
    return {r["value"]: r["n"] for r in rows}


def poll_votes_detail(poll_id: int) -> list[sqlite3.Row]:
    """Every vote with the voter joined in, newest first — for /pollresults."""
    return _exec(
        "SELECT v.tg_id, v.value, v.voted_at, u.first_name, u.username "
        "FROM poll_votes v LEFT JOIN users u ON u.tg_id = v.tg_id "
        "WHERE v.poll_id=? ORDER BY v.voted_at DESC",
        (poll_id,),
    ).fetchall()


def add_poll_message(poll_id: int, tg_id: int, message_id: int) -> None:
    _exec(
        "INSERT INTO poll_messages(poll_id, tg_id, message_id) VALUES(?, ?, ?) "
        "ON CONFLICT(poll_id, tg_id) DO UPDATE SET message_id=excluded.message_id",
        (poll_id, tg_id, message_id),
    )


def poll_messages_for(poll_id: int) -> list[sqlite3.Row]:
    return _exec(
        "SELECT * FROM poll_messages WHERE poll_id=?", (poll_id,)
    ).fetchall()


# --- feedback & suggestions ---------------------------------------------------

def add_feedback(tg_id: int, text: str) -> int:
    cur = _exec(
        "INSERT INTO feedback(tg_id, text, created_at) VALUES(?, ?, ?)",
        (tg_id, text.strip(), _now()),
    )
    return cur.lastrowid


def list_feedback() -> list[sqlite3.Row]:
    """All feedback ever submitted, oldest first."""
    return _exec("SELECT * FROM feedback ORDER BY id").fetchall()


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


# --- stories ("story of the day") --------------------------------------------

def add_story(date: str, tg_id: int, ask_message_id: int | None) -> int:
    cur = _exec(
        "INSERT INTO stories(date, tg_id, ask_message_id, status, asked_at) "
        "VALUES(?, ?, ?, 'asked', ?)",
        (date, tg_id, ask_message_id, _now()),
    )
    return cur.lastrowid


def get_story(sid: int) -> sqlite3.Row | None:
    return _exec("SELECT * FROM stories WHERE id=?", (sid,)).fetchone()


def story_for_photo(date: str, tg_id: int) -> sqlite3.Row | None:
    """Any request already made for this exact day's photo."""
    return _exec(
        "SELECT * FROM stories WHERE date=? AND tg_id=? ORDER BY id DESC LIMIT 1",
        (date, tg_id),
    ).fetchone()


def pending_story_for(tg_id: int) -> sqlite3.Row | None:
    """The author's most recent unanswered ask, if any (for reply capture)."""
    return _exec(
        "SELECT * FROM stories WHERE tg_id=? AND status='asked' "
        "ORDER BY id DESC LIMIT 1",
        (tg_id,),
    ).fetchone()


def story_by_ask_message(tg_id: int, ask_message_id: int) -> sqlite3.Row | None:
    """An unanswered ask matched by the exact message the user replied to —
    unambiguous even if the author was asked about several days."""
    return _exec(
        "SELECT * FROM stories WHERE tg_id=? AND ask_message_id=? "
        "AND status='asked' ORDER BY id DESC LIMIT 1",
        (tg_id, ask_message_id),
    ).fetchone()


def set_story_answer(sid: int, text: str) -> None:
    _exec(
        "UPDATE stories SET text=?, status='answered', answered_at=? WHERE id=?",
        (text.strip(), _now(), sid),
    )


def set_story_text(sid: int, text: str, text_ru: str | None = None) -> bool:
    """Admin edit of a story's text. `text` is the primary/English version and
    `text_ru` the optional translation — an edit always replaces both, so
    editing without a RU half clears any earlier translation. Writing text onto
    an unanswered ask counts as answering it (lets the admin author a story by
    hand). Returns False if the story id doesn't exist."""
    s = get_story(sid)
    if s is None:
        return False
    ru = text_ru.strip() if text_ru else None
    if s["status"] == "asked":
        _exec(
            "UPDATE stories SET text=?, text_ru=?, status='answered', answered_at=? "
            "WHERE id=?",
            (text.strip(), ru, _now(), sid),
        )
    else:
        _exec(
            "UPDATE stories SET text=?, text_ru=? WHERE id=?", (text.strip(), ru, sid)
        )
    return True


def photo_dates() -> list[str]:
    """Distinct dates that have at least one non-excluded submission."""
    rows = _exec(
        "SELECT DISTINCT date FROM photos WHERE excluded=0 ORDER BY date"
    ).fetchall()
    return [r["date"] for r in rows]


def set_story_status(sid: int, status: str) -> bool:
    ts_col = {"published": "published_at"}.get(status)
    if ts_col:
        cur = _exec(
            f"UPDATE stories SET status=?, {ts_col}=? WHERE id=?",
            (status, _now(), sid),
        )
    else:
        cur = _exec("UPDATE stories SET status=? WHERE id=?", (status, sid))
    return cur.rowcount > 0


def toggle_story_like(sid: int, tg_id: int) -> bool:
    """Tap the heart: like if not liked yet, un-like if already liked.
    Returns the new state (True = liked)."""
    row = _exec(
        "SELECT 1 FROM story_likes WHERE story_id=? AND tg_id=?", (sid, tg_id)
    ).fetchone()
    if row:
        _exec(
            "DELETE FROM story_likes WHERE story_id=? AND tg_id=?", (sid, tg_id)
        )
        return False
    _exec(
        "INSERT INTO story_likes(story_id, tg_id, liked_at) VALUES(?, ?, ?)",
        (sid, tg_id, _now()),
    )
    return True


def story_like_count(sid: int) -> int:
    row = _exec(
        "SELECT COUNT(*) AS n FROM story_likes WHERE story_id=?", (sid,)
    ).fetchone()
    return row["n"]


def story_likers(sid: int) -> list[int]:
    rows = _exec(
        "SELECT tg_id FROM story_likes WHERE story_id=? ORDER BY liked_at", (sid,)
    ).fetchall()
    return [r["tg_id"] for r in rows]


def add_story_message(sid: int, tg_id: int, message_id: int) -> None:
    _exec(
        "INSERT INTO story_messages(story_id, tg_id, message_id) VALUES(?, ?, ?) "
        "ON CONFLICT(story_id, tg_id) DO UPDATE SET message_id=excluded.message_id",
        (sid, tg_id, message_id),
    )


def story_messages_for(sid: int) -> list[sqlite3.Row]:
    return _exec(
        "SELECT * FROM story_messages WHERE story_id=?", (sid,)
    ).fetchall()


def answered_stories() -> list[sqlite3.Row]:
    """Stories the author has answered but the admin hasn't published yet."""
    return _exec(
        "SELECT * FROM stories WHERE status='answered' ORDER BY id"
    ).fetchall()


def open_stories() -> list[sqlite3.Row]:
    """Story requests still in progress: awaiting a reply or ready to publish."""
    return _exec(
        "SELECT * FROM stories WHERE status IN ('asked', 'answered') ORDER BY id"
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


def streaks_for(date: str) -> dict[int, int]:
    """tg_id -> consecutive collage days (ending at `date`) the user submitted for.

    Same definition as the /stats board, computed once for every submitter. When
    `date`'s collage is still going out its `collage_sent_at` isn't set yet, so it
    is missing from collage_dates(); it's appended here since today counts."""
    days = collage_dates()
    if not days or days[-1] != date:
        days = days + [date]
    out: dict[int, int] = {}
    for tg_id, user_dates in participation().items():
        streak = 0
        for d in reversed(days):
            if d not in user_dates:
                break
            streak += 1
        if streak:
            out[tg_id] = streak
    return out


# --- the weekly card ----------------------------------------------------------

def week_days(end: str, span: int = 7) -> list[str]:
    """Collage days inside the `span`-day calendar window ending at `end`.

    Counted in collage days, not calendar days, so a skipped or empty day can't
    make a week un-winnable — you can only be measured against days that ran."""
    start = (date_cls.fromisoformat(end) - timedelta(days=span - 1)).isoformat()
    return [d for d in collage_dates() if start <= d <= end]


def week_board(end: str, span: int = 7) -> list[dict]:
    """Everyone who submitted at all in the window ending at `end`: how many of
    its collage days they filled, how long their run is as of that day, and how
    many days they've played in total.

    Ordered the way the week is read — longest streak first, then the fullest
    week, then the longest history — so the first row is the streak leader and
    the tie-break is deterministic rather than dictionary order."""
    days = week_days(end, span)
    if not days:
        return []
    history = [d for d in collage_dates() if d <= end]
    out = []
    for tg_id, user_dates in participation().items():
        filled = [d for d in days if d in user_dates]
        if not filled:
            continue
        streak = 0
        for d in reversed(history):
            if d not in user_dates:
                break
            streak += 1
        out.append(
            {
                "tg_id": tg_id,
                "dates": filled,
                "days": len(filled),
                "of": len(days),
                "streak": streak,
                "total": len([d for d in history if d in user_dates]),
            }
        )
    out.sort(key=lambda r: (-r["streak"], -r["days"], -r["total"], r["tg_id"]))
    return out


def photos_on(tg_id: int, dates: list[str]) -> list[sqlite3.Row]:
    """That user's non-excluded submissions for the given dates, in date order."""
    if not dates:
        return []
    marks = ",".join("?" * len(dates))
    return _exec(
        f"SELECT * FROM photos WHERE tg_id=? AND excluded=0 AND date IN ({marks}) "
        "ORDER BY date",
        (tg_id, *dates),
    ).fetchall()


def add_week_card(
    week_end: str, tg_id: int, days: int, streak: int, status: str = "offered"
) -> None:
    """'offered' = the streak leader, who still has a choice to make; 'gift' =
    everyone else, whose card is theirs and goes no further."""
    _exec(
        "INSERT INTO week_cards(week_end, tg_id, days, streak, status, offered_at) "
        "VALUES(?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(week_end, tg_id) DO NOTHING",
        (week_end, tg_id, days, streak, status, _now()),
    )


def last_crowned(before: str) -> dict[int, str]:
    """tg_id -> the last week they were the leader, for weeks before `before`.

    Gift cards don't count — only the crown does. Feeds the tie-break: two
    people on the same streak take turns instead of one of them being shut out
    forever by a rule they can't see."""
    rows = _exec(
        "SELECT tg_id, MAX(week_end) AS last FROM week_cards "
        "WHERE status<>'gift' AND week_end<? GROUP BY tg_id",
        (before,),
    ).fetchall()
    return {r["tg_id"]: r["last"] for r in rows}


def get_week_card(week_end: str, tg_id: int) -> sqlite3.Row | None:
    return _exec(
        "SELECT * FROM week_cards WHERE week_end=? AND tg_id=?", (week_end, tg_id)
    ).fetchone()


def week_cards_for(week_end: str) -> list[sqlite3.Row]:
    return _exec(
        "SELECT * FROM week_cards WHERE week_end=? ORDER BY streak DESC, days DESC",
        (week_end,),
    ).fetchall()


def set_week_card_file_id(week_end: str, tg_id: int, file_id: str) -> None:
    _exec(
        "UPDATE week_cards SET file_id=? WHERE week_end=? AND tg_id=?",
        (file_id, week_end, tg_id),
    )


def delete_week_cards(week_end: str) -> int:
    """Forget a week so it can be offered again (admin escape hatch/testing)."""
    _exec("DELETE FROM week_card_likes WHERE week_end=?", (week_end,))
    _exec("DELETE FROM week_card_messages WHERE week_end=?", (week_end,))
    return _exec("DELETE FROM week_cards WHERE week_end=?", (week_end,)).rowcount


def set_week_card_status(week_end: str, tg_id: int, status: str) -> bool:
    """Record the author's decision. Returns False if it was already decided —
    the guard against a double tap sharing the card twice."""
    cur = _exec(
        "UPDATE week_cards SET status=?, decided_at=? "
        "WHERE week_end=? AND tg_id=? AND status='offered'",
        (status, _now(), week_end, tg_id),
    )
    return cur.rowcount > 0


def toggle_week_card_like(week_end: str, card_tg_id: int, tg_id: int) -> bool:
    """Toggle one reader's heart on one shared week card.

    Returns the new state (True = liked). The caller checks that the card was
    actually shared before exposing this path.
    """
    key = (week_end, card_tg_id, tg_id)
    row = _exec(
        "SELECT 1 FROM week_card_likes "
        "WHERE week_end=? AND card_tg_id=? AND tg_id=?",
        key,
    ).fetchone()
    if row:
        _exec(
            "DELETE FROM week_card_likes "
            "WHERE week_end=? AND card_tg_id=? AND tg_id=?",
            key,
        )
        return False
    _exec(
        "INSERT INTO week_card_likes(week_end, card_tg_id, tg_id, liked_at) "
        "VALUES(?, ?, ?, ?)",
        (*key, _now()),
    )
    return True


def week_card_like_count(week_end: str, card_tg_id: int) -> int:
    row = _exec(
        "SELECT COUNT(*) AS n FROM week_card_likes "
        "WHERE week_end=? AND card_tg_id=?",
        (week_end, card_tg_id),
    ).fetchone()
    return row["n"]


def week_card_likers(week_end: str, card_tg_id: int) -> list[int]:
    rows = _exec(
        "SELECT tg_id FROM week_card_likes "
        "WHERE week_end=? AND card_tg_id=? ORDER BY liked_at",
        (week_end, card_tg_id),
    ).fetchall()
    return [r["tg_id"] for r in rows]


def add_week_card_message(
    week_end: str, card_tg_id: int, tg_id: int, message_id: int
) -> None:
    _exec(
        "INSERT INTO week_card_messages(week_end, card_tg_id, tg_id, message_id) "
        "VALUES(?, ?, ?, ?) "
        "ON CONFLICT(week_end, card_tg_id, tg_id) "
        "DO UPDATE SET message_id=excluded.message_id",
        (week_end, card_tg_id, tg_id, message_id),
    )


def week_card_messages_for(week_end: str, card_tg_id: int) -> list[sqlite3.Row]:
    return _exec(
        "SELECT * FROM week_card_messages "
        "WHERE week_end=? AND card_tg_id=?",
        (week_end, card_tg_id),
    ).fetchall()
