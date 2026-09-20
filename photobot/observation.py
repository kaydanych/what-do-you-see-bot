"""Season 3: return to one familiar place and photograph it over time.

Announcement and start are intentionally separate manual admin actions.  State
lives in SQLite so retries and NAS restarts do not duplicate successful sends.
"""

import asyncio
import csv
import logging
from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, NetworkError, TimedOut

from . import collage, config, db
from .strings import t

log = logging.getLogger(__name__)

_seen_albums: OrderedDict[str, bool] = OrderedDict()

MONTHS_EN = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
MONTHS_RU = (
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def now_local() -> datetime:
    return datetime.now(config.TZ)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def start_date_label(value: str, lang: str | None) -> str:
    day = date.fromisoformat(value)
    if lang == "ru":
        return f"{day.day} {MONTHS_RU[day.month]}"
    return f"{MONTHS_EN[day.month]} {day.day}"


def member_keyboard(season_id: int, lang: str | None, member=None) -> InlineKeyboardMarkup:
    if member is not None and member["status"] == "opted_out":
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                t(lang, "OBS_REJOIN_BUTTON"), callback_data=f"obs:{season_id}:in"
            )
        ]])
    rows = [[InlineKeyboardButton(
        t(lang, "OBS_OPT_OUT_BUTTON"), callback_data=f"obs:{season_id}:out"
    )]]
    if member is not None:
        enabled = bool(member["reminders_enabled"])
        rows.append([InlineKeyboardButton(
            t(lang, "OBS_MUTE_BUTTON" if enabled else "OBS_UNMUTE_BUTTON"),
            callback_data=f"obs:{season_id}:{'mute' if enabled else 'unmute'}",
        )])
    return InlineKeyboardMarkup(rows)


def _remember_album(group_id: str) -> bool:
    if group_id in _seen_albums:
        return True
    _seen_albums[group_id] = True
    while len(_seen_albums) > 200:
        _seen_albums.popitem(last=False)
    return False


async def notify_admins(context, text: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text)
        except Exception:
            log.exception("failed to notify admin %s about Season 3", admin_id)


async def _send_intro(context, season, uid: int, *, late: bool) -> bool:
    member = db.observation_member(season["id"], uid)
    if member is None or member["status"] != "active" or member["intro_sent_at"]:
        return False
    lang = db.get_user_lang(uid)
    key = "OBS_INTRO_LATE" if late else "OBS_INTRO"
    kwargs = {}
    if not late:
        kwargs["start_date"] = start_date_label(season["planned_start_date"], lang)
    try:
        await context.bot.send_message(
            uid,
            t(lang, key, **kwargs),
            reply_markup=member_keyboard(season["id"], lang, member),
        )
    except Forbidden:
        db.set_user_status(uid, "inactive")
        db.mark_observation_member_field(season["id"], uid, "unreachable_at", now_local().isoformat(timespec="seconds"))
        return False
    except Exception:
        log.exception("Season 3 intro to %s failed", uid)
        return False
    sent_at = now_local().isoformat(timespec="seconds")
    db.mark_observation_member_field(season["id"], uid, "intro_sent_at", sent_at)
    if late:
        db.mark_observation_member_field(season["id"], uid, "start_sent_at", sent_at)
    return True


async def maybe_send_current_intro(context, uid: int) -> bool:
    """Enroll and brief a newly approved/reactivated user, once."""
    season = db.current_observation_season()
    user = db.get_user(uid)
    if season is None or user is None or user["status"] != "active":
        return False
    db.ensure_observation_member(season["id"], uid)
    return await _send_intro(
        context, season, uid, late=season["status"] == "active"
    )


async def announce(context, planned_start: date) -> tuple[int, int, int]:
    current = db.current_observation_season()
    if current is not None:
        if current["status"] != "announced":
            raise ValueError("Season 3 is already active")
        season = current
    else:
        season_id = db.create_observation_season(planned_start.isoformat())
        db.set_observation_season_field(
            season_id, "announced_at", now_local().isoformat(timespec="seconds")
        )
        season = db.get_observation_season(season_id)
    # The announcement begins the intermission from the daily collage game;
    # Season 3 submissions themselves remain closed until the manual start.
    db.set_setting("paused", "1")
    enrolled = db.enroll_active_observation_members(season["id"])
    sent = failed = 0
    for member in db.observation_members(season["id"]):
        if member["status"] != "active" or member["user_status"] != "active":
            continue
        if member["intro_sent_at"]:
            continue
        if await _send_intro(context, season, member["tg_id"], late=False):
            sent += 1
        else:
            failed += 1
    return enrolled, sent, failed


