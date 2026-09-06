import asyncio
from datetime import datetime, timedelta
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
        self.edits = []
        self._next_id = 100

    async def send_message(self, chat_id, text, **kwargs):
        self._next_id += 1
        self.messages.append((chat_id, text, kwargs.get("reply_markup")))
        return SimpleNamespace(message_id=self._next_id)

    async def edit_message_reply_markup(self, **kwargs):
        self.edits.append(kwargs)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.markups = []

    async def answer(self, text=None):
        self.answers.append(text)

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markups.append(reply_markup)


def make_survey():
    survey_id = db.create_survey("Would you join again?", "Ещё раз?", ADMIN)
    choices = [
        db.add_survey_option(survey_id, "Definitely", "Точно"),
        db.add_survey_option(survey_id, "Maybe", "Возможно"),
        db.add_survey_option(survey_id, "No", "Нет"),
        db.add_survey_option(survey_id, "I have not viewed it", "Не смотрел(а)"),
    ]
    db.open_survey(survey_id, "season", 1)
    return survey_id, choices


def text_update(uid, text, replies):
    async def reply_text(value, **kwargs):
        replies.append(value)

    return SimpleNamespace(
        message=SimpleNamespace(
            text=text,
            reply_to_message=None,
            media_group_id=None,
            reply_text=reply_text,
        ),
        effective_user=SimpleNamespace(
            id=uid, first_name="Anna", username="anna"
        ),
        effective_chat=SimpleNamespace(id=uid),
    )


def test_choice_four_then_following_text_is_attached_as_comment():
    uid = 7
    db.upsert_user(uid, "Anna", "anna")
    db.set_user_lang(uid, "en")
    survey_id, choices = make_survey()
    db.add_survey_message(survey_id, uid, 55)
    bot = FakeBot()
    context = SimpleNamespace(bot=bot, user_data={"awaiting": "feedback"})
    query = FakeQuery(f"survey:{survey_id}:{choices[3]}")
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=uid, first_name="Anna", username="anna"),
    )

    asyncio.run(usr.on_survey_choice(update, context))

    response = db.survey_response(survey_id, uid)
    assert response["option_id"] == choices[3]
    assert response["comment_pending"] == 1
    assert "awaiting" not in context.user_data
    assert "Recorded: 4" in bot.messages[-1][1]
    assert query.markups[-1].inline_keyboard[3][0].text.startswith("✓ 4 —")

    replies = []
    asyncio.run(
        usr.on_other(
            text_update(uid, "I saved the link and forgot.", replies), context
        )
    )
    response = db.survey_response(survey_id, uid)
    assert response["comment"] == "I saved the link and forgot."
    assert response["comment_pending"] == 0
    assert replies == ["Thank you! Your comment was added to your answer."]


def test_no_comment_finishes_pending_capture():
    uid = 7
    db.upsert_user(uid, "Anna", None)
    survey_id, choices = make_survey()
    db.add_survey_message(survey_id, uid, 55)
    db.set_survey_choice(survey_id, uid, choices[0])
    query = FakeQuery(f"surveydone:{survey_id}")
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=uid),
    )

    asyncio.run(usr.on_survey_done(update, SimpleNamespace(user_data={})))

    assert db.survey_response(survey_id, uid)["comment_pending"] == 0
    assert query.markups == [None]


def test_a_command_cancels_optional_comment_capture():
    uid = 7
    db.upsert_user(uid, "Anna", None)
    survey_id, choices = make_survey()
    db.set_survey_choice(survey_id, uid, choices[0])
    context = SimpleNamespace(user_data={"awaiting": "feedback"})
    update = SimpleNamespace(effective_user=SimpleNamespace(id=uid))

    asyncio.run(usr.clear_awaiting(update, context))

    assert context.user_data == {}
    assert db.survey_response(survey_id, uid)["comment_pending"] == 0


def test_new_survey_choice_supersedes_an_older_pending_comment():
    uid = 7
    db.upsert_user(uid, "Anna", None)
    first_id, first_choices = make_survey()
    second_id, second_choices = make_survey()
    db.set_survey_choice(first_id, uid, first_choices[0])
    db.set_survey_choice(second_id, uid, second_choices[1])

    assert db.survey_response(first_id, uid)["comment_pending"] == 0
    assert db.pending_survey_response(uid)["survey_id"] == second_id


