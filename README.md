# Photobot

Daily photo-prompt Telegram bot: sends a prompt every morning, collects one
photo per user until the deadline, then sends everyone who participated a
collage of the day. See [DESIGN.md](DESIGN.md) for the full design.

## One-time setup

1. **Create the bot**: message [@BotFather](https://t.me/BotFather) → `/newbot`
   → pick a name and username → copy the token.
2. **Get your user id**: message [@userinfobot](https://t.me/userinfobot).
3. `cp .env.example .env` and fill in `BOT_TOKEN` and `ADMIN_IDS`.

## Run locally (testing)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m photobot.main
```

Then in Telegram: `/start` the bot, `/admin` shows the admin command list,
`/addprompt Пришли фото с водой` adds a prompt, `/forceprompt` fires it
immediately, send a photo, `/preview` or `/forcecollage` to see the collage.

Tests: `.venv/bin/pip install pytest && .venv/bin/python -m pytest tests/`

## Schedule

Defaults: prompt **09:00**, reminder **19:00**, deadline **21:00**, collage
**21:10** (deadline + 10 min = the moderation window), Europe/Berlin. All of it
is stored in the DB and changed from the admin chat — no restart, applies
within a minute:

```
/settimes prompt=09:00 reminder=19:00 deadline=21:00 delay=10
```

At the deadline the admin receives a numbered contact sheet of all
submissions; during the delay window `/exclude N` / `/ban N` remove photos
before the collage goes out. Prompts can be bilingual:
`/addprompt Пришли фото с водой | Send a photo with water`.

## Deploy on the Synology NAS

1. Copy this folder (without `.venv/` and `data/`) to the NAS, e.g.
   `/volume1/docker/photobot/`.
2. Edit `docker-compose.yml`: volume left side → `/volume1/docker/photobot/data`.
3. Container Manager → Project → Create → point at the folder → build & run.
   (Or via SSH: `docker compose up -d --build`.)
4. Done. Long polling means no ports, no DDNS, no certificates.

Updating code later: copy new files over, rebuild the container. The database
and photos live in `data/` and survive rebuilds.

**Backup**: include `/volume1/docker/photobot/data` in Hyper Backup.

## Troubleshooting (no code needed)

- Every crash is DM'd to the admins automatically with a traceback.
- `/status` — did the prompt go out, who submitted, is the collage pending.
- `/errors` — last log lines in chat.
- `/forceprompt`, `/forcecollage` — re-fire a missed step by hand.
- After a NAS reboot the bot catches up on its own (it re-checks the day's
  state every minute).
