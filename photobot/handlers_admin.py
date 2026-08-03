import functools
import html
import io
import logging
import random
from datetime import date as date_cls
from datetime import time, timedelta

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.error import Forbidden
from telegram.ext import ContextTypes

from . import config, db, handlers_user as usr, jobs, version
from .strings import t

log = logging.getLogger(__name__)

ADMIN_HELP = """Admin commands

📊 Overview
/broadcast <text> — message all active users (EN | RU; EN is the fallback)
/errors — last log lines
/stats — participation leaderboard + collage ratings
/status — today at a glance
/users — user list
/version — which build is running (deployed commit)

🚪 New users (nobody joins unseen)
Every newcomer lands on a waiting list and you get their card with ✅ / 🚫.
Until you tap ✅ they are outside everything — no prompt, reminder, collage,
poll or broadcast — and each message they send gets a "you're on the list"
note. ✅ greets them and starts the game, 🚫 closes the door (/unkick undoes it,
/kick undoes a ✅). They show as ⏳ in /users.
/pending — everyone still waiting, with the buttons again

📝 Prompts (the queue)
/addprompt <en> | <ru> — append a prompt (| and RU optional; EN is what everyone gets)
/delprompt <id> — delete a prompt
/exportprompts — download the unused queue as a plain .txt (no ids) to reorder/edit
/prompts — queue overview (sent ones struck through, next one flagged)
/setru <id> <ru text> — add/replace a prompt's Russian version
• Reorder the queue: /exportprompts → drag lines in any editor → re-upload the .txt
• Upload a .txt (one prompt per line) to REPLACE the queue in that order;
  already-sent prompts are kept as done and never repeat

💡 Suggestions & feedback
/approve <id> [en | ru] — approve a suggestion; the suggester's name is baked into the prompt text as "Idea: Name". One /approve per line to batch several.
/dismiss <id> — discard a suggestion
/feedback_all — every /feedback message users have sent, in one place
/suggestions — pending user prompt ideas

📊 Polls (custom 👍/👎 questions to all active users, live shared tally)
/poll <question> — create + send a poll (use <EN> | <RU> for both languages)
/polls — list polls with their tallies
/pollresults <id> — full tally + who voted
/polledit <id> <new question> — fix the wording; rewrites every copy sent
/pollclose <id> — end voting (tallies stay, taps stop)

🗓 Schedule & daily cycle
/forceprompt — send today's prompt now
/settimes key=… — e.g. prompt=09:00 reminder=19:00 final=10 deadline=21:00 preview=21:10
  (final = last-call reminder N min before deadline; preview = evening heads-up of tomorrow's prompt)
/skipday — cancel today
/times — show schedule

🖼 Collage & moderation
At the deadline you get a numbered contact sheet. With proofing off the collage
waits for you, with nudges 10/30/60 min after the deadline while unsent; with
proofing on it goes out as soon as a proofer waves it through (see below).
/ban N — drop photo N and kick its author
/delcollage [YYYY-MM-DD] — delete a sent collage everywhere (Telegram allows this only within 48 h) and reset the day
/exclude N — drop photo N from today's collage
/forcecollage [YYYY-MM-DD] — send the reviewed collage to everyone (default today)
/include N — undo an exclusion
/kick <id|@username> — remove a user
/preview — collage dry-run, sent only to you
/unkick <id|@username> — restore a user

👀 Proofing (trusted users check the collage before it goes out)
Keep a long list of people you trust; each night 3 are picked at random from
whoever on it played that day. At the deadline the collage — no names — goes to them,
unannounced, asking whether anything is wrong; the rules ride in that message.
One 👍 publishes it. A 🚫 (they confirm it twice) freezes the publish and rolls
to a fresh 3; two 🚫 park the day on you with their notes — then /exclude N and
/forcecollage, or /forcecollage as is. Silence rolls to the next 3 every 10
min; when the list runs out you get the nudges, as before. Once the day is
decided, the question is deleted from anyone who hadn't answered.
/proofers — who's on the list and when they were last asked
/proofers add|remove <id> <id> … — bulk edit, safe to re-run
/proofer <id|@username> — toggle one (silent — nobody is ever notified)
/proofing — settings + tonight's state
/proofing batch=3 round=10 quorum=2 — tune it
/proofing off — back to the admin-only flow

💬 Story of the day (the photo + why the author chose it)
/photos [YYYY-MM-DD] — numbered author list for a day (numbers = the contact sheet)
/knocks [YYYY-MM-DD] — who the group knocked on; ranked, then the leader as a picture with their name — ‹ › through the tied ones and 💬 asks that author right there
/askstory [YYYY-MM-DD] N — DM author N their photo and ask why they chose it
/askstory random — pick a random past photo and ask its author
/stories — story requests: who is still replying and what is ready to publish
/editstory <id> <text> — edit a story's text (or write one yourself); <EN> | <RU> stores both languages, each reader gets their half
/publishstory <id> — send that photo + story to everyone in the game (reveals the author's name); it carries a ❤️ button with a live shared tally
/publishstory <id> day — narrower: only that day's submitters, the audience the collage went to
/dismissstory <id> — discard a story

🗓 Week card (Sunday 17:00, one person's own week back as one picture)
Everyone with 5+ of the week's days gets their week rendered and sent to them —
buttonless, a gift, nothing to decide. The streak leader alone is congratulated
and asked «show everyone» / «keep it», and only their tap sends it to the group.
When they share, every copy gets a ❤️ button with one live shared tally.
Ties on the longest streak rotate: the crown goes to whoever was crowned least
recently. The window ends the day *before* it runs (Sun–Sat), so it ignores
Sunday's open submissions and never names an author whose knocks are still live.
/weekcard — who qualifies for the current window (dry run, sends nothing)
/weekcard send [YYYY-MM-DD] — offer the cards now (default window = ends yesterday)
/weekcard me [YYYY-MM-DD] — same, but only your own card (safe way to look at it)
/weekcards [YYYY-MM-DD] — what each author decided that week
/settimes week=sun@21:45 | week=off — when it runs (or turn it off)"""


# How each user status reads in a list. '⏳' is a newcomer still waiting for a
# ✅ — they are registered but outside everything the bot sends.
STATUS_MARK = {"active": "🟢", "pending": "⏳", "inactive": "⚪️", "kicked": "🚫"}
LANG_MARK = {"ru": "🇷🇺", "en": "🇬🇧"}


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


HELP_CHUNK = 3800  # Telegram caps a message at 4096; leave room to breathe


def help_chunks(text: str, limit: int = HELP_CHUNK) -> list[str]:
    """Pack the blank-line-separated sections into as few messages as fit, so a
    split lands between sections instead of halfway through a command list. A
    single oversized section is hard-split as a last resort."""
    chunks: list[str] = []
    for section in text.split("\n\n"):
        while len(section) > limit:
            chunks.append(section[:limit])
            section = section[limit:]
        if chunks and len(chunks[-1]) + 2 + len(section) <= limit:
            chunks[-1] += "\n\n" + section
        else:
            chunks.append(section)
    return chunks


