"""Collage proofing: a few trusted users see the collage before anyone else,
one 👍 publishes it, a double-confirmed 🚫 escalates, two 🚫 park it on the admin.
"""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from photobot import config, db, handlers_admin as adm, handlers_user as usr, jobs


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db.init(tmp_path / "test.db")
    monkeypatch.setattr(config, "ADMIN_IDS", (99,))
    # Rendering is Pillow work the state machine doesn't care about.
    card = tmp_path / "card.jpg"
    card.write_bytes(b"not really a jpeg")

    async def fake_render(date, lang, **kw):
        return card

    monkeypatch.setattr(jobs, "render_collage", fake_render)
    yield


DATE = "2026-07-28"
TG_MAX = 4096


def test_admin_help_is_sent_in_sendable_chunks():
    """/admin died with 'Message is too long' once the proofing section pushed
    it past Telegram's limit, so the split is now enforced here."""
    chunks = adm.help_chunks(adm.ADMIN_HELP)
    assert all(len(c) <= TG_MAX for c in chunks)
    # nothing is dropped and the sections keep their order
    assert "\n\n".join(chunks) == adm.ADMIN_HELP
    # sections stay whole: every chunk starts a section, never mid-list
    assert all(not c.startswith(("/", "•", " ")) for c in chunks)


def test_help_chunks_packs_sections_then_splits():
    text = "\n\n".join(["A" * 1000, "B" * 1000, "C" * 1000])
    chunks = adm.help_chunks(text, limit=2100)
    # the first two sections share a message; the third would overflow it
    assert [len(c) for c in chunks] == [1000 + 2 + 1000, 1000]
    assert chunks[1] == "C" * 1000
    # a single section bigger than the limit is still cut into sendable pieces
    assert [len(c) for c in adm.help_chunks("X" * 350, limit=100)] == [100] * 3 + [50]


class FakeBot:
    """Records what the bot would have sent, and hands back message ids."""

    def __init__(self):
        self.messages: list[tuple[int, str]] = []
        self.photos: list[int] = []
        self.captions: list[tuple[int, str]] = []
        self.deleted: list[int] = []
        self._next_id = 100

    async def send_message(self, chat_id, text, **kw):
        self.messages.append((chat_id, text))
        return self._msg()

    async def send_photo(self, chat_id, photo, **kw):
        self.photos.append(chat_id)
        return self._msg()

    async def edit_message_caption(self, chat_id, message_id, caption, **kw):
        self.captions.append((chat_id, caption))

    async def delete_message(self, chat_id, message_id, **kw):
        self.deleted.append(chat_id)

    def _msg(self):
        self._next_id += 1
        return SimpleNamespace(
            message_id=self._next_id,
            photo=[SimpleNamespace(file_id=f"file{self._next_id}")],
        )

    def texts_to(self, uid: int) -> str:
        return "\n".join(t for c, t in self.messages if c == uid)


class FakeQuery:
    def __init__(self, data: str):
        self.data = data
        self.answers: list[str | None] = []
        self.markups: list = []

    async def answer(self, text=None):
        self.answers.append(text)

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markups.append(reply_markup)


def ctx(bot: FakeBot):
    return SimpleNamespace(bot=bot, user_data={})


def tap(context, uid: int, action: str, date: str = DATE) -> FakeQuery:
    """One button press on the pre-publish check."""
    query = FakeQuery(f"proof:{date}:{action}")
    update = SimpleNamespace(
        callback_query=query, effective_user=SimpleNamespace(id=uid)
    )
    asyncio.run(usr.on_proof(update, context))
    return query


def seed_day(proofers=(1, 2, 3, 4, 5, 6), submitters=(1, 2, 3, 4, 5, 6)):
    """A day past its deadline: photos in, contact sheet out, collage pending."""
    for uid in set(proofers) | set(submitters):
        db.upsert_user(uid, f"U{uid}", None)
    for uid in proofers:
        db.set_proofer(uid, True)
    for uid in submitters:
        db.upsert_photo(DATE, uid, f"/photo{uid}.jpg")
    db.create_day(DATE, db.add_prompt("Send a photo of the sky", 99))
    db.set_day_field(DATE, "moderation_sent_at", "2026-07-28T21:00:00+02:00")


# --- who gets asked -----------------------------------------------------------

def test_batch_prefers_submitters_then_rotates_by_last_asked():
    seed_day(proofers=(1, 2, 3), submitters=(3,))
    # 3 took part today and would receive this collage anyway, so they lead
    assert jobs.pick_proof_batch(DATE, 3) == [3, 1, 2]
    # asking is what advances the rotation, answered or not
    db.add_proof_ask("2026-07-27", 1, 1)
    assert jobs.pick_proof_batch(DATE, 3) == [3, 2, 1]
    # nobody is asked twice in one day
    db.add_proof_ask(DATE, 3, 1)
    assert jobs.pick_proof_batch(DATE, 3) == [2, 1]


