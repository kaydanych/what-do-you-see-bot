# Deploying photobot on a Synology NAS

Everything here is done in the DSM web UI (works remotely over QuickConnect) —
no SSH needed. The generic Docker instructions are in the
[README](../README.md#run-it); this file is the NAS-specific runbook.

## First install

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
   unless-stopped` brings it back after reboots; the bot re-checks the day's
   state every minute, so a missed step self-heals.

## Auto-deploy from GitHub

The NAS deploys itself: a Task Scheduler job runs `update.sh` every few
minutes, which fetches from GitHub and — only when there are new commits —
resets the working tree and restarts the container (code-only change) or
rebuilds it (`requirements.txt` / `Dockerfile` / compose change). So the whole
deploy flow from anywhere is just **`git push`**, then wait one polling
interval. `.env` and `data/` are gitignored, so git never touches them.

> **Security note.** This task runs as `root` and does `git reset --hard
> origin/main`, so push access to the GitHub repo is root code execution on the
> NAS within minutes. Keep 2FA on the GitHub account and protect `main`.

**One-time setup:**

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
   `root`, schedule **Daily**, frequency **every 5 minutes** (in the Schedule
   tab's Frequency dropdown), script:

   ```sh
   /bin/sh /volume1/docker/photobot/update.sh
   ```

   If your DSM's Frequency dropdown only offers hourly, schedule hourly and
   loop inside the script instead — 11 checks 5 min apart, ending before the
   next hourly run:

   ```sh
   for i in 1 2 3 4 5 6 7 8 9 10 11; do
       /bin/sh /volume1/docker/photobot/update.sh
       sleep 300
   done
   ```

   Either way, **select the task → Run** deploys immediately — handy right
   after a push instead of waiting out the interval (works remotely via
   QuickConnect). In the task's Settings tab, enable *Send run details by
   email → only when the script terminates abnormally* to get notified of
   failed deploys.

Deploy activity is logged to `/volume1/docker/photobot/deploy.log` (visible in
File Station); up-to-date polls log nothing. Every deploy also stamps
`data/deploy_info` with the commit, an auto-incrementing build number (the
commit count on main) and the commit subject — on startup the bot DMs the
admins "🚀 Deployed build N (hash) — subject" when the commit changed (plain
restarts and reboots stay silent), and `/version` shows what's running.

**Don't edit files on the NAS** — `update.sh` does `git reset --hard`, so any
manual edits under `/volume1/docker/photobot` (except `.env` and `data/`) are
overwritten on the next deploy. The repo on GitHub is the single source of
truth.

## Maintenance

- **Stale code after a rebuild.** Container Manager's UI Build reuses cached
  layers. Force a clean one: Stop → Action → Clean → **Image tab → delete
  `photobot-photobot:latest`** → Build.
- **Verify what's actually running:** Container → `photobot` → Terminal, e.g.
  `python -c "from photobot import collage; print(collage._grid(4))"`.
- **Backup:** include `/volume1/docker/photobot/data` in Hyper Backup. The
  database and photos live there (outside the image) and are never touched by
  restarts or rebuilds.
