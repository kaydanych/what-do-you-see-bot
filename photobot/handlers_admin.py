import functools
import html
import logging
from datetime import time

from telegram import Update
from telegram.ext import ContextTypes

from . import config, db, jobs

log = logging.getLogger(__name__)

ADMIN_HELP = """Admin commands:
/status — today at a glance
/users — user list
/addprompt <en> | <ru> — append a prompt to the queue (the | and RU part are
  optional, English is the default everyone gets)
/prompts — queue overview (sent prompts shown struck through, next one flagged)
Upload a .txt (one prompt per line) to REPLACE the queue in that order;
  prompts you've already sent are kept as done and never repeat
/setru <id> <ru text> — add/replace the Russian version of an existing prompt
/delprompt <id> — delete a prompt
/times — show schedule
/settimes key=HH:MM … — e.g. /settimes prompt=09:00 reminder=19:00 deadline=21:00 delay=10
/forceprompt — send today's prompt now
Moderation (at the deadline you get a numbered contact sheet):
/exclude N — drop photo N from today's collage
/include N — undo an exclusion
/ban N — drop photo N and kick its author
/forcecollage — build & send collage now
/preview — collage dry-run, sent only to you
/skipday — cancel today
/broadcast <text> — message all active users
/kick <id|@username> / /unkick <id|@username>
/errors — last log lines"""


def parse_prompt_line(line: str) -> tuple[str, str | None]:
    """'EN text | RU text' -> (en, ru); no pipe -> (text, None)."""
    en, sep, ru = line.partition("|")
    en, ru = en.strip(), ru.strip()
    if sep and en and ru:
        return en, ru
    return line.strip().strip("|").strip(), None