def test_inactive_and_unflagged_users_are_never_asked():
    seed_day(proofers=(1, 2), submitters=(1, 2, 3))
    db.set_user_status(2, "inactive")
    assert jobs.pick_proof_batch(DATE, 5) == [1]


# --- the happy path -----------------------------------------------------------

def test_one_approval_publishes_and_clears_every_copy(monkeypatch):
    seed_day(proofers=(1, 2, 3))
    bot = FakeBot()
    context = ctx(bot)
    sent: list[str] = []

    async def fake_send_collage(context, date, preview_to=None):
        sent.append(date)
        return "sent to 6"

    monkeypatch.setattr(jobs, "send_collage", fake_send_collage)

    assert asyncio.run(jobs.send_proof_round(context, DATE, 1)) == 3
    assert sorted(bot.photos) == [1, 2, 3]

    tap(context, 1, "ok")

    assert sent == [DATE]
    assert db.get_day(DATE)["proof_result"] == "approved"
    # the one who acted keeps their copy, captioned with the outcome
    assert [c for c, _ in bot.captions] == [1]
    assert "Published" in bot.captions[0][1]
    # the two who hadn't got round to it just have the question taken away
    assert sorted(bot.deleted) == [2, 3]
    assert db.get_proof_ask(DATE, 2)["message_id"] is None
    assert "approved the collage" in bot.texts_to(99)


def test_a_stranger_cannot_publish_the_collage(monkeypatch):
    seed_day(proofers=(1, 2, 3))
    bot = FakeBot()
    context = ctx(bot)
    monkeypatch.setattr(
        jobs, "send_collage", lambda *a, **k: pytest.fail("must not publish")
    )
    asyncio.run(jobs.send_proof_round(context, DATE, 1))
    query = tap(context, 5, "ok")  # user 5 was never asked tonight
    assert query.answers == ["This check isn't yours tonight 🙂"]
    assert db.get_day(DATE)["proof_result"] is None


# --- holding ------------------------------------------------------------------

def test_a_ban_takes_two_taps():
    seed_day(proofers=(1, 2, 3))
    bot = FakeBot()
    context = ctx(bot)
    asyncio.run(jobs.send_proof_round(context, DATE, 1))

    query = tap(context, 1, "hold")
    labels = [b.text for row in query.markups[0].inline_keyboard for b in row]
    assert labels == ["🚫 Really ban", "✅ Changed my mind, all good"]
    assert db.get_proof_ask(DATE, 1)["value"] is None  # nothing recorded yet

    query = tap(context, 1, "back")
    labels = [b.text for row in query.markups[0].inline_keyboard for b in row]
    assert labels == ["👍 All good", "🚫 Ban"]  # back to the plain question
    assert db.get_proof_ask(DATE, 1)["value"] is None

    tap(context, 1, "holdyes")
    assert db.get_proof_ask(DATE, 1)["value"] == "ban"


def test_a_hold_beats_a_later_approval(monkeypatch):
    """The collage stops being publishable the moment anyone flags it, however
    fast someone else waves it through."""
    seed_day(proofers=(1, 2, 3, 4, 5, 6))
    bot = FakeBot()
    context = ctx(bot)
    monkeypatch.setattr(
        jobs, "send_collage", lambda *a, **k: pytest.fail("must not publish")
    )
    asyncio.run(jobs.send_proof_round(context, DATE, 1))

    tap(context, 1, "holdyes")
    query = tap(context, 2, "ok")

    assert db.proof_counts(DATE) == {"approve": 1, "ban": 1}
    assert db.get_day(DATE)["proof_result"] is None  # not published, not resolved
    assert "looked at again" in query.answers[0]


def test_two_holds_park_the_day_on_the_admin():
    seed_day(proofers=(1, 2, 3, 4, 5, 6))
    bot = FakeBot()
    context = ctx(bot)
    asyncio.run(jobs.send_proof_round(context, DATE, 1))

    tap(context, 1, "holdyes")
    assert db.get_day(DATE)["proof_result"] is None  # one flag is not a veto
    assert db.get_day(DATE)["proof_round"] == 2  # fresh eyes instead

    context.user_data.clear()
    tap(context, 4, "holdyes")  # someone from the escalation batch agrees
    assert db.get_day(DATE)["proof_result"] == "held"
    assert "on hold" in bot.texts_to(99)
    # the four who never answered lose the question rather than keeping a
    # keyboard for a day that's already decided
    assert sorted(set(bot.deleted)) == [2, 3, 5, 6]


