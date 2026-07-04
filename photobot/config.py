import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
}
TZ = ZoneInfo(os.getenv("TZ", "Europe/Berlin"))

DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
DB_PATH = DATA_DIR / "photobot.db"
PHOTOS_DIR = DATA_DIR / "photos"
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "photobot.log"

# Defaults for the schedule; the live values sit in the DB settings table
# and are editable at runtime via /settimes.
DEFAULT_SETTINGS = {
    "prompt_time": "09:00",
    "reminder_time": "19:00",
    "deadline_time": "21:00",
    "collage_delay_min": "10",  # moderation window between deadline and collage
}

MAX_PHOTO_SIDE = 2560      # stored photos are downscaled to this
COLLAGE_CELL_PX = 600
COLLAGE_GUTTER_PX = 4
COLLAGE_MAX_CELLS = 108    # 12 x 9
COLLAGE_MAX_SIDE = 4000    # final canvas downscaled to this before sending


def validate() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN is empty. Copy .env.example to .env and fill in the token "
            "from @BotFather."
        )
    if not ADMIN_IDS:
        raise SystemExit(
            "ADMIN_IDS is empty. Put your Telegram user id into .env "
            "(ask @userinfobot for it)."
        )
    for d in (DATA_DIR, PHOTOS_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
