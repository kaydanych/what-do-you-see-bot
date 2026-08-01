import asyncio
import logging
import random
import zlib
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


# --- knock, knock ------------------------------------------------------------
#
# Under the collage sits one English button — a nursery rhyme, not an
# instruction, so it reads the same to everyone and lands as the surprise it is.
# Tapping it opens a carousel of the day's photos; you knock on the one whose
# story you want. One knock each. Nothing about the author is shown anywhere:
# revealing them is the prize, so the card carries no name, no filename, and no
# position in the mosaic.
KNOCK_LABEL = "🚪 Knock, knock, who's there..."
# Knocking stays open overnight and closes at noon the next day, when the tally
# is read and one author is asked for the story.
KNOCK_CLOSE_HOUR = 12


def knock_open_for(date: str) -> bool:
    """Is the window still open for `date`? Opens when the collage goes out,
    closes at KNOCK_CLOSE_HOUR the following day."""
    day = db.get_day(date)
    if not day or not day["collage_sent_at"]:
        return False
    close = datetime.combine(
        date_cls.fromisoformat(date) + timedelta(days=1),
        time(KNOCK_CLOSE_HOUR),
        tzinfo=config.TZ,
    )
    return now_local() < close


def knock_open_keyboard(date: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(KNOCK_LABEL, callback_data=f"kn:open:{date}")]]
    )


def collage_keyboard(date: str, *, knock: bool | None = None) -> InlineKeyboardMarkup:
    """Everything that hangs under a published collage: the live rating row,
    plus the knock door while the window is open. One function, because a
    rating tap redraws this keyboard on every copy — building the rows
    separately is how the door quietly disappears the first time someone
    taps 🔥. `knock` overrides the window check for the send itself, which
    runs before the day is marked published."""
    rows = list(rating_keyboard(date).inline_keyboard)
    if knock_open_for(date) if knock is None else knock:
        rows += knock_open_keyboard(date).inline_keyboard
    return InlineKeyboardMarkup(rows)


def knock_card_keyboard(date: str, idx: int, total: int) -> InlineKeyboardMarkup:
    """‹ · knock · ›. The counter is the reader's position in the carousel, not
    a photo number — it says nothing about whose photo this is."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("‹", callback_data=f"kn:go:{date}:{(idx - 1) % total}"),
                InlineKeyboardButton(
                    f"🚪 Knock · {idx + 1}/{total}", callback_data=f"kn:hit:{date}:{idx}"
                ),
                InlineKeyboardButton("›", callback_data=f"kn:go:{date}:{(idx + 1) % total}"),
            ]
        ]
    )


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


async def notify_admins(
    context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None
) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception:
            log.exception("failed to notify admin %s", admin_id)


# --- new-user verification ----------------------------------------------------
#
# Nobody joins the game unseen. A newcomer lands in 'pending' and the admins get
# their card with ✅ / 🚫; until someone taps ✅ they are outside
# active_user_ids(), so no prompt, reminder, collage, poll or broadcast reaches
# them — they just get the "you're on the list" note.


def verify_keyboard(tg_id: int) -> InlineKeyboardMarkup:
    """Admin-facing, so the labels are English like the rest of the admin side."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"verify:{tg_id}:ok"),
                InlineKeyboardButton("🚫 Reject", callback_data=f"verify:{tg_id}:no"),
            ]
        ]
    )


def verify_card(user) -> str:
    uname = f"@{user['username']}" if user["username"] else "—"
    joined = (user["joined_at"] or "")[:16].replace("T", " ")
    return (
        f"👤 New user: {user['first_name']} {uname}\n"
        f"id {user['tg_id']} · first seen {joined}\n\n"
        "They're on hold and hear nothing from the bot until you decide."
    )


