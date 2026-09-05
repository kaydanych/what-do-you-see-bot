"""Anonymous two-person visual correspondence seasons.

One shared prompt starts every chain. After the first photograph, each image
answers only the one before it. Photos move immediately, but a recipient must
wait for the season's cooldown before adding the next link. All lifecycle state
lives in SQLite so the NAS can restart at any point without losing a turn.
"""

import asyncio
import logging
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.error import Forbidden, NetworkError, TimedOut

from . import collage, config, db
from .strings import t

log = logging.getLogger(__name__)


def now_local() -> datetime:
    return datetime.now(config.TZ)


def prompt_text(season, lang: str | None) -> str:
    if lang == "ru" and season["prompt_ru"]:
        return season["prompt_ru"]
    return season["prompt"]


def enrollment_keyboard(season_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("📮 I'm in / Я участвую", callback_data=f"corr:enroll:{season_id}:in"),
            InlineKeyboardButton("Not this time / Не сейчас", callback_data=f"corr:enroll:{season_id}:out"),
        ]]
    )


def publication_keyboard(season_id: int, lang: str | None, private: bool = False) -> InlineKeyboardMarkup:
    if private:
        label = "↩️ Снова разрешить публикацию" if lang == "ru" else "↩️ Allow inclusion again"
        decision = "include"
    else:
        label = "🔒 Не публиковать нашу линию" if lang == "ru" else "🔒 Keep our line private"
        decision = "private"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data=f"corr:publish:{season_id}:{decision}")
    ]])


def publication_deadline_label(deadline: datetime, lang: str | None) -> str:
    if lang == "ru":
        return deadline.strftime("%H:%M воскресенья, %d.%m")
    return deadline.strftime("%H:%M on Sunday, %B %d")


def introduction_keyboard(pair_id: int, lang: str | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t(lang, "CORR_INTRO_MEET_BUTTON"),
            callback_data=f"corr:intro:{pair_id}:meet",
        )],
        [InlineKeyboardButton(
            t(lang, "CORR_INTRO_ANONYMOUS_BUTTON"),
            callback_data=f"corr:intro:{pair_id}:anonymous",
        )],
    ])


def introduction_photo_keyboard(
    pair_id: int, tg_id: int, lang: str | None
) -> InlineKeyboardMarkup:
    positions = [
        link["position"] for link in db.correspondence_links(pair_id)
        if link["sender_id"] != tg_id
    ]
    rows = [
        [InlineKeyboardButton(
            f"№{position}" if lang == "ru" else f"#{position}",
            callback_data=f"corr:introphoto:{pair_id}:{position}",
        ) for position in positions[i:i + 5]]
        for i in range(0, len(positions), 5)
    ]
    rows.append([InlineKeyboardButton(
        t(lang, "CORR_INTRO_SKIP_QUESTION_BUTTON"),
        callback_data=f"corr:introphoto:{pair_id}:skip",
    )])
    return InlineKeyboardMarkup(rows)


def introduction_skip_keyboard(
    pair_id: int, action: str, label: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data=f"corr:{action}:{pair_id}:skip")
    ]])


async def notify_admins(context, text: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text)
        except Exception:
            log.exception("failed to notify admin %s about correspondence", admin_id)


async def send_localized(context, recipients: list[int], key: str, **kwargs) -> tuple[int, int]:
    sent = failed = 0
    for uid in recipients:
        try:
            await context.bot.send_message(
                uid, t(db.get_user_lang(uid), key, **kwargs)
            )
            sent += 1
        except Forbidden:
            db.set_user_status(uid, "inactive")
            failed += 1
        except Exception:
            log.exception("correspondence message %s to %s failed", key, uid)
            failed += 1
    return sent, failed


async def open_enrollment(context, season, now: datetime) -> None:
    # Mark first: a crash halfway through the fan-out must not resend it all on
    # the next minute's tick.
    db.set_correspondence_season_field(season["id"], "status", "enrolling")
    db.set_correspondence_season_field(
        season["id"], "enrollment_opened_at", now.isoformat(timespec="seconds")
    )
    sent = failed = 0
    for uid in db.active_user_ids():
        lang = db.get_user_lang(uid)
        try:
            await context.bot.send_message(
                uid,
                t(lang, "CORR_ENROLL_OPEN", prompt=prompt_text(season, lang)),
                reply_markup=enrollment_keyboard(season["id"]),
            )
            sent += 1
        except Forbidden:
            db.set_user_status(uid, "inactive")
            failed += 1
        except Exception:
            log.exception("correspondence enrollment to %s failed", uid)
            failed += 1
    await notify_admins(
        context,
        f"📮 Season #{season['id']} enrollment opened: sent {sent}, failed {failed}. "
        f"Closes {season['starts_at']}.",
    )


async def remind_undecided(context, season, which: int, now: datetime) -> None:
    field = "reminder1_sent_at" if which == 1 else "reminder2_sent_at"
    db.set_correspondence_season_field(
        season["id"], field, now.isoformat(timespec="seconds")
    )
    recipients = db.correspondence_undecided(season["id"])
    for uid in recipients:
        lang = db.get_user_lang(uid)
        try:
            await context.bot.send_message(
                uid,
                t(lang, "CORR_ENROLL_REMINDER"),
                reply_markup=enrollment_keyboard(season["id"]),
            )
        except Forbidden:
            db.set_user_status(uid, "inactive")
        except Exception:
            log.exception("correspondence enrollment reminder to %s failed", uid)
    await notify_admins(
        context, f"📮 Enrollment reminder {which}: {len(recipients)} undecided user(s)."
    )


