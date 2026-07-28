import asyncio
import logging
import random
from datetime import date as date_cls
from datetime import datetime, time, timedelta
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden
from telegram.ext import ContextTypes

from . import collage, config, db
from .strings import t

log = logging.getLogger(__name__)

LOW_LIBRARY_THRESHOLD = 7

# Collage rating buttons: (stored value, emoji). Emoji-only labels, so one
# keyboard works for every language; tallies show up in the button text.
RATING_OPTIONS = [("fire", "🔥"), ("like", "👍"), ("meh", "😐")]
RATING_EMOJI = dict(RATING_OPTIONS)


def rating_keyboard(date: str) -> InlineKeyboardMarkup:
    counts = db.rating_counts(date)
    row = []
    for value, emoji in RATING_OPTIONS:
        n = counts.get(value, 0)
        label = f"{emoji} {n}" if n else emoji
        row.append(InlineKeyboardButton(label, callback_data=f"rate:{date}:{value}"))
    return InlineKeyboardMarkup([row])


STORY_HEART = "❤️"


def story_keyboard(sid: int) -> InlineKeyboardMarkup:
    """A single heart under a published story; the count rides in the label,
    so the keyboard works in every language. Tapping again takes it back."""
    n = db.story_like_count(sid)
    label = f"{STORY_HEART} {n}" if n else STORY_HEART
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"story:{sid}")]]
    )


def rating_summary(date: str) -> str | None:
    """'🔥 5 · 👍 2' or None if nobody rated yet."""
    counts = db.rating_counts(date)
    parts = [f"{e} {counts[v]}" for v, e in RATING_OPTIONS if counts.get(v)]
    return " · ".join(parts) if parts else None


# Custom admin-authored 👍/👎 feedback polls. Same live-tally mechanism as the
# collage ratings, keyed by the poll's id.
POLL_OPTIONS = [("up", "👍"), ("down", "👎")]
POLL_EMOJI = dict(POLL_OPTIONS)


def poll_keyboard(poll_id: int, *, closed: bool = False) -> InlineKeyboardMarkup:
    counts = db.poll_counts(poll_id)
    row = []
    for value, emoji in POLL_OPTIONS:
        n = counts.get(value, 0)
        label = f"{emoji} {n}" if n else emoji
        # A closed poll keeps its final tallies but taps do nothing.
        data = "pollclosed" if closed else f"poll:{poll_id}:{value}"
        row.append(InlineKeyboardButton(label, callback_data=data))
    return InlineKeyboardMarkup([row])


def poll_question(poll, lang: str | None) -> str:
    """Poll question in the user's language; English is the fallback."""
    if lang == "ru" and poll["question_ru"]:
        return poll["question_ru"]
    return poll["question"]


async def send_poll(
    context: ContextTypes.DEFAULT_TYPE, poll, recipients: list[int]
) -> tuple[int, int]:
    """Broadcast a poll with a live up/down keyboard, remembering each message so
    every copy's tallies refresh on a vote. Returns (sent, failed)."""
    keyboard = poll_keyboard(poll["id"])
    sent = failed = 0
    for uid in recipients:
        try:
            msg = await context.bot.send_message(
                uid, poll_question(poll, db.get_user_lang(uid)), reply_markup=keyboard
            )
            db.add_poll_message(poll["id"], uid, msg.message_id)
            sent += 1
        except Forbidden:
            db.set_user_status(uid, "inactive")
            failed += 1
        except Exception:
            log.exception("poll %s send to %s failed", poll["id"], uid)
            failed += 1
    return sent, failed


def prompt_text(prompt, lang: str | None) -> str:
    """Prompt in the user's language; English text is the primary/fallback."""
    if lang == "ru" and prompt["text_ru"]:
        return prompt["text_ru"]
    return prompt["text"]


def story_text(story, lang: str | None) -> str:
    """A story in the reader's language; the captured/English text is the
    primary and the fallback when there is no translation."""
    if lang == "ru" and story["text_ru"]:
        return story["text_ru"]
    return story["text"]


