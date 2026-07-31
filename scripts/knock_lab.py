"""Knock lab — how do you point at one photo inside the day's collage?

The feature under test: readers pick a photo from the collage and "knock" on it;
the photo with enough knocks gets its author asked for the story of the day.
The open question is the picking UI, since numbers drawn on the collage are ugly.

Usage:
    .venv/bin/python scripts/knock_lab.py --chat <id> [--lang en|ru]
    .venv/bin/python scripts/knock_lab.py --chat <id> --only 1,2   # the grids
    .venv/bin/python scripts/knock_lab.py --chat <id> --stress 10x10

Sends the variants, then long-polls so the buttons actually work. Ctrl-C to stop.

  3  Carousel (default) — the collage carries a single English "Knock, knock,
                          who's there..." button; tapping it opens one card you
                          flip through with ‹ ›, explained in the reader's own
                          language.
  1  Shadow grid        — one "·" button per photo, keyboard rows == mosaic rows.
  2  Proportional grid  — same, but a wide tile gets more buttons than a narrow
                          one, so the strip follows the photo edges. (Telegram
                          makes buttons in a row equal width; this is the only
                          lever we have.) Both grids were rejected in testing.

--stress AxB simulates A people each flipping B photos at once and reports CPU,
RAM and latency — the answer to "can the NAS take ten people scrolling at once?"

Test-only, not part of the deployed app.
"""
import argparse
import asyncio
import math
import os
import random
import resource
import statistics
import sys
import tempfile
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram.error import RetryAfter  # noqa: E402
from telegram import (  # noqa: E402
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.ext import (  # noqa: E402
    Application,
    CallbackQueryHandler,
    ContextTypes,
)

from photobot import collage, config  # noqa: E402

# --- the day we're reproducing (same as collage_lab.py) ---
DATE = "2026-07-21"
DAY_NUMBER = 10
PROMPT_EN = "Send a photo of the sky, wherever you are"
# NB: production uses hash(date), which Python randomises per process — fine
# today (one build per process) but it means a rebuilt collage rearranges
# itself. Here we want the same mosaic on every run, so: crc32.
SEED = zlib.crc32(DATE.encode()) & 0x7FFFFFFF

TMP = Path(tempfile.mkdtemp(prefix="knock_lab_"))
MAX_BTN_PER_ROW = 8

SOURCE: list[Path] = []      # photos as submitted (what build_collage is fed)
PHOTOS: list[Path] = []      # the same photos in mosaic order (what a tap means)
FILE_IDS: dict[int, str] = {}  # mosaic index -> Telegram file_id, once uploaded
TIMINGS: list[float] = []      # seconds per carousel step
FLOOD: list[float] = []        # seconds lost to Telegram flood control
STATE: dict[int, dict] = {}    # chat_id -> {"msg": id, "idx": int}


# --- layout ------------------------------------------------------------------
def mosaic_layout(
    paths: list[Path], seed: int
) -> tuple[list[Path], list[list[int]], list[list[int]]]:
    """Reproduce build_collage's arrangement without drawing it.

    Returns (paths in mosaic order, rows as lists of photo indices, per-tile
    widths in each row). Mirrors build_collage step for step — the RNG is
    consumed in the same order, and random.shuffle's permutation depends only on
    the list length, so shuffling an index list gives the identical arrangement.

    Feed this the *submitted* order, the same list build_collage gets. Handing it
    an already-arranged list re-shuffles and the mapping silently drifts.
    """
    rng = random.Random(seed)
    paths = [Path(p) for p in paths if Path(p).exists()]
    if not paths:
        raise SystemExit("no photos")
    if len(paths) > config.COLLAGE_MAX_CELLS:
        paths = rng.sample(paths, config.COLLAGE_MAX_CELLS)
    n = len(paths)

    images = [collage._load_rgb(p) for p in paths]
    order = list(range(n))
    rng.shuffle(order)
    images = [images[i] for i in order]
    ordered = [paths[i] for i in order]

    row_h = collage._base_row_h(n)
    pad, gap = config.COLLAGE_PAD, config.COLLAGE_GAP
    W = max(
        config.COLLAGE_WIDTH,
        int(math.sqrt(config.COLLAGE_PORTRAIT_K * n) * row_h),
    )
    rows = collage._justify(images, W - 2 * pad, row_h, gap)

    # _justify keeps input order, so walk the flat index across rows
    out: list[list[int]] = []
    widths: list[list[int]] = []
    k = 0
    for row in rows:
        out.append(list(range(k, k + len(row))))
        widths.append([w for _, w, _ in row])
        k += len(row)
    return ordered, out, widths


def slot_assignment(widths: list[int], gap: int = config.COLLAGE_GAP) -> list[int]:
    """Map a row of equal-width buttons onto tiles of unequal width.

    Telegram gives every button in a row the same width, so the only way to make
    the strip follow the photo edges is to give a wide tile more buttons. Lay
    `B` equal slots over the row, assign each to the tile its centre falls in,
    and keep the B whose button seams land closest to the real tile seams —
    which correctly leaves an all-equal row at one button per photo instead of
    padding it into a lopsided eight.
    """
    n = len(widths)
    if n >= MAX_BTN_PER_ROW:
        return list(range(n))
    spans, x = [], 0
    for w in widths:
        spans.append((x, x + w))
        x += w + gap
    row_w = x - gap

    def tile_at(c: float) -> int:
        return min(
            range(n),
            key=lambda i: 0 if spans[i][0] <= c <= spans[i][1]
            else min(abs(c - spans[i][0]), abs(c - spans[i][1])),
        )

    seams = [spans[i][1] + gap / 2 for i in range(n - 1)]
    best = (float("inf"), list(range(n)))
    for budget in range(n, MAX_BTN_PER_ROW + 1):
        assign = [tile_at((b + 0.5) / budget * row_w) for b in range(budget)]
        if len(set(assign)) != n:  # a tile too narrow to win any slot
            continue
        cuts = [k / budget * row_w for k in range(1, budget)
                if assign[k] != assign[k - 1]]
        err = sum(abs(a - b) for a, b in zip(seams, cuts))
        if err < best[0]:
            best = (err, assign)
    return best[1]


# --- keyboards ---------------------------------------------------------------
def shadow_keyboard(rows: list[list[int]], dot: str = "·") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(dot, callback_data=f"kl:pick:{i}") for i in row]
            for row in rows
        ]
    )


