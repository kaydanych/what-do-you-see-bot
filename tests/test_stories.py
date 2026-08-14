import asyncio
from types import SimpleNamespace

import pytest

from photobot import db, handlers_admin as adm, jobs


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.init(tmp_path / "test.db")
    yield


def test_stories_lists_waiting_and_answered_requests_only():
    db.upsert_user(41, "Waiting Wendy", "waiting_wendy")
    db.upsert_user(42, "Ready Rita", "ready_rita")
    db.upsert_user(43, "Published Pat", None)
    db.upsert_user(44, "Dismissed Dan", None)

    waiting = db.add_story("2026-08-01", 41, ask_message_id=101)
    ready = db.add_story("2026-08-02", 42, ask_message_id=102)
    db.set_story_answer(ready, "A ready story")
    published = db.add_story("2026-07-30", 43, ask_message_id=103)
    db.set_story_answer(published, "Already sent")
    db.set_story_status(published, "published")
    dismissed = db.add_story("2026-07-31", 44, ask_message_id=104)
    db.set_story_status(dismissed, "dismissed")

    replies = []

    async def reply_text(text):
        replies.append(text)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(reply_text=reply_text)
    )
    asyncio.run(adm.cmd_stories.__wrapped__(update, SimpleNamespace()))

    assert len(replies) == 1
    assert (
        f"⏳ #{waiting} — Waiting Wendy @waiting_wendy, photo from 2026-08-01"
        in replies[0]
    )
    assert "Asked; waiting for their reply." in replies[0]
    assert f"💬 #{ready} — Ready Rita @ready_rita, photo from 2026-08-02" in replies[0]
    assert "A ready story" in replies[0]
    assert "Published Pat" not in replies[0]
    assert "Dismissed Dan" not in replies[0]


def test_three_knocks_offer_an_admin_choice_without_asking_automatically(monkeypatch):
    date = "2026-08-01"
    db.upsert_user(41, "Winning Wendy", "wendy")
    for uid, name, username in (
        (42, "Knocker Kim", "kim"),
        (43, "Knocker Sam", "sam"),
        (44, "Knocker Pat", "pat"),
    ):
        db.upsert_user(uid, name, username)
    db.ensure_day(date)
    db.set_day_field(date, "collage_sent_at", "2026-08-01T21:00:00")
    db.upsert_photo(date, 41, "/tmp/wendy.jpg")
    db.set_knock(date, 42, 41)
    db.set_knock(date, 43, 41)
    db.set_knock(date, 44, 41)

    asked = []
    notices = []

    async def request_story(*_args):
        asked.append(True)

    async def notify_admins(_context, text, reply_markup=None):
        notices.append((text, reply_markup))

    monkeypatch.setattr(jobs, "request_story", request_story)
    monkeypatch.setattr(jobs, "notify_admins", notify_admins)
    context = SimpleNamespace()
    noon = jobs.datetime.fromisoformat("2026-08-02T12:00:00")

    asyncio.run(jobs.resolve_yesterdays_knocks(context, noon))
    asyncio.run(jobs.resolve_yesterdays_knocks(context, noon))

    assert asked == []
    assert db.get_day(date)["knock_resolved_at"]
    assert len(notices) == 1
    assert notices[0][0] == (
        "🚪 2026-08-01: Winning Wendy's photo got 3 knock(s). Ask for their story?"
    )
    assert notices[0][1].inline_keyboard[0][0].callback_data == "ko:ask:2026-08-01:41"


def test_fewer_than_three_knocks_do_not_notify_admins(monkeypatch):
    date = "2026-08-01"
    for uid, name in ((41, "Wendy"), (42, "Rita"), (43, "Kim"), (44, "Sam")):
        db.upsert_user(uid, name, name.lower())
    db.ensure_day(date)
    db.set_day_field(date, "collage_sent_at", "2026-08-01T21:00:00")
    db.upsert_photo(date, 41, "/tmp/wendy.jpg")
    db.upsert_photo(date, 42, "/tmp/rita.jpg")
    db.set_knock(date, 43, 41)
    db.set_knock(date, 44, 42)

    notices = []

    async def notify_admins(_context, text, reply_markup=None):
        notices.append(text)

    monkeypatch.setattr(jobs, "notify_admins", notify_admins)

    asyncio.run(
        jobs.resolve_yesterdays_knocks(
            SimpleNamespace(), jobs.datetime.fromisoformat("2026-08-02T12:00:00")
        )
    )

    assert db.get_day(date)["knock_resolved_at"]
    assert notices == []