def now_local() -> datetime:
    return datetime.now(config.TZ)


def parse_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    t = time(int(h), int(m))
    return t


def deadline_label(lang: str | None) -> str:
    """Deadline clock time tagged with its timezone, e.g. '21:00 (Berlin time)',
    so users aren't left guessing which zone the time is in."""
    return f"{db.get_setting('deadline_time')} ({t(lang, 'TZ_SUFFIX')})"


def get_times() -> dict:
    return {
        "prompt": parse_hhmm(db.get_setting("prompt_time")),
        "reminder": parse_hhmm(db.get_setting("reminder_time")),
        "deadline": parse_hhmm(db.get_setting("deadline_time")),
        "preview": parse_hhmm(db.get_setting("preview_time")),
        "final": int(db.get_setting("final_reminder_min")),
    }


def day_dir(date: str) -> Path:
    return config.PHOTOS_DIR / date


def day_number(date: str) -> int | None:
    """Running day counter for the collage kicker: day 1 is
    project_start_date. Returns None if unset or the date precedes it."""
    start = db.get_setting("project_start_date")
    if not start:
        return None
    n = (date_cls.fromisoformat(date) - date_cls.fromisoformat(start)).days + 1
    return n if n >= 1 else None


async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text)
        except Exception:
            log.exception("failed to notify admin %s", admin_id)


async def send_per_user(
    context: ContextTypes.DEFAULT_TYPE, user_ids: list[int], text_fn
) -> tuple[int, int]:
    """Send text_fn(uid) to each user; auto-deactivate those who blocked the
    bot. Returns (sent, failed)."""
    sent = failed = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(uid, text_fn(uid))
            sent += 1
        except Forbidden:
            db.set_user_status(uid, "inactive")
            failed += 1
        except Exception:
            log.exception("send_message to %s failed", uid)
            failed += 1
    return sent, failed


async def send_to_users(
    context: ContextTypes.DEFAULT_TYPE, user_ids: list[int], text: str
) -> tuple[int, int]:
    return await send_per_user(context, user_ids, lambda _uid: text)