def proportional_keyboard(
    rows: list[list[int]], widths: list[list[int]], dot: str = "·"
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(dot, callback_data=f"kl:pick:{row[t]}")
                for t in slot_assignment(ws)
            ]
            for row, ws in zip(rows, widths)
        ]
    )


# --- copy --------------------------------------------------------------------
# The button under the collage is English for everyone — it's a nursery rhyme,
# not an instruction, and it reads as the surprise it is.
OPEN_LABEL = "🚪 Knock, knock, who's there..."

# Everything the reader is told about the new game, in the two sentences they
# get before their first flip. Nothing here names an author.
EXPLAIN = {
    "en": (
        "There's someone behind every photo. You get one knock — spend it on "
        "the one you're most curious about, and the author of the photo with "
        "the most knocks steps out and tells its story."
    ),
    "ru": (
        "За каждым снимком кто-то стоит. У тебя один стук — постучись в самый "
        "интересный, и автор снимка, набравшего больше всего стуков, "
        "(возможно) откроется и расскажет свою историю."
    ),
}
KNOCKED = {
    "en": "🚪 Knocked. If this door gets the most knocks, we'll hear its story.",
    "ru": "🚪 Ты постучал. Если в эту дверь постучат больше всего, услышим историю за ней.",
}
TOAST = {"en": "🚪 Knocked", "ru": "🚪 Ты постучал"}


