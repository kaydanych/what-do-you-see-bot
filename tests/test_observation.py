"""Season 3: manual announcement/start and repeated-place submissions."""

import asyncio
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from photobot import config, db, observation


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=len(self.messages))


class FakeFile:
    def __init__(self, body):
        self.body = body

    async def download_to_drive(self, custom_path):
        Path(custom_path).write_bytes(self.body)


class FakeMedia:
    file_id = "telegram-photo"

    def __init__(self, body):
        self.body = body

    async def get_file(self):
        return FakeFile(self.body)


class FakeMessage:
    media_group_id = None
    document = None

    def __init__(self, body):
        self.photo = [FakeMedia(body)]
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


def jpeg_bytes():
    out = BytesIO()
    Image.new("RGB", (24, 16), "#668844").save(out, "JPEG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db.init(tmp_path / "test.db")
    monkeypatch.setattr(config, "PHOTOS_DIR", tmp_path / "photos")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ADMIN_IDS", {99})
    for uid, lang in ((1, "en"), (2, "ru")):
        db.upsert_user(uid, f"Person {uid}", f"p{uid}")
        db.set_user_lang(uid, lang)
    yield


def fixed_now():
    return datetime(2026, 9, 20, 12, 0, tzinfo=config.TZ)


def test_membership_is_season_scoped_and_photo_replaces(monkeypatch, tmp_path):
    monkeypatch.setattr(observation, "now_local", fixed_now)
    sid = db.create_observation_season("2026-09-21")
    assert db.enroll_active_observation_members(sid) == 2
    db.set_observation_member_status(sid, 1, "opted_out")
    assert db.get_user(1)["status"] == "active"
    assert db.observation_member(sid, 1)["status"] == "opted_out"

    db.set_observation_member_status(sid, 1, "active")
    first = tmp_path / "one.jpg"
    second = tmp_path / "two.jpg"
    assert db.upsert_observation_photo(
        sid, 1, "2026-09-20", str(first), "a", fixed_now().isoformat()
    ) is False
    assert db.upsert_observation_photo(
        sid, 1, "2026-09-20", str(second), "b", fixed_now().isoformat()
    ) is True
    rows = db.observation_photos_for(sid, 1)
    assert len(rows) == 1 and rows[0]["file_path"] == str(second)


def test_announce_then_manual_start(monkeypatch):
    monkeypatch.setattr(observation, "now_local", fixed_now)

    async def scenario():
        bot = FakeBot()
        context = SimpleNamespace(bot=bot)
        enrolled, sent, failed = await observation.announce(
            context, date(2026, 9, 21)
        )
        assert (enrolled, sent, failed) == (2, 2, 0)
        season = db.current_observation_season()
        assert season["status"] == "announced"
        assert "We begin on September 21" in bot.messages[0][1]
        assert "Начинаем 21 сентября" in bot.messages[1][1]

        season, sent, failed = await observation.start(context)
        assert (sent, failed) == (2, 0)
        assert season["status"] == "active"
        assert season["planned_end_date"] == "2026-10-17"
        # A retry sends nothing twice.
        _season, sent, failed = await observation.start(context)
        assert (sent, failed) == (0, 0)

        season, sent, failed = await observation.finish(context)
        assert season["status"] == "finished" and (sent, failed) == (2, 0)
        # The finish fan-out is retry-safe too.
        _season, sent, failed = await observation.finish(context)
        assert (sent, failed) == (0, 0)

    asyncio.run(scenario())


def test_late_joiner_gets_live_intro_once(monkeypatch):
    monkeypatch.setattr(observation, "now_local", fixed_now)

    async def scenario():
        bot = FakeBot()
        context = SimpleNamespace(bot=bot)
        await observation.announce(context, date(2026, 9, 21))
        await observation.start(context)
        db.upsert_user(3, "Late", "late")
        db.set_user_lang(3, "en")
        assert await observation.maybe_send_current_intro(context, 3) is True
        assert await observation.maybe_send_current_intro(context, 3) is False
        texts = [text for uid, text, _ in bot.messages if uid == 3]
        assert len(texts) == 1 and "already underway" in texts[0]

    asyncio.run(scenario())


def test_photo_is_accepted_only_after_manual_start(monkeypatch):
    monkeypatch.setattr(observation, "now_local", fixed_now)

    async def scenario():
        bot = FakeBot()
        context = SimpleNamespace(bot=bot)
        await observation.announce(context, date(2026, 9, 21))
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=1), message=FakeMessage(jpeg_bytes())
        )
        assert await observation.handle_photo(update, context) is False
        await observation.start(context)
        assert await observation.handle_photo(update, context) is True
        assert len(db.observation_photos_for(1, 1)) == 1
        assert "Photograph 1" in update.message.replies[-1][0]

        update2 = SimpleNamespace(
            effective_user=SimpleNamespace(id=1), message=FakeMessage(jpeg_bytes())
        )
        assert await observation.handle_photo(update2, context) is True
        assert len(db.observation_photos_for(1, 1)) == 1
        assert "Replaced" in update2.message.replies[-1][0]

    asyncio.run(scenario())


def test_reminders_begin_after_48_hours_and_stop_after_three(monkeypatch):
    monkeypatch.setattr(observation, "now_local", fixed_now)

    async def scenario():
        bot = FakeBot()
        context = SimpleNamespace(bot=bot)
        await observation.announce(context, date(2026, 9, 21))
        await observation.start(context)
        season = db.current_observation_season()
        bot.messages.clear()

        before = fixed_now() + timedelta(hours=47, minutes=59)
        assert await observation.send_reminders(context, season, before) == (0, 0)
        for hours in (48, 96, 144):
            now = fixed_now() + timedelta(hours=hours)
            assert await observation.send_reminders(context, season, now) == (2, 0)
        now = fixed_now() + timedelta(hours=192)
        assert await observation.send_reminders(context, season, now) == (0, 0)
        assert db.observation_member(season["id"], 1)["ignored_reminders"] == 3

    asyncio.run(scenario())