async def tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs every minute; drives the whole daily cycle. Because it compares
    current time against DB settings, /settimes changes apply instantly and
    missed jobs (NAS reboot) catch up on the next tick."""
    now = now_local()
    today = now.date().isoformat()
    nowt = now.time()
    t = get_times()
    day = db.get_day(today)

    # Admin-only heads-up (after the day's deadline) of what tomorrow's prompt
    # will be. Fires regardless of whether today ran or was skipped, so it also
    # confirms a queue that was refilled after an empty day.
    if nowt >= t["preview"] and not (day and day["preview_sent_at"]):
        await send_preview(context, today)
        day = db.get_day(today)

    if day and day["skipped"]:
        return

    if (day is None or not day["prompt_sent_at"]) and t["prompt"] <= nowt < t["deadline"]:
        await send_prompt(context, today)
        return

    if day is None or not day["prompt_sent_at"]:
        return

    if (
        not day["reminder_sent_at"]
        and t["reminder"] <= nowt < t["deadline"]
    ):
        await send_reminders(context, today)

    deadline_dt = datetime.combine(now.date(), t["deadline"], tzinfo=config.TZ)
    final_at = deadline_dt - timedelta(minutes=t["final"])
    if not day["final_reminder_sent_at"] and final_at <= now and nowt < t["deadline"]:
        await send_final_reminders(context, today)

    # The collage is never sent automatically: after the moderation message
    # it waits for an admin to review and run /forcecollage.
    if not day["moderation_sent_at"] and nowt >= t["deadline"]:
        await send_moderation(context, today)
        # if the sheet itself went out late (reboot catch-up), skip the nudge
        # marks that already passed — it just arrived, no need to pile on
        db.set_day_field(today, "collage_nudges", nudges_passed(now, t["deadline"]))
        day = db.get_day(today)

    # Proofing owns the collage while it's running; only once it's resolved (or
    # switched off, or nobody answered) do the admin nudges take over.
    if day["moderation_sent_at"] and not day["collage_sent_at"]:
        if not await run_proofing(context, today, now, day):
            await nudge_admins(context, today, now, t["deadline"], day)


NUDGE_MINUTES = (10, 30, 60)


def nudges_passed(now: datetime, deadline: time) -> int:
    """How many NUDGE_MINUTES marks lie behind us."""
    deadline_dt = datetime.combine(now.date(), deadline, tzinfo=config.TZ)
    minutes_over = (now - deadline_dt).total_seconds() / 60
    return sum(1 for m in NUDGE_MINUTES if minutes_over >= m)


async def nudge_admins(
    context: ContextTypes.DEFAULT_TYPE, date: str, now: datetime, deadline: time, day
) -> None:
    """Remind the admins that the collage still needs /forcecollage, at
    NUDGE_MINUTES past the deadline. collage_nudges counts marks already
    covered, so each tick sends at most one nudge and a reboot mid-window
    doesn't repeat the earlier ones."""
    deadline_dt = datetime.combine(now.date(), deadline, tzinfo=config.TZ)
    minutes_over = (now - deadline_dt).total_seconds() / 60
    passed = nudges_passed(now, deadline)
    if passed <= (day["collage_nudges"] or 0):
        return
    db.set_day_field(date, "collage_nudges", passed)
    n = len(db.photos_for(date))
    await notify_admins(
        context,
        f"⏰ {int(minutes_over)} min past the deadline — the collage "
        f"({n} photo(s)) is still waiting for your review.\n"
        "/preview to check it, /forcecollage to send.",
    )


# --- collage proofing ---------------------------------------------------------
#
# A few trusted users see the collage before anyone else. One 👍 publishes it —
# which is where almost every evening ends. A 🚫 (double-confirmed, so a stray
# thumb can't stop the day) freezes the auto-publish and passes the collage to
# fresh eyes; two 🚫 park it on the admin, who decides whether to /exclude a
# photo or send it as is.


def proof_cfg() -> dict:
    return {
        "enabled": db.get_setting("proof_enabled") == "1",
        "batch": int(db.get_setting("proof_batch")),
        "round_min": int(db.get_setting("proof_round_min")),
        "quorum": int(db.get_setting("proof_ban_quorum")),
    }


def proof_keyboard(date: str, lang: str | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t(lang, "PROOF_BTN_OK"), callback_data=f"proof:{date}:ok"
                ),
                InlineKeyboardButton(
                    t(lang, "PROOF_BTN_HOLD"), callback_data=f"proof:{date}:hold"
                ),
            ]
        ]
    )


