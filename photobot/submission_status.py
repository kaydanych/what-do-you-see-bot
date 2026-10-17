"""Small, private NAS snapshot of submission records; never reads photo bytes."""

import json
import logging
import os

from . import config, db

log = logging.getLogger(__name__)


def snapshot() -> dict:
    users = {row["tg_id"]: row for row in db.list_users()}

    def person(uid: int) -> dict:
        user = users.get(uid)
        return {
            "tg_id": uid,
            "name": user["first_name"] if user else None,
            "username": user["username"] if user else None,
        }

    daily = []
    for date in db.submission_status_dates():
        day = db.get_day(date)
        daily.append({
            "date": date,
            "prompt_sent_at": day["prompt_sent_at"] if day else None,
            "skipped": bool(day["skipped"]) if day else False,
            "collage_sent_at": day["collage_sent_at"] if day else None,
            "submissions": [
                {
                    **person(photo["tg_id"]),
                    "status": "excluded" if photo["excluded"] else "accepted",
                    "submitted_at": photo["submitted_at"],
                    "file_path": photo["file_path"],
                }
                for photo in db.photos_for(date, include_excluded=True)
            ],
        })

    correspondence_seasons, observation_seasons = db.submission_status_seasons()
    correspondence = []
    for season in reversed(correspondence_seasons):
        pairs = []
        for pair in db.correspondence_pairs_for(season["id"]):
            draft = db.correspondence_draft(pair["id"])
            pairs.append({
                "pair_id": pair["id"],
                "status": pair["status"],
                "participants": [person(pair["user_a"]), person(pair["user_b"])],
                "next_tg_id": pair["next_tg_id"],
                "links": [
                    {
                        "position": link["position"],
                        "sender_id": link["sender_id"],
                        "submitted_at": link["submitted_at"],
                        "file_path": link["file_path"],
                    }
                    for link in db.correspondence_links(pair["id"])
                ],
                "draft": {
                    "position": draft["position"],
                    "sender_id": draft["sender_id"],
                    "status": draft["status"],
                    "submitted_at": draft["submitted_at"],
                    "file_path": draft["file_path"],
                    "last_error": draft["last_error"],
                } if draft else None,
            })
        correspondence.append({
            "season_id": season["id"],
            "name": season["name"],
            "status": season["status"],
            "target_links": season["target_links"],
            "pairs": pairs,
        })

    observation = []
    for season in reversed(observation_seasons):
        photos_by_user: dict[int, list] = {}
        for photo in db.observation_photos_for(season["id"]):
            photos_by_user.setdefault(photo["tg_id"], []).append(photo)
        observation.append({
            "season_id": season["id"],
            "status": season["status"],
            "members": [
                {
                    **person(member["tg_id"]),
                    "status": member["status"],
                    "user_status": member["user_status"],
                    "submissions": [
                        {
                            "date": photo["local_date"],
                            "submitted_at": photo["submitted_at"],
                            "file_path": photo["file_path"],
                        }
                        for photo in photos_by_user.get(member["tg_id"], [])
                    ],
                }
                for member in db.observation_members(season["id"])
            ],
        })
    return {
        "schema_version": 1,
        "summary": {
            "daily_submissions": sum(len(day["submissions"]) for day in daily),
            "correspondence_links": sum(
                len(pair["links"]) for season in correspondence for pair in season["pairs"]
            ),
            "correspondence_drafts": sum(
                pair["draft"] is not None
                for season in correspondence for pair in season["pairs"]
            ),
            "observation_submissions": sum(
                len(member["submissions"])
                for season in observation for member in season["members"]
            ),
        },
        "daily": daily,
        "correspondence": correspondence,
        "observation": observation,
    }


def sync() -> None:
    """Write a complete snapshot atomically, only when the DB state changed."""
    path = config.DATA_DIR / "exports" / "submissions-status.json"
    payload = (json.dumps(snapshot(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == payload:
        return
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def sync_safely() -> None:
    try:
        sync()
    except OSError:
        log.exception("could not update submission status file")