@admin_only
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The list outgrew Telegram's message limit once already (the proofing
    section tipped it to 4142 chars), so it always goes out in chunks."""
    for chunk in help_chunks(ADMIN_HELP):
        await update.message.reply_text(chunk)


@admin_only
async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = version.read_deploy_info()
    if not info:
        await update.message.reply_text(
            "No deploy info — probably running locally, not via update.sh."
        )
        return
    await update.message.reply_text(
        f"🏷 {version.describe(info)}\ndeployed {info.get('deployed_at', '?')}"
    )


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
        if day["collage_sent_at"]:
            lines.append("Collage: sent ✅")
        elif day["moderation_sent_at"]:
            lines.append("Collage: awaiting your review — /forcecollage to send")
        else:
            lines.append(f"Collage: after deadline {t['deadline_time']} + your review")
        ratings = jobs.rating_summary(today)
        if ratings:
            lines.append(f"Ratings: {ratings}")
        proof = _proof_state_line(today, day)
        if proof:
            lines.append(proof)
    active = len(db.active_user_ids())
    lines.append(f"Active users: {active}")
    waiting = len(db.pending_users())
    if waiting:
        lines.append(f"⏳ Waiting for your ✅: {waiting} — /pending")
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
        mark = STATUS_MARK.get(r["status"], "•")
        flag = LANG_MARK.get(r["lang"], "❔")
        uname = f"@{r['username']}" if r["username"] else ""
        joined = (r["joined_at"] or "")[:10]
        lines.append(
            f"{mark} {flag} {r['first_name']} {uname} (id {r['tg_id']}, {joined})"
        )
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
async def cmd_exportprompts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the unused queue as a plain 'EN | RU' .txt — no ids, so lines can be
    freely reordered in an editor and re-uploaded to become the new order."""
    rows = [r for r in db.list_prompts() if not r["used_on"]]
    if not rows:
        await update.message.reply_text(
            "Queue is empty — nothing to export. /addprompt <text> or upload a .txt."
        )
        return
    lines = [
        f"{r['text']} | {r['text_ru']}" if r["text_ru"] else r["text"]
        for r in rows
    ]
    buf = io.BytesIO(("\n".join(lines) + "\n").encode("utf-8"))
    buf.name = "prompt_queue.txt"
    await update.message.reply_document(
        document=buf,
        filename="prompt_queue.txt",
        caption=(
            f"{len(rows)} unused prompt(s), in queue order. Reorder/edit the lines, "
            "then upload this .txt back to replace the queue in the new order."
        ),
    )


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
        f"final = {db.get_setting('final_reminder_min')} min before deadline\n"
        f"deadline = {db.get_setting('deadline_time')}\n"
        f"preview = {db.get_setting('preview_time')} (admin heads-up: tomorrow's prompt)\n"
        f"week card = {_week_schedule_label()}\n\n"
        "Change: /settimes prompt=09:00 reminder=19:00 final=10 deadline=21:00 preview=21:10\n"
        "(any subset; applies within a minute, no restart needed)\n"
        "Week card: /settimes week=sun@21:45 (or week=off)\n"
        "Collage: sent manually after your review — /forcecollage."
    )


KEY_MAP = {
    "prompt": "prompt_time",
    "reminder": "reminder_time",
    "final": "final_reminder_min",
    "deadline": "deadline_time",
    "preview": "preview_time",
}

DOW_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _week_schedule_label() -> str:
    if db.get_setting("week_card_enabled") != "1":
        return "off"
    dow = DOW_NAMES[int(db.get_setting("week_card_dow"))]
    return f"{dow}@{db.get_setting('week_card_time')} (covers the 7 days ending the day before)"


def _parse_week_arg(val: str) -> dict[str, str]:
    """'off' | 'on' | 'sun@21:45' | '21:45' -> the settings to write.

    Its own shape because the week card is the one job that needs a weekday as
    well as a clock time; everything else in /settimes is HH:MM or minutes."""
    val = val.strip().lower()
    if val in ("off", "on"):
        return {"week_card_enabled": "1" if val == "on" else "0"}
    dow, sep, hhmm = val.partition("@")
    if not sep:
        dow, hhmm = "", val
    out = {"week_card_enabled": "1"}
    if dow:
        if dow not in DOW_NAMES:
            raise ValueError(f"unknown weekday «{dow}» (use {'/'.join(DOW_NAMES)})")
        out["week_card_dow"] = str(DOW_NAMES.index(dow))
    jobs.parse_hhmm(hhmm)  # validates format
    out["week_card_time"] = hhmm
    return out


@admin_only
async def cmd_settimes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: /settimes prompt=09:00 reminder=19:00 final=10 deadline=21:00 "
            "preview=21:10"
        )
        return
    new = {k: db.get_setting(v) for k, v in KEY_MAP.items()}
    week: dict[str, str] = {}
    try:
        for arg in context.args:
            key, _, val = arg.partition("=")
            if key == "week" and val:
                week.update(_parse_week_arg(val))
                continue
            if key not in KEY_MAP or not val:
                raise ValueError(f"unknown argument «{arg}»")
            if key == "final":
                if not (0 <= int(val) <= 60):
                    raise ValueError(f"{key} must be 0–60 minutes")
            else:
                jobs.parse_hhmm(val)  # validates format
            new[key] = val
        p, r, d = (jobs.parse_hhmm(new[k]) for k in ("prompt", "reminder", "deadline"))
        if not (p < r < d):
            raise ValueError("required order: prompt < reminder < deadline")
        if d > time(23, 50):
            raise ValueError(
                "deadline must be 23:50 or earlier (moderation runs after it)"
            )
        if jobs.parse_hhmm(new["preview"]) < d:
            raise ValueError("preview must be at or after the deadline")
        final_minute = d.hour * 60 + d.minute - int(new["final"])
        if final_minute <= r.hour * 60 + r.minute:
            raise ValueError(
                "final reminder (deadline − final min) must fall after the reminder time"
            )
    except ValueError as e:
        await update.message.reply_text(f"Not saved: {e}")
        return
    for key, val in new.items():
        db.set_setting(KEY_MAP[key], val)
    for key, val in week.items():
        db.set_setting(key, val)
    await update.message.reply_text(
        f"Saved ✅ prompt {new['prompt']}, reminder {new['reminder']}, "
        f"final −{new['final']} min, deadline {new['deadline']}, "
        f"preview {new['preview']}, week card {_week_schedule_label()}."
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


# --- collage proofing ---------------------------------------------------------

def _proof_state_line(date: str, day) -> str | None:
    """Where tonight's delegated check stands, as one line for /status."""
    asks = db.proof_asks_for(date)
    if not asks and not day["proof_result"]:
        return None
    counts = db.proof_counts(date)
    tally = f"{len(asks)} asked, 👍 {counts.get('approve', 0)}, 🚫 {counts.get('ban', 0)}"
    state = {
        "approved": "approved ✅",
        "held": "on hold — your call ⏸",
        "exhausted": "nobody answered — your call",
        "forced": "you sent it yourself ✅",
    }.get(day["proof_result"], f"round {day['proof_round']}, waiting")
    return f"Proofing: {state} ({tally})"


async def _bulk_proofers(update: Update, action: str, targets: list[str]) -> None:
    """Flag many people at once. Idempotent, unlike /proofer's toggle — pasting
    thirty ids twice must not silently undo the first paste."""
    if not targets:
        await update.message.reply_text(
            f"Usage: /proofers {action} <id|@username> … (space-separated)"
        )
        return
    on = action == "add"
    changed, already, missing = [], [], []
    for arg in targets:
        user = _resolve_user(arg)
        if user is None:
            missing.append(arg)
        elif bool(user["proofer"]) == on:
            already.append(user["first_name"])
        else:
            db.set_proofer(user["tg_id"], on)
            changed.append(user["first_name"])
    verb = "Added" if on else "Removed"
    lines = [f"👀 {verb} {len(changed)}" + (f": {', '.join(changed)}" if changed else "")]
    if already:
        lines.append(
            f"Already {'on' if on else 'off'} the list ({len(already)}): "
            + ", ".join(already)
        )
    if missing:
        lines.append(
            f"⚠️ Not found ({len(missing)}): {', '.join(missing)} — /users for the ids"
        )
    lines.append(f"\nThe list is now {len(db.proofer_ids())} active proofer(s).")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def cmd_proofers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args and context.args[0].lower() in ("add", "remove"):
        await _bulk_proofers(update, context.args[0].lower(), context.args[1:])
        return
    rows = db.list_proofers()
    lines = ["👀 Collage proofers — they see the collage before anyone else."]
    if not rows:
        lines.append(
            "\nNobody yet, so the collage still waits for you as before.\n"
            "Add someone with /proofer <id|@username>."
        )
    for r in rows:
        mark = STATUS_MARK.get(r["status"], "•")
        uname = f"@{r['username']}" if r["username"] else ""
        last = f"last asked {r['last_proofed_on']}" if r["last_proofed_on"] else "never asked"
        lines.append(f"{mark} {r['first_name']} {uname} (id {r['tg_id']}) — {last}")
    lines.append(
        "\n/proofers add <id|@username> … — add several at once (idempotent)"
        "\n/proofers remove <id|@username> … — drop several"
        "\n/proofer <id|@username> — toggle one"
        "\n/proofing — settings and tonight's state"
    )
    await update.message.reply_text("\n".join(lines))


@admin_only
async def cmd_proofer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle someone's proofer flag, silently — building the trusted list
    doesn't ping anyone. The nightly ask carries its own instructions, so the
    first time someone hears about this is a collage they can act on."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /proofer <id|@username> — toggles them on or off "
            "(/proofers to see the list)"
        )
        return
    user = _resolve_user(context.args[0])
    if user is None:
        await update.message.reply_text("No such user (try /users for the ids).")
        return
    on = not user["proofer"]
    db.set_proofer(user["tg_id"], on)
    name = f"{user['first_name']} (id {user['tg_id']})"
    state = "is now a proofer" if on else "is no longer a proofer"
    await update.message.reply_text(
        f"👀 {name} {state} — {len(db.proofer_ids())} on the list."
    )


