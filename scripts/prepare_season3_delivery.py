"""Prepare, but never send, Telegram commands for a published Season 3 site.

Use the fresh status CSV and the delivery CSV made by build_season3_site.py.
Keep the output under gitignored data/: it contains personal URLs and IDs.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from photobot.season3_consents import consent_fingerprint


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def prepare(
    status_path: Path, delivery_path: Path, base_url: str,
    home_url: str | None = None, schedule_at: str | None = None,
) -> str:
    parsed = urlparse(base_url)
    if (parsed.scheme != "https" or not parsed.netloc or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("Supply the actual public HTTPS gallery URL")
    base_url = base_url.rstrip("/") + "/"
    home_url = home_url or base_url
    home = urlparse(home_url)
    if home.scheme != "https" or home.hostname != parsed.hostname or home.query or home.fragment:
        raise ValueError("Homepage must be an HTTPS URL on the gallery domain")
    home_url = home_url.rstrip("/") + "/"
    status = {row["tg_id"]: row for row in _rows(status_path)}
    deliveries = {row["tg_id"]: row for row in _rows(delivery_path)}
    if len(status) != len(_rows(status_path)) or len(deliveries) != len(_rows(delivery_path)):
        raise ValueError("Duplicate Telegram ID in a CSV")
    eligible = {uid for uid, row in status.items() if int(row["photo_count"]) >= 2}
    if eligible != set(deliveries):
        raise ValueError("Delivery CSV and status CSV disagree about eligible contributors")
    relative_links = {}
    for uid, row in deliveries.items():
        choice = status[uid]["publication_choice"]
        expected = "public" if choice == "yes" else "private"
        if choice not in {"yes", "no", ""} or row["link_type"] != expected:
            raise ValueError(f"Consent or link type mismatch for {uid}; rebuild the site")
        url = row["url"]
        if url.startswith(base_url):
            url = url[len(base_url):]
        if (expected == "public" and url != "index.html") or (
            expected == "private" and not (
                url.startswith("private/") and url.endswith("/index.html")
                and len(url.split("/")) == 3
                and re.fullmatch(r"[A-Za-z0-9_-]+", url.split("/")[1])
            )
        ):
            raise ValueError(f"Unexpected gallery URL for {uid}; rebuild with this base URL")
        relative_links[uid] = url

    yes = sorted(uid for uid in eligible if status[uid]["publication_choice"] == "yes")
    no = sorted(uid for uid in eligible if status[uid]["publication_choice"] == "no")
    unanswered = sorted(uid for uid in eligible if status[uid]["publication_choice"] == "")
    public_en = (
        "Season 3 has become a collection of places we returned to. "
        f"Explore the anonymous photo sequences on our website: {home_url}"
    )
    public_ru = (
        "Третий сезон стал коллекцией мест, куда мы возвращались. "
        f"Посмотрите анонимные серии фотографий на сайте: {home_url}"
    )
    lines = [
        "Season 3 publication send plan — verify consent immediately before scheduling",
        f"Gallery: {base_url}",
        f"Homepage shared with everyone: {home_url}",
        f"Consent fingerprint: {consent_fingerprint(status.values())}",
        f"Eligible: {len(eligible)} · Yes: {len(yes)} · No: {len(no)} · unanswered: {len(unanswered)}",
        "",
    ]
    if schedule_at:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", schedule_at):
            raise ValueError("schedule_at must be YYYY-MM-DD HH:MM Berlin time")
        if len(no) != 1:
            raise ValueError("The current scheduler needs exactly one explicit No contributor")
        uid = no[0]
        lines.extend([
            "Scheduled send (public homepage to all active users, private page to explicit No):",
            f"/season3publishat {schedule_at} {consent_fingerprint(status.values())} "
            f"{uid} {base_url}{relative_links[uid]} yes",
            "Check with /season3publishat status; cancel before delivery with /season3publishat cancel.",
            "",
        ])
    lines.extend([
        "Manual fallback — send this once to all active bot users, including nonparticipants:",
        f"/broadcast {public_en} | {public_ru}",
        "",
        "Then send these personal links only to contributors who answered No:",
    ])
    for uid in no:
        url = base_url + relative_links[uid]
        lines.append(
            f"/dm {uid} Your photo sequence is here: {url} This unlisted page "
            "is not in the public gallery. Anyone with its link can open it. "
            f"Ваша серия фотографий здесь: {url} Эта страница не показана "
            "в общей галерее. Её может открыть любой, у кого есть ссылка."
        )
    if not no:
        lines.append("(none)")
    lines.extend(["", "Unanswered contributors: hold these personal links until you decide how to handle them:"])
    for uid in unanswered:
        lines.append(f"{uid}: {base_url}{relative_links[uid]}")
    if not unanswered:
        lines.append("(none)")
    lines.extend([
        "",
        "The public broadcast goes to active bot users only. /dm reports each personal delivery separately.",
        "Do not upload this plan, the status CSV, or season3-delivery.csv to the website.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("status", type=Path)
    parser.add_argument("delivery", type=Path)
    parser.add_argument("--base-url", required=True, help="Public HTTPS gallery URL")
    parser.add_argument("--home-url", help="Public homepage URL for the all-user broadcast")
    parser.add_argument("--schedule-at", help="YYYY-MM-DD HH:MM Berlin time for the bot scheduler")
    parser.add_argument("--output", type=Path, required=True, help="Private send plan under data/")
    args = parser.parse_args()
    content = prepare(args.status, args.delivery, args.base_url, args.home_url, args.schedule_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"Prepared {args.output}")


if __name__ == "__main__":
    main()
