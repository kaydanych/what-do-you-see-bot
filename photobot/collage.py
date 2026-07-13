import math
import random
from datetime import date as date_cls
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import config

_EN_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_RU_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    """Bundled DejaVu (Cyrillic-capable) so headers render inside the
    font-less Docker slim image. Falls back to Pillow's default."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(str(config.FONTS_DIR / name), size)
    except OSError:
        return ImageFont.load_default()


def _load_cell(path: Path, cell: int) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    return ImageOps.fit(img, (cell, cell))


def _load_rgb(path: Path) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def _rounded(tile: Image.Image, radius: int) -> Image.Image:
    """Return an RGBA copy of tile with rounded corners (alpha mask)."""
    if radius <= 0:
        return tile
    mask = Image.new("L", tile.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, tile.size[0] - 1, tile.size[1] - 1], radius=radius, fill=255
    )
    tile = tile.convert("RGBA")
    tile.putalpha(mask)
    return tile


def _aspect(img: Image.Image) -> float:
    ar = img.width / img.height
    return max(config.COLLAGE_ASPECT_MIN, min(config.COLLAGE_ASPECT_MAX, ar))


def _justify(images: list[Image.Image], width: int, row_h: int, gap: int):
    """Group images into rows scaled to a common height, then stretch each
    row to exactly `width`. Aspect ratios are preserved (no square crop);
    the last row keeps natural height and centres if it is too sparse to
    justify. Returns list of rows, each a list of (image, w, h)."""
    rows: list[list[tuple[Image.Image, int]]] = []
    cur: list[tuple[Image.Image, int]] = []
    cur_w = 0
    for im in images:
        w = max(1, int(row_h * _aspect(im)))
        if cur and cur_w + w + gap * len(cur) > width:
            rows.append(cur)
            cur, cur_w = [], 0
        cur.append((im, w))
        cur_w += w
    if cur:
        rows.append(cur)

    out: list[list[tuple[Image.Image, int, int]]] = []
    for i, row in enumerate(rows):
        total = sum(w for _, w in row)
        gaps = gap * (len(row) - 1)
        last = i == len(rows) - 1
        if last and total + gaps < width * 0.62:
            scale = 1.0  # sparse final row: don't blow tiles up to full width
        else:
            scale = (width - gaps) / total
        h = max(1, int(row_h * scale))
        out.append([(im, max(1, int(w * scale)), h) for im, w in row])
    return out


def _grid(n: int) -> tuple[int, int]:
    """Smallest gap-free-ish grid with a roughly 4:3 shape.

    Considers the two column counts bracketing the 4:3 ideal and picks the
    one leaving the fewest empty cells (so 4 photos -> 2x2, not 3x2, and a
    lone photo fills the frame instead of being duplicated 4x), breaking
    ties toward the 4:3 aspect.
    """
    ideal = math.sqrt(n * 4 / 3)
    candidates = {max(1, math.floor(ideal)), math.ceil(ideal)}
    best = None
    for cols in candidates:
        rows = math.ceil(n / cols)
        empty = cols * rows - n
        aspect_penalty = abs((cols / rows) - 4 / 3)
        score = (empty, aspect_penalty)
        if best is None or score < best[0]:
            best = (score, (cols, rows))
    return best[1]


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    """Greedy word-wrap `text` to fit `max_w` pixels."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fmt_date(on_date, lang: str) -> str:
    """'12 July 2026' / '12 июля 2026' from a date or 'YYYY-MM-DD' string."""
    if isinstance(on_date, str):
        on_date = date_cls.fromisoformat(on_date)
    months = _RU_MONTHS if lang == "ru" else _EN_MONTHS
    return f"{on_date.day} {months[on_date.month - 1]} {on_date.year}"


def _participants(n: int, lang: str) -> str:
    """Localised participant count for the footer."""
    if lang == "ru":
        m10, m100 = n % 10, n % 100
        if m10 == 1 and m100 != 11:
            word = "участник"
        elif m10 in (2, 3, 4) and m100 not in (12, 13, 14):
            word = "участника"
        else:
            word = "участников"
        return f"{n} {word}"
    return "1 participant" if n == 1 else f"{n} participants"


def _base_row_h(n: int) -> int:
    """Taller rows when there are few photos, so small days still feel full."""
    if n <= 3:
        return 460
    if n <= 8:
        return 360
    return 300