PROOF_KEYS = {
    "batch": ("proof_batch", 1, 10),
    "round": ("proof_round_min", 1, 240),
    "quorum": ("proof_ban_quorum", 1, 10),
}


@admin_only
async def cmd_proofing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show or change the proofing knobs (and switch the whole thing off)."""
    today = jobs.now_local().date().isoformat()
    args = [a.lower() for a in context.args]
    if args and args[0] in ("on", "off"):
        db.set_setting("proof_enabled", "1" if args[0] == "on" else "0")
        await update.message.reply_text(
            f"Proofing {args[0]} ✅"
            + ("" if args[0] == "on" else " — the collage waits for you again.")
        )
        return
    if args:
        new = {}
        try:
            for arg in args:
                key, _, val = arg.partition("=")
                if key not in PROOF_KEYS or not val:
                    raise ValueError(f"unknown argument «{arg}»")
                setting, lo, hi = PROOF_KEYS[key]
                if not (lo <= int(val) <= hi):
                    raise ValueError(f"{key} must be {lo}–{hi}")
                new[setting] = val
        except ValueError as e:
            await update.message.reply_text(f"Not saved: {e}")
            return
        for setting, val in new.items():
            db.set_setting(setting, val)

    cfg = jobs.proof_cfg()
    n = len(db.proofer_ids())
    lines = [
        f"👀 Proofing: {'on' if cfg['enabled'] else 'off'} — {n} active proofer(s)",
        f"batch = {cfg['batch']} people asked per round",
        f"round = {cfg['round_min']} min of silence before the next batch",
        f"quorum = {cfg['quorum']} bans park the day on you",
        "",
        "Change: /proofing batch=3 round=10 quorum=2",
        "/proofing off — back to the admin-only flow",
        "/proofers — who's on the list",
    ]
    day = db.get_day(today)
    if day:
        state = _proof_state_line(today, day)
        if state:
            lines.append("")
            lines.append(f"Today: {state}")
            lines += jobs.proof_hold_lines(today)
    await update.message.reply_text("\n".join(lines))


# --- story of the day --------------------------------------------------------

def _parse_date_arg(arg: str | None) -> str | None:
    """Validate an ISO date; None/'' -> today, bad input -> None."""
    if not arg:
        return jobs.now_local().date().isoformat()
    try:
        return date_cls.fromisoformat(arg).isoformat()
    except ValueError:
        return None


def _numbered_photos(date: str) -> list[str]:
    """The contact-sheet numbering for a date (same order as /exclude N)."""
    photos = db.photos_for(date, include_excluded=True)
    lines = []
    for i, p in enumerate(photos, 1):
        u = db.get_user(p["tg_id"])
        name = u["first_name"] if u else "?"
        uname = f" @{u['username']}" if u and u["username"] else ""
        exc = " ✂️excluded" if p["excluded"] else ""
        lines.append(f"{i} — {name}{uname} (id {p['tg_id']}){exc}")
    return lines


@admin_only
async def cmd_photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reprint the numbered author list for any date, so you know which N to
    pass to /askstory (the numbers match the deadline contact sheet)."""
    msg = update.effective_message
    date = _parse_date_arg(context.args[0] if context.args else None)
    if date is None:
        await msg.reply_text("Usage: /photos [YYYY-MM-DD] (default: today)")
        return
    lines = _numbered_photos(date)
    if not lines:
        await msg.reply_text(f"No submissions on {date}.")
        return
    header = f"📷 {date} — {len(lines)} photo(s):"
    footer = f"\n/askstory {date} N — ask author N why they chose their photo"
    await msg.reply_text(header + "\n" + "\n".join(lines) + "\n" + footer)


