"""Seed the local ./data DB (from .env DATA_DIR) with today fully 'done' and a
hybrid collage delivered to --chat, so you can then run the real bot and test
the poll tool (/poll … → vote → /pollresults <id>) from Telegram.

    .venv/bin/python scripts/seed_local.py --chat 87494556
    .venv/bin/python -m photobot.main          # then drive it from Telegram
"""
import argparse
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import Bot  # noqa: E402
from telegram.request import HTTPXRequest  # noqa: E402
from photobot import config, db, jobs  # noqa: E402

# Marking the day 'skipped' makes tick() return immediately, so the running bot
# won't fire prompts/reminders/moderation during the test. preview_sent_at is
# set too since the preview check runs before the skipped guard.
DONE_FIELDS = ["skipped", "preview_sent_at", "moderation_sent_at"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", type=int, required=True)
    ap.add_argument("--photos", type=Path, default=Path.home() / "Downloads" / "2026-07-21")
    args = ap.parse_args()

    config.validate()
    db.init()
    today = jobs.now_local().date().isoformat()

    photos = sorted(args.photos.glob("u*.jpg"))
    assert photos, f"no u*.jpg in {args.photos}"

    pid = db.add_prompt(
        "Send a photo of the sky, wherever you are",
        added_by=args.chat,
        text_ru="Пришли фото неба, где бы ты ни был",
    )
    db.create_day(today, pid)
    db.set_setting("project_start_date", "2026-07-12")
    db.upsert_user(args.chat, "Nikita", "kaydanych")
    db.set_user_lang(args.chat, "en")
    for i, p in enumerate(photos):
        db.upsert_photo(today, 900000 + i, str(p))

    # Deliver the hybrid collage only to the tester (so there's real context for
    # a poll), then mark every milestone done so the running bot's scheduler
    # stays idle during the test.
    config.ADMIN_IDS = {args.chat}
    db.submitter_ids = lambda date: [args.chat]

    async def go():
        req = HTTPXRequest(connect_timeout=30, read_timeout=180, write_timeout=180)
        bot = Bot(config.BOT_TOKEN, request=req)
        async with bot:
            print("send_collage ->", await jobs.send_collage(SimpleNamespace(bot=bot), today))

    asyncio.run(go())
    now = jobs.now_local().isoformat(timespec="seconds")
    for f in DONE_FIELDS:
        db.set_day_field(today, f, 1 if f == "skipped" else now)
    print(f"seeded {today}; collage recipients:",
          [r["tg_id"] for r in db.collage_messages_for(today)])


if __name__ == "__main__":
    main()
