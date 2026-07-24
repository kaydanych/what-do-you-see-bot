"""Seed the local ./data DB with a *past* finished day so you can test the
"story of the day" flow against the test bot end to end — as the author.

One of the seeded photos is owned by --chat (your Telegram id), so /askstory
DMs it back to you and you can reply to test the capture, then /publishstory.

    .venv/bin/python scripts/seed_story.py --chat 87494556 --date 2026-07-23
    .venv/bin/python -m photobot.main        # then drive it from Telegram:
    #   /photos 2026-07-23         -> find your number N
    #   /askstory 2026-07-23 N     -> the bot DMs you the photo + asks why
    #   (reply to that message)    -> "Story #k" lands in your admin chat
    #   /stories                   -> see it waiting
    #   /publishstory k            -> photo + story goes to that day's submitters

The day is marked done (skipped/preview/moderation) so the running bot's
scheduler stays idle during the test. Test-only; not part of the deployed app.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from photobot import config, db, jobs  # noqa: E402

DONE_FIELDS = ["skipped", "preview_sent_at", "moderation_sent_at"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", type=int, required=True, help="your Telegram id (the author)")
    ap.add_argument("--date", default=None, help="ISO date to seed (default: yesterday)")
    ap.add_argument(
        "--photos", type=Path, default=Path.home() / "Downloads" / "2026-07-21"
    )
    args = ap.parse_args()

    config.validate()
    db.init()

    from datetime import date, timedelta

    seed_date = args.date or (jobs.now_local().date() - timedelta(days=1)).isoformat()
    date.fromisoformat(seed_date)  # validate

    photos = sorted(args.photos.glob("u*.jpg"))
    assert photos, f"no u*.jpg in {args.photos}"

    pid = db.add_prompt(
        "Send a photo of the sky, wherever you are",
        added_by=args.chat,
        text_ru="Пришли фото неба, где бы ты ни был",
    )
    db.mark_prompt_used(pid, seed_date)
    db.create_day(seed_date, pid)  # sets prompt_id + prompt_sent_at

    # You own the first photo (so /askstory reaches you); the rest get synthetic
    # ids so the day looks like a real multi-person submission.
    db.upsert_user(args.chat, "Nikita", "kaydanych")
    db.set_user_lang(args.chat, "en")
    db.upsert_photo(seed_date, args.chat, str(photos[0]))
    for i, p in enumerate(photos[1:], 1):
        db.upsert_photo(seed_date, 900000 + i, str(p))

    for f in DONE_FIELDS:
        db.set_day_field(
            seed_date, f, 1 if f == "skipped" else jobs.now_local().isoformat(timespec="seconds")
        )

    # The contact-sheet number is position in photos_for() order (submitted_at,
    # tg_id) — so compute YOUR number rather than assuming it's #1.
    photos = db.photos_for(seed_date, include_excluded=True)
    mine = next(i for i, p in enumerate(photos, 1) if p["tg_id"] == args.chat)
    print(f"seeded {seed_date}: {len(photos)} photos; your photo is #{mine}.")
    print(f"run the bot, then: /photos {seed_date}  ->  /askstory {seed_date} {mine}")


if __name__ == "__main__":
    main()
