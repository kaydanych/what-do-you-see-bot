import functools
import html
import io
import logging
import random
from datetime import date as date_cls
from datetime import time

from telegram import Update
from telegram.error import Forbidden
from telegram.ext import ContextTypes

from . import config, db, jobs, version
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
At the deadline the collage — no numbers, no names — goes to 2–3 proofers,
unannounced, asking whether anything is wrong. One 👍 publishes it. A 🚫 (they
confirm it twice) freezes the publish and rolls to a fresh batch; two 🚫 park
the day on you with their notes — then /exclude N and /forcecollage, or
/forcecollage as is. Silence rolls to the next batch every 10 min; when the
list runs out you get the nudges, as before. Once the day is decided, the
question is deleted from anyone who hadn't answered.
/proofers — who's on the list and when they were last asked
/proofer <id|@username> — add/remove someone (adding DMs them the guidelines)
/proofing — settings + tonight's state
/proofing batch=3 round=10 quorum=2 — tune it
/proofing off — back to the admin-only flow

💬 Story of the day (the photo + why the author chose it)
/photos [YYYY-MM-DD] — numbered author list for a day (numbers = the contact sheet)
/askstory [YYYY-MM-DD] N — DM author N their photo and ask why they chose it
/askstory random — pick a random past photo and ask its author
/stories — stories the authors have answered, waiting to publish
/editstory <id> <text> — edit a story's text (or write one yourself); <EN> | <RU> stores both languages, each reader gets their half
/publishstory <id> — send that photo + story to everyone in the game (reveals the author's name); it carries a ❤️ button with a live shared tally
/publishstory <id> day — narrower: only that day's submitters, the audience the collage went to
/dismissstory <id> — discard a story"""


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
        f"preview = {db.get_setting('preview_time')} (admin heads-up: tomorrow's prompt)\n\n"
        "Change: /settimes prompt=09:00 reminder=19:00 final=10 deadline=21:00 preview=21:10\n"
        "(any subset; applies within a minute, no restart needed)\n"
        "Collage: sent manually after your review — /forcecollage."
    )


KEY_MAP = {
    "prompt": "prompt_time",
    "reminder": "reminder_time",
    "final": "final_reminder_min",
    "deadline": "deadline_time",
    "preview": "preview_time",
}


@admin_only
async def cmd_settimes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: /settimes prompt=09:00 reminder=19:00 final=10 deadline=21:00 "
            "preview=21:10"
        )
        return
    new = {k: db.get_setting(v) for k, v in KEY_MAP.items()}
    try:
        for arg in context.args:
            key, _, val = arg.partition("=")
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
    await update.message.reply_text(
        f"Saved ✅ prompt {new['prompt']}, reminder {new['reminder']}, "
        f"final −{new['final']} min, deadline {new['deadline']}, "
        f"preview {new['preview']}."
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


@admin_only
async def cmd_proofers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = db.list_proofers()
    lines = ["👀 Collage proofers — they see the collage before anyone else."]
    if not rows:
        lines.append(
            "\nNobody yet, so the collage still waits for you as before.\n"
            "Add someone with /proofer <id|@username>."
        )
    for r in rows:
        mark = {"active": "🟢", "inactive": "⚪️", "kicked": "🚫"}[r["status"]]
        uname = f"@{r['username']}" if r["username"] else ""
        last = f"last asked {r['last_proofed_on']}" if r["last_proofed_on"] else "never asked"
        lines.append(f"{mark} {r['first_name']} {uname} (id {r['tg_id']}) — {last}")
    lines.append("\n/proofer <id|@username> — add or remove someone\n/proofing — settings and tonight's state")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def cmd_proofer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle someone's proofer flag. Adding sends them the explanation and the
    guidelines, so the first heads-up doesn't arrive out of nowhere."""
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
    if not on:
        await update.message.reply_text(f"👀 {name} is no longer a proofer.")
        return
    lang = user["lang"]
    try:
        await context.bot.send_message(
            user["tg_id"],
            t(lang, "PROOF_ENROLLED", deadline=jobs.deadline_label(lang))
            + "\n\n"
            + t(lang, "PROOF_RULES"),
        )
        note = "briefed ✅"
    except Exception:
        log.exception("proof enrollment note to %s failed", user["tg_id"])
        note = "⚠️ couldn't DM them the briefing — they'll get the rules with their first heads-up"
    await update.message.reply_text(f"👀 {name} is now a proofer — {note}")


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
    rows = db.answered_stories()
    if not rows:
        await update.effective_message.reply_text(
            "No stories waiting to publish.\n"
            "Ask for one with /askstory [date] N (numbers from /photos)."
        )
        return
    blocks = []
    for s in rows:
        u = db.get_user(s["tg_id"])
        name = u["first_name"] if u else str(s["tg_id"])
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
