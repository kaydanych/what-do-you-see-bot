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


def test_prompt_pick_and_recycle():
    assert db.pick_prompt() == (None, False)
    a = db.add_prompt("water", 1)
    b = db.add_prompt("sad", 1)
    p1, recycled = db.pick_prompt()
    assert not recycled
    db.mark_prompt_used(p1["id"], "2026-07-01")
    p2, recycled = db.pick_prompt()
    assert not recycled and p2["id"] != p1["id"]
    db.mark_prompt_used(p2["id"], "2026-07-02")
    p3, recycled = db.pick_prompt()
    assert recycled and p3["id"] == p1["id"]  # oldest-used comes back first
    assert db.count_unused_prompts() == 0


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
