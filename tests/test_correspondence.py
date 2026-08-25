"""Season 2: anonymous, paced, two-person photo chains."""

import asyncio
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from photobot import (
    config,
    correspondence,
    db,
    handlers_admin as adm,
    handlers_user as usr,
)


class FakeTelegramFile:
    def __init__(self, jpeg: bytes):
        self.jpeg = jpeg

    async def download_to_drive(self, custom_path):
        Path(custom_path).write_bytes(self.jpeg)


class FakeMedia:
    file_id = "incoming-file"

    def __init__(self, jpeg: bytes):
        self.jpeg = jpeg

    async def get_file(self):
        return FakeTelegramFile(self.jpeg)


class FakeMessage:
    media_group_id = None
    document = None

    def __init__(self, jpeg: bytes):
        self.photo = [FakeMedia(jpeg)]
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeBot:
    def __init__(self):
        self.messages = []
        self.photos = []
        self.photo_sources = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=len(self.messages))

    async def send_photo(self, chat_id, photo, **kwargs):
        self.photo_sources.append(photo)
        self.photos.append((chat_id, kwargs.get("caption", ""), kwargs))
        return SimpleNamespace(photo=[SimpleNamespace(file_id=f"relay-{len(self.photos)}")])


class FailingPhotoBot(FakeBot):
    async def send_photo(self, chat_id, photo, **kwargs):
        self.photo_sources.append(photo)
        raise RuntimeError("temporary upload failure")


class FakeQuery:
    def __init__(self, data: str):
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))

    async def edit_message_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


def admin_callback(data: str):
    query = FakeQuery(data)
    return SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=99, first_name="Admin", username="admin"),
    ), query


def text_update(uid: int, text: str):
    replies = []

    async def reply_text(body, **kwargs):
        replies.append(body)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=uid, first_name="Admin", username="admin"),
        message=SimpleNamespace(
            text=text,
            reply_to_message=None,
            reply_text=reply_text,
        ),
    )
    return update, replies


def jpeg_bytes() -> bytes:
    out = BytesIO()
    Image.new("RGB", (16, 12), "#336699").save(out, "JPEG")
    return out.getvalue()


def photo_update(uid: int):
    msg = FakeMessage(jpeg_bytes())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=uid), message=msg
    ), msg


@pytest.fixture
def season(tmp_path, monkeypatch):
    db.init(tmp_path / "test.db")
    monkeypatch.setattr(config, "PHOTOS_DIR", tmp_path / "photos")
    monkeypatch.setattr(config, "ADMIN_IDS", {99})
    for uid in (1, 2):
        db.upsert_user(uid, f"Person {uid}", None)
        db.set_user_lang(uid, "en")
    start = datetime(2026, 8, 17, 9, 0, tzinfo=config.TZ)
    season_id = db.create_correspondence_season(
        name="Test",
        prompt="Follow the blue",
        prompt_ru=None,
        enrollment_opens_at=start.isoformat(timespec="seconds"),
        enrollment_reminder1_at=(start + timedelta(hours=1)).isoformat(timespec="seconds"),
        enrollment_reminder2_at=(start + timedelta(hours=2)).isoformat(timespec="seconds"),
        starts_at=(start + timedelta(hours=3)).isoformat(timespec="seconds"),
        ends_at=(start + timedelta(days=3)).isoformat(timespec="seconds"),
        target_links=4,
        cooldown_minutes=1,
        is_test=True,
    )
    db.set_correspondence_enrollment(season_id, 1, "in")
    db.set_correspondence_enrollment(season_id, 2, "in")
    return season_id, start


def test_seasonbroadcast_reaches_only_enrollees_in_their_language(season):
    async def scenario():
        season_id, _ = season
        db.upsert_user(3, "Not enrolled", None)
        db.set_user_lang(2, "ru")
        update, replies = text_update(99, "/seasonbroadcast Hello | Привет")
        bot = FakeBot()
        context = SimpleNamespace(bot=bot, user_data={})

        await adm.cmd_seasonbroadcast(update, context)

        assert {(uid, text) for uid, text, _ in bot.messages} == {
            (1, "Hello"),
            (2, "Привет"),
        }
        assert not any(uid == 3 for uid, _, _ in bot.messages)
        assert replies == [
            f"📮 Season #{season_id} broadcast: sent 2, failed 0.\n«Hello»\n🇷🇺 «Привет»"
        ]

    asyncio.run(scenario())