@admin_only
async def cmd_knocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/knocks [date] — the night's tally. Deliberately manual: you read the
    result and decide whether it's a winner worth asking, rather than the bot
    asking on its own.

    With no date it reports every day that currently has knocking on it, which
    for most of the day means *yesterday's* collage: today's doesn't open until
    tonight's collage is published, so defaulting to today just showed an empty
    board while the live vote was still running.
    """
    msg = update.effective_message
    if context.args:
        date = _parse_date_arg(context.args[0])
        if date is None:
            await msg.reply_text("Usage: /knocks [YYYY-MM-DD] (default: live days)")
            return
        dates = [date]
    else:
        dates = _live_knock_days()

    for date in dates:
        await _knock_report(update, context, date)


def _live_knock_days() -> list[str]:
    """Yesterday and today — both, because for most of the day they're at
    different stages: last night's vote is still running while today's photos
    are only coming in. A date is skipped only if nothing happened on it at
    all."""
    today = jobs.now_local().date()
    days = [d.isoformat() for d in (today - timedelta(days=1), today)]
    live = [d for d in days if db.get_day(d) or db.knock_tally(d)]
    return live or [today.isoformat()]


async def _knock_report(
    update: Update, context: ContextTypes.DEFAULT_TYPE, date: str
) -> None:
    msg = update.effective_message
    tally = db.knock_tally(date)
    photos = db.photos_for(date, include_excluded=True)
    number_of = {p["tg_id"]: i for i, p in enumerate(photos, 1)}
    voters = len(db.photos_for(date))
    day = db.get_day(date)
    if not day or not day["collage_sent_at"]:
        state = "not open yet"  # knocking starts when the collage is published
    else:
        state = "open" if jobs.knock_open_for(date) else "closed"

    if not tally:
        if state == "not open yet":
            n_in = len(db.photos_for(date))
            await msg.reply_text(
                f"🚪 {date}: knocking opens when the collage goes out "
                f"({n_in} photo(s) in so far)."
            )
        else:
            await msg.reply_text(f"🚪 {date}: nobody knocked yet ({state}).")
        return

    lines = []
    for rank, row in enumerate(tally, 1):
        u = db.get_user(row["target_id"])
        name = u["first_name"] if u else str(row["target_id"])
        n = number_of.get(row["target_id"], "?")
        lines.append(f"{rank}. {row['n']} × 🚪 — #{n} {html.escape(name)}")

    top = tally[0]
    tied = [r for r in tally if r["n"] == top["n"]]
    verdict = (
        f"\n⚖️ {len(tied)} photos tied on {top['n']} — earliest to get there is "
        f"#{number_of.get(top['target_id'], '?')}."
        if len(tied) > 1
        else ""
    )
    # The ask is left as a copyable stem rather than a finished command: which
    # door to open is your call, and on a tie the top of the list isn't
    # automatically the one worth asking.
    await msg.reply_text(
        f"🚪 {date} — {sum(r['n'] for r in tally)} knocks from {voters} players "
        f"({state}):\n" + "\n".join(lines) + verdict + "\n\n"
        f"Any other door — copy this, then add the number:\n"
        f"<pre>/askstory {date} </pre>",
        parse_mode="HTML",
    )
    # ...and the leaders as pictures, because a number tells you nothing about
    # whether the shot has a story in it.
    await send_candidates(
        update, context, date, [r["target_id"] for r in tied], 0
    )


def _candidate_keyboard(date: str, pos: int, total: int) -> InlineKeyboardMarkup:
    row = []
    if total > 1:
        row.append(
            InlineKeyboardButton("‹", callback_data=f"kw:go:{date}:{(pos - 1) % total}")
        )
    row.append(InlineKeyboardButton("💬 Ask this one", callback_data=f"kw:ask:{date}:{pos}"))
    if total > 1:
        row.append(
            InlineKeyboardButton("›", callback_data=f"kw:go:{date}:{(pos + 1) % total}")
        )
    return InlineKeyboardMarkup([row])


def _candidates(date: str) -> list[int]:
    """The tied leaders, in tally order. Recomputed on every tap rather than
    stashed, so a knock landing while you deliberate is reflected instead of
    leaving you choosing from a stale shortlist."""
    tally = db.knock_tally(date)
    if not tally:
        return []
    best = tally[0]["n"]
    return [r["target_id"] for r in tally if r["n"] == best]


async def send_candidates(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    date: str,
    candidates: list[int],
    pos: int,
    message_id: int | None = None,
) -> None:
    """Show a leader as a picture with their name — one card, flipped in place
    when several are tied. Admin-side, so it names names: this is the view the
    reveal is decided from."""
    if not candidates:
        return
    pos %= len(candidates)
    target = candidates[pos]
    photo = db.get_photo(date, target)
    if photo is None:
        return
    u = db.get_user(target)
    name = u["first_name"] if u else str(target)
    photos = db.photos_for(date, include_excluded=True)
    number = next(
        (i for i, p in enumerate(photos, 1) if p["tg_id"] == target), "?"
    )
    knocks = len(db.knockers_for(date, target))
    caption = f"#{number} · {name} · {knocks} × 🚪"
    if len(candidates) > 1:
        caption += f"\ntied leader {pos + 1} of {len(candidates)}"
    keyboard = _candidate_keyboard(date, pos, len(candidates))

    chat = update.effective_chat.id
    handle = photo["file_id"]
    media = handle or open(photo["file_path"], "rb")
    try:
        if message_id is not None:
            await context.bot.edit_message_media(
                chat_id=chat,
                message_id=message_id,
                media=InputMediaPhoto(media, caption=caption),
                reply_markup=keyboard,
            )
        else:
            await context.bot.send_photo(
                chat, media, caption=caption, reply_markup=keyboard
            )
    finally:
        if handle is None:
            media.close()


@admin_only
async def on_knock_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """‹ › and 💬 under the candidate card from /knocks."""
    query = update.callback_query
    _, kind, date, pos = query.data.split(":")
    candidates = _candidates(date)
    if not candidates:
        await query.answer("No knocks on that day any more.")
        return
    pos = int(pos) % len(candidates)

    if kind == "go":
        await query.answer()
        await send_candidates(
            update, context, date, candidates, pos, query.message.message_id
        )
        return

    photo = db.get_photo(date, candidates[pos])
    if photo is None:
        await query.answer("That photo is gone.")
        return
    await query.answer("Asking…")
    # Retire the buttons first: _send_story_ask replies into this chat, and a
    # second tap would DM the author the same question twice.
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        log.debug("candidate keyboard clear failed for %s", date)
    await _send_story_ask(update, context, date, photo)


async def _send_story_ask(
    update: Update, context: ContextTypes.DEFAULT_TYPE, date: str, photo
) -> None:
    """DM the author their own photo + that day's prompt and ask why they chose
    it, then record the pending story."""
    msg = update.effective_message
    author_id = photo["tg_id"]
    u = db.get_user(author_id)
    name = u["first_name"] if u else str(author_id)
    lang = db.get_user_lang(author_id)
    day = db.get_day(date)
    prompt = db.get_prompt(day["prompt_id"]) if day and day["prompt_id"] else None
    ptext = jobs.prompt_text(prompt, lang) if prompt else "—"
    try:
        with open(photo["file_path"], "rb") as f:
            ask = await context.bot.send_photo(
                author_id, f, caption=t(lang, "STORY_ASK", prompt=ptext)
            )
    except Forbidden:
        db.set_user_status(author_id, "inactive")
        await msg.reply_text(f"{name} (id {author_id}) has blocked the bot — can't ask.")
        return
    except Exception as e:
        await msg.reply_text(f"Couldn't ask {name} (id {author_id}): {e}")
        return

    sid = db.add_story(date, author_id, ask.message_id)
    await msg.reply_text(
        f"💬 Asked {name} about their photo from {date}.\n"
        f"Story #{sid} is waiting for their reply — /stories to check."
    )


@admin_only
async def cmd_askstory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/askstory [date] N — DM that photo's author their own shot and ask why
    they chose it. /askstory random picks a past photo for you. The reply is
    captured for review, then /publishstory."""
    msg = update.effective_message
    args = context.args
    if not args:
        await msg.reply_text(
            "Usage: /askstory [YYYY-MM-DD] N   (N from /photos [date])\n"
            "       /askstory random   — surprise me with a past photo"
        )
        return
    # /askstory random — pick a random past submission and ask its author.
    if len(args) == 1 and args[0].lower() == "random":
        candidates = [(d, p) for d in db.photo_dates() for p in db.photos_for(d)]
        if not candidates:
            await msg.reply_text("No past submissions to pick from yet.")
            return
        date, photo = random.choice(candidates)
        await _send_story_ask(update, context, date, photo)
        return
    # A lone date just shows the numbered list; a lone number means today's N.
    if len(args) == 1 and "-" in args[0] and _parse_date_arg(args[0]):
        await cmd_photos(update, context)
        return
    if len(args) == 1:
        date, nstr = jobs.now_local().date().isoformat(), args[0]
    else:
        date, nstr = _parse_date_arg(args[0]), args[1]
    if date is None:
        await msg.reply_text("Bad date. Usage: /askstory [YYYY-MM-DD] N")
        return

    photo, photos = _photo_by_number(date, nstr)
    if photo is None:
        await msg.reply_text(
            f"No photo #{nstr} on {date} (there are {len(photos)}). Try /photos {date}."
        )
        return
    await _send_story_ask(update, context, date, photo)