async def ask_admins_to_verify(context: ContextTypes.DEFAULT_TYPE, user) -> None:
    await notify_admins(
        context, verify_card(user), verify_keyboard(user["tg_id"])
    )


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

    # The weekly card rides on its own clock, not the day's — it must still fire
    # on a skipped day, and it must not be starved by the early returns below.
    await maybe_offer_week_cards(context, now)

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
    """A random n of the people who both played today and are on the trusted
    list, minus anyone already asked today.

    Restricted to that day's submitters, so a proofer only ever gets an early
    look at a collage they're already in — nobody sees a day they sat out. The
    trusted list is long enough that the overlap is normally many batches deep;
    when it does run dry the day falls back to the admin rather than reaching
    for someone who didn't play.

    Random within that pool rather than a rotation, so nobody comes to own a
    particular weekday and an escalation reaches genuinely fresh eyes."""
    asked = {r["tg_id"] for r in db.proof_asks_for(date)}
    submitters = set(db.submitter_ids(date))
    pool = [u for u in db.proofer_ids() if u in submitters and u not in asked]
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


def collage_seed(date: str) -> int:
    """Stable across processes — `hash()` is salted per run, so a collage
    rebuilt after a restart would come out rearranged and no longer match the
    stored knock carousel order."""
    return zlib.crc32(date.encode()) & 0x7FFFFFFF


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
        seed=collage_seed(date),
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

    # The zoom file is now the admin's moderation aid only: readers who want a
    # closer look flip through the photos themselves in the knock carousel.
    attach_hires = preview_to is not None and n >= config.COLLAGE_HIRES_MIN_PHOTOS
    stem = "collage_preview" if preview_to else "collage"

    # Freeze which photo sits in which tile before anything is sent — the
    # carousel walks this order, and a later rebuild must not silently reshuffle
    # under readers who are mid-flip.
    by_path = {p["file_path"]: p["tg_id"] for p in photos}
    if preview_to is None:
        db.set_collage_cells(
            date,
            [
                by_path[str(p)]
                for p in collage.arrangement(
                    [Path(p["file_path"]) for p in photos], collage_seed(date)
                )
            ],
        )

    async def build(lang: str, *, hires: bool = False) -> Path:
        return await render_collage(date, lang, hires=hires, stem=stem)

    def caption_for(uid: int) -> str:
        lang = db.get_user_lang(uid)
        if n == 1:
            return t(lang, "COLLAGE_CAPTION_SOLO")
        return t(lang, "COLLAGE_CAPTION", n=n)

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
    langs = {lang_of(uid) for uid in recipients}
    # Render every needed collage up front (off the event loop) so each user then
    # gets the photo and the hi-res file back-to-back, not minutes apart.
    photo_path = {lang: await build(lang) for lang in langs}
    doc_path = (
        {lang: await build(lang, hires=True) for lang in langs} if attach_hires else {}
    )

    keyboard = collage_keyboard(date, knock=True)
    photo_ids: dict[str, str] = {}
    doc_ids: dict[str, str] = {}
    sent = 0
    for uid in recipients:
        lang = lang_of(uid)
        caption = caption_for(uid)
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


# --- the weekly card ----------------------------------------------------------
#
# Sunday evening, everyone who didn't miss a day gets their own week back as one
# picture. Three things keep it from turning into a leaderboard: it is a line you
# cross, not a place you finish (so it's usually a handful of people, and a
# different handful each week); the card is sent to its author alone; and the
# group only ever sees it if the author taps "show everyone". Nobody is ranked in
# public, and nobody is congratulated in public without being asked first.
#
# The window ends *yesterday*, so on Sunday the card covers Sun–Sat and can't
# name the author of a photo whose knock window (§11a) is still open.


def week_card_keyboard(week_end: str, lang: str | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t(lang, "WEEK_BTN_SHARE"), callback_data=f"wk:s:{week_end}")],
            [InlineKeyboardButton(t(lang, "WEEK_BTN_KEEP"), callback_data=f"wk:k:{week_end}")],
        ]
    )


def week_end_for(today: date_cls) -> str:
    return (today - timedelta(days=1)).isoformat()


def last_week_run(now: datetime) -> date_cls:
    """The most recent scheduled weekly moment at or before `now`. Comparing
    against this (rather than 'is it Sunday right now?') is what makes the job
    survive a NAS reboot over the weekend — it runs late instead of never."""
    dow = int(db.get_setting("week_card_dow"))
    at = parse_hhmm(db.get_setting("week_card_time"))
    back = (now.weekday() - dow) % 7
    run = now.date() - timedelta(days=back)
    if back == 0 and now.time() < at:
        run -= timedelta(days=7)
    return run


