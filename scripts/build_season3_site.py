"""Build a consent-filtered static Season 3 gallery from a NAS backup.

The public page contains only explicit Yes sequences. Other multi-photo
sequences get separate, unlisted pages. Keep --links outside the web root:
it connects Telegram IDs to private URLs and must never be deployed.
"""

from __future__ import annotations

import argparse
import csv
import json
import secrets
import sqlite3
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageOps


TEMPLATE = Path(__file__).resolve().parents[1] / "site" / "season3"


def _copy_page(destination: Path, *, private: bool = False) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "styles.css", "app.js"):
        content = (TEMPLATE / name).read_text(encoding="utf-8")
        if private and name == "index.html":
            content = content.replace(
                '<meta name="theme-color"',
                '<meta name="robots" content="noindex,nofollow" />\n'
                '    <meta name="theme-color"',
                1,
            )
        (destination / name).write_text(content, encoding="utf-8")


def _write_data(destination: Path, season, rows: list[dict]) -> None:
    payload = {
        "start": season["planned_start_date"],
        "end": season["planned_end_date"],
        "status": "finished",
        "through": max((p["date"] for row in rows for p in row["photos"]), default=None),
        "places": rows,
    }
    (destination / "season-data.js").write_text(
        "window.OBSERVATION_SEASON = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )


def _render_sequence(archive, series, destination: Path, number: int) -> dict:
    assets = destination / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    key = f"place-{number:02d}"
    photos = []
    for position, (local_date, archive_name) in enumerate(series, 1):
        stem = f"{key}-{position:02d}"
        with archive.open(archive_name) as source, Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((1800, 1800))
            image.save(assets / f"{stem}.jpg", quality=88, optimize=True)
            width, height = image.size
            small = image.copy()
            small.thumbnail((900, 900))
            small.save(assets / f"{stem}-900.jpg", quality=84, optimize=True)
            if position == 1:
                cover = image.copy()
                cover.thumbnail((640, 640))
                cover.save(assets / f"{key}-cover.jpg", quality=84, optimize=True)
        photos.append({
            "date": local_date,
            "src": f"assets/{stem}.jpg",
            "smallSrc": f"assets/{stem}-900.jpg",
            "smallWidth": small.width,
            "width": width,
            "height": height,
        })
    return {"id": key, "number": number, "cover": f"assets/{key}-cover.jpg", "photos": photos}


def build(archive_path: Path, status_path: Path, output: Path, links_path: Path, base_url: str = "") -> dict:
    output = output.resolve()
    links_path = links_path.resolve()
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    if output == links_path or output in links_path.parents:
        raise ValueError("The identity-to-link map must be outside the web root")
    with status_path.open(newline="", encoding="utf-8") as handle:
        status_rows = list(csv.DictReader(handle))
    if not status_rows or "publication_choice" not in status_rows[0]:
        raise ValueError("Use a fresh /season3export status CSV with publication choices")
    choices = {int(row["tg_id"]): row for row in status_rows}
    if len(choices) != len(status_rows):
        raise ValueError("Duplicate Telegram ID in status CSV")

    links = json.loads(links_path.read_text(encoding="utf-8")) if links_path.exists() else {}
    with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory() as temp:
        db_path = Path(temp) / "photobot.db"
        db_path.write_bytes(archive.read("photobot/data/photobot.db"))
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            season = db.execute(
                "SELECT * FROM observation_seasons ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if season is None or season["status"] != "finished":
                raise ValueError("The backup must contain a finished Season 3")
            if {int(row["season_id"]) for row in status_rows} != {season["id"]}:
                raise ValueError("Status CSV and backup refer to different seasons")
            photos = db.execute(
                "SELECT tg_id, local_date, file_path FROM observation_photos "
                "WHERE season_id=? ORDER BY local_date, submitted_at, tg_id",
                (season["id"],),
            ).fetchall()
        series_by_person = defaultdict(list)
        available = set(archive.namelist())
        for photo in photos:
            archive_name = "photobot/" + photo["file_path"].lstrip("/")
            if archive_name not in available:
                raise ValueError(f"Backup is missing a Season 3 photo dated {photo['local_date']}")
            series_by_person[photo["tg_id"]].append((photo["local_date"], archive_name))
        for uid, row in choices.items():
            if int(row["photo_count"]) != len(series_by_person[uid]):
                raise ValueError(f"Status CSV and backup photo counts differ for {uid}")
            if row["publication_choice"] not in {"", "yes", "no"}:
                raise ValueError(f"Invalid publication choice for {uid}")
        if set(series_by_person) - set(choices):
            raise ValueError("The status CSV is missing a photo contributor")

        _copy_page(output)
        (output / "robots.txt").write_text("User-agent: *\nDisallow: /private/\n", encoding="utf-8")
        public_rows = []
        deliveries = []
        used_tokens = set(links.values())
        for uid, series in series_by_person.items():
            if len(series) < 2:
                continue
            if choices[uid]["publication_choice"] == "yes":
                public_rows.append(_render_sequence(archive, series, output, len(public_rows) + 1))
                deliveries.append((uid, "public", base_url.rstrip("/") + "/" if base_url else "index.html"))
                continue
            key = str(uid)
            token = links.get(key)
            if not token:
                token = secrets.token_urlsafe(24)
                while token in used_tokens:
                    token = secrets.token_urlsafe(24)
                links[key] = token
                used_tokens.add(token)
            private_dir = output / "private" / token
            _copy_page(private_dir, private=True)
            _write_data(private_dir, season, [_render_sequence(archive, series, private_dir, 1)])
            relative = f"private/{token}/"
            deliveries.append((uid, "private", base_url.rstrip("/") + "/" + relative if base_url else relative))
        _write_data(output, season, public_rows)

    links_path.parent.mkdir(parents=True, exist_ok=True)
    links_path.write_text(json.dumps(links, indent=2) + "\n", encoding="utf-8")
    with (links_path.parent / "season3-delivery.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("tg_id", "link_type", "url"))
        writer.writerows(deliveries)
    return {
        "public_sequences": len(public_rows),
        "private_sequences": sum(kind == "private" for _, kind, _ in deliveries),
        "one_photo_excluded": sum(len(series) == 1 for series in series_by_person.values()),
        "output": str(output),
        "delivery_csv": str(links_path.parent / "season3-delivery.csv"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="NAS photobot ZIP backup taken after finishing")
    parser.add_argument("status", type=Path, help="Fresh season3-status.csv from /season3export")
    parser.add_argument("--output", type=Path, required=True, help="New static site directory")
    parser.add_argument("--links", type=Path, required=True, help="Private identity-to-link map outside web root")
    parser.add_argument("--base-url", default="", help="Published site URL for delivery CSV")
    args = parser.parse_args()
    print(json.dumps(build(args.archive, args.status, args.output, args.links, args.base_url), indent=2))


if __name__ == "__main__":
    main()