def proof_confirm_keyboard(date: str, lang: str | None) -> InlineKeyboardMarkup:
    """The second tap. A hold stops the evening for everyone, so it must never
    be one stray thumb on a phone in a pocket."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t(lang, "PROOF_BTN_HOLD_YES"),
                    callback_data=f"proof:{date}:holdyes",
                )
            ],
            [
                InlineKeyboardButton(
                    t(lang, "PROOF_BTN_BACK"), callback_data=f"proof:{date}:back"
                )
            ],
        ]
    )


def pick_proof_batch(date: str, n: int) -> list[int]:
    """A random n from the trusted list, minus anyone already asked today.

    Random rather than a rotation: the list is meant to be long and uniformly
    trusted, so an unpredictable draw spreads the duty without anyone coming to
    own a particular weekday, and an escalation reaches genuinely fresh eyes."""
    asked = {r["tg_id"] for r in db.proof_asks_for(date)}
    pool = [u for u in db.proofer_ids() if u not in asked]
    return random.sample(pool, min(n, len(pool)))


async def send_proof_round(
    context: ContextTypes.DEFAULT_TYPE, date: str, round_no: int
) -> int:
    """Send the check to one batch, unannounced — the collage arriving *is* the
    ask. Returns how many people actually received it."""
    batch = [r["tg_id"] for r in db.proof_asks_for(date, round_no)]
    if not batch:
        batch = pick_proof_batch(date, proof_cfg()["batch"])
        for uid in batch:
            db.add_proof_ask(date, uid, round_no)
    if not batch:
        return 0

    n = len(db.photos_for(date))
    key = "PROOF_ASK" if round_no == 1 else "PROOF_ASK_FLAGGED"
    # Render once per language and reuse Telegram's file_id — a render per
    # proofer would block the NAS for seconds each.
    paths = {lang: await render_collage(date, lang, stem="proof")
             for lang in {lang_of(uid) for uid in batch}}
    file_ids: dict[str, str] = {}
    sent = 0
    for uid in batch:
        lang = db.get_user_lang(uid)
        caption = t(lang, key, n=n)
        keyboard = proof_keyboard(date, lang)
        try:
            if lang_of(uid) in file_ids:
                msg = await context.bot.send_photo(
                    uid, file_ids[lang_of(uid)], caption=caption,
                    reply_markup=keyboard,
                )
            else:
                with open(paths[lang_of(uid)], "rb") as f:
                    msg = await context.bot.send_photo(
                        uid, f, caption=caption, reply_markup=keyboard
                    )
                file_ids[lang_of(uid)] = msg.photo[-1].file_id
            db.set_proof_message(date, uid, msg.message_id)
            sent += 1
        except Forbidden:
            db.set_user_status(uid, "inactive")
            db.delete_proof_ask(date, uid)
        except Exception:
            log.exception("proof ask to %s failed", uid)
            db.delete_proof_ask(date, uid)

    if sent:
        db.set_day_field(date, "proof_round", round_no)
        db.set_day_field(
            date, "proof_asked_at", now_local().isoformat(timespec="seconds")
        )
    return sent


async def close_proof_asks(
    context: ContextTypes.DEFAULT_TYPE, date: str, key: str, only: int | None = None
) -> None:
    """Retire the preview messages once the day is decided. Whoever answered
    keeps their copy, captioned with the outcome; for everyone who didn't get
    round to it the question is deleted outright, so nobody is left staring at
    a decision that was made without them."""
    for r in db.proof_asks_for(date):
        if not r["message_id"] or (only is not None and r["tg_id"] != only):
            continue
        try:
            if r["value"]:
                await context.bot.edit_message_caption(
                    chat_id=r["tg_id"],
                    message_id=r["message_id"],
                    caption=t(db.get_user_lang(r["tg_id"]), key),
                    # an *empty* keyboard is what clears the buttons;
                    # reply_markup=None is omitted from the request and leaves
                    # them in place
                    reply_markup=InlineKeyboardMarkup([]),
                )
            else:
                await context.bot.delete_message(r["tg_id"], r["message_id"])
                db.set_proof_message(date, r["tg_id"], None)
        except Exception:
            log.debug("closing proof ask for %s/%s failed", r["tg_id"], date)


def proof_hold_lines(date: str) -> list[str]:
    """Who held the collage and why — for the admin handover message."""
    lines = []
    for r in db.proof_bans(date):
        u = db.get_user(r["tg_id"])
        who = u["first_name"] if u else f"id {r['tg_id']}"
        lines.append(f"🚫 {who}: {r['note'] or '(no note yet)'}")
    return lines


async def proof_publish(
    context: ContextTypes.DEFAULT_TYPE, date: str, approver_id: int
) -> None:
    """One 👍 with no hold on record — the collage goes out to everyone."""
    db.set_day_field(date, "proof_result", "approved")
    await close_proof_asks(context, date, "PROOF_CLOSED_PUBLISHED")
    u = db.get_user(approver_id)
    who = f"{u['first_name']} (id {approver_id})" if u else f"id {approver_id}"
    await notify_admins(context, f"👍 {date}: {who} approved the collage — publishing.")
    await send_collage(context, date)


async def proof_hold(
    context: ContextTypes.DEFAULT_TYPE, date: str, reason: str
) -> None:
    """Enough holds — the day is the admin's call now."""
    db.set_day_field(date, "proof_result", "held")
    await close_proof_asks(context, date, "PROOF_CLOSED_HELD")
    lines = [f"⏸ {date}: the collage is on hold ({reason})."]
    lines += proof_hold_lines(date)
    lines.append(
        "Numbers match the contact sheet above (/photos to reprint them).\n"
        "/exclude N to drop a photo, then /forcecollage — or /forcecollage "
        "on its own to send it as is."
    )
    await notify_admins(context, "\n".join(lines))


