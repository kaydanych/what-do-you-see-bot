import pytest

from photobot import db, jobs


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.init(tmp_path / "test.db")
    yield


def test_rating_upsert_and_counts():
    assert db.set_rating("2026-07-16", 1, "fire") is True
    assert db.set_rating("2026-07-16", 2, "fire") is True
    assert db.set_rating("2026-07-16", 3, "meh") is True
    # same value again -> no change, callers skip keyboard edits
    assert db.set_rating("2026-07-16", 1, "fire") is False
    # switching the vote replaces, never duplicates
    assert db.set_rating("2026-07-16", 3, "like") is True
    assert db.rating_counts("2026-07-16") == {"fire": 2, "like": 1}
    assert db.rating_counts_total() == {"fire": 2, "like": 1}


def test_rating_keyboard_shows_tallies():
    kb = jobs.rating_keyboard("2026-07-16")
    row = kb.inline_keyboard[0]
    assert [b.text for b in row] == ["🔥", "👍", "😐"]  # no counts before votes
    assert row[0].callback_data == "rate:2026-07-16:fire"
    db.set_rating("2026-07-16", 1, "fire")
    db.set_rating("2026-07-16", 2, "fire")
    row = jobs.rating_keyboard("2026-07-16").inline_keyboard[0]
    assert [b.text for b in row] == ["🔥 2", "👍", "😐"]
    assert jobs.rating_summary("2026-07-16") == "🔥 2"
    assert jobs.rating_summary("2026-07-15") is None


def test_collage_messages_remembered_per_user():
    db.add_collage_message("2026-07-16", 1, 100)
    db.add_collage_message("2026-07-16", 2, 200)
    db.add_collage_message("2026-07-16", 1, 101)  # resend replaces
    rows = {r["tg_id"]: r["message_id"] for r in db.collage_messages_for("2026-07-16")}
    assert rows == {1: 101, 2: 200}


def test_feedback_stored():
    fid = db.add_feedback(1, "  love the collages  ")
    assert fid == 1
    fid2 = db.add_feedback(2, "more prompts please")
    assert fid2 == 2


def test_suggestion_lifecycle_and_credit():
    db.upsert_user(7, "Ann", "ann")
    sid = db.add_suggestion(7, "something red")
    assert [r["id"] for r in db.pending_suggestions()] == [sid]

    pid = db.add_prompt("Something red", 7, text_ru="Что-то красное", source="suggestion")
    db.set_suggestion_status(sid, "approved")
    assert db.pending_suggestions() == []
    assert db.get_suggestion(sid)["status"] == "approved"

    prompt = db.get_prompt(pid)
    assert "Ann" in jobs.prompt_credit(prompt, "en")
    assert "Ann" in jobs.prompt_credit(prompt, "ru")
    # library prompts never carry a credit line
    library = db.get_prompt(db.add_prompt("water", 7))
    assert jobs.prompt_credit(library, "en") == ""


def test_participation_and_collage_dates():
    for d in ("2026-07-14", "2026-07-15", "2026-07-16"):
        db.ensure_day(d)
        db.set_day_field(d, "collage_sent_at", d + "T21:15:00")
    db.ensure_day("2026-07-13")  # no collage -> not counted
    assert db.collage_dates() == ["2026-07-14", "2026-07-15", "2026-07-16"]

    db.upsert_photo("2026-07-14", 1, "/a.jpg")
    db.upsert_photo("2026-07-15", 1, "/b.jpg")
    db.upsert_photo("2026-07-16", 1, "/c.jpg")
    db.upsert_photo("2026-07-16", 2, "/d.jpg")
    db.set_photo_excluded("2026-07-16", 2, True)  # moderated out -> not counted
    part = db.participation()
    assert part[1] == {"2026-07-14", "2026-07-15", "2026-07-16"}
    assert 2 not in part
