import asyncio
import logging
from collections import OrderedDict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import ContextTypes

from . import collage, db, jobs
from .strings import CHOOSE_LANG, LANG_BUTTONS, STRINGS, t

log = logging.getLogger(__name__)

# media_group_id -> True for albums we already handled (bounded memory)
_seen_albums: OrderedDict[str, bool] = OrderedDict()


def _remember_album(group_id: str) -> bool:
    """Returns True if this album was already handled."""
    if group_id in _seen_albums:
        return True
    _seen_albums[group_id] = True
    while len(_seen_albums) > 200:
        _seen_albums.popitem(last=False)
    return False


def _times(lang: str | None = None) -> dict:
    return {
        "prompt_time": db.get_setting("prompt_time"),
        "deadline": jobs.deadline_label(lang),
    }


def _lang_keyboard() -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(label, callback_data=f"lang:{code}")
        for label, code in LANG_BUTTONS
    ]
    return InlineKeyboardMarkup([row])


def day_status(now=None) -> tuple[str, dict | None]:
    """('none' | 'open' | 'late', day_row) for the current moment."""
    now = now or jobs.now_local()
    today = now.date().isoformat()
    day = db.get_day(today)
    if day is None or not day["prompt_sent_at"] or day["skipped"]:
        return "none", day
    if now.time() >= jobs.get_times()["deadline"]:
        return "late", day
    return "open", day