async def proof_exhausted(context: ContextTypes.DEFAULT_TYPE, date: str) -> None:
    """Nobody left to ask. A day carrying an open hold is parked for review; a
    day nobody answered just reverts to the old admin-only flow, nudges and all."""
    if db.proof_bans(date):
        await proof_hold(context, date, "nobody left to confirm the hold")
        return
    db.set_day_field(date, "proof_result", "exhausted")
    await notify_admins(
        context,
        f"👀 {date}: nobody on the proofing list answered "
        f"({len(db.proof_asks_for(date))} asked) — the collage is yours. "
        "/preview, /forcecollage.",
    )


async def _proof_next_round(
    context: ContextTypes.DEFAULT_TYPE, date: str, round_no: int
) -> bool:
    """Ask the next batch; when there's nobody left, hand the day back."""
    if await send_proof_round(context, date, round_no):
        return True
    await proof_exhausted(context, date)
    return False


async def proof_after_hold(context: ContextTypes.DEFAULT_TYPE, date: str) -> None:
    """A hold just landed. Two of them park the day on the admin; a single one
    goes to fresh eyes — one person flagging is a reason to look again, not a veto."""
    cfg = proof_cfg()
    if db.proof_counts(date).get("ban", 0) >= cfg["quorum"]:
        await proof_hold(context, date, f"{cfg['quorum']} holds")
        return
    day = db.get_day(date)
    await _proof_next_round(context, date, (day["proof_round"] or 1) + 1)


async def run_proofing(
    context: ContextTypes.DEFAULT_TYPE, date: str, now: datetime, day
) -> bool:
    """Drive the check from the tick. Returns True while proofing owns the day,
    which is what keeps the admin nudges quiet."""
    cfg = proof_cfg()
    if not cfg["enabled"] or day["proof_result"] or day["collage_sent_at"]:
        return False
    if not db.proofer_ids() or not db.photos_for(date):
        return False
    if not day["proof_round"] or not day["proof_asked_at"]:
        return await _proof_next_round(context, date, 1)
    asked_at = datetime.fromisoformat(day["proof_asked_at"])
    if now - asked_at < timedelta(minutes=cfg["round_min"]):
        return True  # this round still has time to answer
    return await _proof_next_round(context, date, day["proof_round"] + 1)


async def send_prompt(context: ContextTypes.DEFAULT_TYPE, date: str) -> None:
    prompt = db.pick_prompt()
    if prompt is None:
        db.set_day_field(date, "skipped", 1)
        await notify_admins(
            context,
            "⚠️ Prompt queue is empty — today is skipped. Add prompts with "
            "/addprompt or upload a fresh .txt file (one prompt per line).",
        )
        return

    db.mark_prompt_used(prompt["id"], date)
    db.create_day(date, prompt["id"])

    sent, failed = await send_per_user(
        context,
        db.active_user_ids(),
        lambda uid: t(
            db.get_user_lang(uid),
            "PROMPT",
            text=prompt_text(prompt, db.get_user_lang(uid)),
        ),
    )

    unused = db.count_unused_prompts()
    note = f"📤 Prompt sent to {sent} users (failed: {failed}).\n«{prompt['text']}»"
    if prompt["source"] == "suggestion":
        su = db.get_user(prompt["added_by"]) if prompt["added_by"] else None
        if su:
            note += f"\n💡 Suggested by {su['first_name']} (credit is in the prompt text)."
    if unused == 0:
        note += "\n⚠️ That was the LAST prompt in the queue — upload more before tomorrow."
    elif unused < LOW_LIBRARY_THRESHOLD:
        note += f"\n⚠️ Only {unused} unused prompts left — time to add more."
    await notify_admins(context, note)