async def start(context) -> tuple[object, int, int]:
    season = db.current_observation_season()
    if season is None:
        raise ValueError("No announced Season 3")
    now = now_local()
    if season["status"] == "announced":
        end_date = (now.date() + timedelta(days=season["duration_days"] - 1)).isoformat()
        db.start_observation_season(
            season["id"], now.isoformat(timespec="seconds"), end_date
        )
        # Season 3 owns incoming photos while active; keep the daily collage
        # scheduler in intermission so participants never receive two games.
        db.set_setting("paused", "1")
        season = db.get_observation_season(season["id"])
    sent = failed = 0
    for member in db.observation_members(season["id"]):
        if (
            member["status"] != "active"
            or member["user_status"] != "active"
            or member["start_sent_at"]
        ):
            continue
        try:
            await context.bot.send_message(
                member["tg_id"], t(member["lang"], "OBS_START")
            )
        except Forbidden:
            db.set_user_status(member["tg_id"], "inactive")
            db.mark_observation_member_field(
                season["id"], member["tg_id"], "unreachable_at",
                now.isoformat(timespec="seconds"),
            )
            failed += 1
        except Exception:
            log.exception("Season 3 start to %s failed", member["tg_id"])
            failed += 1
        else:
            db.mark_observation_member_field(
                season["id"], member["tg_id"], "start_sent_at",
                now.isoformat(timespec="seconds"),
            )
            sent += 1
    return season, sent, failed


async def finish(context) -> tuple[object, int, int]:
    season = db.current_observation_season() or db.latest_observation_season()
    if season is None or season["status"] not in {"active", "finished"}:
        raise ValueError("Season 3 is not active")
    now = now_local().isoformat(timespec="seconds")
    if season["status"] == "active":
        db.finish_observation_season(season["id"], now)
        season = db.get_observation_season(season["id"])
    sent = failed = 0
    for member in db.observation_members(season["id"]):
        if (
            member["status"] != "active"
            or member["user_status"] != "active"
            or member["finish_sent_at"]
        ):
            continue
        try:
            await context.bot.send_message(
                member["tg_id"], t(member["lang"], "OBS_FINISHED")
            )
            db.mark_observation_member_field(
                season["id"], member["tg_id"], "finish_sent_at", now
            )
            sent += 1
        except Exception:
            log.exception("Season 3 finish to %s failed", member["tg_id"])
            failed += 1
    return db.get_observation_season(season["id"]), sent, failed


def status_text(season=None) -> str:
    season = season or db.current_observation_season() or db.latest_observation_season()
    if season is None:
        return (
            "🌿 Season 3 has not been announced.\n\n"
            "Preview: /season3announce YYYY-MM-DD\n"
            "Send: /season3announce YYYY-MM-DD yes"
        )
    members = db.observation_members(season["id"])
    photos = db.observation_photos_for(season["id"])
    counts = {
        "active": sum(m["status"] == "active" for m in members),
        "out": sum(m["status"] == "opted_out" for m in members),
        "muted": sum(not m["reminders_enabled"] for m in members if m["status"] == "active"),
        "paused": sum(
            m["ignored_reminders"] >= season["reminder_limit"]
            for m in members if m["status"] == "active"
        ),
        "unreachable": sum(bool(m["unreachable_at"]) for m in members),
    }
    lines = [
        f"🌿 Season 3 #{season['id']} — {season['status']}",
        f"Announced start: {season['planned_start_date']}",
    ]
    if season["started_at"]:
        started = _dt(season["started_at"])
        day_no = max(1, (now_local().date() - started.date()).days + 1)
        lines.append(
            f"Actual start: {started.date()} · day {day_no}/{season['duration_days']} "
            f"· planned end {season['planned_end_date']}"
        )
    lines.extend([
        f"Photos: {len(photos)} total · {sum(p['local_date'] == now_local().date().isoformat() for p in photos)} today",
        f"People: {counts['active']} active · {counts['out']} opted out",
        f"Reminders: {counts['muted']} muted · {counts['paused']} auto-paused",
        f"Unreachable: {counts['unreachable']}",
    ])
    if season["status"] == "announced":
        lines.append("\nNext: /season3start yes when you want submissions to open.")
    elif season["status"] == "active":
        lines.append("\nFinish manually: /season3finish yes")
    return "\n".join(lines)


def admin_keyboard(season=None) -> InlineKeyboardMarkup | None:
    season = season or db.current_observation_season()
    if season is None:
        return None
    if season["status"] == "announced":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Start now", callback_data="obsadmin:start")],
            [InlineKeyboardButton("🔄 Retry missing intros", callback_data="obsadmin:retry")],
        ])
    if season["status"] == "active":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Participants", callback_data="obsadmin:people")],
            [InlineKeyboardButton("🏁 Finish season", callback_data="obsadmin:finish")],
        ])
    return None