def _valid_pairing(users: list[int]) -> list[tuple[int, int]] | None:
    blocked = db.correspondence_blocked_pairs()
    rng = random.SystemRandom()
    for _ in range(2000):
        pool = list(users)
        rng.shuffle(pool)
        pairs = list(zip(pool[::2], pool[1::2]))
        if all(tuple(sorted(pair)) not in blocked for pair in pairs):
            return pairs
    return None


async def pair_and_start(context, season_id: int, now: datetime | None = None) -> str:
    now = now or now_local()
    season = db.get_correspondence_season(season_id)
    if season is None:
        return "season not found"
    if not season["prompt"].strip():
        return "season prompt is missing; set it with /seasonprompt <EN> | <RU>"
    users = db.correspondence_enrollees(season_id)
    if len(users) < 2:
        return f"need at least 2 participants ({len(users)} enrolled)"
    if len(users) % 2:
        return f"odd participant count ({len(users)}); one admin account must join or leave"
    if db.correspondence_pairs_for(season_id):
        return "pairs already exist"
    pairs = _valid_pairing(users)
    if pairs is None:
        return "could not find a pairing that respects previous reports"

    started = now.isoformat(timespec="seconds")
    db.set_correspondence_season_field(season_id, "status", "active")
    db.set_correspondence_season_field(season_id, "starts_at", started)
    db.set_correspondence_season_field(season_id, "paired_at", started)
    rng = random.SystemRandom()
    for user_a, user_b in pairs:
        starter = rng.choice((user_a, user_b))
        pair_id = db.create_correspondence_pair(
            season_id, user_a, user_b, starter, started
        )
        for uid in (user_a, user_b):
            lang = db.get_user_lang(uid)
            key = "CORR_STARTER" if uid == starter else "CORR_WAITER"
            try:
                await context.bot.send_message(
                    uid,
                    t(
                        lang,
                        key,
                        prompt=prompt_text(season, lang),
                        target=season["target_links"],
                    ),
                )
            except Forbidden:
                db.set_user_status(uid, "inactive")
                db.set_correspondence_pair_field(pair_id, "status", "ended")
                db.set_correspondence_pair_field(pair_id, "ended_reason", "bot_blocked")
            except Exception:
                log.exception("correspondence start to %s failed", uid)
    await notify_admins(
        context, f"📮 Season #{season_id} started: {len(users)} people, {len(pairs)} chains."
    )
    return f"started {len(pairs)} chain(s)"


def other_user(pair, uid: int) -> int:
    return pair["user_b"] if uid == pair["user_a"] else pair["user_a"]


def available_at(pair, season) -> datetime:
    return datetime.fromisoformat(pair["turn_started_at"]) + timedelta(
        minutes=season["cooldown_minutes"]
    )


def _remaining_label(delta: timedelta, lang: str | None) -> str:
    minutes = max(1, math.ceil(delta.total_seconds() / 60))
    hours, mins = divmod(minutes, 60)
    if lang == "ru":
        if hours and mins:
            return f"{hours} ч {mins} мин"
        return f"{hours} ч" if hours else f"{mins} мин"
    if hours and mins:
        return f"{hours}h {mins}m"
    return f"{hours}h" if hours else f"{mins}m"


