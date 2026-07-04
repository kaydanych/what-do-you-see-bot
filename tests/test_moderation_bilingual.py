import pytest
from PIL import Image

from photobot import collage, db, jobs
from photobot.handlers_admin import parse_prompt_line
from tests.test_collage import make_photos


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.init(tmp_path / "test.db")
    yield


def test_parse_prompt_line():
    assert parse_prompt_line("A photo with water | Фото с водой") == (
        "A photo with water",
        "Фото с водой",
    )
    assert parse_prompt_line("A photo with water") == ("A photo with water", None)
    assert parse_prompt_line("English only |") == ("English only", None)


def test_prompt_text_english_is_primary():
    pid = db.add_prompt("A photo with water", 1, text_ru="Фото с водой")
    p = db.get_prompt(pid)
    assert jobs.prompt_text(p, "en") == "A photo with water"
    assert jobs.prompt_text(p, "ru") == "Фото с водой"
    # missing RU translation falls back to English for everyone
    pid2 = db.add_prompt("No translation", 1)
    p2 = db.get_prompt(pid2)
    assert jobs.prompt_text(p2, "ru") == "No translation"
    assert jobs.prompt_text(p2, None) == "No translation"


def test_setru_updates_existing_prompt():
    pid = db.add_prompt("Send a photo of pink", 1)
    assert db.set_prompt_ru(pid, "Пришли фото розового") is True
    assert db.get_prompt(pid)["text_ru"] == "Пришли фото розового"
    assert db.set_prompt_ru(999, "нет такого") is False


def test_exclusion_filters_and_stable_numbering():
    for uid in (1, 2, 3):
        db.upsert_user(uid, f"U{uid}", None)
        db.upsert_photo("2026-07-04", uid, f"/p{uid}.jpg")
    db.set_photo_excluded("2026-07-04", 2, True)
    assert db.submitter_ids("2026-07-04") == [1, 3]
    full = db.photos_for("2026-07-04", include_excluded=True)
    assert [r["tg_id"] for r in full] == [1, 2, 3]  # numbering never shifts
    db.set_photo_excluded("2026-07-04", 2, False)
    assert db.submitter_ids("2026-07-04") == [1, 2, 3]


def test_contact_sheet(tmp_path):
    paths = make_photos(tmp_path, 7)
    out = collage.build_contact_sheet(paths, tmp_path / "sheet.jpg")
    assert out.exists()
    img = Image.open(out)
    assert img.size[0] > 0
    with pytest.raises(ValueError):
        collage.build_contact_sheet([], tmp_path / "empty.jpg")