def test_pending_comment_expires_after_24_hours():
    uid = 7
    db.upsert_user(uid, "Anna", None)
    survey_id, choices = make_survey()
    db.set_survey_choice(survey_id, uid, choices[0])
    old = (datetime.now(config.TZ) - timedelta(hours=25)).isoformat()
    db._exec(
        "UPDATE survey_responses SET comment_requested_at=? "
        "WHERE survey_id=? AND tg_id=?",
        (old, survey_id, uid),
    )

    assert db.pending_survey_response(uid) is None
    assert db.survey_response(survey_id, uid)["comment_pending"] == 0


def test_survey_keyboard_is_localized_and_has_no_public_counts():
    survey_id, choices = make_survey()
    keyboard = jobs.survey_keyboard(survey_id, "ru", choices[1])
    labels = [row[0].text for row in keyboard.inline_keyboard]
    assert labels == [
        "1 — Точно",
        "✓ 2 — Возможно",
        "3 — Нет",
        "4 — Не смотрел(а)",
    ]


def test_correspondence_participants_are_the_season_audience():
    now = datetime.now(config.TZ)
    season_id = db.create_correspondence_season(
        name="Season 2",
        prompt="Follow a line",
        prompt_ru=None,
        enrollment_opens_at=now.isoformat(),
        enrollment_reminder1_at=now.isoformat(),
        enrollment_reminder2_at=now.isoformat(),
        starts_at=now.isoformat(),
        ends_at=now.isoformat(),
    )
    db.create_correspondence_pair(season_id, 1, 2, 1, now.isoformat())
    db.create_correspondence_pair(season_id, 3, 4, 3, now.isoformat())

    assert db.correspondence_participant_ids(season_id) == [1, 2, 3, 4]


def test_admin_sends_draft_only_to_latest_season_participants():
    for uid in (1, 2, 3):
        db.upsert_user(uid, f"User {uid}", None)
    now = datetime.now(config.TZ).isoformat()
    season_id = db.create_correspondence_season(
        name="Season 2",
        prompt="Follow a line",
        prompt_ru=None,
        enrollment_opens_at=now,
        enrollment_reminder1_at=now,
        enrollment_reminder2_at=now,
        starts_at=now,
        ends_at=now,
    )
    db.create_correspondence_pair(season_id, 1, 2, 1, now)
    survey_id = db.create_survey("Again?", "Ещё?", ADMIN)
    db.add_survey_option(survey_id, "Yes", "Да")
    db.add_survey_option(survey_id, "No", "Нет")
    bot = FakeBot()
    replies = []
    update = text_update(ADMIN, f"/surveysend {survey_id} season", replies)
    context = SimpleNamespace(bot=bot, args=[str(survey_id), "season"])

    asyncio.run(adm.cmd_surveysend(update, context))

    assert [message[0] for message in bot.messages] == [1, 2]
    assert db.get_survey(survey_id)["status"] == "open"
    assert len(db.survey_messages_for(survey_id)) == 2
    assert "delivered privately to 2/2" in replies[0]

    asyncio.run(adm.cmd_surveysend(update, context))
    assert [message[0] for message in bot.messages] == [1, 2]
    assert "already reached all 2 recipients" in replies[-1]


def test_admin_results_group_counts_and_comments():
    for uid, name in ((7, "Anna"), (8, "Ben")):
        db.upsert_user(uid, name, None)
    survey_id, choices = make_survey()
    for uid in (7, 8):
        db.add_survey_message(survey_id, uid, uid + 100)
    db.set_survey_choice(survey_id, 7, choices[1])
    db.set_survey_comment(survey_id, 7, "Shorter delays, please.")
    db.set_survey_choice(survey_id, 8, choices[3])

    replies = []
    update = text_update(ADMIN, f"/surveyresults {survey_id}", replies)
    context = SimpleNamespace(args=[str(survey_id)])
    asyncio.run(adm.cmd_surveyresults(update, context))

    result = "\n".join(replies)
    assert "2/2 answered" in result
    assert "2 — Maybe: 1" in result
    assert "4 — I have not viewed it: 1" in result
    assert "[2] Anna (id 7): Shorter delays, please." in result