async def maybe_offer_week_cards(
    context: ContextTypes.DEFAULT_TYPE, now: datetime
) -> None:
    """Fire the weekly offers once per week, from the same one-minute tick as
    everything else — so the time is DB-editable and a late start still runs."""
    if db.get_setting("week_card_enabled") != "1":
        return
    week_end = week_end_for(last_week_run(now))
    if db.get_setting("week_card_last") == week_end:
        return
    if not db.get_setting("week_card_last"):
        # First run ever: arm the job rather than retro-celebrating a week that
        # ended before the feature existed.
        db.set_setting("week_card_last", week_end)
        return
    await offer_week_cards(context, week_end)


def week_card_path(week_end: str, tg_id: int) -> Path:
    return config.PHOTOS_DIR / "weeks" / week_end / f"u{tg_id}.jpg"


async def render_week_card(
    week_end: str, tg_id: int, dates: list[str], streak: int
) -> Path | None:
    """Render one person's week off the event loop (same reason as the collage:
    Pillow is CPU-bound and the NAS is slow). None if too few of their photos
    survive on disk to still be a week."""
    photos = {p["date"]: Path(p["file_path"]) for p in db.photos_on(tg_id, dates)}
    if len(photos) < config.WEEK_MIN_PHOTOS:
        return None
    user = db.get_user(tg_id)
    return await asyncio.to_thread(
        collage.build_week_card,
        photos,
        week_card_path(week_end, tg_id),
        name=(user["first_name"] if user else str(tg_id)),
        dates=dates,
        lang=lang_of(tg_id),
        streak=streak,
    )


def tied_leaders(board: list[dict]) -> list[dict]:
    """Everyone sharing the longest streak on the board. A run of 1 isn't a
    streak, so a week where nobody strung two days together has no leader."""
    if not board or board[0]["streak"] < 2:
        return []
    return [r for r in board if r["streak"] == board[0]["streak"]]


def pick_leader(week_end: str, board: list[dict]) -> dict | None:
    """The one person congratulated this week.

    Ties are real and will stay real: two people who never miss are level
    forever, so a fixed tie-break would crown one of them every week until one
    of them slipped, and the other would never once be named. So the crown
    **rotates** — among everyone on the longest streak, it goes to whoever has
    been crowned least recently (never > longest ago), and only then to the
    fuller week, the longer history, and finally the id, so the answer is always
    a single deterministic person."""
    tied = tied_leaders(board)
    if not tied:
        return None
    if len(tied) == 1:
        return tied[0]
    last = db.last_crowned(week_end)
    return min(
        tied,
        key=lambda r: (last.get(r["tg_id"], ""), -r["days"], -r["total"], r["tg_id"]),
    )


def week_cast(week_end: str) -> tuple[list[str], list[dict], dict | None]:
    """Who this week's cards are for: the window's collage days, everyone with a
    full-enough week to be handed one, and the single streak leader among them."""
    dates = db.week_days(week_end, config.WEEK_SPAN_DAYS)
    if len(dates) < config.WEEK_MIN_DAYS:
        return dates, [], None
    board = [
        r
        for r in db.week_board(week_end, config.WEEK_SPAN_DAYS)
        if r["days"] >= config.WEEK_MIN_PHOTOS
    ]
    return dates, board, pick_leader(week_end, board)


