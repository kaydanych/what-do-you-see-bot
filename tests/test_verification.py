"""New-user verification: a newcomer waits on a list until an admin taps ✅,
and hears nothing from the bot in the meantime.
"""
import asyncio
from types import SimpleNamespace

import pytest

from photobot import config, db, handlers_admin as adm, handlers_user as usr

ADMIN = 99


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db.init(tmp_path / "test.db")
    monkeypatch.setattr(config, "ADMIN_IDS", (ADMIN,))
    yield


class FakeBot:
    def __init__(self):
        self.messages: list[tuple[int, str]] = []
        self.markups: list[tuple[int, object]] = []
        self._next_id = 500

    async def send_message(self, chat_id, text, **kw):
        self.messages.append((chat_id, text))
        self.markups.append((chat_id, kw.get("reply_markup")))
        self._next_id += 1
        return SimpleNamespace(message_id=self._next_id)

    def texts_to(self, uid: int) -> str:
        return "\n".join(t for c, t in self.messages if c == uid)

    def buttons_to(self, uid: int) -> list[str]:
        return [
            b.text
            for c, m in self.markups
            if c == uid and m is not None
            for row in m.inline_keyboard
            for b in row
        ]


class FakeQuery:
    def __init__(self, data: str, chat_id: int = ADMIN):
        self.data = data
        self.answers: list[str | None] = []
        self.edits: list[str] = []
        self.markups: list = []
        self.message = SimpleNamespace(chat_id=chat_id)

    async def answer(self, text=None):
        self.answers.append(text)

    async def edit_message_text(self, text, **kw):
        self.edits.append(text)

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markups.append(reply_markup)


def ctx(bot: FakeBot):
    return SimpleNamespace(bot=bot, user_data={})


def message_from(uid: int, text: str, replies: list[str], name: str = "Anna"):
    async def reply_text(t, **kw):
        replies.append(t)

    return SimpleNamespace(
        message=SimpleNamespace(
            text=text,
            reply_to_message=None,
            media_group_id=None,
            reply_text=reply_text,
        ),
        effective_chat=SimpleNamespace(id=uid),
        effective_user=SimpleNamespace(id=uid, first_name=name, username="anna_k"),
    )


def start(context, uid: int, name: str = "Anna") -> list[str]:
    replies: list[str] = []
    asyncio.run(usr.cmd_start(message_from(uid, "/start", replies, name), context))
    return replies


def tap(context, data: str, admin: int = ADMIN) -> FakeQuery:
    query = FakeQuery(data)
    update = SimpleNamespace(
        callback_query=query,
        effective_message=query.message,
        effective_user=SimpleNamespace(id=admin, first_name="Nikita", username="n"),
    )
    asyncio.run(adm.on_verify(update, context))
    return query


# --- arriving -----------------------------------------------------------------

def test_a_newcomer_waits_and_the_admin_gets_the_buttons():
    bot = FakeBot()
    context = ctx(bot)
    replies = start(context, 7)

    assert db.get_user(7)["status"] == "pending"
    assert db.active_user_ids() == []          # outside every broadcast
    assert [r["tg_id"] for r in db.pending_users()] == [7]
    # the admin's card carries the two buttons
    assert "New user: Anna @anna_k" in bot.texts_to(ADMIN)
    assert bot.buttons_to(ADMIN) == [
        "✅ Approve",
        "🚫 Reject",
        "💬 Ask who they are",
    ]
    # and the newcomer is asked to pick a language, not held silently
    assert replies == ["Choose your language / Выбери язык:"]


def test_the_wait_is_explained_in_their_own_language():
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7)

    query = FakeQuery("lang:ru", chat_id=7)
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=7, first_name="Anna", username="anna_k"),
    )
    asyncio.run(usr.on_lang_choice(update, context))

    assert "Ты в списке" in bot.texts_to(7)
    assert "добро пожаловать" not in bot.texts_to(7)  # no welcome before the ✅
    assert db.get_user(7)["status"] == "pending"


def test_a_pending_user_stays_out_of_the_game_and_text_goes_to_the_admin():
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7)

    replies: list[str] = []
    asyncio.run(usr.on_photo(message_from(7, None, replies), context))
    asyncio.run(usr.cmd_today(message_from(7, "/today", replies), context))
    asyncio.run(usr.on_other(message_from(7, "hello?", replies), context))

    assert all("You're on the list" in r for r in replies[:2])
    assert "passed your message to the organizer" in replies[2]
    assert "Reply from Anna" in bot.texts_to(ADMIN)
    assert db.active_user_ids() == []


def test_repeated_starts_do_not_pile_up_cards_or_promote_anyone():
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7)
    start(context, 7)
    start(context, 7)

    assert bot.texts_to(ADMIN).count("New user") == 1  # only the first arrival
    assert db.get_user(7)["status"] == "pending"


def test_an_admin_never_waits_for_their_own_approval():
    bot = FakeBot()
    context = ctx(bot)
    start(context, ADMIN, name="Nikita")
    assert db.get_user(ADMIN)["status"] == "active"
    assert db.pending_users() == []


def test_stop_then_start_does_not_slip_past_the_gate():
    """/stop marks people inactive, and a later /start revives them — a pending
    user must not be able to launder themselves active that way."""
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7)

    replies: list[str] = []
    asyncio.run(usr.cmd_stop(message_from(7, "/stop", replies), context))
    assert db.get_user(7)["status"] == "pending"

    start(context, 7)
    assert db.get_user(7)["status"] == "pending"
    assert db.active_user_ids() == []


