import asyncio
from datetime import datetime

import pytest
from PIL import Image

from photobot import collage, config, db, jobs

DAYS = [f"2026-07-{d:02d}" for d in range(20, 28)]  # Mon 20th … Mon 27th


def seed_week(sent_through: str = "2026-07-26") -> None:
    """A collage on every day of the window, so participation is the only
    variable the tests are moving."""
    for i, d in enumerate(DAYS):
        pid = db.add_prompt(f"prompt {i}", added_by=1)
        db.create_day(d, pid)
        if d <= sent_through:
            db.set_day_field(d, "collage_sent_at", f"{d}T21:00:00")


def submit(tg_id: int, dates: list[str], tmp_path) -> None:
    db.upsert_user(tg_id, f"User{tg_id}", None)
    for d in dates:
        p = tmp_path / f"{d}_u{tg_id}.jpg"
        Image.new("RGB", (900, 600), (tg_id % 255, 40, 90)).save(p, "JPEG")
        db.upsert_photo(d, tg_id, str(p))


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.init(tmp_path / "test.db")
    yield


def test_window_counts_collage_days_not_calendar_days():
    seed_week()
    # window ending Sunday the 26th: Mon 20th … Sun 26th, all of which ran
    assert db.week_days("2026-07-26") == DAYS[:7]
    # a day whose collage never went out drops out of the window entirely, so a
    # dead day can't cost anyone their week
    db.set_day_field("2026-07-22", "collage_sent_at", None)
    assert "2026-07-22" not in db.week_days("2026-07-26")


def test_board_is_ordered_by_streak_then_the_fuller_week(tmp_path):
    seed_week()
    week = DAYS[:7]
    submit(1, week, tmp_path)          # a full week, but the run starts here
    submit(2, week[2:], tmp_path)      # 5 days, run of 5
    submit(3, week[:4], tmp_path)      # 4 days, and the run ended on Thursday
    board = db.week_board("2026-07-26")
    assert [(r["tg_id"], r["days"], r["streak"]) for r in board] == [
        (1, 7, 7),
        (2, 5, 5),
        (3, 4, 0),
    ]


def test_the_crown_goes_to_one_person_and_the_rest_still_get_a_card(tmp_path):
    seed_week()
    week = DAYS[:7]
    submit(1, week, tmp_path)          # 7/7, run of 7
    submit(2, week[1:], tmp_path)      # 6/7, run of 6
    submit(3, week[:5], tmp_path)      # 5/7, run ended — still gets a card
    submit(4, week[:3], tmp_path)      # 3/7 — under the floor, gets nothing
    dates, board, leader = jobs.week_cast("2026-07-26")
    assert len(dates) == 7
    assert [r["tg_id"] for r in board] == [1, 2, 3]
    assert leader["tg_id"] == 1


def test_a_tied_crown_rotates_instead_of_settling_on_one_name(tmp_path):
    """Two people who never miss are level forever — a fixed tie-break would
    crown the same one of them every week and never name the other."""
    seed_week()
    week = DAYS[:7]
    submit(1, week, tmp_path)
    submit(2, week, tmp_path)
    board = [r for r in db.week_board("2026-07-26") if r["days"] >= 5]
    assert len(jobs.tied_leaders(board)) == 2

    # nobody has been crowned yet: the deterministic order decides
    first = jobs.pick_leader("2026-07-26", board)["tg_id"]
    db.add_week_card("2026-07-26", first, 7, 7)
    db.set_week_card_status("2026-07-26", first, "shared")
    # ...and next week it's the other one's turn
    second = jobs.pick_leader("2026-07-27", board)["tg_id"]
    assert second != first
    db.add_week_card("2026-07-27", second, 7, 8)
    # ...then back again, oldest crown first
    assert jobs.pick_leader("2026-07-28", board)["tg_id"] == first

    # a gift card is not a crown and doesn't cost anyone their turn
    db.add_week_card("2026-07-29", first, 7, 9, status="gift")
    assert jobs.pick_leader("2026-07-30", board)["tg_id"] == first


def test_a_run_of_one_is_not_a_streak_worth_crowning(tmp_path):
    seed_week()
    week = DAYS[:7]
    # everyone stopped before the last day, so nobody has a live run
    submit(1, week[:5], tmp_path)
    submit(2, week[:6], tmp_path)
    _, board, leader = jobs.week_cast("2026-07-26")
    assert [r["tg_id"] for r in board] == [2, 1]  # cards for both...
    assert leader is None                          # ...but nobody is congratulated


