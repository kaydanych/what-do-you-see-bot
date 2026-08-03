import asyncio
from types import SimpleNamespace

import pytest

from photobot import db, handlers_admin as adm


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