async def offer_week_cards(
    context: ContextTypes.DEFAULT_TYPE, week_end: str, *, only: int | None = None
) -> str:
    """Hand everyone their own week back, and ask the streak leader — and only
    them — whether the group should see theirs.

    Everyone else's card carries no buttons at all: it's a gift, not a
    nomination, so there's nothing to decide and nothing to feel second about.

    Idempotent: a row in week_cards means that person already got this week, so
    a restart (or a second /weekcard) can't send it twice."""
    dates, board, leader = week_cast(week_end)
    if len(dates) < config.WEEK_MIN_DAYS:
        return f"only {len(dates)} collage day(s) in the week ending {week_end} — skipped"
    if only is not None:
        board = [r for r in board if r["tg_id"] == only]

    active = set(db.active_user_ids())
    sent = skipped = 0
    won = ""
    names = []
    for row in board:
        uid = row["tg_id"]
        if uid not in active or db.get_week_card(week_end, uid):
            skipped += 1
            continue
        is_leader = leader is not None and uid == leader["tg_id"]
        try:
            card = await render_week_card(week_end, uid, dates, row["streak"])
            if card is None:
                log.warning("week card %s/%s: photos missing", week_end, uid)
                skipped += 1
                continue
            lang = db.get_user_lang(uid)
            if is_leader:
                text = t(
                    lang, "WEEK_CARD",
                    n=row["streak"], k=row["days"], of=len(dates),
                )
                keyboard = week_card_keyboard(week_end, lang)
            else:
                text = t(lang, "WEEK_GIFT", k=row["days"], of=len(dates))
                # Only worth mentioning when the run reaches past this week.
                if row["streak"] > row["days"]:
                    text += t(lang, "WEEK_GIFT_STREAK", n=row["streak"])
                keyboard = None
            db.add_week_card(
                week_end, uid, row["days"], row["streak"],
                status="offered" if is_leader else "gift",
            )
            with open(card, "rb") as f:
                msg = await context.bot.send_photo(
                    uid, f, caption=text, reply_markup=keyboard
                )
            db.set_week_card_file_id(week_end, uid, msg.photo[-1].file_id)
            sent += 1
            u = db.get_user(uid)
            name = u["first_name"] if u else str(uid)
            if is_leader:
                tied = len(tied_leaders(board))
                won = (
                    f"👑 {name} ({row['streak']}🔥"
                    + (f", tie of {tied} — rotated" if tied > 1 else "")
                    + ") was asked to share; "
                )
            else:
                names.append(f"{name} {row['days']}/{len(dates)}")
        except Forbidden:
            db.set_user_status(uid, "inactive")
            skipped += 1
        except Exception:
            log.exception("week card %s to %s failed", week_end, uid)
            skipped += 1

    db.set_setting("week_card_last", week_end)
    note = (
        f"🗓 Week ending {week_end} ({len(dates)} collage days): {won}"
        f"{sent} card(s) sent"
        + (f" — {', '.join(names)}" if names else "")
        + (f", {skipped} skipped" if skipped else "")
    )
    await notify_admins(context, note)
    return note


def share_audience(tg_id: int) -> list[int]:
    """Who a shared week card reaches: everyone in the game except its author,
    who is looking at it already. (A seam the lab script narrows to one chat.)"""
    return [uid for uid in db.active_user_ids() if uid != tg_id]


async def share_week_card(
    context: ContextTypes.DEFAULT_TYPE, week_end: str, tg_id: int
) -> int:
    """Publish an approved card to everyone else. Returns how many got it."""
    row = db.get_week_card(week_end, tg_id)
    user = db.get_user(tg_id)
    name = user["first_name"] if user else str(tg_id)
    audience = share_audience(tg_id)
    file_id = row["file_id"] if row else None
    path = week_card_path(week_end, tg_id)
    sent = 0
    for uid in audience:
        caption = t(db.get_user_lang(uid), "WEEK_CARD_PUBLIC", name=name, n=row["streak"])
        try:
            if file_id:
                await context.bot.send_photo(uid, file_id, caption=caption)
            else:  # card never made it to Telegram (or DB predates file_id)
                with open(path, "rb") as f:
                    msg = await context.bot.send_photo(uid, f, caption=caption)
                file_id = msg.photo[-1].file_id
                db.set_week_card_file_id(week_end, tg_id, file_id)
            sent += 1
        except Forbidden:
            db.set_user_status(uid, "inactive")
        except Exception:
            log.exception("week card share %s/%s to %s failed", week_end, tg_id, uid)
    await notify_admins(
        context, f"🖼 {name} shared their week ({week_end}) — sent to {sent}."
    )
    return sent