def _admin_age_label(delta: timedelta) -> str:
    """Compact English duration for the private admin surface."""
    minutes = max(0, int(delta.total_seconds() // 60))
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{minutes}m"


def admin_pair_summary(pair, season, number: int, now: datetime | None = None) -> str:
    """One anonymous, actionable line for the season's admin pair list."""
    links = len(db.correspondence_links(pair["id"]))
    if pair["status"] == "complete":
        state = "complete"
    elif pair["status"] != "active":
        reason = pair["ended_reason"] or pair["status"]
        state = f"{pair['status']} ({reason})"
    else:
        now = now or now_local()
        age = _admin_age_label(now - datetime.fromisoformat(pair["turn_started_at"]))
        draft = db.correspondence_draft(pair["id"])
        if draft is not None:
            state = f"draft queued · {age}"
        elif links == 0:
            state = f"awaiting first photo · {age}"
        else:
            state = f"awaiting photo {links + 1} · {age}"
    return f"{number}: {links}/{season['target_links']} · {state}"


def admin_pair_detail(pair, season, number: int, now: datetime | None = None) -> str:
    links = len(db.correspondence_links(pair["id"]))
    draft = db.correspondence_draft(pair["id"])
    lines = [
        f"📮 Pair {number} · Season #{season['id']}",
        f"Progress: {links}/{season['target_links']}",
        f"Status: {pair['status']}",
        f"Languages: {_pair_language_summary(pair)}",
    ]
    if pair["status"] == "active":
        now = now or now_local()
        age = _admin_age_label(now - datetime.fromisoformat(pair["turn_started_at"]))
        waiting_for = "first photo" if links == 0 else f"photo {links + 1}"
        lines.extend((f"Waiting for: {waiting_for}", f"Current turn: {age}"))
        if draft is None:
            lines.append("Draft: none")
        else:
            deliver_at = datetime.fromisoformat(draft["deliver_at"])
            if deliver_at <= now:
                lines.append("Draft: due for delivery")
            else:
                lines.append(f"Draft: queued for {deliver_at:%H:%M}")
    elif pair["ended_reason"]:
        lines.append(f"Reason: {pair['ended_reason']}")
    return "\n".join(lines)


def _admin_language_label(tg_id: int) -> str:
    """Human-friendly language for the organizer's private pair controls."""
    return {"en": "English", "ru": "Русский"}.get(
        db.get_user_lang(tg_id), "not chosen"
    )


def _pair_language_summary(pair) -> str:
    """Keep the pair anonymous while making an organizer's message language clear."""
    labels = [
        _admin_language_label(pair["user_a"]),
        _admin_language_label(pair["user_b"]),
    ]
    if pair["status"] == "active":
        awaited = _admin_language_label(pair["next_tg_id"])
        return f"both — {' + '.join(labels)} · awaited — {awaited}"
    return f"both — {' + '.join(labels)}"


def admin_pair_names_text(season) -> str:
    """Private organizer-only map from a season's pair numbers to people."""
    lines = [f"📮 Season #{season['id']} · pair names (admin only)"]
    for number, pair in enumerate(db.correspondence_pairs_for(season["id"]), 1):
        people = []
        for tg_id in (pair["user_a"], pair["user_b"]):
            user = db.get_user(tg_id)
            if user is None:
                people.append(f"id {tg_id}")
                continue
            name = (user["first_name"] or "").strip() or f"id {tg_id}"
            username = f" @{user['username']}" if user["username"] else ""
            people.append(f"{name}{username}")
        lines.append(f"{number}: {' ↔ '.join(people)}")
    return "\n".join(lines)


async def send_admin_pair_message(
    context,
    pair_id: int,
    scope: str,
    text: str,
    expected_awaited_id: int | None = None,
) -> tuple[int, int]:
    """Send a host message without exposing either member to the other."""
    pair = db.get_correspondence_pair(pair_id)
    if pair is None:
        return 0, 0
    if scope == "both":
        recipients = (pair["user_a"], pair["user_b"])
    elif (
        scope == "awaited"
        and pair["status"] == "active"
        and db.correspondence_draft(pair_id) is None
        and pair["next_tg_id"] == expected_awaited_id
    ):
        recipients = (pair["next_tg_id"],)
    else:
        return 0, 0
    return await send_localized(context, list(recipients), "ORGANIZER_MESSAGE", text=text)


async def handle_photo(update, context) -> bool:
    """Consume a photo when the sender belongs to the current active season.

    Returns False only when correspondence has nothing to do with this user, so
    the legacy daily-photo handler may continue normally.
    """
    season = db.current_correspondence_season()
    if season is None or season["status"] != "active":
        return False
    uid = update.effective_user.id
    pair = db.correspondence_pair_for_user(season["id"], uid)
    if pair is None:
        return False
    lang = db.get_user_lang(uid)
    msg = update.message
    if pair["status"] == "complete":
        await msg.reply_text(t(lang, "CORR_ALREADY_COMPLETE"))
        return True
    if pair["status"] != "active":
        await msg.reply_text(t(lang, "CORR_NO_LONGER_ACTIVE"))
        return True
    if pair["next_tg_id"] != uid:
        await msg.reply_text(t(lang, "CORR_NOT_YOUR_TURN"))
        return True

    links = db.correspondence_links(pair["id"])
    now = now_local()
    deliver_at = available_at(pair, season) if links else now
    position = len(links) + 1
    dest = (
        config.PHOTOS_DIR
        / "correspondence"
        / f"s{season['id']}"
        / f"p{pair['id']}"
        / f"draft{position:02d}-{now:%Y%m%dT%H%M%S%f}.jpg"
    )
    tmp = dest.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    media = msg.photo[-1] if msg.photo else msg.document
    for attempt in range(3):
        try:
            tg_file = await media.get_file()
            await tg_file.download_to_drive(custom_path=tmp)
            break
        except (TimedOut, NetworkError) as exc:
            log.warning("correspondence photo fetch %s attempt %s: %s", uid, attempt + 1, exc)
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

    submitted = now.isoformat(timespec="seconds")
    previous = db.correspondence_draft(pair["id"])
    try:
        replaced = db.upsert_correspondence_draft(
            pair["id"],
            uid,
            position,
            str(dest),
            media.file_id,
            submitted,
            deliver_at.isoformat(timespec="seconds"),
        )
    except ValueError:
        dest.unlink(missing_ok=True)
        await msg.reply_text(t(lang, "CORR_TURN_CHANGED"))
        return True
    if previous is not None and previous["file_path"] != str(dest):
        Path(previous["file_path"]).unlink(missing_ok=True)

    if now < deliver_at:
        await msg.reply_text(t(
            lang,
            "CORR_DRAFT_REPLACED" if replaced else "CORR_DRAFT_SAVED",
            remaining=_remaining_label(deliver_at - now, lang),
            time=deliver_at.strftime("%H:%M"),
        ))
        return True

    draft = db.claim_due_correspondence_draft(pair["id"], submitted)
    if draft is None:
        await msg.reply_text(t(lang, "CORR_TURN_CHANGED"))
        return True
    await deliver_draft(context, season, pair, draft, now)
    return True


async def deliver_draft(context, season, pair, draft, now: datetime) -> bool:
    """Deliver one scheduler-claimed draft, then advance the chain."""
    sender = draft["sender_id"]
    sender_lang = db.get_user_lang(sender)
    recipient = other_user(pair, sender)
    recipient_lang = db.get_user_lang(recipient)
    position = draft["position"]
    finished = position == season["target_links"]
    caption = t(
        recipient_lang,
        "CORR_RECEIVED_FINAL" if finished else "CORR_RECEIVED",
        position=position,
        target=season["target_links"],
        wait=_remaining_label(
            timedelta(minutes=season["cooldown_minutes"]), recipient_lang
        ),
    )
    try:
        delivered = None
        local_path = Path(draft["file_path"])
        sources = []
        if local_path.is_file():
            sources.append(("saved file", local_path))
        if draft["telegram_file_id"]:
            # Telegram file IDs are a second durable copy. They let a queued
            # delivery survive a missing/corrupt bind-mounted file on the NAS.
            sources.append(("Telegram file", draft["telegram_file_id"]))
        if not sources:
            raise FileNotFoundError(f"queued photo is missing: {local_path}")

        errors = []
        for source_name, source in sources:
            for attempt in range(3):
                try:
                    if isinstance(source, Path):
                        with source.open("rb") as photo:
                            delivered = await context.bot.send_photo(
                                recipient, photo, caption=caption
                            )
                    else:
                        delivered = await context.bot.send_photo(
                            recipient, source, caption=caption
                        )
                    break
                except Forbidden:
                    raise
                except (TimedOut, NetworkError) as exc:
                    log.warning(
                        "correspondence draft %s %s attempt %s: %s",
                        pair["id"], source_name, attempt + 1, exc,
                    )
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    errors.append(exc)
                except Exception as exc:
                    # A normalized local JPEG can still become unavailable or
                    # unreadable later. Try Telegram's retained copy before
                    # postponing the turn.
                    log.warning(
                        "correspondence draft %s %s failed: %s",
                        pair["id"], source_name, exc,
                    )
                    errors.append(exc)
                    break
            if delivered is not None:
                break
        if delivered is None:
            raise errors[-1] if errors else RuntimeError("no photo delivery source")
    except Forbidden:
        db.set_user_status(recipient, "inactive")
        db.set_correspondence_pair_field(pair["id"], "status", "ended")
        db.set_correspondence_pair_field(pair["id"], "ended_reason", "bot_blocked")
        await notify_admins(
            context, f"⚠️ Chain #{pair['id']} ended: recipient {recipient} blocked the bot."
        )
        await context.bot.send_message(sender, t(sender_lang, "CORR_DELIVERY_FAILED"))
        return False
    except Exception as exc:
        log.exception("correspondence draft for pair %s delivery failed", pair["id"])
        prior_attempts = draft["delivery_attempts"] or 0
        retry_minutes = min(60, 5 * (3 ** min(prior_attempts, 3)))
        retry_at = now + timedelta(minutes=retry_minutes)
        attempts = db.defer_correspondence_draft(
            pair["id"], f"{type(exc).__name__}: {exc}",
            retry_at.isoformat(timespec="seconds"),
        )
        if attempts == 1:
            await notify_admins(
                context,
                f"⚠️ Chain #{pair['id']} photo delivery delayed "
                f"({type(exc).__name__}); retrying in {retry_minutes} min.",
            )
            try:
                await context.bot.send_message(
                    sender, t(sender_lang, "CORR_DELIVERY_DELAYED")
                )
            except Exception:
                log.exception("could not notify correspondence sender %s", sender)
        return False

    delivered_at = now.isoformat(timespec="seconds")
    try:
        link = db.add_correspondence_link(
            pair["id"], sender, draft["file_path"], delivered_at,
            season["target_links"],
        )
    except ValueError:
        log.exception("draft for chain %s was sent but could not be committed", pair["id"])
        db.set_correspondence_pair_field(pair["id"], "status", "ended")
        db.set_correspondence_pair_field(pair["id"], "ended_reason", "commit_failed")
        await notify_admins(
            context, f"⚠️ Chain #{pair['id']} frozen after delivery state changed."
        )
        return False
    if delivered and delivered.photo:
        db.set_correspondence_link_file_id(link["id"], delivered.photo[-1].file_id)
    try:
        await context.bot.send_message(sender, t(
            sender_lang,
            "CORR_SENT_FINAL" if finished else "CORR_SENT",
            position=position,
            target=season["target_links"],
        ))
    except Exception:
        log.debug("could not confirm correspondence delivery to %s", sender)
    if finished:
        await notify_admins(
            context, f"✅ Chain #{pair['id']} completed all {position} links."
        )
    return True


async def _end_pair(context, pair, actor: int, reason: str, report: bool = False) -> None:
    status = "reported" if report else "ended"
    db.set_correspondence_pair_field(pair["id"], "status", status)
    db.set_correspondence_pair_field(pair["id"], "ended_reason", reason)
    if report:
        latest = db.latest_correspondence_link(pair["id"])
        db.set_correspondence_pair_field(pair["id"], "reported_by", actor)
        db.set_correspondence_pair_field(
            pair["id"], "reported_link_id", latest["id"] if latest else None
        )
        db.block_correspondence_pair(pair["user_a"], pair["user_b"], "reported")
    partner = other_user(pair, actor)
    try:
        await context.bot.send_message(
            partner, t(db.get_user_lang(partner), "CORR_PARTNER_ENDED")
        )
    except Exception:
        log.debug("could not notify partner %s that chain ended", partner)


async def send_introduction_offer(context, pair_id: int, tg_id: int) -> bool:
    response = db.correspondence_introduction_response(pair_id, tg_id)
    pair = db.get_correspondence_pair(pair_id)
    if response is None or pair is None or response["offer_sent_at"]:
        return False
    lang = db.get_user_lang(tg_id)
    try:
        await context.bot.send_message(
            tg_id,
            t(lang, "CORR_INTRO_OFFER"),
            reply_markup=introduction_keyboard(pair_id, lang),
        )
    except Forbidden:
        db.set_user_status(tg_id, "inactive")
        db.mark_correspondence_introduction_offer_sent(
            pair_id, tg_id, now_local().isoformat(timespec="seconds")
        )
        return False
    except Exception:
        log.exception("introduction offer for pair %s to %s failed", pair_id, tg_id)
        return False
    db.mark_correspondence_introduction_offer_sent(
        pair_id, tg_id, now_local().isoformat(timespec="seconds")
    )
    return True


async def open_introductions(context, season_id: int) -> tuple[int, int, int]:
    """Offer a mutual introduction to every completed pair in one season."""
    now = now_local().isoformat(timespec="seconds")
    opened = 0
    for pair in db.correspondence_pairs_for(season_id):
        if pair["status"] == "complete":
            opened += int(db.offer_correspondence_introduction(pair["id"], now))
    sent = failed = 0
    for response in db.pending_correspondence_introduction_offers():
        pair = db.get_correspondence_pair(response["pair_id"])
        if pair is None or pair["season_id"] != season_id:
            continue
        if await send_introduction_offer(context, pair["id"], response["tg_id"]):
            sent += 1
        else:
            failed += 1
    return opened, sent, failed


async def send_introduction_questions(context, pair_id: int, tg_id: int) -> bool:
    """Show one participant the frames they received, then ask question 1."""
    response = db.correspondence_introduction_response(pair_id, tg_id)
    if response is None or response["questions_sent_at"] or response["stage"] != "photo":
        return False
    lang = db.get_user_lang(tg_id)
    links = [
        link for link in db.correspondence_links(pair_id)
        if link["sender_id"] != tg_id
    ]
    if not links:
        log.error("introduction pair %s has no received photos for %s", pair_id, tg_id)
        return False

    opened = []
    media = []
    try:
        for index, link in enumerate(links):
            source = link["file_id"]
            if not source:
                source = Path(link["file_path"]).open("rb")
                opened.append(source)
            key = "CORR_INTRO_PHOTO_FIRST_CAPTION" if index == 0 else "CORR_INTRO_PHOTO_CAPTION"
            media.append(InputMediaPhoto(
                source, caption=t(lang, key, position=link["position"])
            ))
        await context.bot.send_message(tg_id, t(lang, "CORR_INTRO_MUTUAL"))
        if len(media) == 1:
            await context.bot.send_photo(
                tg_id, media[0].media, caption=media[0].caption
            )
        else:
            await context.bot.send_media_group(tg_id, media=media)
        await context.bot.send_message(
            tg_id,
            t(lang, "CORR_INTRO_FAVORITE_ASK"),
            reply_markup=introduction_photo_keyboard(pair_id, tg_id, lang),
        )
    except Forbidden:
        db.set_user_status(tg_id, "inactive")
        db.mark_correspondence_introduction_questions_sent(
            pair_id, tg_id, now_local().isoformat(timespec="seconds")
        )
        return False
    except Exception:
        log.exception("introduction questions for pair %s to %s failed", pair_id, tg_id)
        return False
    finally:
        for handle in opened:
            handle.close()
    db.mark_correspondence_introduction_questions_sent(
        pair_id, tg_id, now_local().isoformat(timespec="seconds")
    )
    return True


def _introduction_text(pair_id: int, recipient: int) -> tuple[str, InlineKeyboardMarkup] | None:
    pair = db.get_correspondence_pair(pair_id)
    if pair is None:
        return None
    partner_id = other_user(pair, recipient)
    response = db.correspondence_introduction_response(pair_id, partner_id)
    if response is None or not response["share_username"]:
        return None
    lang = db.get_user_lang(recipient)
    username = response["share_username"]
    name = (response["share_name"] or "").strip() or f"@{username}"
    parts = [t(
        lang, "CORR_INTRO_REVEAL", name=name, username=username
    )]
    if response["favorite_position"] is not None:
        key = (
            "CORR_INTRO_FAVORITE_REASON"
            if response["favorite_reason"]
            else "CORR_INTRO_FAVORITE_ONLY"
        )
        parts.append(t(
            lang,
            key,
            name=name,
            position=response["favorite_position"],
            answer=response["favorite_reason"] or "",
        ))
    if response["question"]:
        parts.append(t(
            lang, "CORR_INTRO_QUESTION_FROM", name=name, answer=response["question"]
        ))
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            t(lang, "CORR_INTRO_MESSAGE_BUTTON", name=name[:40]),
            url=f"https://t.me/{username}",
        )
    ]])
    return "\n\n".join(parts), keyboard


