"""Week card — rehearsal against a copy of the real data.

Two modes, both pointed at a DATA_DIR you copied out of production (the DB and
the photos), so the cards are built from real weeks rather than seeded noise:

    # 1. just render: every qualifying week for that window, as JPEGs on disk
    DATA_DIR=~/tmp/prod/data .venv/bin/python scripts/weekcard_lab.py render

    # 2. the whole flow on the test bot: the card arrives with its two buttons,
    #    and tapping "show everyone" delivers the public copy to your own chat
    DATA_DIR=~/tmp/prod/data .venv/bin/python scripts/weekcard_lab.py live --chat 87494556
    #    ...or --role gift for the buttonless card everyone else gets

`live` narrows both audiences to the one chat you pass — the offer goes only to
you, and jobs.share_audience is stubbed so "everyone" is you as well. Nothing
reaches a real participant even though the DB is full of real ids.

Test-only; never imported by the app. Point DATA_DIR at a COPY: the run writes
week_cards rows and card JPEGs into it.
"""
import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load(data_dir: str | None):
    if data_dir:
        os.environ["DATA_DIR"] = os.path.expanduser(data_dir)
    if "DATA_DIR" not in os.environ:
        raise SystemExit("set DATA_DIR (a COPY of the real data folder)")
    from photobot import collage, config, db, jobs  # noqa: E402

    db.init()
    relocate_photos(config, db)
    return collage, config, db, jobs


def relocate_photos(config, db) -> None:
    """The production DB stores container paths (/data/photos/…). Point them at
    this copy so the same rows resolve on the Mac — the export is disposable, so
    rewriting it is cheaper than teaching the app about two filesystems."""
    fixed = 0
    for row in db._exec("SELECT date, tg_id, file_path FROM photos").fetchall():
        if Path(row["file_path"]).exists():
            continue
        local = config.PHOTOS_DIR / row["date"] / Path(row["file_path"]).name
        if local.exists():
            db._exec(
                "UPDATE photos SET file_path=? WHERE date=? AND tg_id=?",
                (str(local), row["date"], row["tg_id"]),
            )
            fixed += 1
    if fixed:
        print(f"relocated {fixed} photo path(s) to {config.PHOTOS_DIR}")


def window(db, jobs, config, week_end: str | None) -> tuple[str, list[str]]:
    week_end = week_end or jobs.week_end_for(jobs.now_local().date())
    dates = db.week_days(week_end, config.WEEK_SPAN_DAYS)
    if not dates:
        raise SystemExit(f"no collage days in the week ending {week_end}")
    print(f"week ending {week_end}: {len(dates)} collage days, {dates[0]} … {dates[-1]}")
    return week_end, dates


def cmd_render(args) -> None:
    collage, config, db, jobs = load(args.data_dir)
    week_end, dates = window(db, jobs, config, args.week_end)
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    _, board, leader = jobs.week_cast(week_end)
    if not board:
        raise SystemExit(f"nobody reached {config.WEEK_MIN_PHOTOS} days that week")
    for r in board:
        uid = r["tg_id"]
        user = db.get_user(uid)
        photos = {p["date"]: Path(p["file_path"]) for p in db.photos_on(uid, dates)}
        if len(photos) < config.WEEK_MIN_PHOTOS:
            print(f"  ! {uid}: only {len(photos)} photos on disk — skipped")
            continue
        for lang in ("ru", "en"):
            out = out_dir / f"{week_end}_u{uid}_{lang}.jpg"
            collage.build_week_card(
                photos,
                out,
                name=user["first_name"] if user else str(uid),
                dates=dates,
                lang=lang,
                streak=r["streak"],
            )
        crown = "👑 " if leader and uid == leader["tg_id"] else "   "
        print(
            f"  {crown}{user['first_name'] if user else uid} — "
            f"{r['days']}/{len(dates)}, streak {r['streak']} -> {out.name}"
        )
    print(f"\ncards in {out_dir}")


def cmd_live(args) -> None:
    collage, config, db, jobs = load(args.data_dir)
    if not config.ALLOWED_USER_IDS:
        raise SystemExit(
            "ALLOWED_IDS is empty — this .env looks like PRODUCTION. Refusing to "
            "run: it would message real users."
        )
    config.validate()
    week_end, _ = window(db, jobs, config, args.week_end)
    me = args.chat

    # Both fan-outs collapse onto the tester: the offer only reaches `me`, and
    # a shared card is "published" to `me` as well, so the public copy is
    # visible without a single real chat being touched.
    config.ADMIN_IDS = {me}
    db.active_user_ids = lambda: [me]
    jobs.share_audience = lambda _tg_id: [me]
    if args.again:
        db.delete_week_cards(week_end)

    # Which of the two messages you want to look at. The real leader is whoever
    # tops the streak board, which usually isn't the tester — so `leader` hands
    # the crown over for the run, and `gift` makes sure it isn't yours.
    real_cast = jobs.week_cast

    def cast(week_end: str):
        dates, board, leader = real_cast(week_end)
        mine = next((r for r in board if r["tg_id"] == me), None)
        if args.role == "leader" and mine:
            leader = mine
        elif args.role == "gift" and leader and leader["tg_id"] == me:
            leader = next((r for r in board if r["tg_id"] != me), None)
        return dates, board, leader

    jobs.week_cast = cast

    from telegram import Update  # noqa: E402
    from photobot import main as app_main  # noqa: E402

    app = app_main.build_app()
    # This is a handler rehearsal, not a schedule one — keep the daily tick from
    # running the day (prompts, deadlines, collages) on top of it.
    for job in app.job_queue.jobs():
        job.schedule_removal()

    async def post_init(application):
        note = await jobs.offer_week_cards(
            SimpleNamespace(bot=application.bot), week_end, only=me
        )
        print(note, flush=True)
        if "0 card(s)" in note:
            print(
                "Nothing was offered — either you didn't have a perfect week in "
                "that window, or it was already offered (re-run with --again).",
                flush=True,
            )

    app.post_init = post_init
    print("Polling — tap a button on the card. Ctrl-C to stop.", flush=True)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", help="copy of the real data folder (or set DATA_DIR)")
    sub = ap.add_subparsers(dest="mode", required=True)

    r = sub.add_parser("render", help="build every qualifying card to disk")
    r.add_argument("week_end", nargs="?", help="YYYY-MM-DD (default: yesterday)")
    r.add_argument("--out", default="/tmp/weekcards")
    r.set_defaults(func=cmd_render)

    live = sub.add_parser("live", help="run the real flow against the test bot")
    live.add_argument("week_end", nargs="?", help="YYYY-MM-DD (default: yesterday)")
    live.add_argument("--chat", type=int, required=True)
    live.add_argument(
        "--role", choices=("leader", "gift"), default="leader",
        help="which message to rehearse: the congratulated streak leader (with "
             "the share buttons) or a plain gift card",
    )
    live.add_argument("--again", action="store_true", help="re-offer an already-offered week")
    live.set_defaults(func=cmd_live)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
