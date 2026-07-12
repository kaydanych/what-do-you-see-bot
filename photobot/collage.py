import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import config


def _load_cell(path: Path, cell: int) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    return ImageOps.fit(img, (cell, cell))


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


def build_collage(photo_paths: list[Path], out_path: Path) -> Path:
    """Assemble a filled rectangle from the day's photos, padding empty
    cells with random duplicates (spread evenly across users)."""
    paths = [Path(p) for p in photo_paths if Path(p).exists()]
    if not paths:
        raise ValueError("no photos to build a collage from")

    if len(paths) > config.COLLAGE_MAX_CELLS:
        paths = random.sample(paths, config.COLLAGE_MAX_CELLS)

    cols, rows = _grid(len(paths))
    cells = cols * rows

    dup_pool = paths.copy()
    random.shuffle(dup_pool)
    assignment = paths.copy()
    i = 0
    while len(assignment) < cells:
        assignment.append(dup_pool[i % len(dup_pool)])
        i += 1
    random.shuffle(assignment)

    cell = config.COLLAGE_CELL_PX
    gut = config.COLLAGE_GUTTER_PX
    w = cols * cell + (cols + 1) * gut
    h = rows * cell + (rows + 1) * gut
    canvas = Image.new("RGB", (w, h), "white")

    cache: dict[Path, Image.Image] = {}
    for idx, p in enumerate(assignment):
        if p not in cache:
            cache[p] = _load_cell(p, cell)
        r, c = divmod(idx, cols)
        x = gut + c * (cell + gut)
        y = gut + r * (cell + gut)
        canvas.paste(cache[p], (x, y))

    if max(canvas.size) > config.COLLAGE_MAX_SIDE:
        canvas.thumbnail((config.COLLAGE_MAX_SIDE, config.COLLAGE_MAX_SIDE))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=85)
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