def open_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(OPEN_LABEL, callback_data="kl:pick:0")]]
    )


def card_keyboard(idx: int, knocked: bool = False) -> InlineKeyboardMarkup:
    if knocked:
        return InlineKeyboardMarkup([])
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("‹", callback_data=f"kl:nav:{idx}:-1"),
                InlineKeyboardButton(
                    f"🚪 Knock  ·  {idx + 1}/{len(PHOTOS)}",
                    callback_data=f"kl:knock:{idx}",
                ),
                InlineKeyboardButton("›", callback_data=f"kl:nav:{idx}:1"),
            ]
        ]
    )


def where(idx: int, rows: list[list[int]]) -> str:
    for r, row in enumerate(rows, 1):
        if idx in row:
            return f"row {r}, photo {row.index(idx) + 1} of {len(row)}"
    return "?"


# --- the card ----------------------------------------------------------------
async def media_for(bot, idx: int, caption: str) -> InputMediaPhoto:
    """A file_id if Telegram has seen this photo before, bytes otherwise.

    This is the whole performance story: the first view of a photo uploads it,
    every later view is a ~200-byte API call referencing the id. In production
    we get the id for free — it arrives on the submitted message.
    """
    if idx in FILE_IDS:
        return InputMediaPhoto(FILE_IDS[idx], caption=caption)
    return InputMediaPhoto(PHOTOS[idx].read_bytes(), caption=caption)


def remember(idx: int, message) -> None:
    if idx not in FILE_IDS and message and message.photo:
        FILE_IDS[idx] = message.photo[-1].file_id


async def show_card(context, chat: int, idx: int, rows) -> None:
    """Open (or update in place) the single-photo card.

    The caption must never carry the filename — it's u<telegram_id>.jpg, so it
    would hand out the very identity the whole game is built on hiding. Position
    within the mosaic stays out too: it's a step towards naming who submitted
    when. Debug detail goes to the console, not the chat.
    """
    t0 = time.perf_counter()
    lang = context.bot_data.get("lang", "en")
    caption = EXPLAIN[lang]
    st = STATE.get(chat)
    if st:
        try:
            msg = await context.bot.edit_message_media(
                chat_id=chat,
                message_id=st["msg"],
                media=await media_for(context.bot, idx, caption),
                reply_markup=card_keyboard(idx),
            )
            remember(idx, msg)
            st["idx"] = idx
            TIMINGS.append(time.perf_counter() - t0)
            return
        except Exception as e:  # message gone / too old — send a fresh one
            print(f"  edit failed ({e}), sending fresh")
    msg = await context.bot.send_photo(
        chat,
        FILE_IDS.get(idx) or PHOTOS[idx].read_bytes(),
        caption=caption,
        reply_markup=card_keyboard(idx),
    )
    remember(idx, msg)
    STATE[chat] = {"msg": msg.message_id, "idx": idx}
    TIMINGS.append(time.perf_counter() - t0)


async def on_tap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    chat = q.message.chat_id
    _, kind, *rest = q.data.split(":")
    rows = context.bot_data["rows"]

    lang = context.bot_data.get("lang", "en")

    if kind == "pick":
        idx = int(rest[0])
        await q.answer()
        await show_card(context, chat, idx, rows)
    elif kind == "nav":
        idx = (int(rest[0]) + int(rest[1])) % len(PHOTOS)
        await q.answer()
        await show_card(context, chat, idx, rows)
    elif kind == "knock":
        idx = int(rest[0])
        await q.answer(TOAST[lang])
        await q.edit_message_caption(
            caption=KNOCKED[lang],
            reply_markup=card_keyboard(idx, knocked=True),
        )
        print(f"  knocked on {PHOTOS[idx].name} ({where(idx, rows)})")
        STATE.pop(chat, None)
    if TIMINGS:
        print(f"  step {len(TIMINGS)}: {TIMINGS[-1] * 1000:.0f} ms "
              f"({len(FILE_IDS)}/{len(PHOTOS)} cached)")