def admin_only(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if (
            update.effective_user is None
            or update.effective_user.id not in config.ADMIN_IDS
        ):
            return
        return await func(update, context)

    return wrapper


@admin_only
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(ADMIN_HELP)


@admin_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = jobs.now_local().date().isoformat()
    day = db.get_day(today)
    t = {k: db.get_setting(k) for k in config.DEFAULT_SETTINGS}
    lines = [f"📅 {today}"]
    if day is None or not day["prompt_sent_at"]:
        state = "skipped" if (day and day["skipped"]) else "not sent yet"
        lines.append(f"Prompt: {state} (scheduled {t['prompt_time']})")
    else:
        prompt = db.get_prompt(day["prompt_id"])
        lines.append(f"Prompt: «{prompt['text']}»")
        subs = db.photos_for(today)
        names = []
        for s in subs:
            u = db.get_user(s["tg_id"])
            names.append(u["first_name"] if u else str(s["tg_id"]))
        lines.append(f"Submitted: {len(subs)}" + (f" — {', '.join(names)}" if names else ""))
        excluded = len(db.photos_for(today, include_excluded=True)) - len(subs)
        if excluded:
            lines.append(f"Excluded by moderation: {excluded}")
        lines.append(
            "Collage: sent ✅" if day["collage_sent_at"]
            else f"Collage: pending ({t['deadline_time']} + {t['collage_delay_min']} min)"
        )
    active = len(db.active_user_ids())
    lines.append(f"Active users: {active}")
    lines.append(f"Unused prompts: {db.count_unused_prompts()}")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = db.list_users()
    if not rows:
        await update.message.reply_text("No users yet.")
        return
    lines = []
    for r in rows:
        mark = {"active": "🟢", "inactive": "⚪️", "kicked": "🚫"}[r["status"]]
        uname = f"@{r['username']}" if r["username"] else ""
        joined = (r["joined_at"] or "")[:10]
        lines.append(f"{mark} {r['first_name']} {uname} (id {r['tg_id']}, {joined})")
    await update.message.reply_text("\n".join(lines[:100]))


@admin_only
async def cmd_addprompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text(
            "Usage: /addprompt <en text> | <ru text>\n(the | and RU part are optional)"
        )
        return
    en, ru = parse_prompt_line(text)
    pid = db.add_prompt(en, update.effective_user.id, text_ru=ru)
    note = "" if ru else "\n(no RU version — everyone gets this text as-is)"
    await update.message.reply_text(
        f"Added prompt #{pid}. Unused prompts: {db.count_unused_prompts()}{note}"
    )


@admin_only
async def cmd_setru(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setru <id> <russian text>")
        return
    try:
        pid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /setru <id> <russian text>")
        return
    ru = " ".join(context.args[1:]).strip()
    if not db.set_prompt_ru(pid, ru):
        await update.message.reply_text(f"No prompt #{pid}.")
        return
    p = db.get_prompt(pid)
    await update.message.reply_text(f"#{pid} now:\nEN: {p['text']}\nRU: {p['text_ru']}")


@admin_only
async def cmd_prompts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = db.list_prompts()
    if not rows:
        await update.message.reply_text(
            "Queue is empty. /addprompt <text> or upload a .txt (one per line)."
        )
        return
    used = sum(1 for r in rows if r["used_on"])
    lines = [f"<b>Prompt queue</b> — {used} sent · {len(rows) - used} left"]
    next_flagged = False
    for r in rows:
        label = html.escape(r["text"])
        flag = " 🇷🇺" if r["text_ru"] else ""
        if r["used_on"]:
            lines.append(f"<s>#{r['id']} {label}</s>{flag}")
        elif not next_flagged:
            lines.append(f"▶️ <b>#{r['id']} {label}</b>{flag} ← next")
            next_flagged = True
        else:
            lines.append(f"#{r['id']} {label}{flag}")

    buf = ""
    for ln in lines:
        if buf and len(buf) + len(ln) + 1 > 3800:
            await update.message.reply_text(buf, parse_mode="HTML")
            buf = ""
        buf += ("\n" if buf else "") + ln
    if buf:
        await update.message.reply_text(buf, parse_mode="HTML")


@admin_only
async def cmd_delprompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        pid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /delprompt <id>")
        return
    ok = db.delete_prompt(pid)
    await update.message.reply_text(f"Deleted #{pid}." if ok else f"No prompt #{pid}.")


@admin_only
async def import_prompts_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    tg_file = await doc.get_file()
    data = bytes(await tg_file.download_as_bytearray())
    parsed = [
        parse_prompt_line(ln)
        for ln in data.decode("utf-8", errors="replace").splitlines()
        if ln.strip()
    ]
    if not parsed:
        await update.message.reply_text("That file had no prompt lines — queue unchanged.")
        return
    queued, kept = db.replace_prompt_queue(parsed, update.effective_user.id)
    bilingual = sum(1 for _, ru in parsed if ru)
    note = f"Queue replaced: {queued} prompts ({bilingual} bilingual) in file order."
    if kept:
        note += f"\n{kept} already-sent prompt(s) kept as history (won't repeat)."
    note += f"\nUnused now: {db.count_unused_prompts()}."
    await update.message.reply_text(note)


@admin_only
async def cmd_times(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"prompt = {db.get_setting('prompt_time')}\n"
        f"reminder = {db.get_setting('reminder_time')}\n"
        f"deadline = {db.get_setting('deadline_time')}\n"
        f"delay = {db.get_setting('collage_delay_min')} min after deadline\n\n"
        "Change: /settimes prompt=09:00 reminder=19:00 deadline=21:00 delay=5\n"
        "(any subset; applies within a minute, no restart needed)"
    )


KEY_MAP = {
    "prompt": "prompt_time",
    "reminder": "reminder_time",
    "deadline": "deadline_time",
    "delay": "collage_delay_min",
}


@admin_only
async def cmd_settimes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: /settimes prompt=09:00 reminder=19:00 deadline=21:00 delay=5"
        )
        return
    new = {k: db.get_setting(v) for k, v in KEY_MAP.items()}
    try:
        for arg in context.args:
            key, _, val = arg.partition("=")
            if key not in KEY_MAP or not val:
                raise ValueError(f"unknown argument «{arg}»")
            if key == "delay":
                if not (0 <= int(val) <= 60):
                    raise ValueError("delay must be 0–60 minutes")
            else:
                jobs.parse_hhmm(val)  # validates format
            new[key] = val
        p, r, d = (jobs.parse_hhmm(new[k]) for k in ("prompt", "reminder", "deadline"))
        if not (p < r < d):
            raise ValueError("required order: prompt < reminder < deadline")
        if d > time(23, 50):
            raise ValueError("deadline must be 23:50 or earlier (collage runs after it)")
    except ValueError as e:
        await update.message.reply_text(f"Not saved: {e}")
        return
    for key, val in new.items():
        db.set_setting(KEY_MAP[key], val)
    await update.message.reply_text(
        f"Saved ✅ prompt {new['prompt']}, reminder {new['reminder']}, "
        f"deadline {new['deadline']}, collage +{new['delay']} min."
    )


def _photo_by_number(date: str, arg: str):
    """Resolve a contact-sheet number to a photo row (numbers include
    already-excluded photos, so they never shift)."""
    photos = db.photos_for(date, include_excluded=True)
    try:
        n = int(arg)
    except ValueError:
        return None, photos
    if not 1 <= n <= len(photos):
        return None, photos
    return photos[n - 1], photos


async def _moderate(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action: str
) -> None:
    today = jobs.now_local().date().isoformat()
    day = db.get_day(today)
    if day and day["collage_sent_at"]:
        await update.message.reply_text(
            "Today's collage was already sent — too late to moderate."
        )
        return
    if not context.args:
        await update.message.reply_text(f"Usage: /{action} N (see the contact sheet)")
        return
    photo, photos = _photo_by_number(today, context.args[0])
    if photo is None:
        await update.message.reply_text(
            f"No photo with that number (today: 1–{len(photos)})."
        )
        return
    u = db.get_user(photo["tg_id"])
    name = f"{u['first_name']} (id {photo['tg_id']})" if u else f"id {photo['tg_id']}"
    if action == "include":
        db.set_photo_excluded(today, photo["tg_id"], False)
        await update.message.reply_text(f"↩️ Photo of {name} is back in.")
        return
    db.set_photo_excluded(today, photo["tg_id"], True)
    if action == "ban":
        db.set_user_status(photo["tg_id"], "kicked")
        await update.message.reply_text(f"🚫 Photo excluded and {name} kicked.")
    else:
        await update.message.reply_text(f"✂️ Photo of {name} excluded from today.")
    remaining = len(db.photos_for(today))
    await update.message.reply_text(f"Photos left in the collage: {remaining}.")


@admin_only
async def cmd_exclude(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _moderate(update, context, "exclude")


@admin_only
async def cmd_include(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _moderate(update, context, "include")


@admin_only
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _moderate(update, context, "ban")


@admin_only
async def cmd_forceprompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = jobs.now_local().date().isoformat()
    day = db.get_day(today)
    if day and day["prompt_sent_at"]:
        await update.message.reply_text("Today's prompt was already sent.")
        return
    if day and day["skipped"]:
        db.set_day_field(today, "skipped", 0)
    await jobs.send_prompt(context, today)


@admin_only
async def cmd_forcecollage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = jobs.now_local().date().isoformat()
    day = db.get_day(today)
    if day is None or not day["prompt_sent_at"]:
        await update.message.reply_text("No prompt was sent today — nothing to collect.")
        return
    if day["collage_sent_at"]:
        await update.message.reply_text("Collage was already sent today.")
        return
    result = await jobs.send_collage(context, today)
    await update.message.reply_text(f"Done: {result}")


@admin_only
async def cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = jobs.now_local().date().isoformat()
    result = await jobs.send_collage(
        context, today, preview_to=update.effective_user.id
    )
    if result == "no submissions":
        await update.message.reply_text("No submissions yet — nothing to preview.")


@admin_only
async def cmd_skipday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = jobs.now_local().date().isoformat()
    db.set_day_field(today, "skipped", 1)
    await update.message.reply_text(
        "Today is cancelled: no reminder, no collage. Photos already stored stay on disk."
    )


@admin_only
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: /broadcast <text>")
        return
    sent, failed = await jobs.send_to_users(context, db.active_user_ids(), text)
    await update.message.reply_text(f"Broadcast: sent {sent}, failed {failed}.")


def _resolve_user(arg: str):
    if arg.startswith("@"):
        return db.get_user_by_username(arg)
    try:
        return db.get_user(int(arg))
    except ValueError:
        return None


@admin_only
async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /kick <id|@username>")
        return
    row = _resolve_user(context.args[0])
    if row is None:
        await update.message.reply_text("User not found.")
        return
    db.set_user_status(row["tg_id"], "kicked")
    await update.message.reply_text(f"Kicked {row['first_name']} (id {row['tg_id']}).")


@admin_only
async def cmd_unkick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /unkick <id|@username>")
        return
    row = _resolve_user(context.args[0])
    if row is None:
        await update.message.reply_text("User not found.")
        return
    db.set_user_status(row["tg_id"], "active")
    await update.message.reply_text(
        f"Restored {row['first_name']} (id {row['tg_id']})."
    )


@admin_only
async def cmd_errors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        lines = config.LOG_FILE.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        await update.message.reply_text("No log file yet.")
        return
    tail = "\n".join(lines[-20:]) or "Log is empty."
    await update.message.reply_text(tail[-3800:])