def test_seasoncompleted_notifies_only_completed_chain_participants(season):
    async def scenario():
        season_id, start = season
        db.upsert_user(3, "Not completed", None)
        db.set_user_lang(2, "ru")
        pair_id = db.create_correspondence_pair(season_id, 1, 2, 1, start.isoformat())
        db.set_correspondence_pair_field(pair_id, "status", "complete")
        update, replies = text_update(
            99,
            "/seasoncompleted Wait until August 30 | Ждите до 30 августа",
        )
        bot = FakeBot()
        context = SimpleNamespace(bot=bot, user_data={})

        await adm.cmd_seasoncompleted(update, context)

        assert {(uid, text) for uid, text, _ in bot.messages} == {
            (1, "Wait until August 30"),
            (2, "Ждите до 30 августа"),
        }
        assert replies == [
            f"📮 Season #{season_id} completion note: sent 2, failed 0."
        ]

    asyncio.run(scenario())


def test_early_reply_is_replaceable_and_delivered_after_cooldown(season, monkeypatch):
    async def scenario():
        season_id, start = season
        bot = FakeBot()
        context = SimpleNamespace(bot=bot, user_data={})
        assert await correspondence.pair_and_start(context, season_id, start) == "started 1 chain(s)"
        assert all("reply_markup" not in kwargs for _, _, kwargs in bot.messages)
        pair = db.correspondence_pairs_for(season_id)[0]
        starter = pair["next_tg_id"]
        recipient = correspondence.other_user(pair, starter)

        monkeypatch.setattr(correspondence, "now_local", lambda: start)
        first_update, _ = photo_update(starter)
        assert await correspondence.handle_photo(first_update, context)
        assert bot.photos[-1][0] == recipient
        assert "Photograph 1 of 4" in bot.photos[-1][1]
        assert "Your task now: reply to the photograph above" in bot.photos[-1][1]
        assert "reply_markup" not in bot.photos[-1][2]
        assert len(db.correspondence_links(pair["id"])) == 1

        too_early, early_msg = photo_update(recipient)
        assert await correspondence.handle_photo(too_early, context)
        assert "NOT sent it to your partner" in early_msg.replies[-1]
        assert len(db.correspondence_links(pair["id"])) == 1
        assert len(bot.photos) == 1
        first_draft = db.correspondence_draft(pair["id"])
        assert first_draft is not None

        monkeypatch.setattr(
            correspondence, "now_local", lambda: start + timedelta(seconds=30)
        )
        replacement_update, replacement_msg = photo_update(recipient)
        assert await correspondence.handle_photo(replacement_update, context)
        assert "Photograph replaced" in replacement_msg.replies[-1]
        replacement = db.correspondence_draft(pair["id"])
        assert replacement["file_path"] != first_draft["file_path"]
        assert not Path(first_draft["file_path"]).exists()
        assert len(bot.photos) == 1

        await correspondence.tick(context, start + timedelta(minutes=1))
        assert bot.photos[-1][0] == starter
        assert len(db.correspondence_links(pair["id"])) == 2
        assert db.correspondence_draft(pair["id"]) is None
        # Relayed captions and start messages never identify either participant.
        public_text = "\n".join(text for _, text, _ in bot.messages)
        public_text += "\n" + "\n".join(caption for _, caption, _ in bot.photos)
        assert "Person 1" not in public_text
        assert "Person 2" not in public_text

    asyncio.run(scenario())


def test_delayed_delivery_falls_back_to_telegram_file_id(season, monkeypatch):
    async def scenario():
        season_id, start = season
        bot = FakeBot()
        context = SimpleNamespace(bot=bot, user_data={})
        await correspondence.pair_and_start(context, season_id, start)
        pair = db.correspondence_pairs_for(season_id)[0]
        starter = pair["next_tg_id"]

        monkeypatch.setattr(correspondence, "now_local", lambda: start)
        first_update, _ = photo_update(starter)
        await correspondence.handle_photo(first_update, context)

        recipient = correspondence.other_user(pair, starter)
        queued_update, _ = photo_update(recipient)
        await correspondence.handle_photo(queued_update, context)
        draft = db.correspondence_draft(pair["id"])
        Path(draft["file_path"]).unlink()

        await correspondence.tick(context, start + timedelta(minutes=1))

        assert bot.photo_sources[-1] == "incoming-file"
        assert len(db.correspondence_links(pair["id"])) == 2
        assert db.get_correspondence_pair(pair["id"])["status"] == "active"

    asyncio.run(scenario())


