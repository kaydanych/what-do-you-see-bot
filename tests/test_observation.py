"""Season 3: manual announcement/start and repeated-place submissions."""

import asyncio
import csv
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from photobot import config, db, handlers_admin, observation


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


def test_finish_asks_only_eligible_contributors_and_saves_answer(monkeypatch, tmp_path):
    monkeypatch.setattr(observation, "now_local", fixed_now)
    sid = db.create_observation_season("2026-09-21")
    db.enroll_active_observation_members(sid)
    db.start_observation_season(sid, fixed_now().isoformat(), "2026-10-18")
    for day in ("2026-09-21", "2026-09-22"):
        db.upsert_observation_photo(sid, 1, day, str(tmp_path / f"{day}.jpg"), None, fixed_now().isoformat())
    db.upsert_observation_photo(sid, 2, "2026-09-21", str(tmp_path / "one.jpg"), None, fixed_now().isoformat())

    async def scenario():
        bot = FakeBot()
        context = SimpleNamespace(bot=bot)
        _season, sent, failed = await observation.finish(context)
        assert (sent, failed) == (2, 0)
        assert len(bot.messages) == 2
        assert "May I show yours publicly" in bot.messages[0][1]
        assert bot.messages[0][2]["reply_markup"].inline_keyboard[0][0].callback_data == f"obs:{sid}:publish_yes"
        assert "Спасибо за твой снимок" in bot.messages[1][1]
        assert "reply_markup" not in bot.messages[1][2]
        assert db.observation_member(sid, 1)["publication_choice"] is None
        assert db.observation_member(sid, 1)["consent_asked_at"]
        assert db.observation_member(sid, 2)["consent_asked_at"] is None

        class Query:
            data = f"obs:{sid}:publish_yes"
            edits = []

            async def answer(self, *args):
                pass

            async def edit_message_text(self, text, **kwargs):
                self.edits.append(text)

        query = Query()
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        await observation.on_callback(update, context)
        assert db.observation_member(sid, 1)["publication_choice"] == "yes"
        assert query.edits and "shared gallery" in query.edits[-1]
        query.data = f"obs:{sid}:publish_no"
        await observation.on_callback(update, context)
        assert db.observation_member(sid, 1)["publication_choice"] == "no"
        assert db.set_observation_publication_choice(sid, 2, "yes") is False

        status = tmp_path / "exports" / f"season3-{sid}-status.csv"
        with status.open(newline="", encoding="utf-8") as handle:
            rows = {int(row["tg_id"]): row for row in csv.DictReader(handle)}
        assert rows[1]["publication_choice"] == "no"
        assert rows[2]["publication_choice"] == ""
        _season, sent, failed = await observation.finish(context)
        assert (sent, failed) == (0, 0)

    asyncio.run(scenario())


def test_finish_retry_asks_for_consent_after_prior_generic_note(monkeypatch):
    monkeypatch.setattr(observation, "now_local", fixed_now)
    sid = db.create_observation_season("2026-09-21")
    db.enroll_active_observation_members(sid)
    db.start_observation_season(sid, fixed_now().isoformat(), "2026-10-18")
    db.finish_observation_season(sid, fixed_now().isoformat())
    db.mark_observation_member_field(sid, 1, "finish_sent_at", fixed_now().isoformat())
    for day in ("2026-09-21", "2026-09-22"):
        db.upsert_observation_photo(sid, 1, day, day, None, fixed_now().isoformat())

    async def scenario():
        bot = FakeBot()
        await observation.finish(SimpleNamespace(bot=bot))
        assert len([m for m in bot.messages if m[0] == 1]) == 1
        assert "I'm preparing a website" in bot.messages[0][1]
        assert db.observation_member(sid, 1)["consent_asked_at"]

    asyncio.run(scenario())


def test_photo_is_accepted_only_after_manual_start(monkeypatch, tmp_path):
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
        manifest = tmp_path / "exports" / "season3-1-manifest.csv"
        status = tmp_path / "exports" / "season3-1-status.csv"
        with manifest.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1
        assert rows[0]["local_date"] == "2026-09-20"
        with status.open(newline="", encoding="utf-8") as handle:
            people = {int(row["tg_id"]): row for row in csv.DictReader(handle)}
        assert people[1]["photo_count"] == "1"
        assert people[1]["submitted_dates"] == "2026-09-20"
        assert people[2]["photo_count"] == "0"

        update2 = SimpleNamespace(
            effective_user=SimpleNamespace(id=1), message=FakeMessage(jpeg_bytes())
        )
        assert await observation.handle_photo(update2, context) is True
        assert len(db.observation_photos_for(1, 1)) == 1
        assert "Replaced" in update2.message.replies[-1][0]
        with manifest.open(newline="", encoding="utf-8") as handle:
            assert len(list(csv.DictReader(handle))) == 1

    asyncio.run(scenario())


def test_export_sends_old_submission_status_without_photo_download(tmp_path):
    sid = db.create_observation_season("2026-09-21")
    db.enroll_active_observation_members(sid)
    db.upsert_observation_photo(
        sid, 1, "2026-09-22", "/nas/old-photo.jpg", None,
        "2026-09-22T12:00:00+02:00",
    )

    class DocumentBot:
        def __init__(self):
            self.documents = []

        async def send_document(self, chat_id, document, **kwargs):
            self.documents.append((chat_id, document.read().decode("utf-8")))

    bot = DocumentBot()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=99),
        effective_chat=SimpleNamespace(id=99),
        message=SimpleNamespace(reply_text=None),
    )
    asyncio.run(handlers_admin.cmd_season3export(update, SimpleNamespace(bot=bot)))
    assert len(bot.documents) == 2
    assert "2026-09-22" in bot.documents[0][1]
    assert "/nas/old-photo.jpg" in bot.documents[1][1]
    assert "Person 2" in bot.documents[0][1]


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


def test_weekly_pulse_reopens_door_without_restarting_reminders(monkeypatch):
    monkeypatch.setattr(observation, "now_local", fixed_now)

    async def scenario():
        bot = FakeBot()
        context = SimpleNamespace(bot=bot)
        await observation.announce(context, date(2026, 9, 21))
        await observation.start(context)
        season = db.current_observation_season()
        bot.messages.clear()
        for uid in (1, 2):
            db.mark_observation_member_field(
                season["id"], uid, "ignored_reminders", 3
            )
            db.mark_observation_member_field(
                season["id"], uid, "last_reminder_at",
                datetime(2026, 9, 24, 18, 0, tzinfo=config.TZ).isoformat(),
            )
        db.set_observation_reminders_enabled(season["id"], 2, False)

        sunday = datetime(2026, 9, 27, 18, 0, tzinfo=config.TZ)
        assert await observation.send_weekly_pulses(
            context, season, sunday
        ) == (1, 0)
        assert bot.messages[-1][0] == 1
        assert "door to Season 3" in bot.messages[-1][1]
        assert db.observation_member(season["id"], 1)["ignored_reminders"] == 3

        # Repeated scheduler ticks in the same week do not duplicate the pulse.
        assert await observation.send_weekly_pulses(
            context, season, sunday + timedelta(hours=1)
        ) == (0, 0)
        # A still-capped participant receives one fresh note in the next week.
        assert await observation.send_weekly_pulses(
            context, season, sunday + timedelta(days=7)
        ) == (1, 0)

    asyncio.run(scenario())
