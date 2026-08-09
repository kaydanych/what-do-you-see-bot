import asyncio
from types import SimpleNamespace

import pytest

from photobot import config, db, handlers_admin as adm, handlers_user as usr, jobs


ADMIN = 99


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db.init(tmp_path / "test.db")
    monkeypatch.setattr(config, "ADMIN_IDS", (ADMIN,))
    yield


class FakeBot:
    def __init__(self):
        self.messages = []
        self.markups = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))
        self.markups.append((chat_id, kwargs.get("reply_markup")))


def user_update(uid, replies):
    async def reply_text(text, **kwargs):
        replies.append((text, kwargs.get("reply_markup")))

    return SimpleNamespace(
        message=SimpleNamespace(reply_text=reply_text),
        effective_user=SimpleNamespace(id=uid, first_name="Ann", username="ann"),
    )


def test_reminder_preference_defaults_to_evening_nudges():
    db.upsert_user(1, "Ann", "ann")
    assert db.reminders_enabled(1) is True
    db.set_reminders_enabled(1, False)
    assert db.reminders_enabled(1) is False


def test_reminders_command_changes_preference_and_can_show_the_picker():
    db.upsert_user(1, "Ann", "ann")
    db.set_user_lang(1, "en")
    replies = []
    context = SimpleNamespace(bot=FakeBot(), user_data={}, args=["morning"])

    asyncio.run(usr.cmd_reminders(user_update(1, replies), context))
    assert db.reminders_enabled(1) is False
    assert "morning prompt only" in replies[0][0]

    context.args = []
    asyncio.run(usr.cmd_reminders(user_update(1, replies), context))
    buttons = replies[1][1].inline_keyboard[0]
    assert [button.callback_data for button in buttons] == [
        "reminders:all",
        "reminders:morning",
    ]


def test_both_evening_nudges_skip_morning_only_users():
    prompt_id = db.add_prompt("water", ADMIN)
    db.create_day("2026-08-09", prompt_id)
    for uid in (1, 2, 3):
        db.upsert_user(uid, f"User {uid}", f"u{uid}")
        db.set_user_lang(uid, "en")
    db.set_reminders_enabled(2, False)
    db.upsert_photo("2026-08-09", 3, "/tmp/submitted.jpg")
    bot = FakeBot()
    context = SimpleNamespace(bot=bot)

    asyncio.run(jobs.send_reminders(context, "2026-08-09"))
    asyncio.run(jobs.send_final_reminders(context, "2026-08-09"))

    assert [uid for uid, _ in bot.messages] == [1, 1]


def test_admin_can_ask_all_active_users_with_localized_buttons():
    db.upsert_user(1, "Ann", "ann")
    db.set_user_lang(1, "en")
    db.upsert_user(2, "Анна", "anna")
    db.set_user_lang(2, "ru")
    db.upsert_user(3, "Away", "away")
    db.set_user_status(3, "inactive")
    bot = FakeBot()
    replies = []

    async def reply_text(text, **kwargs):
        replies.append(text)

    update = SimpleNamespace(
        message=SimpleNamespace(reply_text=reply_text),
        effective_user=SimpleNamespace(id=ADMIN),
    )
    asyncio.run(adm.cmd_askreminders(update, SimpleNamespace(bot=bot)))

    assert [uid for uid, _ in bot.messages] == [1, 2]
    assert "How many photo notifications" in bot.messages[0][1]
    assert "Сколько напоминаний" in bot.messages[1][1]
    assert bot.markups[0][1].inline_keyboard[0][0].text == "All 3 notifications"
    assert bot.markups[1][1].inline_keyboard[0][0].text == "Все 3 уведомления"
    assert replies == ["Reminder preference question: sent 2, failed 0."]