async def send_preview(context: ContextTypes.DEFAULT_TYPE, date: str) -> None:
    """Admin-only preview of the prompt queued to go out next. By preview_time
    (evening) today's prompt is already marked used, so pick_prompt() returns
    tomorrow's — the next unused prompt in queue order."""
    db.set_day_field(date, "preview_sent_at", now_local().isoformat(timespec="seconds"))
    prompt = db.pick_prompt()
    if prompt is None:
        await notify_admins(
            context,
            "🔮 Tomorrow's prompt: the queue is empty — nothing lined up. Add "
            "prompts with /addprompt or upload a fresh .txt before 09:00.",
        )
        return
    lines = ["🔮 Tomorrow's prompt (next in queue):", f"«{prompt['text']}»"]
    if prompt["text_ru"]:
        lines.append(f"🇷🇺 «{prompt['text_ru']}»")
    if prompt["source"] == "suggestion" and prompt["added_by"]:
        su = db.get_user(prompt["added_by"])
        if su:
            lines.append(f"💡 Suggested by {su['first_name']} (credit is in the prompt text).")
    unused = db.count_unused_prompts()
    lines.append(f"📚 {unused} unused prompt(s) in the queue (this one included).")
    await notify_admins(context, "\n".join(lines))


async def send_reminders(context: ContextTypes.DEFAULT_TYPE, date: str) -> None:
    db.set_day_field(date, "reminder_sent_at", now_local().isoformat(timespec="seconds"))
    day = db.get_day(date)
    prompt = db.get_prompt(day["prompt_id"]) if day["prompt_id"] else None
    if prompt is None:
        return
    submitted = set(db.submitter_ids(date))
    targets = [u for u in db.active_user_ids() if u not in submitted]
    if not targets:
        return
    await send_per_user(
        context,
        targets,
        lambda uid: t(
            db.get_user_lang(uid),
            "REMINDER",
            deadline=deadline_label(db.get_user_lang(uid)),
            text=prompt_text(prompt, db.get_user_lang(uid)),
        ),
    )


async def send_final_reminders(context: ContextTypes.DEFAULT_TYPE, date: str) -> None:
    """Last-call nudge a few minutes before the deadline, to everyone who still
    hasn't submitted."""
    db.set_day_field(
        date, "final_reminder_sent_at", now_local().isoformat(timespec="seconds")
    )
    day = db.get_day(date)
    prompt = db.get_prompt(day["prompt_id"]) if day["prompt_id"] else None
    if prompt is None:
        return
    submitted = set(db.submitter_ids(date))
    targets = [u for u in db.active_user_ids() if u not in submitted]
    if not targets:
        return
    minutes = int(db.get_setting("final_reminder_min"))
    await send_per_user(
        context,
        targets,
        lambda uid: t(
            db.get_user_lang(uid),
            "FINAL_REMINDER",
            minutes=minutes,
            text=prompt_text(prompt, db.get_user_lang(uid)),
        ),
    )


