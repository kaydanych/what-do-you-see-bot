# 📸 Photobot — a daily photo game for your group

**[@what_do_you_see_bot](https://t.me/what_do_you_see_bot)** · self-hosted Telegram bot · RU 🇷🇺 / EN 🇬🇧

Every morning the bot sends everyone the same tiny creative prompt —
*"send a photo with water"*, *"something that made you smile today"*. Each
person replies with **one** photo before the evening deadline. Then the bot
stitches all of that day's photos into a single collage and sends it back —
**only to the people who played**. Next morning, a new prompt. It's a quiet
daily ritual for a closed circle of friends: a reason to look a little closer
at an ordinary day.

![Example collage of the day](docs/collage-example.jpg)

## What it does

- 🗓 **One prompt a day** from a curated bilingual library, sent to everyone at once
- 📷 **One photo per person** — a new one replaces your old one, right up to the deadline
- 🖼 **Automatic collage** at the end of the day, shared only with that day's participants
- 🧹 **Admin moderation window** — drop a photo or ban a sender before the collage goes out
- 🇷🇺🇬🇧 **Per-user language**, prompts sent verbatim in `RU | EN` format
- 🏠 **Self-hosted & private** — long polling, so no open ports; photos never leave your machine

## How a day works

Times are Europe/Berlin and live in the DB — change them from the admin chat
with `/settimes`, no restart needed.

| Time (default) | What happens |
|---|---|
| **09:00** | A random unused prompt is picked from the library and sent to all active users |
| 09:00–21:00 | Users submit photos — one each, a new one replaces the old |
| **19:00** | Gentle reminder, only to those who haven't submitted yet |
| **21:00** | Deadline. Late photos are politely rejected. Admin gets a numbered contact sheet for moderation |
| 21:00–21:10 | Moderation window: `/exclude N`, `/ban N`, `/include N` |
| **21:10** | Collage is built and sent to everyone who took part |

The bot self-heals: a tick job every minute compares the clock to the day's
state, so runtime schedule changes and NAS reboots can't silently kill a day.
See [DESIGN.md](DESIGN.md) for the full design.

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

Web UI only (QuickConnect), no SSH needed:

1. In File Station, copy this folder (without `.venv/`, `.git/`, `__pycache__/`)
   to `/volume1/docker/photobot/`. Create the `.env` there with your real
   `BOT_TOKEN` / `ADMIN_IDS` (it's gitignored, so it isn't in the copy).
2. **Create an empty `data/` folder** inside it. Container Manager does *not*
   auto-create bind-mount sources — without it the container fails to start
   with `Bind mount failed: ... does not exist`. The compose file mounts
   `./data` and `./photobot` relative to the project folder, so no path edits
   are needed.
3. Container Manager → Project → Create → point at the folder → Build.
4. Done. Long polling means no ports, no DDNS, no certificates. `restart:
   unless-stopped` brings it back after reboots; it re-checks the day's state
   every minute, so a missed step self-heals.

### Updating on the NAS (automatic via git pull)

The NAS deploys itself: a Task Scheduler job runs `update.sh` every few
minutes, which fetches from GitHub and — only when there are new commits —
resets the working tree and restarts the container (code-only change) or
rebuilds it (`requirements.txt` / `Dockerfile` / compose change). So the whole
deploy flow from anywhere is just **`git push`**, then wait one polling
interval. `.env` and `data/` are gitignored, so git never touches them.

**One-time setup** (all in the DSM web UI, no SSH):

1. Package Center → install **Git Server** (we only need the `git` binary it
   ships; don't enable/configure the server itself).
2. Control Panel → Task Scheduler → Create → **Scheduled Task → User-defined
   script**. User: `root`. Schedule: doesn't matter (run manually once).
   Script — turns the existing folder into a git checkout:

   ```sh
   cd /volume1/docker/photobot
   git init
   git remote add origin https://github.com/kaydanych/what-do-you-see-bot.git
   git fetch origin main
   git reset --hard origin/main
   git branch -M main
   git branch --set-upstream-to=origin/main main
   ```

   Run it once (select task → Run), check `git status` works via a follow-up
   run if unsure, then delete this task.
3. Create the recurring task: **Scheduled Task → User-defined script**, user
   `root`, schedule **every 5 minutes**, script:

   ```sh
   /bin/sh /volume1/docker/photobot/update.sh
   ```

   In the task's Settings tab, enable *Send run details by email → only when
   the script terminates abnormally* to get notified of failed deploys.

Deploy activity is logged to `/volume1/docker/photobot/deploy.log` (visible in
File Station); up-to-date polls log nothing.

**Don't edit files on the NAS anymore** — `update.sh` does `git reset --hard`,
so any manual edits under `/volume1/docker/photobot` (except `.env` and
`data/`) are overwritten on the next deploy. The repo on GitHub is the single
source of truth.

If a rebuild ever serves stale code (Container Manager's UI Build reuses
cached layers), force a clean one: Stop → Action → Clean → **Image tab →
delete `photobot-photobot:latest`** → Build.

Verify what's actually running via Container → `photobot` → Terminal, e.g.
`python -c "from photobot import collage; print(collage._grid(4))"`.

The database and photos live in `data/` (outside the image) and are never
touched by restarts or rebuilds.

**Backup**: include `/volume1/docker/photobot/data` in Hyper Backup.

## Troubleshooting (no code needed)

- Every crash is DM'd to the admins automatically with a traceback.
- `/status` — did the prompt go out, who submitted, is the collage pending.
- `/errors` — last log lines in chat.
- `/forceprompt`, `/forcecollage` — re-fire a missed step by hand.
- After a NAS reboot the bot catches up on its own (it re-checks the day's
  state every minute).

## Stack

Python 3.12 · [`python-telegram-bot`](https://python-telegram-bot.org) v21
(async, built-in JobQueue scheduler) · Pillow (collage) · SQLite · Docker.
Full design notes in [DESIGN.md](DESIGN.md).