async def _register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Ensure the sender exists and is not kicked. Returns False to abort."""
    u = update.effective_user
    row = db.get_user(u.id)
    if row is not None and row["status"] == "kicked":
        await update.message.reply_text(t(row["lang"], "KICKED"))
        return False
    is_new = db.upsert_user(u.id, u.first_name or "", u.username)
    if is_new:
        await jobs.notify_admins(
            context,
            f"👤 New user: {u.first_name} @{u.username or '—'} (id {u.id})",
        )
    return True


async def _send_welcome(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, name: str, lang: str | None
) -> None:
    await context.bot.send_message(
        chat_id, t(lang, "WELCOME", name=name, **_times(lang))
    )
    status, day = day_status()
    if status == "open":
        prompt = db.get_prompt(day["prompt_id"])
        if prompt:
            await context.bot.send_message(chat_id, t(lang, "PROMPT_TODAY_ACTIVE"))
            await context.bot.send_message(
                chat_id, t(lang, "PROMPT", text=jobs.prompt_text(prompt, lang))
            )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _register(update, context):
        return
    u = update.effective_user
    if db.get_user_lang(u.id) is None:
        await update.message.reply_text(CHOOSE_LANG, reply_markup=_lang_keyboard())
        return
    await _send_welcome(
        context, update.effective_chat.id, u.first_name or "", db.get_user_lang(u.id)
    )


async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _register(update, context):
        return
    await update.message.reply_text(CHOOSE_LANG, reply_markup=_lang_keyboard())


async def on_lang_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    lang = query.data.split(":", 1)[1]
    if lang not in STRINGS:
        await query.answer()
        return
    u = update.effective_user
    db.upsert_user(u.id, u.first_name or "", u.username)
    first_choice = db.get_user_lang(u.id) is None
    db.set_user_lang(u.id, lang)
    await query.answer()
    await query.edit_message_text(t(lang, "LANG_SET"))
    if first_choice:
        await _send_welcome(context, query.message.chat_id, u.first_name or "", lang)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = db.get_user_lang(update.effective_user.id)
    db.set_user_status(update.effective_user.id, "inactive")
    await update.message.reply_text(t(lang, "STOPPED"))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = db.get_user_lang(update.effective_user.id)
    await update.message.reply_text(t(lang, "HELP", **_times(lang)))


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _register(update, context):
        return
    lang = db.get_user_lang(update.effective_user.id)
    status, day = day_status()
    if status != "open":
        await update.message.reply_text(t(lang, "NO_ACTIVE_DAY", **_times(lang)))
        return
    prompt = db.get_prompt(day["prompt_id"])
    text = t(lang, "PROMPT", text=jobs.prompt_text(prompt, lang))
    today = jobs.now_local().date().isoformat()
    if update.effective_user.id in db.submitter_ids(today):
        text += t(lang, "TODAY_SUBMITTED")
    else:
        text += t(lang, "TODAY_NOT_SUBMITTED", deadline=jobs.deadline_label(lang))
    await update.message.reply_text(text)


async def _store_feedback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    u = update.effective_user
    db.add_feedback(u.id, text)
    await jobs.notify_admins(
        context,
        f"💬 Feedback from {u.first_name} @{u.username or '—'} (id {u.id}):\n{text}",
    )
    await update.message.reply_text(t(db.get_user_lang(u.id), "FEEDBACK_THANKS"))


async def _store_suggestion(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> None:
    u = update.effective_user
    sid = db.add_suggestion(u.id, text)
    await jobs.notify_admins(
        context,
        f"💡 Suggestion #{sid} from {u.first_name} @{u.username or '—'}:\n«{text}»\n\n"
        f"/approve {sid} <en> | <ru> — queue an edited version,\n"
        f"/approve {sid} — queue as-is, /dismiss {sid} — discard.",
    )
    await update.message.reply_text(t(db.get_user_lang(u.id), "SUGGEST_THANKS"))


async def cmd_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _register(update, context):
        return
    u = update.effective_user
    lang = db.get_user_lang(u.id)
    text = " ".join(context.args).strip()
    if not text:
        # Tapping the command from Telegram's menu sends it with no text — so
        # ask for the message and capture whatever they send next (see on_other).
        context.user_data["awaiting"] = "feedback"
        await update.message.reply_text(t(lang, "FEEDBACK_ASK"))
        return
    await _store_feedback(update, context, text)


async def cmd_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _register(update, context):
        return
    u = update.effective_user
    lang = db.get_user_lang(u.id)
    text = " ".join(context.args).strip()
    if not text:
        context.user_data["awaiting"] = "suggest"
        await update.message.reply_text(t(lang, "SUGGEST_ASK"))
        return
    await _store_suggestion(update, context, text)


async def on_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Collage rating tap: store the vote, refresh tallies on every copy."""
    query = update.callback_query
    _, date, value = query.data.split(":", 2)
    if value not in jobs.RATING_EMOJI:
        await query.answer()
        return
    u = update.effective_user
    lang = db.get_user_lang(u.id)
    changed = db.set_rating(date, u.id, value)
    await query.answer(t(lang, "RATE_THANKS", emoji=jobs.RATING_EMOJI[value]))
    if not changed:
        return
    keyboard = jobs.rating_keyboard(date)
    for row in db.collage_messages_for(date):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=row["tg_id"],
                message_id=row["message_id"],
                reply_markup=keyboard,
            )
        except Exception:
            log.debug(
                "rating keyboard update failed for %s/%s", row["tg_id"], date
            )


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Photo messages and image documents — the actual submissions."""
    if not await _register(update, context):
        return
    # Sending a photo cancels any pending /feedback or /suggest_prompt capture.
    context.user_data.pop("awaiting", None)
    msg = update.message
    lang = db.get_user_lang(update.effective_user.id)

    status, _day = day_status()
    if status == "none":
        await msg.reply_text(t(lang, "NO_ACTIVE_DAY", **_times(lang)))
        return
    if status == "late":
        await msg.reply_text(t(lang, "LATE"))
        return

    if msg.media_group_id and _remember_album(msg.media_group_id):
        return  # rest of an album we already took a photo from

    uid = update.effective_user.id
    date = jobs.now_local().date().isoformat()
    dest = jobs.day_dir(date) / f"u{uid}.jpg"
    tmp = dest.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)

    # Fetching the file from Telegram occasionally times out (flaky network on
    # the host). Retry a few times, then tell the user to resend rather than
    # letting the photo silently vanish.
    media = msg.photo[-1] if msg.photo else msg.document
    for attempt in range(3):
        try:
            tg_file = await media.get_file()
            await tg_file.download_to_drive(custom_path=tmp)
            break
        except (TimedOut, NetworkError) as exc:
            log.warning(
                "photo fetch failed for %s (attempt %d/3): %s", uid, attempt + 1, exc
            )
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            tmp.unlink(missing_ok=True)
            await msg.reply_text(t(lang, "PHOTO_FAILED"))
            return

    try:
        collage.save_submission(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)

    replaced = db.upsert_photo(date, uid, str(dest))
    if msg.media_group_id:
        await msg.reply_text(t(lang, "ALBUM_ONE"))
    elif replaced:
        await msg.reply_text(t(lang, "REPLACED"))
    else:
        await msg.reply_text(t(lang, "ACCEPTED", deadline=jobs.deadline_label(lang)))


async def clear_awaiting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any command cancels a pending /feedback or /suggest_prompt capture.
    Runs in an earlier handler group, so the command it precedes still fires
    (and /feedback / /suggest_prompt re-arm the state right after)."""
    context.user_data.pop("awaiting", None)


async def on_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Text / stickers / video etc. — nudge towards a photo, or capture a
    pending /feedback or /suggest_prompt message."""
    if update.message is None:
        return
    if not await _register(update, context):
        return
    # A tapped /feedback or /suggest_prompt left us waiting for the actual text.
    awaiting = context.user_data.pop("awaiting", None)
    if awaiting and update.message.text:
        text = update.message.text.strip()
        if text:
            if awaiting == "feedback":
                await _store_feedback(update, context, text)
            else:
                await _store_suggestion(update, context, text)
            return
    lang = db.get_user_lang(update.effective_user.id)
    status, _ = day_status()
    if status == "open":
        key = "TEXT_NUDGE" if update.message.text else "NOT_A_PHOTO"
        await update.message.reply_text(t(lang, key))
    else:
        await update.message.reply_text(t(lang, "NO_ACTIVE_DAY", **_times(lang)))
