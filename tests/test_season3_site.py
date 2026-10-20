"""Consent filtering for the static Season 3 publication package."""

import csv
import io
import json
import sqlite3
import zipfile

from PIL import Image

from scripts.build_season3_site import build


def _jpeg(color):
    stream = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(stream, "JPEG")
    return stream.getvalue()


def test_public_gallery_contains_only_yes_and_private_pages_are_separate(tmp_path):
    database = tmp_path / "photobot.db"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE observation_seasons (
                id INTEGER PRIMARY KEY, status TEXT, planned_start_date TEXT,
                planned_end_date TEXT
            );
            CREATE TABLE observation_photos (
                season_id INTEGER, tg_id INTEGER, local_date TEXT,
                file_path TEXT, submitted_at TEXT
            );
            INSERT INTO observation_seasons VALUES
                (1, 'finished', '2026-09-21', '2026-10-18');
        """)
        for uid, count in ((1, 2), (2, 2), (3, 1), (4, 2)):
            for n in range(1, count + 1):
                connection.execute(
                    "INSERT INTO observation_photos VALUES (1, ?, ?, ?, ?)",
                    (uid, f"2026-10-{n:02d}", f"data/photos/u{uid}-{n}.jpg", f"2026-10-{n:02d}"),
                )
    archive = tmp_path / "photobot.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.write(database, "photobot/data/photobot.db")
        for uid, count in ((1, 2), (2, 2), (3, 1), (4, 2)):
            for n in range(1, count + 1):
                bundle.writestr(f"photobot/data/photos/u{uid}-{n}.jpg", _jpeg(f"#{uid}{n}8844"))
    status = tmp_path / "status.csv"
    with status.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("season_id", "tg_id", "photo_count", "publication_choice"))
        writer.writerows(((1, 1, 2, "yes"), (1, 2, 2, "no"), (1, 3, 1, ""), (1, 4, 2, "")))

    output = tmp_path / "site"
    links = tmp_path / "private-links.json"
    result = build(archive, status, output, links, "https://example.org/gallery")
    assert result["public_sequences"] == 1
    assert result["private_sequences"] == 2
    assert result["one_photo_excluded"] == 1
    assert len(list((output / "assets").glob("*.jpg"))) == 5
    public_data = (output / "season-data.js").read_text(encoding="utf-8")
    public_payload = json.loads(public_data.split("=", 1)[1].rstrip(";\n"))
    assert len(public_payload["places"]) == 1
    assert public_payload["private"] is False
    assert 'season-data.js?v=' in (output / "index.html").read_text(encoding="utf-8")
    token = json.loads(links.read_text(encoding="utf-8"))["2"]
    assert len(token) >= 32
    private = output / "private" / token
    assert "noindex,nofollow" in (private / "index.html").read_text(encoding="utf-8")
    assert "noindex,nofollow" in (output / "private" / "index.html").read_text(encoding="utf-8")
    assert token not in (output / "private" / "index.html").read_text(encoding="utf-8")
    private_payload = json.loads((private / "season-data.js").read_text(encoding="utf-8").split("=", 1)[1].rstrip(";\n"))
    assert private_payload["private"] is True
    assert len(private_payload["places"]) == 1
    assert len(list((private / "assets").glob("*.jpg"))) == 5
    assert not (output / "private-links.json").exists()
    with (tmp_path / "season3-delivery.csv").open(newline="", encoding="utf-8") as handle:
        deliveries = list(csv.DictReader(handle))
    assert {row["tg_id"] for row in deliveries} == {"1", "2", "4"}
    assert next(row["url"] for row in deliveries if row["tg_id"] == "2").endswith(f"/private/{token}/index.html")