@admin_only
async def cmd_stories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = db.open_stories()
    if not rows:
        await update.effective_message.reply_text(
            "No story requests in progress.\n"
            "Ask for one with /askstory [date] N (numbers from /photos)."
        )
        return
    blocks = []
    for s in rows:
        u = db.get_user(s["tg_id"])
        name = u["first_name"] if u else str(s["tg_id"])
        if s["status"] == "asked":
            blocks.append(
                f"⏳ #{s['id']} — {name}, photo from {s['date']}\n"
                "Asked; waiting for their reply.\n"
                f"/editstory {s['id']} <EN> | <RU> — write it yourself · "
                f"/dismissstory {s['id']} — discard"
            )
            continue
        blocks.append(
            f"💬 #{s['id']} — {name}, photo from {s['date']}:\n«{s['text']}»"
            + (f"\n🇷🇺 «{s['text_ru']}»" if s["text_ru"] else "")
            + f"\n/publishstory {s['id']} — send to everyone "
            f"(add ' day' for that day's submitters only)\n"
            f"/editstory {s['id']} <EN> | <RU> — edit / translate · "
            f"/dismissstory {s['id']} — discard"
        )
    await update.effective_message.reply_text("\n\n".join(blocks))


@admin_only
async def cmd_editstory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/editstory <id> <text> — replace a story's text (also lets you author one
    by hand for an author who hasn't replied). Takes the 'EN | RU' pipe format,
    so you can pair the author's original with your translation; each reader
    then gets the half in their language."""
    msg = update.effective_message
    parts = (msg.text or "").split(None, 2)
    if len(parts) < 3 or not parts[1].isdigit():
        await msg.reply_text(
            "Usage: /editstory <id> <new story text>\n"
            "       /editstory <id> <English> | <Russian>"
        )
        return
    sid = int(parts[1])
    en, ru = parse_prompt_line(parts[2].strip())
    if not db.set_story_text(sid, en, ru):
        await msg.reply_text(f"No story #{sid}.")
        return
    s = db.get_story(sid)
    u = db.get_user(s["tg_id"])
    name = u["first_name"] if u else str(s["tg_id"])
    await msg.reply_text(
        f"✏️ Story #{sid} ({name}, {s['date']}) updated:\n«{s['text']}»"
        + (f"\n🇷🇺 «{s['text_ru']}»" if s["text_ru"] else "")
        + f"\n/publishstory {sid} to send it."
    )


def story_recipients(date: str, scope: str) -> list[int]:
    """Who gets a published story: everyone in the game, or — with the 'day'
    scope — only that day's submitters, the audience the collage went to.
    Admins are always included."""
    base = db.submitter_ids(date) if scope == "day" else db.active_user_ids()
    return list(dict.fromkeys(base + list(config.ADMIN_IDS)))


@admin_only
async def cmd_publishstory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the photo + the author's story to every active user, or just that
    day's submitters with /publishstory <id> day (admins always included).
    This is where the author's name is revealed."""
    msg = update.effective_message
    usage = (
        "Usage: /publishstory <id>       — everyone in the game\n"
        "       /publishstory <id> day   — only that day's submitters"
    )
    if not context.args:
        await msg.reply_text(f"{usage}\n(ids from /stories)")
        return
    try:
        sid = int(context.args[0])
    except ValueError:
        await msg.reply_text(usage)
        return
    scope = context.args[1].lower() if len(context.args) > 1 else "all"
    if scope not in ("all", "day"):
        await msg.reply_text(f"Unknown audience {context.args[1]!r}.\n{usage}")
        return
    s = db.get_story(sid)
    if s is None:
        await msg.reply_text(f"No story #{sid}.")
        return
    if s["status"] == "published":
        await msg.reply_text(f"Story #{sid} was already published.")
        return
    if not s["text"]:
        await msg.reply_text(f"Story #{sid} has no reply yet — nothing to publish.")
        return
    photo = next(
        (
            p
            for p in db.photos_for(s["date"], include_excluded=True)
            if p["tg_id"] == s["tg_id"]
        ),
        None,
    )
    if photo is None:
        await msg.reply_text(
            f"The photo for story #{sid} is gone from {s['date']} — can't publish."
        )
        return
    author = db.get_user(s["tg_id"])
    name = author["first_name"] if author else str(s["tg_id"])
    day = db.get_day(s["date"])
    prompt = db.get_prompt(day["prompt_id"]) if day and day["prompt_id"] else None
    recipients = story_recipients(s["date"], scope)
    sent = failed = 0
    for uid in recipients:
        lang = db.get_user_lang(uid)
        ptext = jobs.prompt_text(prompt, lang) if prompt else "—"
        caption = t(
            lang, "STORY_PUBLISH", name=name, text=jobs.story_text(s, lang),
            prompt=ptext, date=s["date"],
        )
        try:
            with open(photo["file_path"], "rb") as f:
                out = await context.bot.send_photo(
                    uid, f, caption=caption, reply_markup=jobs.story_keyboard(sid)
                )
            # remembered so one reader's ❤️ refreshes the tally on every copy
            db.add_story_message(sid, uid, out.message_id)
            sent += 1
        except Forbidden:
            db.set_user_status(uid, "inactive")
            failed += 1
        except Exception:
            log.exception("publishstory %s to %s failed", sid, uid)
            failed += 1
    db.set_story_status(sid, "published")
    who = f"{s['date']}'s submitters" if scope == "day" else "everyone in the game"
    note = f"💬 Story #{sid} published to {who} — sent {sent}, failed {failed}."
    note += (
        "\nRussian readers got the RU version."
        if s["text_ru"]
        else f"\nEveryone got the same text — /editstory {sid} <EN> | <RU> next time "
        "to give each language its own."
    )
    await msg.reply_text(note)