def test_excluded_photo_costs_the_day(tmp_path):
    seed_week()
    submit(1, DAYS[:7], tmp_path)
    db.set_photo_excluded("2026-07-23", 1, True)
    row = db.week_board("2026-07-26")[0]
    assert row["days"] == 6 and row["streak"] == 3  # the run restarts after the gap


def test_streak_is_measured_at_the_end_of_the_window(tmp_path):
    seed_week(sent_through="2026-07-27")
    submit(1, DAYS, tmp_path)
    # 8 days of history, but the window ending Sunday only knows about 7 of them
    assert db.week_board("2026-07-26")[0]["streak"] == 7
    assert db.week_board("2026-07-27")[0]["streak"] == 8


def test_only_one_decision_per_card():
    db.add_week_card("2026-07-26", 1, 7, 9)
    db.add_week_card("2026-07-26", 1, 7, 9)  # a second offer is a no-op
    assert len(db.week_cards_for("2026-07-26")) == 1
    assert db.set_week_card_status("2026-07-26", 1, "shared") is True
    # the double tap that would otherwise publish the same week twice
    assert db.set_week_card_status("2026-07-26", 1, "kept") is False
    assert db.get_week_card("2026-07-26", 1)["status"] == "shared"
    # ...and a tap on a card that was never offered decides nothing
    assert db.set_week_card_status("2026-07-26", 999, "shared") is False


def test_a_gift_card_has_nothing_to_decide():
    """The buttonless cards carry no share path even if a callback is forged."""
    db.add_week_card("2026-07-26", 2, 6, 6, status="gift")
    assert db.set_week_card_status("2026-07-26", 2, "shared") is False
    assert db.get_week_card("2026-07-26", 2)["status"] == "gift"


@pytest.mark.parametrize("filled", [7, 5])
def test_card_renders_full_and_partial_weeks(tmp_path, filled):
    seed_week()
    submit(1, DAYS[:filled], tmp_path)
    dates = db.week_days("2026-07-26")
    photos = {p["date"]: p["file_path"] for p in db.photos_on(1, dates)}
    assert len(photos) == filled
    out = collage.build_week_card(
        photos, tmp_path / "card.jpg", name="Sasha", dates=dates, lang="ru", streak=19
    )
    with Image.open(out) as im:
        assert im.width == config.COLLAGE_WIDTH
        assert im.height > config.COLLAGE_WIDTH / 2


def test_a_manual_run_cannot_trip_the_schedule(tmp_path):
    """The bug this guards: /weekcard me for a *different* window moved the
    scheduler's bookmark, the `!=` test read that as "this week isn't done", and
    the tick fired a whole fan-out on the spot for a week already in the past."""
    seed_week()
    submit(1, DAYS[:7], tmp_path)
    db.set_setting("week_card_dow", "6")
    db.set_setting("week_card_time", "17:00")
    fired = []

    async def boom(context, week_end, **kw):
        fired.append(week_end)
        return "should not happen"

    saturday = datetime.fromisoformat("2026-08-01T12:30")
    sunday = datetime.fromisoformat("2026-08-02T17:00")
    tick = lambda when: asyncio.run(jobs.maybe_offer_week_cards(None, when))  # noqa: E731
    monkey = jobs.offer_week_cards
    try:
        jobs.offer_week_cards = boom
        # a fresh install arms itself and sends nothing
        db.set_setting("week_card_last", "")
        tick(saturday)
        assert fired == [] and db.get_setting("week_card_last") == "2026-07-25"

        # now the admin runs /weekcard me for a newer window by hand
        db.set_setting("week_card_last", "2026-07-31")
        tick(saturday)
        assert fired == []  # ...and the tick a minute later stays quiet

        # the real Sunday still fires, once
        tick(sunday)
        assert fired == ["2026-08-01"]
        tick(sunday)
        assert fired == ["2026-08-01"]
    finally:
        jobs.offer_week_cards = monkey


def test_weekly_run_is_late_rather_than_never():
    db.set_setting("week_card_dow", "6")      # Sunday
    db.set_setting("week_card_time", "21:45")
    at = lambda s: jobs.last_week_run(datetime.fromisoformat(s))  # noqa: E731

    # before Sunday's moment the current week hasn't happened yet
    assert at("2026-07-26T21:44").isoformat() == "2026-07-19"
    assert at("2026-07-26T21:45").isoformat() == "2026-07-26"
    # a bot that was down all Sunday night still owes that run on Tuesday
    assert at("2026-07-28T09:00").isoformat() == "2026-07-26"
    # the window it covers ends the day before, so Sunday's own knocks are safe
    assert jobs.week_end_for(at("2026-07-26T21:45")) == "2026-07-25"