# --- stress ------------------------------------------------------------------
def rss_mb() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / (1024 ** 2) if sys.platform == "darwin" else raw / 1024


async def with_retry(fn, *a, **kw):
    """Telegram flood control, not the NAS, is what actually throttles this —
    back off and retry rather than dying mid-measurement."""
    for _ in range(6):
        try:
            return await fn(*a, **kw)
        except RetryAfter as e:
            print(f"  flood control: sleeping {e.retry_after}s")
            FLOOD.append(e.retry_after)
            await asyncio.sleep(e.retry_after + 0.5)
    raise RuntimeError("gave up after repeated flood control")


async def warm_cache(bot, chat: int) -> float:
    """Upload every photo once and keep its file_id (send, grab id, delete).
    In production this is free — the id comes in with the submission."""
    t0 = time.perf_counter()
    for i in range(len(PHOTOS)):
        msg = await with_retry(bot.send_photo, chat, PHOTOS[i].read_bytes(),
                               disable_notification=True)
        remember(i, msg)
        await with_retry(bot.delete_message, chat, msg.message_id)
        await asyncio.sleep(0.4)  # stay under the ~20/min media-send ceiling
    return time.perf_counter() - t0


async def stress(app: Application, chat: int, users: int, flips: int) -> None:
    """`users` carousels flipping `flips` times each, all at once."""
    bot = app.bot
    await bot.send_message(
        chat, f"⏱ Stress: warming the file_id cache ({len(PHOTOS)} uploads)…"
    )
    warm = await warm_cache(bot, chat)
    print(f"warm-up: {warm:.1f}s for {len(PHOTOS)} uploads "
          f"({warm / len(PHOTOS) * 1000:.0f} ms each)", flush=True)

    cards = []
    for u in range(users):
        msg = await with_retry(
            bot.send_photo, chat, FILE_IDS[0],
            caption=f"stress card {u + 1}", disable_notification=True,
        )
        cards.append(msg.message_id)

    lat: list[float] = []
    cpu0, wall0 = time.process_time(), time.perf_counter()

    async def flipper(u: int, mid: int) -> None:
        for f in range(flips):
            idx = (u * 3 + f) % len(PHOTOS)
            t0 = time.perf_counter()
            try:
                await with_retry(
                    bot.edit_message_media, chat_id=chat, message_id=mid,
                    media=InputMediaPhoto(FILE_IDS[idx], caption=f"u{u} · {idx}"),
                )
                lat.append(time.perf_counter() - t0)
            except Exception as e:
                print(f"  u{u} f{f}: {e}")

    await asyncio.gather(*(flipper(u, m) for u, m in enumerate(cards)))
    cpu, wall = time.process_time() - cpu0, time.perf_counter() - wall0
    n = len(lat) or 1
    report = (
        f"⏱ {users} users × {flips} flips = {len(lat)} edits in {wall:.1f}s\n"
        f"CPU used: {cpu:.2f}s total = {cpu / n * 1000:.1f} ms/flip "
        f"({cpu / wall * 100:.0f}% of one core)\n"
        f"peak RSS: {rss_mb():.0f} MB\n"
        f"latency: median {statistics.median(lat) * 1000:.0f} ms, "
        f"p95 {sorted(lat)[int(n * 0.95) - 1] * 1000:.0f} ms "
        f"(that's Telegram's round trip, not the NAS)\n"
        f"warm-up (once/day, free in prod): {warm:.1f}s\n"
        f"flood-control waits: {len(FLOOD)} ({sum(FLOOD):.0f}s total)"
    )
    print(report, flush=True)
    (TMP / "stress_report.txt").write_text(report)
    await bot.send_message(chat, report)
    for mid in cards:
        await bot.delete_message(chat, mid)


