"""Drive the collage-proofing flow end to end against the TEST bot.

    .venv/bin/python scripts/proof_lab.py --chat 87494556
    .venv/bin/python -m photobot.main        # then watch it land in Telegram

Seeds today with real submissions, makes --chat the only proofer, and puts the
deadline a few minutes out — so the check and the publish both fire on the real
one-minute tick rather than being faked here.

Refuses to run unless ALLOWED_IDS is set, i.e. against the private test bot.
"""
import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from photobot import config, db, jobs  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", type=int, required=True)
    ap.add_argument(
        "--minutes", type=int, default=3, help="minutes until the deadline"
    )
    ap.add_argument(
        "--photos", type=Path, default=Path.home() / "Downloads" / "2026-07-21"
    )
    ap.add_argument(
        "--reset",
        action="store_true",
        help="wipe today's proofing + collage state first, to run the flow again",
    )
    ap.add_argument("--lang", choices=("en", "ru"), default="en")
    args = ap.parse_args()

    config.validate()
    if not config.ALLOWED_USER_IDS:
        raise SystemExit(
            "ALLOWED_IDS is empty — that's the production bot. Refusing to seed."
        )
    db.init()

    photos = sorted(args.photos.glob("u*.jpg"))
    assert photos, f"no u*.jpg in {args.photos}"

    now = jobs.now_local()
    today = now.date().isoformat()
    deadline = (now + timedelta(minutes=args.minutes)).replace(second=0, microsecond=0)

    if args.reset:
        db._exec("DELETE FROM proof_asks WHERE date=?", (today,))
        db._exec("DELETE FROM collage_messages WHERE date=?", (today,))
        db._exec("DELETE FROM days WHERE date=?", (today,))
        db._exec("DELETE FROM photos WHERE date=?", (today,))
        db._exec("UPDATE users SET last_proofed_on=NULL")
        print(f"reset {today}")

    pid = db.add_prompt(
        "Send a photo of the sky, wherever you are",
        added_by=args.chat,
        text_ru="Пришли фото неба, где бы ты ни был",
    )
    db.create_day(today, pid)
    db.set_setting("project_start_date", "2026-07-12")

    # The tester is a submitter (so they get the published collage) and the only
    # proofer (so the whole batch is reachable on one phone).
    db.upsert_user(args.chat, "Nikita", "kaydanych")
    db.set_user_lang(args.chat, args.lang)
    db.set_proofer(args.chat, True)
    db.upsert_photo(today, args.chat, str(photos[0]))
    for i, p in enumerate(photos[1:]):
        db.upsert_photo(today, 900000 + i, str(p))

    # Nobody needs nagging during a lab run.
    stamp = now.isoformat(timespec="seconds")
    db.set_day_field(today, "reminder_sent_at", stamp)
    db.set_day_field(today, "final_reminder_sent_at", stamp)

    db.set_setting("prompt_time", "09:00")
    db.set_setting("reminder_time", "09:30")
    db.set_setting("deadline_time", deadline.strftime("%H:%M"))
    db.set_setting(
        "preview_time", (deadline + timedelta(minutes=10)).strftime("%H:%M")
    )
    db.set_setting("proof_enabled", "1")
    db.set_setting("proof_batch", "1")
    db.set_setting("proof_round_min", "10")
    db.set_setting("proof_ban_quorum", "2")

    print(f"seeded {today}: {len(photos)} photos, proofer = {args.chat} ({args.lang})")
    print(f"  {deadline:%H:%M}  contact sheet to you, collage + buttons to the proofer")
    print("\nNow run:  .venv/bin/python -m photobot.main")
    print(
        "Expect ~20 'chat not found' log lines on publish — the other "
        "submitters are seeded ids with no real chat."
    )


if __name__ == "__main__":
    main()
