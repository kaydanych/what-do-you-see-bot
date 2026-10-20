"""The send plan must respect the latest consent choices."""

import csv

import pytest

from scripts.prepare_season3_delivery import prepare


def _csv(path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_send_plan_targets_only_no_with_personal_command(tmp_path):
    status = tmp_path / "status.csv"
    delivery = tmp_path / "delivery.csv"
    _csv(status, ("tg_id", "photo_count", "publication_choice"), (
        (1, 3, "yes"), (2, 2, "no"), (3, 2, ""), (4, 1, ""),
    ))
    _csv(delivery, ("tg_id", "link_type", "url"), (
        (1, "public", "index.html"), (2, "private", "private/abc123/index.html"),
        (3, "private", "private/xyz789/index.html"),
    ))
    plan = prepare(status, delivery, "https://example.org/season3/", "https://example.org/")
    assert "/broadcast " in plan
    assert "/dm 2 " in plan
    assert "/dm 3 " not in plan
    assert "https://example.org/season3/private/abc123/index.html" in plan
    assert "3: https://example.org/season3/private/xyz789/index.html" in plan
    assert "Homepage shared with everyone: https://example.org/" in plan
    assert "/dm 4 " not in plan


def test_send_plan_rejects_stale_consent_and_localhost(tmp_path):
    status = tmp_path / "status.csv"
    delivery = tmp_path / "delivery.csv"
    _csv(status, ("tg_id", "photo_count", "publication_choice"), ((1, 2, "yes"),))
    _csv(delivery, ("tg_id", "link_type", "url"), ((1, "private", "private/abc123/index.html"),))
    with pytest.raises(ValueError, match="Consent or link type mismatch"):
        prepare(status, delivery, "https://example.org/")
    with pytest.raises(ValueError, match="public HTTPS"):
        prepare(status, delivery, "http://127.0.0.1:4174/")


def test_scheduled_plan_includes_only_explicit_no_link(tmp_path):
    status = tmp_path / "status.csv"
    delivery = tmp_path / "delivery.csv"
    _csv(status, ("tg_id", "photo_count", "publication_choice"), (
        (1, 3, "yes"), (2, 2, "no"), (3, 2, ""),
    ))
    _csv(delivery, ("tg_id", "link_type", "url"), (
        (1, "public", "index.html"),
        (2, "private", "private/abc123/index.html"),
        (3, "private", "private/xyz789/index.html"),
    ))
    plan = prepare(status, delivery, "https://example.org/season3/",
                   "https://example.org/", "2026-10-20 18:00")
    command = next(line for line in plan.splitlines() if line.startswith("/season3publishat "))
    assert " 2 https://example.org/season3/private/abc123/index.html yes" in command
    assert "xyz789" not in command
