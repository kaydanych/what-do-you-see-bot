# Photobot — Daily Photo Prompt & Collage Bot

**Status:** v1 implemented (see README.md), pending live Telegram test
**Date:** 2026-07-04

## 1. Concept

A Telegram bot for a closed circle of up to ~100 people. Every day it sends one
photo prompt (e.g. «Сегодня пришли фото, которое тебя грустит» / "Today send me
a photo with water"). Participants reply with a photo before the evening
deadline. The bot assembles all submissions into a single collage and sends it
back — **only to the people who submitted that day**. Next morning, a new
prompt; the cycle repeats.

## 2. Platform & stack

| Piece | Choice | Why |
|---|---|---|
| Messenger | Telegram Bot API | Free, native photo handling, no business-API approval, admin-through-chat |
| Language | Python 3.12 | |
| Bot framework | `python-telegram-bot` v21 (async) | Mature, built-in `JobQueue` scheduler |
| Database | SQLite (single file) | ~100 users, one write per user per day — trivially sufficient |
| Images | Pillow | Collage generation |
| Scheduling | `JobQueue` (APScheduler under the hood) | Daily cron-style jobs inside the bot process |
| Hosting | Docker container on Synology NAS | Always on, photos land directly on NAS storage |
| Networking | **Long polling** (not webhooks) | No open ports, no DDNS, no TLS certs, no reverse proxy — the NAS only needs outbound internet |
| AI prompt generation | **Not in v1.** | Library-only; bot warns admin when running low (see §6) |

## 3. Language policy

- **Per-user choice.** Right after `/start` the bot shows an inline 🇷🇺/🇬🇧
  picker; the choice is stored per user (`users.lang`) and every service
  message (welcome, confirmations, reminders, collage captions) comes in that
  user's language. `/lang` switches at any time.
- Both language tables live in one `strings.py` module; a test enforces that
  RU and EN have identical keys and placeholders, so they can't drift apart.
- **Prompts are sent verbatim** as written in the library — Russian, English,
  or mixed, whatever Nikita puts in.
- Admin interface stays English.

## 4. Daily lifecycle (Europe/Berlin; times live in the DB and are changed from the admin chat via `/settimes` — applied within a minute, no restart)

| Time (default) | Event |
|---|---|
| 09:00 | Pick a random **unused** prompt from the library, mark it used, send to all active users. A `days` row is created for today. |
| 09:00–21:00 | Users submit photos. One photo per user per day; **re-sending replaces** the previous one (message: «Заменил твоё фото на новое»). |
| 19:00 | Gentle reminder — only to users who haven't submitted yet. Skipped if the user already submitted. |
| 21:00 | Deadline. Late photos get a polite rejection and are not stored. **Admin gets a numbered contact sheet** (every photo once, submission order) + a number→name list for moderation. |
| after 21:00 | Review: `/exclude N` drops a photo, `/ban N` drops it and kicks the author, `/include N` undoes, `/preview` dry-runs. Numbers never shift. Excluded users don't receive the collage. |
| admin's call | The collage is **never sent automatically** — the admin reviews and runs `/forcecollage` (reminder nudges to the admin 10/30/60 min after the deadline while unsent). It is then generated from the remaining photos and sent **only to that day's submitters** (admin always included). `/delcollage [date]` deletes a sent collage from every chat (≤48 h, Telegram limit) and resets the day for a re-send. |

Implementation: a single tick job runs every minute and compares the clock
against the DB-stored times and the day's state — this is what makes runtime
reconfiguration and reboot catch-up free.

**Catch-up on restart:** on startup the bot checks the `days` table — if
today's prompt wasn't sent yet and it's between 09:00 and 22:00, it sends it;
if the deadline passed but no moderation sheet went out, it sends it. NAS
reboots and DSM updates therefore can't silently kill a day.

**Zero/one submissions:** 0 photos → no collage, admin gets a note. 1 photo →
that user gets their own photo back as a 2×2 mini-collage with a friendly note
(still fun, keeps the ritual).

## 5. Users & onboarding

- Users join by opening the bot and sending `/start` (invite = just share the
  bot's `t.me/...` link).
- On each new join, the **admin gets a notification** («Новый участник: Имя,
  @username»). Admin can `/kick` anyone; kicked users are blocked from
  rejoining unless un-kicked.
  - *Open question for Nikita:* is notify-and-kick enough, or do you want
    explicit approval (new users held in "pending" until admin confirms)?
- `/stop` (or blocking the bot) marks a user inactive; `/start` reactivates.
- If Telegram reports the bot is blocked by a user during a broadcast, the user
  is auto-marked inactive — no crash, no retry storm.

**User commands:** `/start`, `/stop`, `/help`, `/today` (re-shows today's
prompt and whether your photo is in).

## 6. Prompt library

- Table `prompts(id, text, text_en, used_on, added_by, added_at)` — prompts are
  **bilingual**: `text` (RU/primary) is sent to Russian-language users, `text_en`
  to English ones; if `text_en` is missing everyone gets the primary text as-is.
- Admin adds prompts by:
  - `/addprompt Пришли фото с водой | Send a photo with water` — the `| EN` part
    is optional;
  - sending a **`.txt` file** to the bot (one prompt per line, same `RU | EN`
    format) — bulk import.
- `/prompts` lists all with IDs and used/unused status; `/delprompt <id>` removes.
- Selection: random among unused. When **fewer than 7 unused** remain, the
  daily prompt message to admin includes a warning. When the library is fully
  exhausted, the used-flags reset and prompts recycle (oldest-used first),
  with a louder admin warning.
- AI generation is explicitly **out of scope for v1**; the schema leaves room
  for it (a `source` column) if added later.

## 7. Photo handling & storage

- Accepted: Telegram **photos** (compressed) — the bot downloads the largest
  available size (~1280–2560 px), which is plenty for a collage cell.
  Documents/videos/stickers get a polite «Мне нужна именно фотография 🙂».
- Uncompressed originals (sent as file) — accepted too, but downscaled to max
  2560 px on save to keep storage sane.
- Layout on disk (Docker volume → NAS share):

```
/data/
  photobot.db
  photos/
    2026-07-04/
      u123456789.jpg      # one file per user, overwritten on resubmit
      collage.jpg
  logs/
    photobot.log          # rotating, 5 × 2 MB
```

- ~100 photos/day ≈ 30–80 MB/day ≈ under 30 GB/year — nothing for a NAS.
  Optional retention config: delete daily photos after N days, keep collages
  forever (default: keep everything).

## 8. Collage algorithm

Goal: a clean filled rectangle regardless of how many photos came in, using
random duplicates as filler — per Nikita's spec.

1. `N` = number of submissions. Cell = 600×600 px square.
2. Choose grid: `cols = ceil(sqrt(N * 4/3))`, `rows = ceil(N / cols)` —
   roughly 4:3 landscape. Cap at 12×9 (108 cells) so the file stays reasonable.
3. `cells = cols × rows`; the `cells − N` extra slots are filled with
   duplicates drawn randomly from the submissions (max 1 duplicate per user
   until everyone has one, then round-robin — nobody's photo dominates).
4. Shuffle all cell assignments so duplicates aren't adjacent to originals
   (retry shuffle a few times if they are).
5. Each photo is **center-cropped to a square** and resized to the cell.
6. Optional 4 px white gutter between cells (config flag).
7. Output JPEG quality 85. Sent as a Telegram *photo* (Telegram recompresses);
   config flag to also send as *document* for full quality.

Worst case (100 photos, 108 cells at 600 px) ≈ 7200×5400 px before Telegram's
photo cap — the bot downscales the final canvas to max 4000 px on the long
side before sending. Generation time on NAS-grade CPU: seconds.

## 9. Admin — troubleshooting without touching code

Admin = Telegram user IDs listed in config (`ADMIN_IDS`). All of the below
happens in the bot chat:

| Command | Does |
|---|---|
| `/status` | Today's prompt, submitted count + names, time to deadline, unused-prompt count |
| `/users` | Active/inactive/kicked list with join dates |
| `/addprompt`, `/prompts`, `/delprompt` | Library management (see §6) |
| `/times`, `/settimes` | Show / change the daily schedule (stored in DB, applies within a minute) |
| `/forceprompt` | Send today's prompt now (if the 09:00 job misfired) |
| `/forcecollage [date]` | Build & send the collage after review (this is the ONLY way it goes out) |
| `/delcollage [date]` | Delete a sent collage from every chat (≤48 h) and reset the day |
| `/preview` | Build the collage and send it **only to admin** — dry run |
| `/skipday` | Cancel today (no collage, no reminder) |
| `/broadcast <text>` | Message all active users |
| `/kick <id|@username>`, `/unkick` | Remove/restore a user |
| `/errors` | Last 20 error-log lines |

Plus **push-style error reporting**: every unhandled exception is caught by a
global error handler and DM'd to admin with a short traceback. In practice
this answers "why didn't the collage arrive" without ever opening SSH.

## 10. Configuration

Secrets and identity in `.env` (mounted into the container); the schedule in
the DB, editable from the admin chat:

```
# .env
BOT_TOKEN=...
ADMIN_IDS=123456789
TZ=Europe/Berlin
DATA_DIR=/data
```

```
# admin chat, any time:
/settimes prompt=09:00 reminder=19:00 deadline=21:00
```

## 11. Deployment on Synology

1. Create the bot with @BotFather → token.
2. NAS: Container Manager → project from `docker-compose.yml`:

```yaml
services:
  photobot:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - /volume1/docker/photobot/data:/data
```

3. Long polling → **no ports exposed, no firewall/DDNS/cert work at all.**
4. Logs visible in Container Manager UI as well as `/errors` in chat.
5. Backup: `/volume1/docker/photobot/` is a normal share — include it in the
   existing Hyper Backup task. SQLite is snapshot-safe at this write volume.

Development flow: build & test locally on the Mac (same Docker image, test bot
token), then copy the folder to the NAS and `docker compose up -d`. Updates =
copy new code, rebuild container; DB and photos live in the volume and survive.

## 12. Data model (SQLite)

```
users   (tg_id PK, first_name, username, status TEXT       -- active|inactive|kicked
         , joined_at, kicked_at)
prompts (id PK, text, source TEXT DEFAULT 'library', used_on DATE NULL,
         added_by, added_at)
days    (date PK, prompt_id FK, prompt_sent_at, collage_sent_at,
         skipped INT DEFAULT 0)
photos  (date FK, tg_id FK, file_path, submitted_at,
         PRIMARY KEY (date, tg_id))                          -- resubmit = UPSERT
ratings (date, tg_id, value TEXT, rated_at,                  -- fire|like|meh
         PRIMARY KEY (date, tg_id))                          -- revote = UPSERT
collage_messages (date, tg_id, message_id,                   -- per-user copy of the
         PRIMARY KEY (date, tg_id))                          -- collage, for live tallies
feedback    (id PK, tg_id, text, created_at)
suggestions (id PK, tg_id, text, status TEXT, created_at)    -- pending|approved|dismissed
```

## 12a. Community features

- **Collage ratings** — every collage goes out with an inline 🔥/👍/😐 row.
  A tap stores/updates the user's vote for that date and the bot edits the
  keyboard on *every* stored copy (`collage_messages`), so tallies are shared
  and live. Emoji-only labels keep one keyboard valid for both languages.
- **/feedback <text>** — stored in `feedback` and forwarded to the admins.
  Mentioned in the welcome and /help texts only; the bot never nags for it.
- **/suggest_prompt <idea>** — stored in `suggestions`, admins get a DM with
  `/approve <id> [en | ru]` / `/dismiss <id>` (plus `/suggestions` to list
  pending). Approving inserts a prompt with `source='suggestion'` and
  `added_by=<suggester>`; on the day it is sent (and in /today) users see
  "💡 Today's challenge was suggested by <name>".
- **/stats (admin-only for now)** — participation leaderboard derived from
  `photos` × collage days: N/total per user, current streak, plus overall
  rating tallies.

## 13. Edge cases covered

- Photo sent when no prompt is active (before 09:00 / after deadline / skipped
  day) → polite explanation, nothing stored.
- Album (multiple photos in one message) → first photo taken, user told only
  one counts.
- User joins mid-day → gets today's prompt immediately, can participate.
- Bot blocked by user → auto-inactive, no repeated send attempts.
- NAS reboot mid-day → catch-up logic (§4) repairs the day.
- Two admins pressing `/forcecollage` twice → `days.collage_sent_at` guard,
  second call answers «Коллаж уже отправлен».

## 14. Explicitly out of scope for v1

- AI-generated prompts (library-only, low-count warnings instead)
- Web dashboard (admin chat commands instead)
- Public (user-facing) stats — /stats exists but is admin-only for now (§12a)
- Multiple photos per user in the collage

## 15. Open questions for Nikita

1. **Join policy** — open link + kick, or explicit admin approval per user? (§5)
2. **Deadline 22:00 / prompt 09:00 / reminder 20:00** — good defaults?
3. Collage back **only to submitters** is confirmed; should the admin-received
   copy also go to a private archive channel? (Nice history-keeping, 1 line of code.)
4. Photo retention: keep dailies forever (default) or auto-delete after N days?