def test_one_hold_then_an_approval_publishes_and_tells_the_admin(monkeypatch):
    seed_day(proofers=(1, 2, 3, 4, 5, 6))
    bot = FakeBot()
    context = ctx(bot)
    sent: list[str] = []

    async def fake_send_collage(context, date, preview_to=None):
        sent.append(date)
        return "sent to 6"

    monkeypatch.setattr(jobs, "send_collage", fake_send_collage)
    asyncio.run(jobs.send_proof_round(context, DATE, 1))

    tap(context, 1, "holdyes")
    db.set_proof_note(DATE, 1, "photo 4 has an address on it")
    # round 2 sees nothing wrong — one flag alone doesn't hold the day
    context.user_data.clear()
    tap(context, 4, "ok")

    assert sent == [DATE]
    assert db.get_day(DATE)["proof_result"] == "approved"
    assert "photo 4 has an address on it" in "\n".join(jobs.proof_hold_lines(DATE))


def test_a_hold_with_nobody_left_to_ask_is_held():
    seed_day(proofers=(1, 2))
    bot = FakeBot()
    context = ctx(bot)
    asyncio.run(jobs.send_proof_round(context, DATE, 1))
    tap(context, 1, "holdyes")
    # both proofers were in round 1, so there is no fresh batch to escalate to
    assert db.get_day(DATE)["proof_result"] == "held"


# --- timeouts and fallbacks ---------------------------------------------------

def run_proofing(context, minutes_later: int = 0):
    day = db.get_day(DATE)
    now = jobs.now_local() + timedelta(minutes=minutes_later)
    return asyncio.run(jobs.run_proofing(context, DATE, now, day))


def test_silence_escalates_to_the_next_batch():
    seed_day(proofers=(1, 2, 3, 4, 5, 6))
    bot = FakeBot()
    context = ctx(bot)

    assert run_proofing(context) is True  # first batch goes out
    assert sorted(bot.photos) == [1, 2, 3]

    assert run_proofing(context, minutes_later=5) is True  # still their round
    assert len(bot.photos) == 3

    assert run_proofing(context, minutes_later=20) is True
    assert sorted(bot.photos) == [1, 2, 3, 4, 5, 6]
    assert db.get_day(DATE)["proof_round"] == 2


def test_nobody_answers_at_all_hands_the_day_back():
    seed_day(proofers=(1, 2))
    bot = FakeBot()
    context = ctx(bot)
    assert run_proofing(context) is True
    # the whole list has been asked and stayed silent -> admin nudges resume
    assert run_proofing(context, minutes_later=20) is False
    assert db.get_day(DATE)["proof_result"] == "exhausted"
    assert "nobody on the proofing list answered" in bot.texts_to(99)


def test_proofing_stays_out_of_the_way_when_it_cannot_run():
    seed_day(proofers=())
    bot = FakeBot()
    context = ctx(bot)
    assert run_proofing(context) is False  # nobody flagged as a proofer
    assert bot.photos == []

    db.set_proofer(1, True)
    db.set_setting("proof_enabled", "0")
    assert run_proofing(context) is False
    assert bot.photos == []

    db.set_setting("proof_enabled", "1")
    assert run_proofing(context) is True


def test_a_settled_day_ignores_late_taps(monkeypatch):
    seed_day(proofers=(1, 2, 3))
    bot = FakeBot()
    context = ctx(bot)
    monkeypatch.setattr(
        jobs, "send_collage", lambda *a, **k: pytest.fail("must not publish twice")
    )
    asyncio.run(jobs.send_proof_round(context, DATE, 1))
    db.set_day_field(DATE, "collage_sent_at", "2026-07-28T21:02:00+02:00")

    query = tap(context, 2, "ok")
    assert query.answers == ["Already handled — thanks anyway!"]
    assert db.get_proof_ask(DATE, 2)["value"] is None
    # and proofing no longer owns the day
    assert run_proofing(context) is False


# --- the note that comes after a hold -----------------------------------------

def test_the_note_after_a_hold_reaches_the_admin():
    seed_day(proofers=(1, 2, 3))
    bot = FakeBot()
    context = ctx(bot)
    asyncio.run(jobs.send_proof_round(context, DATE, 1))
    tap(context, 1, "holdyes")
    assert context.user_data["awaiting"] == f"proofnote:{DATE}"

    replies: list[str] = []

    async def reply_text(text):
        replies.append(text)

    message = SimpleNamespace(
        text="number 4, someone's passport is in the shot",
        reply_to_message=None,
        media_group_id=None,
        reply_text=reply_text,
    )
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=1, first_name="U1", username=None),
    )
    asyncio.run(usr.on_other(update, context))

    assert db.get_proof_ask(DATE, 1)["note"].startswith("number 4")
    assert "passport" in bot.texts_to(99)
    assert replies == ["Passed it on to the organizer 🙏"]