async def send_due_introductions(context, now: datetime | None = None) -> None:
    now = now or now_local()
    stamp = now.isoformat(timespec="seconds")
    for pair_id in db.due_correspondence_introductions(stamp):
        pair = db.get_correspondence_pair(pair_id)
        if pair is None:
            continue
        for uid in (pair["user_a"], pair["user_b"]):
            response = db.correspondence_introduction_response(pair_id, uid)
            if response is None or response["introduction_sent_at"]:
                continue
            payload = _introduction_text(pair_id, uid)
            if payload is None:
                await notify_admins(
                    context,
                    f"⚠️ Pair #{pair_id} introduction is missing a Telegram username.",
                )
                continue
            text, keyboard = payload
            try:
                await context.bot.send_message(uid, text, reply_markup=keyboard)
            except Forbidden:
                db.set_user_status(uid, "inactive")
                db.mark_correspondence_introduction_sent(pair_id, uid, stamp)
            except Exception:
                log.exception("introduction for pair %s to %s failed", pair_id, uid)
            else:
                db.mark_correspondence_introduction_sent(pair_id, uid, stamp)


async def handle_introduction_text(update, context, response, text: str) -> None:
    """Capture the optional explanation or question after mutual consent."""
    uid = update.effective_user.id
    pair_id = response["pair_id"]
    lang = db.get_user_lang(uid)
    value = text.strip()[:1000]
    if response["stage"] == "reason":
        if not db.save_correspondence_introduction_reason(pair_id, uid, value):
            return
        await update.message.reply_text(
            t(lang, "CORR_INTRO_QUESTION_ASK"),
            reply_markup=introduction_skip_keyboard(
                pair_id, "introquestion", t(lang, "CORR_INTRO_SKIP_QUESTION_BUTTON")
            ),
        )
        return
    if response["stage"] == "question":
        if not db.save_correspondence_introduction_question(
            pair_id, uid, value, now_local().isoformat(timespec="seconds")
        ):
            return
        await update.message.reply_text(t(lang, "CORR_INTRO_READY"))
        await send_due_introductions(context)