def test_delayed_delivery_failure_is_retried_without_ending_chain(season, monkeypatch):
    async def scenario():
        season_id, start = season
        setup_bot = FakeBot()
        context = SimpleNamespace(bot=setup_bot, user_data={})
        await correspondence.pair_and_start(context, season_id, start)
        pair = db.correspondence_pairs_for(season_id)[0]
        starter = pair["next_tg_id"]

        monkeypatch.setattr(correspondence, "now_local", lambda: start)
        first_update, _ = photo_update(starter)
        await correspondence.handle_photo(first_update, context)
        recipient = correspondence.other_user(pair, starter)
        queued_update, _ = photo_update(recipient)
        await correspondence.handle_photo(queued_update, context)

        failing_bot = FailingPhotoBot()
        context.bot = failing_bot
        await correspondence.tick(context, start + timedelta(minutes=1))

        saved_pair = db.get_correspondence_pair(pair["id"])
        draft = db.correspondence_draft(pair["id"])
        assert saved_pair["status"] == "active"
        assert saved_pair["ended_reason"] is None
        assert draft["status"] == "pending"
        assert draft["delivery_attempts"] == 1
        assert draft["next_attempt_at"] == (start + timedelta(minutes=6)).isoformat(
            timespec="seconds"
        )
        assert any("delivery delayed" in text for _, text, _ in failing_bot.messages)

    asyncio.run(scenario())


def test_waiting_turn_gets_one_and_two_day_nudges(season):
    async def scenario():
        season_id, start = season
        bot = FakeBot()
        context = SimpleNamespace(bot=bot, user_data={})
        await correspondence.pair_and_start(context, season_id, start)
        pair = db.correspondence_pairs_for(season_id)[0]
        waiting = pair["next_tg_id"]

        await correspondence.tick(context, start + timedelta(hours=24))
        texts = "\n".join(text for uid, text, _ in bot.messages if uid == waiting)
        assert "waiting for a day" in texts

        await correspondence.tick(context, start + timedelta(hours=48))
        texts = "\n".join(text for uid, text, _ in bot.messages if uid == waiting)
        assert "for two days" in texts
        assert any(uid == 99 and "waited 48h" in text for uid, text, _ in bot.messages)

    asyncio.run(scenario())


def test_reported_pair_is_never_matched_again(season):
    season_id, _ = season
    db.block_correspondence_pair(1, 2, "reported")
    assert correspondence._valid_pairing([1, 2]) is None


def test_admin_can_view_pairs_and_message_only_the_awaited_person(season, monkeypatch):
    async def scenario():
        season_id, start = season
        bot = FakeBot()
        context = SimpleNamespace(bot=bot, user_data={})
        await correspondence.pair_and_start(context, season_id, start)
        pair = db.correspondence_pairs_for(season_id)[0]
        awaited = pair["next_tg_id"]
        partner = correspondence.other_user(pair, awaited)
        monkeypatch.setattr(adm.jobs, "now_local", lambda: start + timedelta(hours=4))

        replies = []
        markups = []

        async def reply_text(body, **kwargs):
            replies.append(body)
            markups.append(kwargs.get("reply_markup"))

        command = SimpleNamespace(
            effective_user=SimpleNamespace(id=99),
            message=SimpleNamespace(reply_text=reply_text),
        )
        await adm.cmd_seasonpairs(command, context)
        assert replies == [
            f"📮 Season #{season_id} · 1 pairs\n"
            "Tap a pair for details or messaging."
        ]
        assert markups[0].inline_keyboard[0][0].text == (
            "1: 0/4 · awaiting first photo · 4h"
        )

        update, query = admin_callback(f"corradmin:view:{pair['id']}")
        await adm.on_correspondence_admin(update, context)
        labels = [
            button.text
            for row in query.edits[-1][1]["reply_markup"].inline_keyboard
            for button in row
        ]
        assert labels == [
            "✉️ Message both",
            "✉️ Message awaited person",
            "‹ All pairs",
        ]

        update, _ = admin_callback(f"corradmin:awaited:{pair['id']}")
        await adm.on_correspondence_admin(update, context)
        assert context.user_data["awaiting"] == (
            f"corr_admin_dm:{pair['id']}:awaited:{awaited}"
        )
        assert f"Language: English" in bot.messages[-1][1]

        before = len(bot.messages)
        message, confirmations = text_update(99, "A gentle personal nudge")
        await usr.on_other(message, context)
        new_messages = bot.messages[before:]
        assert any(
            uid == awaited and "A gentle personal nudge" in text
            for uid, text, _ in new_messages
        )
        assert not any(uid == partner for uid, _, _ in new_messages)
        assert confirmations == ["💬 Sent to 1/1 intended recipient(s)."]

        update, _ = admin_callback(f"corradmin:both:{pair['id']}")
        await adm.on_correspondence_admin(update, context)
        assert f"Languages: English + English" in bot.messages[-1][1]
        before = len(bot.messages)
        message, confirmations = text_update(99, "A note for the pair")
        await usr.on_other(message, context)
        recipients = {
            uid
            for uid, text, _ in bot.messages[before:]
            if "A note for the pair" in text
        }
        assert recipients == {awaited, partner}
        assert confirmations == ["💬 Sent to 2/2 intended recipient(s)."]

    asyncio.run(scenario())