async def send_moderation(context: ContextTypes.DEFAULT_TYPE, date: str) -> None:
    """At the deadline: numbered contact sheet + name list to the admins so
    they can /exclude or /ban before the collage goes out."""
    db.set_day_field(
        date, "moderation_sent_at", now_local().isoformat(timespec="seconds")
    )
    photos = db.photos_for(date, include_excluded=True)
    if not photos:
        # nothing to review or send — close the day so it doesn't stay pending
        db.set_day_field(
            date, "collage_sent_at", now_local().isoformat(timespec="seconds")
        )
        await notify_admins(context, f"📭 {date}: deadline passed, no submissions.")
        return

    out = day_dir(date) / "moderation.jpg"
    collage.build_contact_sheet([Path(p["file_path"]) for p in photos], out)

    lines = []
    for i, p in enumerate(photos, 1):
        u = db.get_user(p["tg_id"])
        name = u["first_name"] if u else "?"
        uname = f" @{u['username']}" if u and u["username"] else ""
        lines.append(f"{i} — {name}{uname} (id {p['tg_id']})")
    text = (
        f"🔍 Moderation for {date} — the collage waits for your review.\n"
        "/exclude N — drop a photo, /ban N — drop + kick the user,\n"
        "/include N — undo, /preview — dry-run to you only,\n"
        "/forcecollage — send the collage to everyone.\n\n" + "\n".join(lines)
    )
    for admin_id in config.ADMIN_IDS:
        try:
            with open(out, "rb") as f:
                await context.bot.send_photo(admin_id, f)
            for start in range(0, len(text), 3800):
                await context.bot.send_message(admin_id, text[start : start + 3800])
        except Exception:
            log.exception("moderation send to admin %s failed", admin_id)


def _render_collage(
    date: str, lang: str, *, hires: bool = False, stem: str = "collage"
) -> Path:
    """Render the day's collage card to disk. Same mosaic in every language —
    only the header/footer text differs, hence the shared date-derived seed."""
    paths = [Path(p["file_path"]) for p in db.photos_for(date)]
    prompt_en = prompt_ru = None
    day = db.get_day(date)
    if day and day["prompt_id"]:
        prompt = db.get_prompt(day["prompt_id"])
        if prompt:
            prompt_en, prompt_ru = prompt["text"], prompt["text_ru"]
    suffix = "_hires" if hires else ""
    out = day_dir(date) / f"{stem}{suffix}_{lang}.jpg"
    extra = (
        dict(
            scale=config.COLLAGE_HIRES_SCALE,
            max_side=config.COLLAGE_HIRES_MAX_SIDE,
            quality=config.COLLAGE_HIRES_QUALITY,
        )
        if hires
        else {}
    )
    collage.build_collage(
        paths,
        out,
        prompt=(prompt_ru or prompt_en) if lang == "ru" else prompt_en,
        on_date=date,
        day_number=day_number(date),
        lang=lang,
        seed=hash(date) & 0x7FFFFFFF,
        **extra,
    )
    return out


async def render_collage(
    date: str, lang: str, *, hires: bool = False, stem: str = "collage"
) -> Path:
    """Render a collage off the event loop. Pillow is CPU-bound and a big hi-res
    canvas takes many seconds on the NAS — running it inline froze the whole bot
    (rating taps timed out). asyncio.to_thread keeps it responsive."""
    return await asyncio.to_thread(_render_collage, date, lang, hires=hires, stem=stem)


def lang_of(uid: int) -> str:
    """Collages exist in exactly two languages; anything else reads English."""
    return "ru" if db.get_user_lang(uid) == "ru" else "en"


