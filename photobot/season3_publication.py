"""Persistent, consent-checked delivery of the published Season 3 website."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urlparse

from telegram.error import Forbidden
from telegram.ext import ContextTypes

from . import config, db
from .season3_consents import consent_fingerprint
from .strings import t

log = logging.getLogger(__name__)
HOME_URL = "https://what-do-you-see.art/"


def validate_private_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(
        parsed.scheme == "https"
        and parsed.netloc == "what-do-you-see.art"
        and re.fullmatch(r"/season3/private/[A-Za-z0-9_-]+/index\.html", parsed.path)
        and not parsed.query
        and not parsed.fragment
    )


def schedule(
    due_date: str, due_time: str, fingerprint: str, private_tg_id: int,
    private_url: str, now: datetime | None = None,
) -> tuple[int, datetime]:
    season = db.latest_observation_season()
    if season is None or season["status"] != "finished":
        raise ValueError("Season 3 must be finished first.")
    if db.latest_season3_publication(season["id"]):
        raise ValueError(
            "A Season 3 website send already exists. Check /season3publishat status; "
            "cancel a pending send before scheduling again."
        )
    try:
        due = datetime.strptime(f"{due_date} {due_time}", "%Y-%m-%d %H:%M").replace(tzinfo=config.TZ)
    except ValueError as exc:
        raise ValueError("Use YYYY-MM-DD HH:MM in Berlin time.") from exc
    if due <= (now or datetime.now(config.TZ)):
        raise ValueError("Choose a future time in Berlin.")
    members = db.observation_members(season["id"])
    if fingerprint != consent_fingerprint(members):
        raise ValueError("Consent has changed since the website export. Refresh the site and send plan.")
    no_members = [m for m in members if m["photo_count"] >= 2 and m["publication_choice"] == "no"]
    if len(no_members) != 1 or no_members[0]["tg_id"] != private_tg_id:
        raise ValueError("The private recipient must be the sole explicit No contributor.")
    if no_members[0]["user_status"] != "active":
        raise ValueError("The private recipient is not an active bot user.")
    if not validate_private_url(private_url):
        raise ValueError("Use the exact Season 3 personal HTTPS page on what-do-you-see.art.")
    publication_id = db.create_season3_publication(
        season["id"], due.isoformat(), fingerprint, private_tg_id, private_url
    )
    return publication_id, due


async def tick(context: ContextTypes.DEFAULT_TYPE, now: datetime) -> None:
    for publication in db.due_season3_publications(now.isoformat()):
        pid = publication["id"]
        season = db.get_observation_season(publication["season_id"])
        members = db.observation_members(publication["season_id"])
        no_members = [m for m in members if m["photo_count"] >= 2 and m["publication_choice"] == "no"]
        if (
            season is None or season["status"] != "finished"
            or consent_fingerprint(members) != publication["consent_fingerprint"]
            or len(no_members) != 1
            or no_members[0]["tg_id"] != publication["private_tg_id"]
        ):
            db.set_season3_publication_status(pid, "blocked")
            for admin_id in config.ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        "⛔ Season 3 website send paused: consent changed. "
                        "Refresh the site and delivery plan before rescheduling.",
                    )
                except Exception:
                    log.exception("Could not notify admin %s of publication hold", admin_id)
            continue
        if publication["status"] == "scheduled":
            db.prepare_season3_publication_deliveries(pid, publication["private_tg_id"])
            db.set_season3_publication_status(pid, "sending")
        for delivery in db.pending_season3_publication_deliveries(pid):
            uid, kind = delivery["tg_id"], delivery["kind"]
            user = db.get_user(uid)
            if user is None or user["status"] != "active":
                db.mark_season3_publication_delivery(pid, uid, kind, "inactive", skip=True)
                continue
            key = "SEASON3_SITE_PUBLIC" if kind == "public" else "SEASON3_SITE_PRIVATE"
            url = HOME_URL if kind == "public" else publication["private_url"]
            try:
                await context.bot.send_message(uid, t(db.get_user_lang(uid), key, url=url))
            except Forbidden:
                db.set_user_status(uid, "inactive")
                db.mark_season3_publication_delivery(pid, uid, kind, "forbidden", skip=True)
            except Exception as exc:
                log.exception("Season 3 publication %s to %s failed", kind, uid)
                db.mark_season3_publication_delivery(pid, uid, kind, str(exc)[:200])
            else:
                db.mark_season3_publication_delivery(pid, uid, kind)
        if not db.pending_season3_publication_deliveries(pid):
            db.set_season3_publication_status(pid, "complete")
            for admin_id in config.ADMIN_IDS:
                try:
                    await context.bot.send_message(admin_id, "✅ Season 3 website links delivered.")
                except Exception:
                    log.exception("Could not notify admin %s of publication completion", admin_id)