def test_pair_admin_detail_shows_each_recipient_language(season):
    season_id, _ = season
    pair = db.create_correspondence_pair(season_id, 1, 2, 1)
    db.set_user_lang(1, "en")
    db.set_user_lang(2, "ru")

    detail = correspondence.admin_pair_detail(
        db.get_correspondence_pair(pair), db.get_correspondence_season(season_id), 1
    )

    assert "Languages: both — English + Русский · awaited — English" in detail


def test_seasonpairnames_is_a_separate_admin_only_view(season):
    async def scenario():
        season_id, start = season
        bot = FakeBot()
        context = SimpleNamespace(bot=bot, user_data={})
        await correspondence.pair_and_start(context, season_id, start)
        update, replies = text_update(99, "/seasonpairnames")

        await adm.cmd_seasonpairnames(update, context)

        assert replies[0] in {
            f"📮 Season #{season_id} · pair names (admin only)\n"
            "1: Person 1 ↔ Person 2",
            f"📮 Season #{season_id} · pair names (admin only)\n"
            "1: Person 2 ↔ Person 1",
        }

    asyncio.run(scenario())


def test_admin_can_resume_legacy_delivery_failure(season):
    async def scenario():
        season_id, start = season
        bot = FakeBot()
        context = SimpleNamespace(bot=bot, user_data={}, args=["1"])
        await correspondence.pair_and_start(context, season_id, start)
        pair = db.correspondence_pairs_for(season_id)[0]
        saved = config.PHOTOS_DIR / "legacy-draft.jpg"
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(jpeg_bytes())
        db.upsert_correspondence_draft(
            pair["id"], pair["next_tg_id"], 1, str(saved), None,
            start.isoformat(timespec="seconds"), start.isoformat(timespec="seconds"),
        )
        db.set_correspondence_pair_field(pair["id"], "status", "ended")
        db.set_correspondence_pair_field(pair["id"], "ended_reason", "delivery_failed")
        update, replies = text_update(99, "/seasonretry 1")

        await adm.cmd_seasonretry(update, context)

        assert db.get_correspondence_pair(pair["id"])["status"] == "active"
        assert db.correspondence_draft(pair["id"])["status"] == "pending"
        assert replies == ["📮 Pair 1 resumed. The saved photo is queued for retry."]

    asyncio.run(scenario())


def test_awaited_person_message_is_cancelled_if_they_submit_a_draft(season):
    async def scenario():
        season_id, start = season
        bot = FakeBot()
        context = SimpleNamespace(bot=bot, user_data={})
        await correspondence.pair_and_start(context, season_id, start)
        pair = db.correspondence_pairs_for(season_id)[0]
        awaited = pair["next_tg_id"]

        update, _ = admin_callback(f"corradmin:awaited:{pair['id']}")
        await adm.on_correspondence_admin(update, context)
        db.upsert_correspondence_draft(
            pair["id"],
            awaited,
            1,
            "/tmp/queued.jpg",
            "queued-file-id",
            start.isoformat(timespec="seconds"),
            start.isoformat(timespec="seconds"),
        )

        before = len(bot.messages)
        message, confirmations = text_update(99, "This should not be sent")
        await usr.on_other(message, context)
        assert len(bot.messages) == before
        assert confirmations == [
            "⚠️ Message not sent; the pair or awaited turn changed."
        ]

    asyncio.run(scenario())
