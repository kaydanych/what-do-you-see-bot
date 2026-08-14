"""Season 2: anonymous, paced, two-person photo chains."""

import asyncio
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from photobot import config, correspondence, db


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

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=len(self.messages))

    async def send_photo(self, chat_id, photo, **kwargs):
        self.photos.append((chat_id, kwargs.get("caption", ""), kwargs))
        return SimpleNamespace(photo=[SimpleNamespace(file_id=f"relay-{len(self.photos)}")])


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


def test_early_reply_is_replaceable_and_delivered_after_cooldown(season, monkeypatch):
    async def scenario():
        season_id, start = season
        bot = FakeBot()
        context = SimpleNamespace(bot=bot, user_data={})
        assert await correspondence.pair_and_start(context, season_id, start) == "started 1 chain(s)"
        pair = db.correspondence_pairs_for(season_id)[0]
        starter = pair["next_tg_id"]
        recipient = correspondence.other_user(pair, starter)

        monkeypatch.setattr(correspondence, "now_local", lambda: start)
        first_update, _ = photo_update(starter)
        assert await correspondence.handle_photo(first_update, context)
        assert bot.photos[-1][0] == recipient
        assert "Photograph 1 of 4" in bot.photos[-1][1]
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
