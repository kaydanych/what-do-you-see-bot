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


def test_preview_sent_at_field():
    db.set_day_field("2026-07-04", "preview_sent_at", "2026-07-04T21:10:00")
    assert db.get_day("2026-07-04")["preview_sent_at"] == "2026-07-04T21:10:00"


def test_preview_time_default():
    assert db.get_setting("preview_time") == "21:10"


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


def test_streaks_for_counts_today_before_collage_marked():
    # Three prior collage days already went out; today's is still in flight.
    for d in ("2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23"):
        db.create_day(d, None)
    for d in ("2026-07-20", "2026-07-21", "2026-07-22"):
        db.set_day_field(d, "collage_sent_at", f"{d}T21:00:00")
    # Ann submitted every day incl. today; Bob missed 07-21 (breaks his streak).
    for d in ("2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23"):
        db.upsert_photo(d, 1, f"/x/{d}-ann.jpg")
    for d in ("2026-07-20", "2026-07-22", "2026-07-23"):
        db.upsert_photo(d, 2, f"/x/{d}-bob.jpg")

    streaks = db.streaks_for("2026-07-23")
    assert streaks[1] == 4          # counts today even though it's unmarked
    assert streaks[2] == 2          # 07-22 + 07-23, broken by missing 07-21


def test_streaks_for_excludes_non_submitters():
    db.create_day("2026-07-22", None)
    db.set_day_field("2026-07-22", "collage_sent_at", "2026-07-22T21:00:00")
    db.create_day("2026-07-23", None)
    db.upsert_photo("2026-07-23", 1, "/x/a.jpg")
    streaks = db.streaks_for("2026-07-23")
    assert streaks == {1: 1}        # only actual submitters appear


def test_story_lifecycle():
    sid = db.add_story("2026-07-21", 42, ask_message_id=555)
    # freshly asked: shows up as the author's pending ask, matchable by reply
    assert db.pending_story_for(42)["id"] == sid
    assert db.story_by_ask_message(42, 555)["id"] == sid
    assert db.story_by_ask_message(42, 999) is None  # wrong message
    assert db.answered_stories() == []  # not answered yet

    db.set_story_answer(sid, "  it reminded me of home  ")
    s = db.get_story(sid)
    assert s["status"] == "answered" and s["text"] == "it reminded me of home"
    assert s["answered_at"] is not None
    # answered asks no longer count as pending, and now await publishing
    assert db.pending_story_for(42) is None
    assert [r["id"] for r in db.answered_stories()] == [sid]

    assert db.set_story_status(sid, "published") is True
    assert db.get_story(sid)["published_at"] is not None
    assert db.answered_stories() == []
    assert db.set_story_status(9999, "dismissed") is False  # missing id


def test_story_edit_and_manual_authoring():
    # editing an unanswered ask authors it (moves asked -> answered)
    sid = db.add_story("2026-07-21", 5, ask_message_id=None)
    assert db.get_story(sid)["status"] == "asked"
    assert db.set_story_text(sid, "  admin-written  ") is True
    s = db.get_story(sid)
    assert s["status"] == "answered" and s["text"] == "admin-written"
    assert [r["id"] for r in db.answered_stories()] == [sid]
    # editing a published story tweaks text but keeps it published
    db.set_story_status(sid, "published")
    assert db.set_story_text(sid, "post-publish tweak") is True
    assert db.get_story(sid)["status"] == "published"
    assert db.set_story_text(999, "x") is False  # missing id


def test_story_translation_replaces_both_halves():
    sid = db.add_story("2026-07-26", 8, ask_message_id=None)
    db.set_story_answer(sid, "почему я выбрал этот кадр")
    assert db.get_story(sid)["text_ru"] is None  # a raw reply has no translation
    assert db.set_story_text(sid, "why I chose it", "  почему я выбрал  ") is True
    s = db.get_story(sid)
    assert (s["text"], s["text_ru"]) == ("why I chose it", "почему я выбрал")
    # an edit without a RU half drops the old translation rather than keeping
    # a stale one paired with new English
    db.set_story_text(sid, "why I chose it, take two")
    assert db.get_story(sid)["text_ru"] is None


def test_photo_dates():
    db.upsert_photo("2026-07-20", 1, "/a.jpg")
    db.upsert_photo("2026-07-20", 2, "/b.jpg")
    db.upsert_photo("2026-07-21", 1, "/c.jpg")
    assert db.photo_dates() == ["2026-07-20", "2026-07-21"]


def test_story_reply_match_prefers_exact_ask():
    # same author asked about two different days
    a = db.add_story("2026-07-20", 7, ask_message_id=100)
    b = db.add_story("2026-07-21", 7, ask_message_id=200)
    # a reply to the older ask resolves to that story, not just the latest
    assert db.story_by_ask_message(7, 100)["id"] == a
    assert db.story_by_ask_message(7, 200)["id"] == b
    # the bare fallback returns the most recent open ask
    assert db.pending_story_for(7)["id"] == b
