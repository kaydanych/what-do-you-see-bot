import random

import pytest
from PIL import Image

from photobot import collage, config


def make_photos(tmp_path, n):
    paths = []
    for i in range(n):
        img = Image.new(
            "RGB",
            (random.randint(400, 1600), random.randint(400, 1600)),
            (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)),
        )
        p = tmp_path / f"u{i}.jpg"
        img.save(p, "JPEG")
        paths.append(p)
    return paths


@pytest.mark.parametrize(
    "n, grid",
    [
        (1, (1, 1)),
        (2, (2, 1)),
        (3, (2, 2)),
        (4, (2, 2)),
        (5, (3, 2)),
        (6, (3, 2)),
        (7, (4, 2)),
    ],
)
def test_grid_minimal_padding(n, grid):
    cols, rows = collage._grid(n)
    assert (cols, rows) == grid
    cells = cols * rows
    # never fewer cells than photos, and never more than one short row of pad
    assert n <= cells < n + cols


@pytest.mark.parametrize("n", [1, 2, 3, 7, 23, 60])
def test_collage_shapes(tmp_path, n):
    paths = make_photos(tmp_path, n)
    out = collage.build_collage(paths, tmp_path / "out" / "collage.jpg")
    assert out.exists()
    img = Image.open(out)
    w, h = img.size
    assert max(w, h) <= config.COLLAGE_MAX_SIDE
    # justified mosaic: adaptive width keeps the card within a sane aspect band
    assert 0.35 < w / h < 2.5


@pytest.mark.parametrize("lang", ["en", "ru"])
def test_collage_with_header(tmp_path, lang):
    """Localised prompt + date header must render without error."""
    prompts = {
        "en": "Send a photo of something older than you",
        "ru": "Пришли фото чего-то старше тебя",
    }
    paths = make_photos(tmp_path, 5)
    out = collage.build_collage(
        paths,
        tmp_path / f"hdr_{lang}.jpg",
        prompt=prompts[lang],
        on_date="2026-07-12",
        lang=lang,
    )
    assert out.exists()
    assert Image.open(out).size[0] > 0


def test_collage_seed_identical_layout(tmp_path):
    """Same seed => identical mosaic size regardless of header language."""
    paths = make_photos(tmp_path, 9)
    en = collage.build_collage(
        paths, tmp_path / "en.jpg", prompt="hello", on_date="2026-07-12",
        lang="en", seed=42,
    )
    ru = collage.build_collage(
        paths, tmp_path / "ru.jpg", prompt="привет", on_date="2026-07-12",
        lang="ru", seed=42,
    )
    # width is header-independent; identical seed must yield identical width
    assert Image.open(en).size[0] == Image.open(ru).size[0]


def test_collage_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        collage.build_collage([], tmp_path / "c.jpg")


def test_collage_caps_cells(tmp_path):
    paths = make_photos(tmp_path, 5)
    # pretend many photos by repeating paths beyond the cap
    many = (paths * 30)[: config.COLLAGE_MAX_CELLS + 20]
    out = collage.build_collage(many, tmp_path / "big.jpg")
    assert out.exists()


def test_save_submission_normalizes(tmp_path):
    big = Image.new("RGB", (6000, 3000), (10, 200, 30))
    src = tmp_path / "src.png"
    big.save(src, "PNG")
    dest = collage.save_submission(src, tmp_path / "norm.jpg")
    img = Image.open(dest)
    assert max(img.size) <= config.MAX_PHOTO_SIDE
    assert img.format == "JPEG"
