import pytest

from photobot import db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.init(tmp_path / "test.db")
    yield


def test_user_lifecycle():
    assert db.upsert_user(1, "Nik", "nik") is True
    assert db.upsert_user(1, "Nik", "nik") is False
    db.set_user_status(1, "kicked")
    # kicked users are not reactivated by upsert
    db.upsert_user(1, "Nik", "nik")
    assert db.get_user(1)["status"] == "kicked"
    db.set_user_status(1, "active")
    assert db.active_user_ids() == [1]
    assert db.get_user_by_username("@NIK")["tg_id"] == 1


def test_prompt_pick_is_sequential_then_stops():
    assert db.pick_prompt() is None
    a = db.add_prompt("water", 1)
    b = db.add_prompt("sad", 1)
    # sequential: lowest id (first added) comes first
    assert db.pick_prompt()["id"] == a
    db.mark_prompt_used(a, "2026-07-01")
    assert db.pick_prompt()["id"] == b
    db.mark_prompt_used(b, "2026-07-02")
    # exhausted -> stop (no recycling)
    assert db.pick_prompt() is None
    assert db.count_unused_prompts() == 0


def test_replace_prompt_queue_keeps_used_and_orders():
    old = db.add_prompt("old unused", 1)
    used = db.add_prompt("already sent", 1)
    db.mark_prompt_used(used, "2026-07-01")

    queued, kept = db.replace_prompt_queue(
        [("first", None), ("already sent", None), ("second", "второй")], 1
    )
    assert (queued, kept) == (2, 1)  # "already sent" skipped as done

    rows = db.list_prompts()
    texts = [r["text"] for r in rows]
    # the stale unused prompt is gone; the used one is kept as history
    assert "old unused" not in texts
    assert "already sent" in texts
    # queue is served in file order, after the kept (older-id) used prompt
    assert db.pick_prompt()["text"] == "first"
    # bilingual survives the upload
    assert next(r["text_ru"] for r in rows if r["text"] == "second") == "второй"


def test_photo_upsert_replaces():
    assert db.upsert_photo("2026-07-04", 1, "/a.jpg") is False
    assert db.upsert_photo("2026-07-04", 1, "/b.jpg") is True
    rows = db.photos_for("2026-07-04")
    assert len(rows) == 1 and rows[0]["file_path"] == "/b.jpg"
    assert db.submitter_ids("2026-07-04") == [1]


def test_day_fields():
    db.ensure_day("2026-07-04")
    db.set_day_field("2026-07-04", "skipped", 1)
    assert db.get_day("2026-07-04")["skipped"] == 1


def test_user_lang():
    db.upsert_user(5, "Ann", "ann")
    assert db.get_user_lang(5) is None
    db.set_user_lang(5, "en")
    assert db.get_user_lang(5) == "en"
    # lang survives re-registration (e.g. repeated /start)
    db.upsert_user(5, "Ann", "ann")
    assert db.get_user_lang(5) == "en"


def test_settings_defaults_and_override():
    assert db.get_setting("prompt_time") == "09:00"
    db.set_setting("prompt_time", "10:30")
    assert db.get_setting("prompt_time") == "10:30"
