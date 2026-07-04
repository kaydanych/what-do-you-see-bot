import logging
from datetime import datetime, time, timedelta
from pathlib import Path

from telegram.error import Forbidden
from telegram.ext import ContextTypes

from . import collage, config, db
from .strings import t

log = logging.getLogger(__name__)

LOW_LIBRARY_THRESHOLD = 7


def prompt_text(prompt, lang: str | None) -> str:
    """Prompt in the user's language; English text is the primary/fallback."""
    if lang == "ru" and prompt["text_ru"]:
        return prompt["text_ru"]
    return prompt["text"]


def now_local() -> datetime:
    return datetime.now(config.TZ)


def parse_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    t = time(int(h), int(m))
    return t


def get_times() -> dict:
    return {
        "prompt": parse_hhmm(db.get_setting("prompt_time")),
        "reminder": parse_hhmm(db.get_setting("reminder_time")),
        "deadline": parse_hhmm(db.get_setting("deadline_time")),
        "delay": int(db.get_setting("collage_delay_min")),
    }


def day_dir(date: str) -> Path:
    return config.PHOTOS_DIR / date


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

    if not day["moderation_sent_at"] and nowt >= t["deadline"]:
        await send_moderation(context, today)
        day = db.get_day(today)

    collage_at = datetime.combine(
        now.date(), t["deadline"], tzinfo=config.TZ
    ) + timedelta(minutes=t["delay"])
    if not day["collage_sent_at"] and now >= collage_at:
        await send_collage(context, today)


async def send_prompt(context: ContextTypes.DEFAULT_TYPE, date: str) -> None:
    prompt, recycled = db.pick_prompt()
    if prompt is None:
        db.set_day_field(date, "skipped", 1)
        await notify_admins(
            context,
            "⚠️ Prompt library is EMPTY — today is skipped. Add prompts with "
            "/addprompt or send me a .txt file (one prompt per line).",
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
    if recycled:
        note += "\n♻️ Library exhausted — this prompt was RECYCLED."
    elif unused < LOW_LIBRARY_THRESHOLD:
        note += f"\n⚠️ Only {unused} unused prompts left — time to add more."
    await notify_admins(context, note)


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
    deadline = db.get_setting("deadline_time")
    await send_per_user(
        context,
        targets,
        lambda uid: t(
            db.get_user_lang(uid),
            "REMINDER",
            deadline=deadline,
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
    delay = db.get_setting("collage_delay_min")
    text = (
        f"🔍 Moderation for {date} — collage goes out in {delay} min.\n"
        "/exclude N — drop a photo, /ban N — drop + kick the user,\n"
        "/include N — undo, /forcecollage — send now.\n\n" + "\n".join(lines)
    )
    for admin_id in config.ADMIN_IDS:
        try:
            with open(out, "rb") as f:
                await context.bot.send_photo(admin_id, f)
            for start in range(0, len(text), 3800):
                await context.bot.send_message(admin_id, text[start : start + 3800])
        except Exception:
            log.exception("moderation send to admin %s failed", admin_id)


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

    out = day_dir(date) / ("collage_preview.jpg" if preview_to else "collage.jpg")
    paths = [Path(p["file_path"]) for p in photos]
    collage.build_collage(paths, out)

    n = len(photos)

    def caption_for(uid: int) -> str:
        lang = db.get_user_lang(uid)
        if n == 1:
            return t(lang, "COLLAGE_CAPTION_SOLO")
        return t(lang, "COLLAGE_CAPTION", n=n)

    if preview_to is not None:
        with open(out, "rb") as f:
            await context.bot.send_photo(
                preview_to, f, caption=f"[preview] {caption_for(preview_to)}"
            )
        return f"preview sent ({n} photos)"

    recipients = list(dict.fromkeys(db.submitter_ids(date) + list(config.ADMIN_IDS)))
    file_id = None
    sent = 0
    for uid in recipients:
        try:
            if file_id is None:
                with open(out, "rb") as f:
                    msg = await context.bot.send_photo(uid, f, caption=caption_for(uid))
                file_id = msg.photo[-1].file_id
            else:
                await context.bot.send_photo(uid, file_id, caption=caption_for(uid))
            sent += 1
        except Forbidden:
            db.set_user_status(uid, "inactive")
        except Exception:
            log.exception("collage send to %s failed", uid)

    db.set_day_field(
        date, "collage_sent_at", now_local().isoformat(timespec="seconds")
    )
    await notify_admins(context, f"🖼 {date}: collage from {n} photos sent to {sent}.")
    return f"sent to {sent}"