async def send_collage(
    context: ContextTypes.DEFAULT_TYPE,
    date: str,
    preview_to: int | None = None,
) -> str:
    """Build and distribute the day's collage. With preview_to set, sends only
    to that admin and does not mark the day done. Returns a status string."""
    photos = db.photos_for(date)
    if not photos:
        if preview_to is None:
            db.set_day_field(
                date, "collage_sent_at", now_local().isoformat(timespec="seconds")
            )
            await notify_admins(context, f"📭 {date}: no submissions, no collage.")
        return "no submissions"

    n = len(photos)

    # Busy days: the compressed inline photo is too small to read, so attach a
    # zoomable hi-res file (a document) alongside it. Small days don't need it.
    attach_hires = n >= config.COLLAGE_HIRES_MIN_PHOTOS
    stem = "collage_preview" if preview_to else "collage"

    async def build(lang: str, *, hires: bool = False) -> Path:
        return await render_collage(date, lang, hires=hires, stem=stem)

    def caption_for(uid: int, streak: int = 0) -> str:
        lang = db.get_user_lang(uid)
        if n == 1:
            base = t(lang, "COLLAGE_CAPTION_SOLO")
        else:
            base = t(lang, "COLLAGE_CAPTION", n=n)
        # A streak of 1 is just "showed up today" — only celebrate from 2 up.
        if streak >= 2:
            base += t(lang, "COLLAGE_STREAK", days=streak)
        return base

    fname = f"collage_{date}.jpg"

    if preview_to is not None:
        lang = lang_of(preview_to)
        with open(await build(lang), "rb") as f:
            await context.bot.send_photo(
                preview_to, f, caption=f"[preview] {caption_for(preview_to)}"
            )
        if attach_hires:
            with open(await build(lang, hires=True), "rb") as f:
                await context.bot.send_document(
                    preview_to, f, filename=fname,
                    caption="[preview] " + t(lang, "COLLAGE_ZOOM"),
                )
        return f"preview sent ({n} photos)"

    recipients = list(dict.fromkeys(db.submitter_ids(date) + list(config.ADMIN_IDS)))
    streaks = db.streaks_for(date)
    langs = {lang_of(uid) for uid in recipients}
    # Render every needed collage up front (off the event loop) so each user then
    # gets the photo and the hi-res file back-to-back, not minutes apart.
    photo_path = {lang: await build(lang) for lang in langs}
    doc_path = (
        {lang: await build(lang, hires=True) for lang in langs} if attach_hires else {}
    )

    keyboard = rating_keyboard(date)
    photo_ids: dict[str, str] = {}
    doc_ids: dict[str, str] = {}
    sent = 0
    for uid in recipients:
        lang = lang_of(uid)
        caption = caption_for(uid, streaks.get(uid, 0))
        try:
            # Upload each collage to Telegram once, then reuse its file_id.
            if lang in photo_ids:
                msg = await context.bot.send_photo(
                    uid, photo_ids[lang], caption=caption, reply_markup=keyboard
                )
            else:
                with open(photo_path[lang], "rb") as f:
                    msg = await context.bot.send_photo(
                        uid, f, caption=caption, reply_markup=keyboard
                    )
                photo_ids[lang] = msg.photo[-1].file_id
            # remembered so every copy's tallies can be updated on each vote
            db.add_collage_message(date, uid, msg.message_id)
            sent += 1
            if attach_hires:
                caption = t(lang, "COLLAGE_ZOOM")
                if lang in doc_ids:
                    await context.bot.send_document(
                        uid, doc_ids[lang], caption=caption, filename=fname
                    )
                else:
                    with open(doc_path[lang], "rb") as f:
                        dmsg = await context.bot.send_document(
                            uid, f, caption=caption, filename=fname
                        )
                    doc_ids[lang] = dmsg.document.file_id
        except Forbidden:
            db.set_user_status(uid, "inactive")
        except Exception:
            log.exception("collage send to %s failed", uid)

    db.set_day_field(
        date, "collage_sent_at", now_local().isoformat(timespec="seconds")
    )
    # Sent by hand (/forcecollage) while a check was still open — retire those
    # buttons rather than leaving proofers with a decision that no longer exists.
    day = db.get_day(date)
    if day and not day["proof_result"] and db.proof_asks_for(date):
        db.set_day_field(date, "proof_result", "forced")
        await close_proof_asks(context, date, "PROOF_CLOSED_PUBLISHED")
    await notify_admins(context, f"🖼 {date}: collage from {n} photos sent to {sent}.")
    return f"sent to {sent}"
