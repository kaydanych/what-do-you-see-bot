"""Collage delivery lab — build the day's collage several ways and send them all
to a Telegram chat so we can compare how they look/zoom in the client.

Usage:
    .venv/bin/python scripts/collage_lab.py --chat <id> [--photos DIR] [--only 1,2]

Photos default to ~/Downloads/2026-07-21 (the 21 real "sky" submissions);
only files named u*.jpg are used (the u<tgid>.jpg submission format), so the
existing collage_*.jpg / moderation.jpg in that folder are ignored.

Variants:
  1  Baseline        — current single collage, sent as a compressed photo.
  2  Hi-res file     — same collage at ~3x native res, sent as a document you
                       can open and pinch-zoom. Target < 30 MB.
  3  Split collages  — photos split into groups of ~7, one collage each, sent as
                       an album so each juxtaposition reads bigger.
  4  Raw album       — the 21 original photos as swipeable albums (Telegram's
                       "carousel" == a media group; max 10 per group).
  5  Hybrid (rec.)   — baseline photo (keeps the rating buttons) immediately
                       followed by the hi-res file as "tap to zoom".
"""
import argparse
import asyncio
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import Bot, InputMediaPhoto  # noqa: E402
from telegram.request import HTTPXRequest  # noqa: E402

from photobot import collage, config  # noqa: E402

# --- the day we're reproducing (matches the reference collage in Downloads) ---
DATE = "2026-07-21"
DAY_NUMBER = 10
PROMPT_EN = "Send a photo of the sky, wherever you are"
SEED = hash(DATE) & 0x7FFFFFFF

TMP = Path(tempfile.mkdtemp(prefix="collage_lab_"))


def load_photos(photos_dir: Path) -> list[Path]:
    paths = sorted(photos_dir.glob("u*.jpg"))
    if not paths:
        raise SystemExit(f"No u*.jpg submissions found in {photos_dir}")
    return paths


def mb(path: Path) -> float:
    return path.stat().st_size / 1_048_576


def chunk(seq: list, size: int) -> list[list]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def build_baseline(paths: list[Path]) -> Path:
    out = TMP / "v1_baseline.jpg"
    collage.build_collage(
        paths, out, prompt=PROMPT_EN, on_date=DATE, day_number=DAY_NUMBER,
        lang="en", seed=SEED,
    )
    return out


def build_hires(paths: list[Path], scale: float = 3.0) -> Path:
    out = TMP / f"v2_hires_x{scale:g}.jpg"
    collage.build_collage(
        paths, out, prompt=PROMPT_EN, on_date=DATE, day_number=DAY_NUMBER,
        lang="en", seed=SEED, scale=scale, max_side=8000, quality=90,
    )
    return out


def build_split(paths: list[Path], per: int = 7) -> list[Path]:
    outs = []
    groups = chunk(paths, per)
    total = len(groups)
    for i, group in enumerate(groups, 1):
        out = TMP / f"v3_split_{i}of{total}.jpg"
        # A slightly larger scale since each has few photos = bigger cells.
        collage.build_collage(
            group, out, prompt=f"{PROMPT_EN}  ·  {i}/{total}", on_date=DATE,
            day_number=DAY_NUMBER, lang="en", seed=SEED + i, scale=1.6,
        )
        outs.append(out)
    return outs


async def send_header(bot: Bot, chat: int, text: str) -> None:
    await bot.send_message(chat, text)


async def run(chat: int, photos_dir: Path, only: set[int]) -> None:
    paths = load_photos(photos_dir)
    n = len(paths)
    req = HTTPXRequest(connect_timeout=30, read_timeout=120, write_timeout=120)
    bot = Bot(config.BOT_TOKEN, request=req)

    async with bot:
        await send_header(
            bot, chat,
            f"🧪 Collage delivery lab — {n} photos, prompt: «{PROMPT_EN}»\n"
            f"Comparing ways to show a busy day. Variants: {sorted(only)}",
        )

        if 1 in only:
            p = build_baseline(paths)
            await send_header(
                bot, chat,
                f"1️⃣ BASELINE — single collage as a compressed photo "
                f"({mb(p):.2f} MB native). This is what ships today.",
            )
            with open(p, "rb") as f:
                await bot.send_photo(chat, f, caption="Baseline (compressed)")

        if 2 in only:
            p = build_hires(paths, scale=3.0)
            await send_header(
                bot, chat,
                f"2️⃣ HI-RES FILE — same collage at 3× native res, sent as a "
                f"document ({mb(p):.1f} MB). Open it → pinch to zoom into any "
                f"single photo. Well under the 30 MB target.",
            )
            with open(p, "rb") as f:
                await bot.send_document(
                    chat, f, filename=f"collage_{DATE}_hires.jpg",
                    caption=f"Hi-res file · {mb(p):.1f} MB · zoomable",
                )

        if 3 in only:
            outs = build_split(paths, per=7)
            await send_header(
                bot, chat,
                f"3️⃣ SPLIT — {len(outs)} collages of ~7 photos, sent as one "
                f"album. Fewer photos per card = bigger tiles = clearer "
                f"juxtaposition. (Albums can't carry the 🔥/👍 rating buttons.)",
            )
            media = [InputMediaPhoto(Path(o).read_bytes()) for o in outs]
            await bot.send_media_group(chat, media)

        if 4 in only:
            groups = chunk(paths, 7)
            await send_header(
                bot, chat,
                f"4️⃣ RAW ALBUM — the {n} original photos as {len(groups)} "
                f"swipeable albums (Telegram 'carousel' = a media group, max 10 "
                f"each). Tap any → full-screen swipe. No collage, no captions per "
                f"photo, no rating buttons.",
            )
            for group in groups:
                media = [InputMediaPhoto(p.read_bytes()) for p in group]
                await bot.send_media_group(chat, media)

        if 5 in only:
            base = build_baseline(paths)
            hi = build_hires(paths, scale=3.0)
            await send_header(
                bot, chat,
                "5️⃣ HYBRID (recommended) — ship the collage as the hero image "
                "(inline preview, keeps the 🔥/👍 buttons) AND attach the hi-res "
                "file right after for anyone who wants to zoom. Best of both.",
            )
            with open(base, "rb") as f:
                await bot.send_photo(chat, f, caption="The day's collage")
            with open(hi, "rb") as f:
                await bot.send_document(
                    chat, f, filename=f"collage_{DATE}_full.jpg",
                    caption="📎 Full resolution — tap to zoom in",
                )

        await send_header(bot, chat, "✅ Done. Which one feels best?")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", type=int, required=True, help="Telegram chat/user id")
    ap.add_argument(
        "--photos", type=Path,
        default=Path.home() / "Downloads" / "2026-07-21",
    )
    ap.add_argument(
        "--only", type=str, default="1,2,3,4,5",
        help="comma list of variants to send, e.g. 2,5",
    )
    args = ap.parse_args()
    only = {int(x) for x in args.only.split(",") if x.strip()}
    asyncio.run(run(args.chat, args.photos, only))


if __name__ == "__main__":
    main()