@admin_only
async def cmd_dismissstory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not context.args:
        await msg.reply_text("Usage: /dismissstory <id>")
        return
    try:
        sid = int(context.args[0])
    except ValueError:
        await msg.reply_text("Usage: /dismissstory <id>")
        return
    if not db.set_story_status(sid, "dismissed"):
        await msg.reply_text(f"No story #{sid}.")
        return
    await msg.reply_text(f"Story #{sid} dismissed.")


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
    date = context.args[0] if context.args else jobs.now_local().date().isoformat()
    try:
        date_cls.fromisoformat(date)
    except ValueError:
        await update.message.reply_text(
            "Usage: /forcecollage [YYYY-MM-DD] (default: today)"
        )
        return
    day = db.get_day(date)
    if day is None or not day["prompt_sent_at"]:
        await update.message.reply_text(
            f"No prompt was sent on {date} — nothing to collect."
        )
        return
    if day["collage_sent_at"]:
        await update.message.reply_text(f"Collage for {date} was already sent.")
        return
    result = await jobs.send_collage(context, date)
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
async def cmd_delcollage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a sent collage from every recipient's chat (Telegram only allows
    a bot to delete its own messages within 48 h), then reset the day so the
    moderation commands and /forcecollage work again."""
    date = context.args[0] if context.args else jobs.now_local().date().isoformat()
    try:
        date_cls.fromisoformat(date)
    except ValueError:
        await update.message.reply_text("Usage: /delcollage [YYYY-MM-DD] (default: today)")
        return
    day = db.get_day(date)
    if day is None or not day["collage_sent_at"]:
        await update.message.reply_text(f"No sent collage recorded for {date}.")
        return
    msgs = db.collage_messages_for(date)
    deleted = failed = 0
    for m in msgs:
        try:
            await context.bot.delete_message(m["tg_id"], m["message_id"])
            deleted += 1
        except Exception:
            log.exception(
                "delete collage message for %s (%s) failed", m["tg_id"], date
            )
            failed += 1
    db.delete_collage_messages(date)
    db.delete_ratings(date)
    db.set_day_field(date, "collage_sent_at", None)
    lines = [f"🗑 {date}: deleted the collage in {deleted} chat(s)."]
    if failed:
        lines.append(
            f"⚠️ {failed} could not be deleted — older than Telegram's 48 h "
            "limit or the chat is gone; those copies stay visible."
        )
    lines.append(
        f"Ratings cleared, day reset — fix things, then /forcecollage {date} "
        "to re-send."
    )
    await update.message.reply_text("\n".join(lines))


@admin_only
async def cmd_skipday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = jobs.now_local().date().isoformat()
    db.set_day_field(today, "skipped", 1)
    await update.message.reply_text(
        "Today is cancelled: no reminder, no collage. Photos already stored stay on disk."
    )


@admin_only
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # split off just the "/broadcast" token so line breaks in the rest of the
    # message survive (context.args + " ".join would collapse them)
    parts = (update.message.text or "").split(None, 1)
    body = parts[1].strip() if len(parts) > 1 else ""
    if not body:
        await update.message.reply_text(
            "Usage: /broadcast <text>   (or  <English> | <Russian>)\n"
            "Russian users see the RU half; English text is the fallback."
        )
        return
    en, ru = parse_prompt_line(body)

    def text_for(uid: int) -> str:
        return ru if (ru and db.get_user_lang(uid) == "ru") else en

    sent, failed = await jobs.send_per_user(context, db.active_user_ids(), text_for)
    note = f"Broadcast: sent {sent}, failed {failed}.\n«{en}»" + (
        f"\n🇷🇺 «{ru}»" if ru else ""
    )
    await update.message.reply_text(note)


def _parse_poll_id(arg: str) -> int | None:
    try:
        return int(arg)
    except (TypeError, ValueError):
        return None


@admin_only
async def cmd_poll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create and broadcast a custom 👍/👎 poll to all active users, with a live
    shared tally. Supports the 'English | Russian' pipe format."""
    parts = (update.message.text or "").split(None, 1)
    body = parts[1].strip() if len(parts) > 1 else ""
    if not body:
        await update.message.reply_text(
            "Usage: /poll <question>   (or  <English> | <Russian>)\n"
            "Sends a 👍/👎 poll to all active users with a live tally.\n"
            "Manage with /polls, /pollresults <id>, /polledit <id> …, "
            "/pollclose <id>."
        )
        return
    en, ru = parse_prompt_line(body)
    pid = db.create_poll(en, ru, update.effective_user.id)
    poll = db.get_poll(pid)
    sent, failed = await jobs.send_poll(context, poll, db.active_user_ids())
    note = (
        f"📊 Poll #{pid} sent to {sent} user(s) (failed: {failed}).\n«{en}»"
        + (f"\n🇷🇺 «{ru}»" if ru else "")
        + f"\n\nTallies update live. /pollresults {pid} for details, "
        f"/pollclose {pid} to end voting."
    )
    await update.message.reply_text(note)