async def process_introductions(context, now: datetime) -> None:
    """Retry durable intro delivery and enforce the 24-hour reveal deadline."""
    for response in db.pending_correspondence_introduction_offers():
        await send_introduction_offer(context, response["pair_id"], response["tg_id"])
    for response in db.correspondence_introduction_question_recipients():
        await send_introduction_questions(context, response["pair_id"], response["tg_id"])
    await send_due_introductions(context, now)


async def on_callback(update, context) -> None:
    query = update.callback_query
    parts = query.data.split(":")
    if len(parts) < 3:
        await query.answer()
        return
    action = parts[1]
    uid = update.effective_user.id
    lang = db.get_user_lang(uid)

    if action == "enroll" and len(parts) == 4:
        try:
            season_id = int(parts[2])
        except ValueError:
            await query.answer()
            return
        decision = parts[3]
        if decision not in {"in", "out"}:
            await query.answer()
            return
        season = db.get_correspondence_season(season_id)
        if season is None or season["status"] not in {"enrolling", "pairing"}:
            await query.answer(t(lang, "CORR_ENROLL_CLOSED"), show_alert=True)
            return
        db.set_correspondence_enrollment(season_id, uid, decision)
        await query.answer(t(lang, "CORR_JOINED" if decision == "in" else "CORR_DECLINED"))
        # Keep both choices available until pairing so someone can change their
        # mind — and an admin account can deliberately fix an odd participant pool.
        # An admin fixing an odd pool after Monday should start it immediately.
        season = db.get_correspondence_season(season_id)
        if season["status"] == "pairing" and len(db.correspondence_enrollees(season_id)) % 2 == 0:
            await pair_and_start(context, season_id)
        return

    if action == "publish" and len(parts) == 4:
        try:
            season_id = int(parts[2])
        except ValueError:
            await query.answer()
            return
        decision = parts[3]
        season = db.get_correspondence_season(season_id)
        pair = db.correspondence_pair_for_user(season_id, uid) if season else None
        if pair is None or decision not in {"include", "private"}:
            await query.answer(t(lang, "CORR_NOT_YOURS"), show_alert=True)
            return
        deadline_raw = season["publication_opt_out_deadline"]
        deadline = datetime.fromisoformat(deadline_raw) if deadline_raw else None
        if deadline is None or now_local() >= deadline:
            await query.answer(t(lang, "CORR_PUBLICATION_CLOSED"), show_alert=True)
            return
        db.set_correspondence_publication_choice(season_id, uid, decision)
        label = publication_deadline_label(deadline, lang)
        key = "CORR_PUBLICATION_PRIVATE" if decision == "private" else "CORR_PUBLICATION_INCLUDED"
        await query.answer(t(lang, key, deadline=label), show_alert=True)
        await query.edit_message_reply_markup(
            reply_markup=publication_keyboard(season_id, lang, decision == "private")
        )
        return

    try:
        pair_id = int(parts[2])
    except ValueError:
        await query.answer()
        return
    pair = db.get_correspondence_pair(pair_id)
    if pair is None or uid not in {pair["user_a"], pair["user_b"]}:
        await query.answer(t(lang, "CORR_NOT_YOURS"), show_alert=True)
        return

    if action == "intro" and len(parts) == 4:
        response = db.correspondence_introduction_response(pair_id, uid)
        if pair["status"] != "complete" or response is None:
            await query.answer(t(lang, "CORR_NO_LONGER_ACTIVE"), show_alert=True)
            return
        if response["introduction_sent_at"]:
            await query.answer(t(lang, "CORR_INTRO_ALREADY_SENT"), show_alert=True)
            return
        decision = parts[3]
        if decision not in {"meet", "anonymous"}:
            await query.answer()
            return
        user = update.effective_user
        if hasattr(user, "username"):
            db.update_user_identity(
                uid, getattr(user, "first_name", "") or "", user.username
            )
        saved_user = db.get_user(uid)
        if decision == "meet" and not saved_user["username"]:
            await query.answer(
                t(lang, "CORR_INTRO_USERNAME_REQUIRED"), show_alert=True
            )
            return
        now = now_local()
        result = db.set_correspondence_introduction_decision(
            pair_id,
            uid,
            decision,
            now.isoformat(timespec="seconds"),
            (now + timedelta(hours=24)).isoformat(timespec="seconds"),
            share_name=saved_user["first_name"],
            share_username=saved_user["username"],
        )
        if result == "missing":
            await query.answer(t(lang, "CORR_NOT_YOURS"), show_alert=True)
            return
        key = (
            "CORR_INTRO_STAYED_ANONYMOUS"
            if decision == "anonymous"
            else "CORR_INTRO_WAITING"
        )
        await query.answer(t(lang, key), show_alert=True)
        await query.edit_message_reply_markup(reply_markup=None)
        if result == "mutual":
            for pending in db.correspondence_introduction_question_recipients():
                if pending["pair_id"] == pair_id:
                    await send_introduction_questions(context, pair_id, pending["tg_id"])
        return

    if action == "introphoto" and len(parts) == 4:
        raw_position = parts[3]
        try:
            position = None if raw_position == "skip" else int(raw_position)
        except ValueError:
            await query.answer()
            return
        if not db.select_correspondence_introduction_photo(pair_id, uid, position):
            await query.answer(t(lang, "CORR_INTRO_ALREADY_DECIDED"), show_alert=True)
            return
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        if position is None:
            await context.bot.send_message(
                uid,
                t(lang, "CORR_INTRO_QUESTION_ASK"),
                reply_markup=introduction_skip_keyboard(
                    pair_id,
                    "introquestion",
                    t(lang, "CORR_INTRO_SKIP_QUESTION_BUTTON"),
                ),
            )
        else:
            await context.bot.send_message(
                uid,
                t(lang, "CORR_INTRO_REASON_ASK", position=position),
                reply_markup=introduction_skip_keyboard(
                    pair_id,
                    "introreason",
                    t(lang, "CORR_INTRO_SKIP_REASON_BUTTON"),
                ),
            )
        return

    if action == "introreason" and len(parts) == 4 and parts[3] == "skip":
        if not db.save_correspondence_introduction_reason(pair_id, uid, None):
            await query.answer(t(lang, "CORR_INTRO_ALREADY_DECIDED"), show_alert=True)
            return
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            uid,
            t(lang, "CORR_INTRO_QUESTION_ASK"),
            reply_markup=introduction_skip_keyboard(
                pair_id,
                "introquestion",
                t(lang, "CORR_INTRO_SKIP_QUESTION_BUTTON"),
            ),
        )
        return

    if action == "introquestion" and len(parts) == 4 and parts[3] == "skip":
        if not db.save_correspondence_introduction_question(
            pair_id, uid, None, now_local().isoformat(timespec="seconds")
        ):
            await query.answer(t(lang, "CORR_INTRO_ALREADY_DECIDED"), show_alert=True)
            return
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(uid, t(lang, "CORR_INTRO_READY"))
        await send_due_introductions(context)
        return

    if pair["status"] != "active":
        await query.answer(t(lang, "CORR_NO_LONGER_ACTIVE"), show_alert=True)
        return
    if action in {"menu", "back", "leaveask", "leaveyes", "report"}:
        # Season 2 originally attached an end/report control to every chain
        # message.  Existing Telegram messages cannot be edited without their
        # message IDs, which were not retained, so make those old controls
        # harmless and remove the keyboard from the message when one is tapped.
        await query.answer(t(lang, "CORR_SAFETY_MOVED"), show_alert=True)
        await query.edit_message_reply_markup(reply_markup=None)
    else:
        await query.answer()


