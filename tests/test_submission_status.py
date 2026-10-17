"""A small NAS status file tracks all three games without opening image files."""

import json

from photobot import config, db, submission_status


def test_snapshot_covers_daily_correspondence_and_observation(tmp_path, monkeypatch):
    db.init(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.upsert_user(1, "Ada", "ada")
    db.upsert_user(2, "Bo", "bo")

    db.upsert_photo("2026-07-04", 1, "/missing/daily.jpg")
    db.set_photo_excluded("2026-07-04", 1, True)
    db.ensure_day("2026-07-05")

    when = "2026-08-17T09:00:00+02:00"
    season_id = db.create_correspondence_season(
        name="Letters", prompt="Blue", prompt_ru=None,
        enrollment_opens_at=when, enrollment_reminder1_at=when,
        enrollment_reminder2_at=when, starts_at=when, ends_at=when,
    )
    db.set_correspondence_season_field(season_id, "status", "active")
    pair_id = db.create_correspondence_pair(season_id, 1, 2, 1, when)
    db.upsert_correspondence_draft(
        pair_id, 1, 1, "/missing/draft.jpg", "telegram-id", when, when
    )

    observation_id = db.create_observation_season("2026-09-21")
    db.enroll_active_observation_members(observation_id)
    db.upsert_observation_photo(
        observation_id, 2, "2026-09-22", "/missing/place.jpg", None, when
    )

    submission_status.sync()
    path = tmp_path / "exports" / "submissions-status.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["summary"] == {
        "daily_submissions": 1,
        "correspondence_links": 0,
        "correspondence_drafts": 1,
        "observation_submissions": 1,
    }
    assert payload["daily"][0]["submissions"] == []
    assert payload["daily"][1]["submissions"][0]["status"] == "excluded"
    pair = payload["correspondence"][0]["pairs"][0]
    assert pair["draft"]["file_path"] == "/missing/draft.jpg"
    assert pair["links"] == []
    members = payload["observation"][0]["members"]
    assert next(m for m in members if m["tg_id"] == 2)["submissions"][0]["date"] == "2026-09-22"
    before = path.stat().st_mtime_ns
    submission_status.sync()
    assert path.stat().st_mtime_ns == before