@admin_only
async def cmd_polls(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    polls = db.list_polls()
    if not polls:
        await update.message.reply_text(
            "No polls yet. Create one with /poll <question>."
        )
        return
    lines = ["📊 Polls (newest first):"]
    for p in polls:
        c = db.poll_counts(p["id"])
        flag = "🟢" if p["status"] == "open" else "🔒"
        q = p["question"] if len(p["question"]) <= 60 else p["question"][:57] + "…"
        lines.append(f"{flag} #{p['id']}  👍{c.get('up', 0)} 👎{c.get('down', 0)}  «{q}»")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def cmd_pollresults(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pid = _parse_poll_id(context.args[0]) if context.args else None
    if pid is None:
        await update.message.reply_text("Usage: /pollresults <id>")
        return
    poll = db.get_poll(pid)
    if poll is None:
        await update.message.reply_text(f"No poll #{pid}.")
        return
    counts = db.poll_counts(pid)
    up, down = counts.get("up", 0), counts.get("down", 0)
    total = up + down
    status = "open" if poll["status"] == "open" else "closed"
    header = f"📊 Poll #{pid} ({status})\n«{poll['question']}»\n"
    if total == 0:
        await update.message.reply_text(header + "\nNo votes yet.")
        return
    pct = round(100 * up / total)
    lines = [header, f"{total} vote(s) · {pct}% 👍", f"👍 {up} · 👎 {down}", ""]
    for r in db.poll_votes_detail(pid):
        name = r["first_name"] or "?"
        uname = f" @{r['username']}" if r["username"] else ""
        lines.append(f"{jobs.POLL_EMOJI.get(r['value'], '?')} {name}{uname}")
    text = "\n".join(lines)
    for start in range(0, len(text), 3800):
        await update.message.reply_text(text[start : start + 3800])


@admin_only
async def cmd_polledit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Edit a poll's question and rewrite every copy that's already been sent."""
    parts = (update.message.text or "").split(None, 2)
    pid = _parse_poll_id(parts[1]) if len(parts) >= 2 else None
    if pid is None or len(parts) < 3:
        await update.message.reply_text(
            "Usage: /polledit <id> <new question>   (| Russian optional)"
        )
        return
    poll = db.get_poll(pid)
    if poll is None:
        await update.message.reply_text(f"No poll #{pid}.")
        return
    en, ru = parse_prompt_line(parts[2].strip())
    db.update_poll_question(pid, en, ru)
    poll = db.get_poll(pid)
    keyboard = jobs.poll_keyboard(pid, closed=poll["status"] != "open")
    edited = 0
    for row in db.poll_messages_for(pid):
        try:
            await context.bot.edit_message_text(
                chat_id=row["tg_id"],
                message_id=row["message_id"],
                text=jobs.poll_question(poll, db.get_user_lang(row["tg_id"])),
                reply_markup=keyboard,
            )
            edited += 1
        except Exception:
            log.debug("poll edit failed for %s/%s", row["tg_id"], pid)
    await update.message.reply_text(f"✏️ Poll #{pid} updated in {edited} chat(s).")


@admin_only
async def cmd_pollclose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop accepting votes: taps stop registering, final tallies stay visible."""
    pid = _parse_poll_id(context.args[0]) if context.args else None
    if pid is None:
        await update.message.reply_text("Usage: /pollclose <id>")
        return
    poll = db.get_poll(pid)
    if poll is None:
        await update.message.reply_text(f"No poll #{pid}.")
        return
    db.set_poll_status(pid, "closed")
    keyboard = jobs.poll_keyboard(pid, closed=True)
    for row in db.poll_messages_for(pid):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=row["tg_id"],
                message_id=row["message_id"],
                reply_markup=keyboard,
            )
        except Exception:
            log.debug("poll close update failed for %s/%s", row["tg_id"], pid)
    c = db.poll_counts(pid)
    await update.message.reply_text(
        f"🔒 Poll #{pid} closed. Final: 👍 {c.get('up', 0)} · 👎 {c.get('down', 0)}."
    )


# --- new-user verification ----------------------------------------------------

@admin_only
async def on_verify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """✅ / 🚫 under a newcomer's card. ✅ lets them into the game and greets
    them there and then; 🚫 closes the door. Both are one tap — /kick and
    /unkick undo either, and the edited card says so."""
    query = update.callback_query
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, uid_s, action = parts
    uid = int(uid_s)
    row = db.get_user(uid)
    if row is None:
        await query.answer("No such user any more.")
        await query.edit_message_reply_markup(None)
        return

    who = f"{row['first_name']} (id {uid})"
    if row["status"] != "pending":
        # Another admin (or a /kick) already settled this; converge this copy.
        await query.answer("Already handled.")
        await query.edit_message_text(f"👤 {who} — already {row['status']}.")
        return

    if action == "ok":
        db.set_user_status(uid, "active")
        await query.answer("Approved ✅")
        await query.edit_message_text(f"✅ {who} is in — /kick to undo.")
        try:
            await usr.send_entry_point(context, uid, row["first_name"])
        except Exception:
            # They may have blocked the bot while waiting — they're still in.
            log.exception("welcome to freshly approved %s failed", uid)
            await update.effective_message.reply_text(
                f"⚠️ Couldn't message {who} — approved anyway."
            )
        return

    if action == "no":
        db.set_user_status(uid, "kicked")
        await query.answer("Rejected 🚫")
        await query.edit_message_text(f"🚫 {who} turned away — /unkick to undo.")
        try:
            await context.bot.send_message(uid, t(db.get_user_lang(uid), "KICKED"))
        except Exception:
            log.debug("rejection notice to %s failed", uid)
        return

    await query.answer()


@admin_only
async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The waiting list with its buttons again — for when the original card has
    scrolled away."""
    rows = db.pending_users()
    if not rows:
        await update.message.reply_text(
            "Nobody waiting ✅ Every newcomer so far has been let in or turned away."
        )
        return
    await update.message.reply_text(f"⏳ {len(rows)} waiting for your ✅:")
    for r in rows:
        await update.message.reply_text(
            jobs.verify_card(r), reply_markup=jobs.verify_keyboard(r["tg_id"])
        )


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


def _who(tg_id: int) -> str:
    u = db.get_user(tg_id)
    if u is None:
        return str(tg_id)
    return f"{u['first_name']}" + (f" @{u['username']}" if u["username"] else "")


def _week_end_arg(args: list[str]) -> str | None:
    """Optional trailing YYYY-MM-DD; defaults to yesterday (the window the
    scheduled job would be covering). None means the argument was malformed."""
    if not args:
        return jobs.week_end_for(jobs.now_local().date())
    try:
        return date_cls.fromisoformat(args[0]).isoformat()
    except ValueError:
        return None


@admin_only
async def cmd_weekcard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/weekcard — dry run; `send`/`me` actually offer the cards; `reset` clears
    the record of a week so it can be offered again."""
    usage = (
        "Usage: /weekcard                     — who qualifies now (sends nothing)\n"
        "       /weekcard send [YYYY-MM-DD]   — offer the cards\n"
        "       /weekcard me [YYYY-MM-DD]     — offer only your own\n"
        "       /weekcard reset [YYYY-MM-DD]  — forget that week, so it can run again"
    )
    args = list(context.args)
    mode = "show"
    if args and args[0].lower() in ("send", "me", "reset"):
        mode = args.pop(0).lower()
    week_end = _week_end_arg(args)
    if week_end is None:
        await update.message.reply_text(usage)
        return

    dates = db.week_days(week_end, config.WEEK_SPAN_DAYS)
    if mode == "reset":
        n = db.delete_week_cards(week_end)
        if db.get_setting("week_card_last") == week_end:
            db.set_setting("week_card_last", "")
        await update.message.reply_text(
            f"Cleared {n} record(s) for the week ending {week_end}."
        )
        return

    if mode == "show":
        if not dates:
            await update.message.reply_text(f"No collage days in the week ending {week_end}.")
            return
        _, board, leader = jobs.week_cast(week_end)
        lines = [
            f"🗓 Week ending {week_end} — {len(dates)} collage day(s): "
            f"{dates[0]} … {dates[-1]}",
        ]
        if len(dates) < config.WEEK_MIN_DAYS:
            lines.append(
                f"Too few days ({len(dates)} < {config.WEEK_MIN_DAYS}) — the job would skip this week."
            )
        if not board:
            lines.append(f"Nobody reached {config.WEEK_MIN_PHOTOS} days — no cards.")
        for r in board:
            card = db.get_week_card(week_end, r["tg_id"])
            crown = "👑 " if leader and r["tg_id"] == leader["tg_id"] else "• "
            mark = f" — {card['status']}" if card else ""
            lines.append(
                f"{crown}{_who(r['tg_id'])} — {r['days']}/{len(dates)}, "
                f"streak {r['streak']}🔥{mark}"
            )
        if leader:
            tied = jobs.tied_leaders(board)
            if len(tied) > 1:
                last = db.last_crowned(week_end)
                who = ", ".join(
                    f"{_who(r['tg_id'])} (last 👑 {last.get(r['tg_id'], 'never')})"
                    for r in tied
                )
                lines.append(f"\n{len(tied)} tied on {leader['streak']}🔥: {who}")
                lines.append("👑 rotates to whoever was crowned least recently.")
            lines.append("👑 is the only one asked to share; the rest just get theirs.")
        # The bookmark is what misfired once; show it, so "will it run?" is a
        # question you can answer by looking rather than by waiting.
        book = db.get_setting("week_card_last")
        due = jobs.week_end_for(jobs.last_week_run(jobs.now_local()))
        lines.append(
            f"\nSchedule: {_week_schedule_label()}"
            f"\nBookmark: {book or '—'} · last scheduled window {due} "
            f"({'already handled' if book >= due else 'DUE, runs on the next tick'})"
        )
        lines.append("\n/weekcard send — send these now")
        await update.message.reply_text("\n".join(lines))
        return

    only = update.effective_user.id if mode == "me" else None
    result = await jobs.offer_week_cards(
        context, week_end, only=only, announce=False
    )
    await update.message.reply_text(result)


@admin_only
async def cmd_weekcards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """What each author decided about their own card that week."""
    week_end = _week_end_arg(list(context.args))
    if week_end is None:
        await update.message.reply_text("Usage: /weekcards [YYYY-MM-DD]")
        return
    rows = db.week_cards_for(week_end)
    if not rows:
        await update.message.reply_text(f"No week cards for the week ending {week_end}.")
        return
    mark = {
        "offered": "👑 asked to share, hasn't decided",
        "shared": "👑 🖼 shared it",
        "kept": "👑 🤫 kept it",
        "gift": "🎁 card sent, nothing to decide",
    }
    total = len(db.week_days(week_end, config.WEEK_SPAN_DAYS)) or "?"
    lines = [f"🗓 Week ending {week_end}:"]
    for r in rows:
        reactions = (
            f" · ❤️ {db.week_card_like_count(week_end, r['tg_id'])}"
            if r["status"] == "shared"
            else ""
        )
        lines.append(
            f"• {_who(r['tg_id'])} — {r['days']}/{total}, streak {r['streak']}🔥 "
            f"— {mark.get(r['status'], r['status'])}{reactions}"
        )
    await update.message.reply_text("\n".join(lines))


@admin_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    dates = db.collage_dates()
    participation = db.participation()
    if not dates or not participation:
        await update.message.reply_text("No collage days yet — stats start tomorrow.")
        return
    collage_days = set(dates)
    board = []
    for tg_id, user_dates in participation.items():
        n = len(user_dates & collage_days)
        if n == 0:
            continue
        streak = 0
        for d in reversed(dates):
            if d not in user_dates:
                break
            streak += 1
        u = db.get_user(tg_id)
        name = u["first_name"] if u else str(tg_id)
        uname = f" @{u['username']}" if u and u["username"] else ""
        board.append((n, streak, f"{name}{uname}"))
    board.sort(key=lambda x: (-x[0], -x[1], x[2].lower()))
    lines = [f"📊 Participation — {len(dates)} collage day(s):"]
    for i, (n, streak, who) in enumerate(board, 1):
        line = f"{i}. {who} — {n}/{len(dates)}"
        if streak >= 2:
            line += f", streak {streak}🔥"
        lines.append(line)
    totals = db.rating_counts_total()
    if totals:
        parts = [f"{e} {totals[v]}" for v, e in jobs.RATING_OPTIONS if totals.get(v)]
        lines.append(f"\nCollage ratings so far: {' · '.join(parts)}")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def cmd_suggestions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = db.pending_suggestions()
    if not rows:
        await update.message.reply_text("No pending suggestions.")
        return
    lines = ["💡 Pending suggestions (/approve <id> [en | ru], /dismiss <id>):"]
    for r in rows:
        u = db.get_user(r["tg_id"])
        name = u["first_name"] if u else str(r["tg_id"])
        lines.append(f"#{r['id']} {name}: «{r['text']}»")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def cmd_feedback_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = db.list_feedback()
    if not rows:
        await update.message.reply_text("No feedback yet.")
        return
    lines = [f"💬 All feedback ({len(rows)}):"]
    for r in rows:
        u = db.get_user(r["tg_id"])
        name = u["first_name"] if u else str(r["tg_id"])
        uname = f" @{u['username']}" if u and u["username"] else ""
        when = (r["created_at"] or "")[:16].replace("T", " ")
        lines.append(f"#{r['id']} · {when} · {name}{uname} (id {r['tg_id']}):\n{r['text']}")
    text = "\n\n".join(lines)
    for start in range(0, len(text), 3800):
        await update.message.reply_text(text[start : start + 3800])


def _has_cyrillic(s: str) -> bool:
    return any("Ѐ" <= c <= "ӿ" for c in s)


def bake_credit(text: str, name: str, lang: str) -> str:
    """Append the suggester's name into the prompt text itself (WYSIWYG credit),
    e.g. 'Send a photo of a smile. Idea: Olya'. The credit travels as plain text,
    so it survives export/edit/reupload and shows up verbatim in the message and
    on the collage. Avoids doubling terminal punctuation."""
    base = text.strip()
    sep = "" if base.endswith((".", "!", "?", "…")) else "."
    return f"{base}{sep} " + t(lang, "IDEA_CREDIT", name=name)


def _approve_one(line: str) -> str:
    """Process a single '/approve <id> [en | ru]' line; return the reply text."""
    body = line.split(maxsplit=1)
    rest = body[1].strip() if len(body) > 1 else ""
    parts = rest.split(maxsplit=1)
    try:
        sid = int(parts[0])
    except (IndexError, ValueError):
        return f"«{line}» — usage: /approve <id> [en text | ru text]"
    s = db.get_suggestion(sid)
    if s is None:
        return f"No suggestion #{sid}."
    if s["status"] != "pending":
        return f"Suggestion #{sid} is already {s['status']}."

    edit = parts[1].strip() if len(parts) > 1 else ""
    en, ru = parse_prompt_line(edit or s["text"])
    u = db.get_user(s["tg_id"])
    name = u["first_name"].strip() if u and (u["first_name"] or "").strip() else None
    if name:
        # The primary field may hold a Russian-only suggestion, so pick the label
        # by script rather than assuming English.
        en = bake_credit(en, name, "ru" if _has_cyrillic(en) else "en")
        if ru:
            ru = bake_credit(ru, name, "ru")
    # added_by/source keep the suggestion audit trail; the visible credit is the
    # baked-in text above, not this metadata.
    pid = db.add_prompt(en, s["tg_id"], text_ru=ru, source="suggestion")
    db.set_suggestion_status(sid, "approved")
    who = name or f"id {s['tg_id']}"
    note = "" if ru else "\n  (no RU yet — add it when you /exportprompts and edit)"
    return f"Queued #{pid} «{en}» — credited to {who} in the text.{note}"


@admin_only
async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # One /approve per line, so a multi-line message batch-approves cleanly
    # instead of swallowing the following lines as edited prompt text.
    text = update.message.text or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    cmd_lines = [ln for ln in lines if ln.lower().startswith("/approve")] or [text.strip()]
    replies = [_approve_one(ln) for ln in cmd_lines]
    replies.append(f"Unused prompts: {db.count_unused_prompts()}")
    await update.message.reply_text("\n".join(replies))


@admin_only
async def cmd_dismiss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        sid = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /dismiss <id>")
        return
    s = db.get_suggestion(sid)
    if s is None or s["status"] != "pending":
        await update.message.reply_text(f"No pending suggestion #{sid}.")
        return
    db.set_suggestion_status(sid, "dismissed")
    await update.message.reply_text(f"Dismissed #{sid}.")


@admin_only
async def cmd_errors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        lines = config.LOG_FILE.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        await update.message.reply_text("No log file yet.")
        return
    tail = "\n".join(lines[-20:]) or "Log is empty."
    await update.message.reply_text(tail[-3800:])