def build_collage(
    photo_paths: list[Path],
    out_path: Path,
    *,
    prompt: str | None = None,
    on_date=None,
    lang: str = "en",
    seed: int | None = None,
) -> Path:
    """Assemble the day's photos into a justified-mosaic "card": each photo
    keeps its own aspect ratio (no square-cropping, no duplicate padding),
    rounded tiles on a dark mat, with a localised (`lang`) date + prompt header
    and a footer participant count. Extreme aspect ratios are mildly clamped.

    `seed` fixes the photo arrangement so that per-language renders of the same
    day share an identical mosaic and differ only in the header text."""
    rng = random.Random(seed)
    paths = [Path(p) for p in photo_paths if Path(p).exists()]
    if not paths:
        raise ValueError("no photos to build a collage from")

    if len(paths) > config.COLLAGE_MAX_CELLS:
        paths = rng.sample(paths, config.COLLAGE_MAX_CELLS)
    n = len(paths)

    images = [_load_rgb(p) for p in paths]
    rng.shuffle(images)

    pad = config.COLLAGE_PAD
    gap = config.COLLAGE_GAP
    radius = config.COLLAGE_RADIUS
    row_h = _base_row_h(n)
    # Aim for a phone-portrait card (~3:4). The width grows with sqrt(n) so the
    # total aspect stays roughly constant as photos pile up, rather than turning
    # into a tall sliver; small days are floored to COLLAGE_WIDTH so a lone photo
    # still reads at a sane width instead of a thin strip.
    W = max(config.COLLAGE_WIDTH, int(math.sqrt(config.COLLAGE_PORTRAIT_K * n) * row_h))
    content_w = W - 2 * pad

    rows = _justify(images, content_w, row_h, gap)

    # --- measure header / footer so we can size the canvas ---
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    f_date = _font(False, 28)
    f_prompt = _font(True, 34)
    f_foot = _font(False, 28)

    header_lines: list[tuple[str, object, str]] = []  # (text, font, colour)
    if on_date is not None:
        header_lines.append((_fmt_date(on_date, lang), f_date, config.COLLAGE_DIM))
    if prompt:
        # Locale-aware quotes: guillemets for Russian, curly for everyone else.
        lq, rq = ("«", "»") if lang == "ru" else ("“", "”")
        quoted = f"{lq}{prompt.strip()}{rq}"
        for line in _wrap(scratch, quoted, f_prompt, content_w):
            header_lines.append((line, f_prompt, config.COLLAGE_FG))

    def line_h(font) -> int:
        asc, desc = font.getmetrics()
        return asc + desc

    header_h = 0
    if header_lines:
        header_h = sum(int(line_h(f) * 1.28) for _, f, _ in header_lines) + 26

    footer_h = int(line_h(f_foot) * 1.3) + 10
    body_h = sum(row[0][2] for row in rows) + gap * (len(rows) - 1)
    total_h = pad + header_h + body_h + footer_h + pad

    canvas = Image.new("RGB", (W, total_h), config.COLLAGE_BG)
    draw = ImageDraw.Draw(canvas)

    # header
    y = pad
    for text, font, colour in header_lines:
        draw.text((pad, y), text, font=font, fill=colour)
        y += int(line_h(font) * 1.28)
    y += 26 if header_lines else 0

    # mosaic
    for row in rows:
        row_w = sum(w for _, w, _ in row) + gap * (len(row) - 1)
        x = pad + (content_w - row_w) // 2  # centres sparse (unstretched) rows
        rh = row[0][2]
        for im, w, h in row:
            tile = _rounded(ImageOps.fit(im, (w, h)), radius)
            canvas.paste(tile, (x, y), tile)
            x += w + gap
        y += rh + gap

    # footer: one number (one photo per person, so photos == participants)
    who = _participants(n, lang)
    draw.text(
        (pad, total_h - pad - line_h(f_foot)),
        f"{who} · @what_do_you_see_bot",
        font=f_foot,
        fill=config.COLLAGE_DIM,
    )

    if max(canvas.size) > config.COLLAGE_MAX_SIDE:
        canvas.thumbnail((config.COLLAGE_MAX_SIDE, config.COLLAGE_MAX_SIDE))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=88)
    return out_path


def build_contact_sheet(photo_paths: list[Path], out_path: Path) -> Path:
    """Moderation view: every submission exactly once, in the given order,
    with a big number on each cell matching /exclude N. No duplicates,
    leftover cells stay gray."""
    paths = [Path(p) for p in photo_paths]
    if not paths:
        raise ValueError("no photos for a contact sheet")

    cols, rows = _grid(len(paths))
    cell = config.COLLAGE_CELL_PX
    gut = config.COLLAGE_GUTTER_PX
    w = cols * cell + (cols + 1) * gut
    h = rows * cell + (rows + 1) * gut
    canvas = Image.new("RGB", (w, h), "#d0d0d0")
    try:
        font = ImageFont.load_default(size=cell // 5)
    except TypeError:  # very old Pillow
        font = ImageFont.load_default()

    for idx, p in enumerate(paths):
        r, c = divmod(idx, cols)
        x = gut + c * (cell + gut)
        y = gut + r * (cell + gut)
        tile = _load_cell(p, cell) if p.exists() else Image.new(
            "RGB", (cell, cell), "black"
        )
        draw = ImageDraw.Draw(tile)
        draw.text(
            (cell // 20, cell // 20),
            str(idx + 1),
            fill="white",
            font=font,
            stroke_width=max(2, cell // 100),
            stroke_fill="black",
        )
        canvas.paste(tile, (x, y))

    if max(canvas.size) > config.COLLAGE_MAX_SIDE:
        canvas.thumbnail((config.COLLAGE_MAX_SIDE, config.COLLAGE_MAX_SIDE))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=85)
    return out_path


def save_submission(src: Path, dest: Path) -> Path:
    """Normalize an incoming photo: fix orientation, cap size, save as JPEG."""
    img = Image.open(src)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail((config.MAX_PHOTO_SIDE, config.MAX_PHOTO_SIDE))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=90)
    return dest
