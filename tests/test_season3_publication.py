"""The website send must be durable and obey the latest consent choice."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from photobot import config, db, season3_publication
from photobot.season3_consents import consent_fingerprint


PRIVATE_URL = "https://what-do-you-see.art/season3/private/opaque123/index.html"


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


@pytest.fixture
def season(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_IDS", {99})
    path = tmp_path / "test.db"
    db.init(path)
    for uid, status in ((1, "active"), (2, "active"), (3, "active"),
                        (4, "active"), (5, "pending")):
        db.upsert_user(uid, f"Person {uid}", None, new_status=status)
    sid = db.create_observation_season("2026-09-21")
    for uid in (1, 2, 3):
        db.ensure_observation_member(sid, uid)
        for day in (21, 22):
            db.upsert_observation_photo(
                sid, uid, f"2026-09-{day}", f"photo-{uid}-{day}.jpg", None,
                f"2026-09-{day}T12:00:00+02:00",
            )
    db.set_observation_publication_choice(sid, 1, "yes")
    db.set_observation_publication_choice(sid, 2, "no")
    db.set_observation_season_field(sid, "status", "active")
    db.finish_observation_season(sid, "2026-10-19T12:00:00+02:00")
    return sid, path


def _schedule(sid):
    now = datetime(2026, 10, 20, 12, tzinfo=config.TZ)
    fingerprint = consent_fingerprint(db.observation_members(sid))
    pid, due = season3_publication.schedule(
        "2026-10-20", "18:00", fingerprint, 2, PRIVATE_URL, now=now
    )
    return pid, due


def test_scheduled_delivery_survives_restart_and_sends_private_only_to_no(season):
    sid, path = season
    pid, due = _schedule(sid)
    bot = FakeBot()
    db.init(path)  # NAS restart keeps the schedule and delivery state.
    asyncio.run(season3_publication.tick(SimpleNamespace(bot=bot), due + timedelta(minutes=1)))
    public = [(uid, text) for uid, text in bot.messages if "what-do-you-see.art/" in text]
    assert {uid for uid, text in public if PRIVATE_URL not in text} == {1, 2, 3, 4}
    assert [(uid, text) for uid, text in public if PRIVATE_URL in text][0][0] == 2
    assert all(uid != 5 for uid, _ in bot.messages)
    assert db.active_season3_publication(sid) is None
    before = list(bot.messages)
    asyncio.run(season3_publication.tick(SimpleNamespace(bot=bot), due + timedelta(minutes=2)))
    assert bot.messages == before
    assert db.pending_season3_publication_deliveries(pid) == []


def test_changed_consent_blocks_all_messages(season):
    sid, _ = season
    _, due = _schedule(sid)
    db.set_observation_publication_choice(sid, 3, "yes")
    bot = FakeBot()
    asyncio.run(season3_publication.tick(SimpleNamespace(bot=bot), due + timedelta(minutes=1)))
    assert [uid for uid, _ in bot.messages] == [99]
    assert db.active_season3_publication(sid)["status"] == "blocked"


def test_schedule_rejects_wrong_private_page(season):
    sid, _ = season
    fingerprint = consent_fingerprint(db.observation_members(sid))
    with pytest.raises(ValueError, match="exact Season 3 personal"):
        season3_publication.schedule(
            "2026-10-20", "18:00", fingerprint, 2,
            "https://evil.example/season3/private/opaque123/index.html",
            now=datetime(2026, 10, 20, 12, tzinfo=config.TZ),
        )
