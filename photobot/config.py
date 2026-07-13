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
    "final_reminder_min": "10",  # last-call reminder this many minutes before deadline
    "collage_delay_min": "10",  # moderation window between deadline and collage
    "project_start_date": "2026-07-12",  # day 1; collage shows "Day N" counting from here
    "deployed_commit": "",  # last build announced to admins (set on startup)
}

MAX_PHOTO_SIDE = 2560      # stored photos are downscaled to this
COLLAGE_CELL_PX = 600      # square cell size for the moderation contact sheet
COLLAGE_GUTTER_PX = 4      # gutter for the moderation contact sheet
COLLAGE_MAX_CELLS = 108    # 12 x 9
COLLAGE_MAX_SIDE = 4000    # final canvas downscaled to this before sending

# --- Daily collage (justified-mosaic "card") --------------------------------
FONTS_DIR = Path(__file__).resolve().parent / "fonts"
COLLAGE_WIDTH = 1080          # minimum canvas width (phone-portrait floor); busy
                              # days grow wider via COLLAGE_PORTRAIT_K below
COLLAGE_PORTRAIT_K = 1.0      # width tightness: higher = wider canvas = less
                              # portrait. Tuned so medium/large days land ~3:4.
COLLAGE_BG = "#141414"        # mat colour behind the photos
COLLAGE_FG = "#f2f2f2"        # header prompt text
COLLAGE_DIM = "#8a8f98"       # date kicker + footer
COLLAGE_RADIUS = 18           # tile corner radius
COLLAGE_GAP = 14              # space between tiles
COLLAGE_PAD = 48              # outer margin
COLLAGE_ASPECT_MIN = 0.55     # clamp extreme portraits (below this = mild crop)
COLLAGE_ASPECT_MAX = 1.9      # clamp extreme panoramas


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
