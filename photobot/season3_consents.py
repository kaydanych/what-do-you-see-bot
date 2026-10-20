"""Pure consent snapshot calculation shared by the bot and send-plan script."""

import hashlib


def consent_fingerprint(members) -> str:
    eligible = sorted(
        (
            int(row["tg_id"]),
            int(row["photo_count"]),
            row["publication_choice"] or "",
        )
        for row in members
        if int(row["photo_count"]) >= 2
    )
    payload = "\n".join(f"{uid},{count},{choice}" for uid, count, choice in eligible)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
