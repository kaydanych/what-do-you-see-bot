"""Print the Telegram user id(s) of whoever has messaged the (test) bot.

Run AFTER you've sent the bot a message:  .venv/bin/python scripts/whoami.py
Then paste the id into .env as ADMIN_IDS and ALLOWED_IDS.
"""
import sys
import urllib.request
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from photobot import config  # noqa: E402


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN missing — fill in .env first.")
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getUpdates"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    seen: dict[int, tuple] = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or {}
        frm = msg.get("from") or {}
        if frm:
            seen[frm["id"]] = (frm.get("first_name"), frm.get("username"))
    if not seen:
        print("Nobody has messaged the bot yet. Send it /start, then re-run.")
        return
    for uid, (name, uname) in seen.items():
        print(f"{uid}\t{name}\t@{uname or '-'}")


if __name__ == "__main__":
    main()
