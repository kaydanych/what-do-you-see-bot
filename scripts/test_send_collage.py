"""Integration test for the REAL send_collage() path (hybrid photo + hi-res
file), against the test bot, isolated in a temp data dir. Only sends to --chat.

    .venv/bin/python scripts/test_send_collage.py --chat 87494556
"""
import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATE = "2026-07-21"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", type=int, required=True)
    ap.add_argument("--photos", type=Path, default=Path.home() / "Downloads" / DATE)
    args = ap.parse_args()

    # Isolate all DB/photo/log writes into a throwaway dir.
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="photobot_it_")

    from telegram import Bot  # noqa: E402
    from telegram.request import HTTPXRequest  # noqa: E402
    from photobot import config, db, jobs  # noqa: E402

    config.validate()
    db.init()

    photos = sorted(args.photos.glob("u*.jpg"))
    assert photos, f"no u*.jpg in {args.photos}"

    pid = db.add_prompt(
        "Send a photo of the sky, wherever you are",
        added_by=args.chat,
        text_ru="Пришли фото неба, где бы ты ни был",
    )
    db.create_day(DATE, pid)
    db.set_setting("project_start_date", "2026-07-12")  # -> "Day 10"
    db.upsert_user(args.chat, "Nikita", "kaydanych")
    db.set_user_lang(args.chat, "en")
    for i, p in enumerate(photos):
        db.upsert_photo(DATE, 900000 + i, str(p))  # distinct fake submitters

    # Deliver only to the tester, exercising the full hybrid path.
    config.ADMIN_IDS = {args.chat}
    db.submitter_ids = lambda date: [args.chat]

    async def go():
        req = HTTPXRequest(connect_timeout=30, read_timeout=180, write_timeout=180)
        bot = Bot(config.BOT_TOKEN, request=req)
        async with bot:
            ctx = SimpleNamespace(bot=bot)
            result = await jobs.send_collage(ctx, DATE)
            print("send_collage ->", result)

    asyncio.run(go())


if __name__ == "__main__":
    main()
