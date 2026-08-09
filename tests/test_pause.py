import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from photobot import config, db, handlers_admin as adm, jobs


ADMIN = 99


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db.init(tmp_path / "test.db")
    monkeypatch.setattr(config, "ADMIN_IDS", (ADMIN,))
    yield


def admin_update(replies):
    async def reply_text(text, **kwargs):
        replies.append(text)

    return SimpleNamespace(
        message=SimpleNamespace(reply_text=reply_text),
        effective_user=SimpleNamespace(id=ADMIN),
    )


def test_pause_and_resume_are_manual_admin_switches():
    replies = []
    update = admin_update(replies)

    asyncio.run(adm.cmd_pause(update, SimpleNamespace()))
    assert jobs.is_paused() is True
    assert replies[-1].startswith("Paused")

    asyncio.run(adm.cmd_pause(update, SimpleNamespace()))
    assert replies[-1].startswith("Already paused")

    asyncio.run(adm.cmd_resume(update, SimpleNamespace()))
    assert jobs.is_paused() is False
    assert replies[-1].startswith("Resumed")


def test_paused_tick_never_starts_a_new_day_or_week_card(monkeypatch):
    db.set_setting("paused", "1")
    now = datetime(2026, 8, 10, 10, 0, tzinfo=config.TZ)
    monkeypatch.setattr(jobs, "now_local", lambda: now)
    calls = []

    async def weekly(*args):
        calls.append("week")

    async def prompt(*args):
        calls.append("prompt")

    monkeypatch.setattr(jobs, "maybe_offer_week_cards", weekly)
    monkeypatch.setattr(jobs, "send_prompt", prompt)

    asyncio.run(jobs.tick(SimpleNamespace()))

    assert calls == []
    assert db.get_day("2026-08-10") is None


def test_forceprompt_refuses_to_override_a_pause(monkeypatch):
    db.set_setting("paused", "1")
    replies = []
    update = admin_update(replies)

    asyncio.run(adm.cmd_forceprompt(update, SimpleNamespace()))

    assert "paused" in replies[-1]