def people_text(season_id: int) -> str:
    lines = [f"🌿 Season 3 #{season_id} participants"]
    for member in db.observation_members(season_id):
        mark = "🚪" if member["status"] == "opted_out" else "🌿"
        if member["unreachable_at"]:
            mark = "⚠️"
        uname = f" @{member['username']}" if member["username"] else ""
        last = (member["last_photo_at"] or "—")[:10]
        reminder = "muted" if not member["reminders_enabled"] else str(member["ignored_reminders"])
        lines.append(
            f"{mark} {member['first_name']}{uname} — {member['photo_count']} photo(s), "
            f"last {last}, reminders {reminder}"
        )
    return "\n".join(lines)


async def handle_photo(update, context) -> bool:
    """Claim an image only while the observation season is active."""
    season = db.current_observation_season()
    if season is None or season["status"] != "active":
        return False
    uid = update.effective_user.id
    db.ensure_observation_member(season["id"], uid)
    member = db.observation_member(season["id"], uid)
    lang = db.get_user_lang(uid)
    msg = update.message
    if member["status"] == "opted_out":
        await msg.reply_text(
            t(lang, "OBS_REJOIN_RESEND"),
            reply_markup=member_keyboard(season["id"], lang, member),
        )
        return True
    if msg.media_group_id and _remember_album(msg.media_group_id):
        return True

    local_date = now_local().date().isoformat()
    dest = config.PHOTOS_DIR / f"season3-{season['id']}" / local_date / f"u{uid}.jpg"
    tmp = dest.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    media = msg.photo[-1] if msg.photo else msg.document
    for attempt in range(3):
        try:
            tg_file = await media.get_file()
            await tg_file.download_to_drive(custom_path=tmp)
            break
        except (TimedOut, NetworkError) as exc:
            log.warning("Season 3 photo fetch failed for %s (%s/3): %s", uid, attempt + 1, exc)
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            tmp.unlink(missing_ok=True)
            await msg.reply_text(t(lang, "PHOTO_FAILED"))
            return True
    try:
        collage.save_submission(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    submitted = now_local().isoformat(timespec="seconds")
    replaced = db.upsert_observation_photo(
        season["id"], uid, local_date, str(dest),
        msg.photo[-1].file_id if msg.photo else None, submitted,
    )
    count = len(db.observation_photos_for(season["id"], uid))
    if msg.media_group_id:
        await msg.reply_text(t(lang, "OBS_ALBUM_ONE") + "\n\n" + t(lang, "OBS_ACCEPTED", count=count))
    elif replaced:
        await msg.reply_text(t(lang, "OBS_REPLACED"))
    else:
        await msg.reply_text(t(lang, "OBS_ACCEPTED", count=count))
    return True


async def on_callback(update, context) -> None:
    query = update.callback_query
    try:
        _, sid_raw, action = query.data.split(":", 2)
        season_id = int(sid_raw)
    except (AttributeError, TypeError, ValueError):
        await query.answer()
        return
    season = db.get_observation_season(season_id)
    uid = update.effective_user.id
    user = db.get_user(uid)
    if (
        season is None
        or season["status"] not in {"announced", "active"}
        or user is None
        or user["status"] != "active"
    ):
        await query.answer("This season is no longer available.")
        return
    db.ensure_observation_member(season_id, uid)
    lang = db.get_user_lang(uid)
    if action == "out":
        db.set_observation_member_status(season_id, uid, "opted_out")
        await query.answer()
        await query.edit_message_text(
            t(lang, "OBS_OPTED_OUT"),
            reply_markup=member_keyboard(
                season_id, lang, db.observation_member(season_id, uid)
            ),
        )
    elif action == "in":
        db.set_observation_member_status(season_id, uid, "active")
        await query.answer()
        await query.edit_message_text(
            t(lang, "OBS_REJOINED"),
            reply_markup=member_keyboard(
                season_id, lang, db.observation_member(season_id, uid)
            ),
        )
    elif action in {"mute", "unmute"}:
        enabled = action == "unmute"
        db.set_observation_reminders_enabled(season_id, uid, enabled)
        await query.answer(t(lang, "OBS_REMINDERS_UNMUTED" if enabled else "OBS_REMINDERS_MUTED"))
        await query.edit_message_reply_markup(
            reply_markup=member_keyboard(
                season_id, lang, db.observation_member(season_id, uid)
            )
        )
    else:
        await query.answer()


async def cmd_season(update, context) -> None:
    uid = update.effective_user.id
    lang = db.get_user_lang(uid)
    user = db.get_user(uid)
    if user is None:
        await update.message.reply_text("Send /start first.")
        return
    if user["status"] == "pending":
        await update.message.reply_text(t(lang, "PENDING"))
        return
    if user["status"] == "kicked":
        await update.message.reply_text(t(lang, "KICKED"))
        return
    if user["status"] != "active":
        await update.message.reply_text("Send /start to return to the bot.")
        return
    season = db.current_observation_season()
    if season is None:
        await update.message.reply_text(t(lang, "OBS_STATUS_NONE"))
        return
    db.ensure_observation_member(season["id"], uid)
    text, keyboard = member_status(uid, season)
    await update.message.reply_text(text, reply_markup=keyboard)


def member_status(uid: int, season=None) -> tuple[str, InlineKeyboardMarkup | None]:
    season = season or db.current_observation_season()
    lang = db.get_user_lang(uid)
    if season is None:
        return t(lang, "OBS_STATUS_NONE"), None
    member = db.observation_member(season["id"], uid)
    if member["status"] == "opted_out":
        text = t(lang, "OBS_STATUS_OUT")
    elif season["status"] == "announced":
        text = t(
            lang, "OBS_STATUS_ANNOUNCED",
            start_date=start_date_label(season["planned_start_date"], lang),
        )
    else:
        photos = db.observation_photos_for(season["id"], uid)
        last = photos[-1]["local_date"] if photos else t(lang, "OBS_NO_PHOTOS")
        reminders = t(
            lang,
            "OBS_REMINDERS_ON" if member["reminders_enabled"] else "OBS_REMINDERS_OFF",
        )
        text = t(
            lang, "OBS_STATUS_ACTIVE", count=len(photos), last_date=last,
            reminders=reminders,
        )
    return text, member_keyboard(season["id"], lang, member)


async def send_member_status(context, uid: int) -> None:
    season = db.current_observation_season()
    if season is not None:
        db.ensure_observation_member(season["id"], uid)
    text, keyboard = member_status(uid, season)
    await context.bot.send_message(uid, text, reply_markup=keyboard)


async def send_reminders(context, season, now: datetime) -> tuple[int, int]:
    sent = failed = 0
    started = _dt(season["started_at"])
    if started is None:
        return sent, failed
    for member in db.observation_members(season["id"]):
        if (
            member["status"] != "active"
            or member["user_status"] != "active"
            or not member["reminders_enabled"]
            or member["ignored_reminders"] >= season["reminder_limit"]
            or member["unreachable_at"]
        ):
            continue
        baseline = _dt(member["last_photo_at"]) or started
        last_reminder = _dt(member["last_reminder_at"])
        wait = timedelta(hours=season["reminder_hours"])
        if now - baseline < wait or (last_reminder and now - last_reminder < wait):
            continue
        try:
            await context.bot.send_message(
                member["tg_id"], t(member["lang"], "OBS_REMINDER")
            )
        except Forbidden:
            db.set_user_status(member["tg_id"], "inactive")
            db.mark_observation_member_field(
                season["id"], member["tg_id"], "unreachable_at",
                now.isoformat(timespec="seconds"),
            )
            failed += 1
        except Exception:
            log.exception("Season 3 reminder to %s failed", member["tg_id"])
            failed += 1
        else:
            db.mark_observation_member_field(
                season["id"], member["tg_id"], "ignored_reminders",
                member["ignored_reminders"] + 1,
            )
            db.mark_observation_member_field(
                season["id"], member["tg_id"], "last_reminder_at",
                now.isoformat(timespec="seconds"),
            )
            sent += 1
    return sent, failed


async def tick(context, now: datetime | None = None) -> None:
    now = now or now_local()
    season = db.current_observation_season()
    if season is None or season["status"] != "active":
        return
    reminder_at = time.fromisoformat(season["reminder_time"])
    if now.time() >= reminder_at:
        await send_reminders(context, season, now)
    if now.weekday() == 6 and now.time() >= time(18, 0):
        last = _dt(season["weekly_report_at"])
        if last is None or last.date() != now.date():
            db.set_observation_season_field(
                season["id"], "weekly_report_at", now.isoformat(timespec="seconds")
            )
            await notify_admins(context, status_text(season))


def export_manifest(season_id: int, path: Path) -> int:
    rows = db.observation_photos_for(season_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("season_id", "tg_id", "local_date", "submitted_at", "file_path"))
        for row in rows:
            writer.writerow((
                row["season_id"], row["tg_id"], row["local_date"],
                row["submitted_at"], row["file_path"],
            ))
    return len(rows)