async def capture_report_note(update, context, pair_id: int, text: str) -> None:
    context.user_data.pop("awaiting", None)
    await notify_admins(
        context,
        f"📝 Report note for anonymous chain #{pair_id} from {update.effective_user.id}:\n{text[:3000]}",
    )
    await update.message.reply_text(t(db.get_user_lang(update.effective_user.id), "CORR_REPORT_THANKS"))


async def end_for_admin(context, tg_id: int) -> list[int]:
    """End a kicked user's chains and tell the anonymous partner only."""
    pairs = []
    season = db.current_correspondence_season()
    if season is not None:
        pair = db.correspondence_pair_for_user(season["id"], tg_id)
        if pair is not None and pair["status"] == "active":
            pairs.append(pair)
    for pair in pairs:
        db.set_correspondence_pair_field(pair["id"], "status", "ended")
        db.set_correspondence_pair_field(pair["id"], "ended_reason", "admin_kick")
        partner = other_user(pair, tg_id)
        try:
            await context.bot.send_message(
                partner, t(db.get_user_lang(partner), "CORR_PARTNER_ENDED")
            )
        except Exception:
            log.debug("could not notify partner %s after admin kick", partner)
    return [pair["id"] for pair in pairs]


async def tick(context, now: datetime) -> None:
    # Introductions outlive the active season and must keep progressing after
    # /seasonfinish closes it.
    await process_introductions(context, now)
    season = db.current_correspondence_season()
    if season is None:
        return
    opens = datetime.fromisoformat(season["enrollment_opens_at"])
    reminder1 = datetime.fromisoformat(season["enrollment_reminder1_at"])
    reminder2 = datetime.fromisoformat(season["enrollment_reminder2_at"])
    starts = datetime.fromisoformat(season["starts_at"])
    ends = datetime.fromisoformat(season["ends_at"])

    if season["status"] == "scheduled" and now >= opens:
        await open_enrollment(context, season, now)
        season = db.get_correspondence_season(season["id"])
    if season["status"] == "enrolling":
        if not season["reminder1_sent_at"] and now >= reminder1:
            await remind_undecided(context, season, 1, now)
            season = db.get_correspondence_season(season["id"])
        if not season["reminder2_sent_at"] and now >= reminder2:
            await remind_undecided(context, season, 2, now)
            season = db.get_correspondence_season(season["id"])
        if now >= starts:
            db.set_correspondence_season_field(season["id"], "status", "pairing")
            result = await pair_and_start(context, season["id"], now)
            if not result.startswith("started"):
                await notify_admins(context, f"⚠️ Season #{season['id']} waiting to pair: {result}.")
            season = db.get_correspondence_season(season["id"])
    elif season["status"] == "pairing":
        users = db.correspondence_enrollees(season["id"])
        if len(users) >= 2 and len(users) % 2 == 0:
            await pair_and_start(context, season["id"], now)
            season = db.get_correspondence_season(season["id"])

    # ``ends_at`` is now a review point, not an automatic shutdown.  The
    # organizer decides when the remaining chains are satisfactory and closes
    # the season explicitly with /seasonfinish yes.
    if now >= ends and not season["planned_end_notified_at"]:
        db.set_correspondence_season_field(
            season["id"], "planned_end_notified_at", now.isoformat(timespec="seconds")
        )
        await notify_admins(
            context,
            f"📮 Season #{season['id']} reached its planned end. Active chains remain "
            "open; review /seasonpairs and close when ready with /seasonfinish yes.",
        )
    if season["status"] != "active":
        return

    for pair in db.correspondence_pairs_for(season["id"]):
        if pair["status"] != "active":
            continue
        uid = pair["next_tg_id"]
        turn = datetime.fromisoformat(pair["turn_started_at"])
        links = db.correspondence_links(pair["id"])
        draft = db.correspondence_draft(pair["id"])
        if draft is not None and now >= datetime.fromisoformat(draft["deliver_at"]):
            claimed = db.claim_due_correspondence_draft(
                pair["id"], now.isoformat(timespec="seconds")
            )
            if claimed is not None:
                await deliver_draft(context, season, pair, claimed, now)
                continue
        if (
            links
            and draft is None
            and not pair["ready_notified_at"]
            and now >= available_at(pair, season)
        ):
            db.set_correspondence_pair_field(
                pair["id"], "ready_notified_at", now.isoformat(timespec="seconds")
            )
            try:
                await context.bot.send_message(
                    uid, t(db.get_user_lang(uid), "CORR_TURN_READY")
                )
            except Exception:
                log.exception("ready notification for chain %s failed", pair["id"])
        if not pair["reminder24_at"] and now >= turn + timedelta(hours=24):
            db.set_correspondence_pair_field(
                pair["id"], "reminder24_at", now.isoformat(timespec="seconds")
            )
            try:
                await context.bot.send_message(
                    uid, t(db.get_user_lang(uid), "CORR_REMINDER_24"),
                )
            except Exception:
                log.exception("24h reminder for chain %s failed", pair["id"])
        if not pair["reminder48_at"] and now >= turn + timedelta(hours=48):
            db.set_correspondence_pair_field(
                pair["id"], "reminder48_at", now.isoformat(timespec="seconds")
            )
            try:
                await context.bot.send_message(
                    uid, t(db.get_user_lang(uid), "CORR_REMINDER_48"),
                )
            except Exception:
                log.exception("48h reminder for chain %s failed", pair["id"])
            await notify_admins(
                context, f"⏳ Chain #{pair['id']} has waited 48h for user {uid}."
            )


def status_text(season) -> str:
    enrollees = db.correspondence_enrollees(season["id"])
    pairs = db.correspondence_pairs_for(season["id"])
    complete = sum(1 for p in pairs if p["status"] == "complete")
    active = sum(1 for p in pairs if p["status"] == "active")
    ended = len(pairs) - complete - active
    links = sum(len(db.correspondence_links(p["id"])) for p in pairs)
    return (
        f"📮 Season #{season['id']} · {season['name']}\n"
        f"Status: {season['status']}" + (" · TEST" if season["is_test"] else "") + "\n"
        f"Enrollment: {len(enrollees)} in / {len(db.correspondence_enrollees(season['id'], 'out'))} out / "
        f"{len(db.correspondence_undecided(season['id']))} undecided\n"
        f"Chains: {active} active · {complete} complete · {ended} ended\n"
        f"Links: {links} · target {season['target_links']} each · cooldown {season['cooldown_minutes']} min\n"
        f"Starts: {season['starts_at']}\nEnds: {season['ends_at']}\n"
        "Pair details: /seasonpairs"
    )