# --- run ---------------------------------------------------------------------
async def send_variants(app: Application, chat: int, only: set[int]) -> None:
    rows, widths = app.bot_data["rows"], app.bot_data["widths"]
    bot = app.bot

    shape = " / ".join(str(len(r)) for r in rows)
    if only != {3}:
        await bot.send_message(
            chat,
            f"🚪 Knock lab — {len(PHOTOS)} photos, mosaic rows: {shape}\n"
            f"Variants: {sorted(only)}",
        )

    card = TMP / "collage.jpg"
    collage.build_collage(
        SOURCE, card, prompt=PROMPT_EN, on_date=DATE, day_number=DAY_NUMBER,
        lang="en", seed=SEED,
    )

    if 1 in only:
        await bot.send_message(
            chat,
            f"1️⃣ SHADOW GRID — one button per photo, keyboard rows == mosaic "
            f"rows ({shape}). Aim at a photo, tap the button under it.",
        )
        await bot.send_photo(
            chat, card.read_bytes(), caption="The day's collage",
            reply_markup=shadow_keyboard(rows),
        )

    if 2 in only:
        await bot.send_message(
            chat,
            "2️⃣ PROPORTIONAL GRID — a wide tile gets more buttons than a "
            "narrow one, so the strip follows the photo edges.",
        )
        await bot.send_photo(
            chat, card.read_bytes(), caption="The day's collage",
            reply_markup=proportional_keyboard(rows, widths),
        )

    if 3 in only:
        await bot.send_photo(
            chat, card.read_bytes(), caption="The day's collage",
            reply_markup=open_keyboard(),
        )
        other = "ru" if app.bot_data.get("lang", "en") == "en" else "en"
        await bot.send_message(
            chat,
            f"— copy check, the other language ({other.upper()}) —\n\n"
            f"{EXPLAIN[other]}\n\n{KNOCKED[other]}\n\n"
            f"(run with --lang {other} to see that side for real)",
        )


async def post_init(app: Application) -> None:
    chat = app.bot_data["chat"]
    if app.bot_data.get("stress"):
        users, flips = app.bot_data["stress"]
        await stress(app, chat, users, flips)
        sys.stdout.flush()
        os._exit(0)
    await send_variants(app, chat, app.bot_data["only"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", type=int, required=True)
    ap.add_argument(
        "--photos", type=Path, default=Path.home() / "Downloads" / "2026-07-21"
    )
    ap.add_argument("--only", type=str, default="3")
    ap.add_argument("--lang", choices=("en", "ru"), default="en")
    ap.add_argument("--stress", type=str, help="AxB — A users, B flips each")
    args = ap.parse_args()

    if not config.ALLOWED_USER_IDS:
        raise SystemExit(
            "ALLOWED_IDS is empty — this .env looks like PRODUCTION. Refusing "
            "to run: it would collide with the NAS instance."
        )

    global SOURCE, PHOTOS
    SOURCE = sorted(args.photos.glob("u*.jpg"))
    if not SOURCE:
        raise SystemExit(f"No u*.jpg submissions in {args.photos}")
    PHOTOS, rows, widths = mosaic_layout(SOURCE, SEED)
    print(f"{len(PHOTOS)} photos, rows: {[len(r) for r in rows]}", flush=True)

    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()
    app.bot_data.update(
        rows=rows, widths=widths, chat=args.chat, lang=args.lang,
        only={int(x) for x in args.only.split(",") if x.strip()},
        stress=(
            tuple(int(x) for x in args.stress.lower().split("x"))
            if args.stress else None
        ),
    )
    app.add_handler(CallbackQueryHandler(on_tap, pattern=r"^kl:"))
    print("Polling — tap the buttons in Telegram. Ctrl-C to stop.", flush=True)
    app.run_polling(allowed_updates=["callback_query"])


if __name__ == "__main__":
    main()
