"""Knock, knock — end-to-end rehearsal against the test bot.

Seeds a throwaway day from real submissions, sends the collage through the REAL
send_collage() (so the door button, the frozen mosaic order and the file_id
path are all the shipping code), pours a fake knock distribution into the
tally, and then runs the real Application so every handler works: tap the door,
flip the carousel, knock, and run /knocks to read the result.

    .venv/bin/python scripts/knock_sim.py --chat 87494556
    .venv/bin/python scripts/knock_sim.py --chat 87494556 --dist "1 1 0 0 0 2 3 1 3 1 0"

Everything lands in a temp DATA_DIR, so the real DB is untouched. Test-only.
"""
import argparse
import asyncio
import os
import sys
import tempfile
from datetime import date as date_cls
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROMPT_EN = "Send a photo of the sky, wherever you are"
PROMPT_RU = "Пришли фото неба, где бы ты ни был"
DEFAULT_DIST = "1 1 0 0 0 2 3 1 3 1 0"


def author_id(path: Path) -> int:
    """Submissions are stored as u<telegram_id>.jpg — reuse the real ids so the
    tally reads like a real night, including the tester's own photo."""
    return int(path.stem.lstrip("u"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", type=int, required=True)
    ap.add_argument(
        "--photos", type=Path, default=Path.home() / "Downloads" / "2026-07-21"
    )
    ap.add_argument("--dist", type=str, default=DEFAULT_DIST,
                    help="knocks per photo, in mosaic order")
    args = ap.parse_args()

    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="photobot_knock_")

    from telegram import Update  # noqa: E402
    from photobot import config, db, jobs, main as app_main  # noqa: E402

    if not config.ALLOWED_USER_IDS:
        raise SystemExit(
            "ALLOWED_IDS is empty — this .env looks like PRODUCTION. Refusing to "
            "run: it would collide with the NAS instance."
        )
    config.validate()
    db.init()

    photos = sorted(args.photos.glob("u*.jpg"))
    if not photos:
        raise SystemExit(f"no u*.jpg in {args.photos}")

    # Today, because the knock window is "until noon tomorrow" — a day from the
    # archive would open already closed.
    date = date_cls.today().isoformat()
    pid = db.add_prompt(PROMPT_EN, added_by=args.chat, text_ru=PROMPT_RU)
    db.create_day(date, pid)
    db.set_setting("project_start_date", date)
    db.upsert_user(args.chat, "Nikita", "kaydanych")
    db.set_user_lang(args.chat, "en")
    for i, p in enumerate(photos, 1):
        uid = author_id(p)
        db.upsert_user(uid, f"Player {i}", None)
        db.upsert_photo(date, uid, str(p))

    # Deliver only to the tester; the other 20 are fake chats.
    config.ADMIN_IDS = {args.chat}
    db.submitter_ids = lambda d: [args.chat]

    async def go(bot):
        await jobs.send_collage(SimpleNamespace(bot=bot), date)

    app = app_main.build_app()
    # The one-minute tick would start running the day (prompts, deadlines) on
    # top of the rehearsal — this is a handler test, not a schedule test.
    for job in app.job_queue.jobs():
        job.schedule_removal()

    async def post_init(application):
        await go(application.bot)
        seed_knocks(db, date, args.dist, args.chat)
        print(report(db, jobs, date), flush=True)

    app.post_init = post_init
    print(f"day {date}: {len(photos)} photos, dist [{args.dist}]", flush=True)
    print("Polling — tap the door, then try /knocks. Ctrl-C to stop.", flush=True)
    # Telegram remembers the allowed_updates of the last getUpdates call, so a
    # previous run of knock_lab.py (callback_query only) would otherwise keep
    # swallowing every command here — taps work, /knocks silently never arrives.
    app.run_polling(allowed_updates=Update.ALL_TYPES)


def seed_knocks(db, date: str, dist: str, tester: int) -> None:
    """Pour `dist` knocks onto the first photos in mosaic order, drawn from the
    day's other submitters. The tester's own knock is left unspent so there's
    still something to do by hand."""
    cells = db.collage_cells(date)
    counts = [int(x) for x in dist.split()]
    pool = [uid for uid in cells if uid != tester]
    used: set[int] = set()
    for idx, want in enumerate(counts):
        if idx >= len(cells):
            break
        target = cells[idx]
        for uid in pool:
            if want <= 0:
                break
            if uid == target or uid in used:
                continue
            db.set_knock(date, uid, target)
            used.add(uid)
            want -= 1


def report(db, jobs, date: str) -> str:
    photos = db.photos_for(date, include_excluded=True)
    number_of = {p["tg_id"]: i for i, p in enumerate(photos, 1)}
    lines = [f"seeded {len(db.knock_tally(date))} doors with knocks:"]
    for rank, row in enumerate(db.knock_tally(date), 1):
        u = db.get_user(row["target_id"])
        lines.append(
            f"  {rank}. {row['n']} × knock — #{number_of.get(row['target_id'], '?')} "
            f"{u['first_name'] if u else row['target_id']}"
        )
    lines.append(f"window open: {jobs.knock_open_for(date)}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