def test_admin_can_ask_who_a_pending_user_is_and_their_reply_is_relayed():
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7)
    db.set_user_lang(7, "en")

    query = tap(context, "verify:7:ask")

    assert query.answers == ["Question sent 💬"]
    assert "who invited you" in bot.texts_to(7)
    assert db.get_user(7)["status"] == "pending"

    replies: list[str] = []
    asyncio.run(
        usr.on_other(
            message_from(7, "Dafna invited me — we work together.", replies),
            context,
        )
    )

    assert "Reply from Anna @anna_k" in bot.texts_to(ADMIN)
    assert "Dafna invited me — we work together." in bot.texts_to(ADMIN)
    assert bot.buttons_to(ADMIN)[-3:] == [
        "✅ Approve",
        "🚫 Reject",
        "💬 Ask who they are",
    ]
    assert replies == [
        "Thanks — I've passed your message to the organizer. You're still on "
        "the waiting list for now; I'll message you as soon as you're in 👋"
    ]
    assert db.get_user(7)["status"] == "pending"
    assert db.active_user_ids() == []


def test_identity_question_is_bilingual_until_the_user_picks_a_language():
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7)

    tap(context, "verify:7:ask")

    assert "who invited you" in bot.texts_to(7)
    assert "кто тебя пригласил" in bot.texts_to(7)


def test_admin_can_dm_a_registered_user_by_large_telegram_id():
    bot = FakeBot()
    context = ctx(bot)
    uid = 8_280_321_049
    start(context, uid, name="Dafna")
    db.set_user_lang(uid, "en")
    replies: list[str] = []
    update = message_from(
        ADMIN,
        f"/dm {uid} Hi Dafna!\nWho invited you?",
        replies,
        name="Nikita",
    )

    asyncio.run(adm.cmd_dm(update, context))

    assert bot.texts_to(uid).endswith(
        "💬 Message from the organizer:\n\nHi Dafna!\nWho invited you?"
    )
    assert replies == [f"💬 Sent to Dafna (id {uid}, pending)."]
    assert db.get_user(uid)["status"] == "pending"


# --- the decision -------------------------------------------------------------

def test_approving_lets_them_in_and_greets_them():
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7)
    db.set_user_lang(7, "en")

    query = tap(context, "verify:7:ok")

    assert db.get_user(7)["status"] == "active"
    assert db.active_user_ids() == [7]
    assert query.answers == ["Approved ✅"]
    assert "Anna (id 7) is in" in query.edits[0]
    assert "You're in — welcome!" in bot.texts_to(7)
    assert "welcome to the little game" in bot.texts_to(7)


def test_approving_someone_who_never_picked_a_language_asks_them_first():
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7)                       # never answered the picker

    tap(context, "verify:7:ok")

    assert db.get_user(7)["status"] == "active"
    # the welcome waits for their tap rather than going out in a guessed language
    assert "Choose your language" in bot.texts_to(7)
    assert "welcome to the little game" not in bot.texts_to(7)

    query = FakeQuery("lang:en", chat_id=7)
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=7, first_name="Anna", username="anna_k"),
    )
    asyncio.run(usr.on_lang_choice(update, context))
    assert "welcome to the little game" in bot.texts_to(7)


def test_rejecting_closes_the_door_and_says_so():
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7)
    db.set_user_lang(7, "en")

    query = tap(context, "verify:7:no")

    assert db.get_user(7)["status"] == "kicked"
    assert "turned away" in query.edits[0]
    assert "Access to the game is closed" in bot.texts_to(7)

    # and they stay out: a later message gets the kicked line, not the hold note
    replies: list[str] = []
    asyncio.run(usr.on_other(message_from(7, "let me in", replies), context))
    assert replies == ["Access to the game is closed. If this is a mistake, "
                       "contact the organizer."]


def test_a_second_tap_on_a_settled_card_changes_nothing():
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7)
    tap(context, "verify:7:ok")
    before = bot.texts_to(7)

    query = tap(context, "verify:7:no")      # a stale copy, or a slipped thumb

    assert db.get_user(7)["status"] == "active"   # the decision stands
    assert query.answers == ["Already handled."]
    assert "already active" in query.edits[0]
    assert bot.texts_to(7) == before               # nothing new sent to them


def test_only_admins_can_decide():
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7)

    tap(context, "verify:7:ok", admin=1234)  # not in ADMIN_IDS

    assert db.get_user(7)["status"] == "pending"


def test_pending_command_re_sends_the_cards():
    bot = FakeBot()
    context = ctx(bot)
    start(context, 7, name="Anna")
    start(context, 8, name="Bob")

    replies: list[str] = []
    markups: list = []

    async def reply_text(text, **kw):
        replies.append(text)
        markups.append(kw.get("reply_markup"))

    update = SimpleNamespace(
        message=SimpleNamespace(reply_text=reply_text),
        effective_user=SimpleNamespace(id=ADMIN),
    )
    asyncio.run(adm.cmd_pending(update, context))

    assert replies[0] == "⏳ 2 waiting for your ✅:"
    assert "id 7" in replies[1] and "id 8" in replies[2]
    assert all(m is not None for m in markups[1:])

    tap(context, "verify:7:ok")
    tap(context, "verify:8:no")
    replies.clear()
    asyncio.run(adm.cmd_pending(update, context))
    assert replies == [
        "Nobody waiting ✅ Every newcomer so far has been let in or turned away."
    ]
