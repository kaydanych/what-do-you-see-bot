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
| 21:00 | Deadline. Late photos get a polite rejection and are not stored. **Admin gets a numbered contact sheet** (every photo once, submission order) + a number→name list for moderation. 2–3 **proofers** (§4a) get the finished collage itself, with 👍/🚫. |
| after 21:00 | Review: `/exclude N` drops a photo, `/ban N` drops it and kicks the author, `/include N` undoes, `/preview` dry-runs. Numbers never shift. Excluded users don't receive the collage. |
| a proofer's 👍 | The collage goes out immediately — this is where almost every evening ends. |
| admin's call | With proofing off (or held, or unanswered), the collage is **never sent automatically** — the admin reviews and runs `/forcecollage` (reminder nudges to the admin 10/30/60 min after the deadline while unsent). It is then generated from the remaining photos and sent **only to that day's submitters** (admin always included). `/delcollage [date]` deletes a sent collage from every chat (≤48 h, Telegram limit) and resets the day for a re-send. |

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

## 4a. Collage proofing (delegated pre-publish check)

Waiting for the admin every single night is the bottleneck the rest of the day
doesn't have. So a small **trusted list** sees the collage before anyone else
and, in the overwhelming majority of cases, waves it through.

**Who is asked.** A standing list of people flagged with `/proofer` — meant to
be long (most of the group) and uniformly trusted, not a rota. Adding someone
is silent: no enrollment DM, no ceremony, just a list.

Each night the batch is drawn **at random** from the overlap of that list with
**that day's submitters**, so a proofer only ever gets an early look at a
collage they're already in. With most of the group trusted, the overlap is
normally many batches deep; when it does run dry the day falls back to the
admin rather than reaching for someone who didn't play. Escalations draw again
from whoever in that overlap hasn't been asked yet — random rather than
round-robin, so nobody comes to own a particular weekday and a second batch is
genuinely fresh eyes.

**No warning shot.** There is no heads-up message: the collage simply arrives
at the deadline asking whether anything is wrong. Silence rolls to the next
batch every 10 minutes, which handles "wasn't looking at my phone" better than
a reminder would.

**What they see.** The finished collage exactly as it would be published — no
numbers, no names, no contact sheet. They're answering "is anything wrong with
this?", not doing photo-by-photo moderation; picking out *which* photo is the
admin's job and needs the numbered sheet the admin already has.

**The two taps.** 👍 publishes. 🚫 swaps the keyboard for
`🚫 Really ban` / `✅ Changed my mind, all good` and only the second tap counts —
a ban stops the evening for everyone and must not be one stray thumb.

**Resolution.**

| Situation | Outcome |
|---|---|
| Any 👍, no ban on record | Published immediately; the admin is told who approved it |
| 👍 from the *same* batch as a ban | Recorded, but doesn't publish — the flag stands |
| 👍 from a *later* batch (one that was shown "someone flagged this") | Published; the admin gets the flagger's note either way |
| 1 ban | Rolls to a fresh batch — one person flagging is a reason to look again, not a veto |
| 2 bans (`quorum`) | Parked on the admin, with both notes: `/exclude N` + `/forcecollage`, or `/forcecollage` as is |
| A batch stays silent for 10 min (`round`) | Next batch |
| The list runs out | With an open ban → parked on the admin. Otherwise → the old admin-only flow, nudges and all |

Once the day is decided, whoever answered keeps their copy captioned with the
outcome, and the question is **deleted** from everyone who hadn't got round to
it — no stale buttons, no "who already decided this?".

**What "inappropriate" means** is deliberately narrow and rides in the ask
itself (`PROOF_ASK`, both languages) — there is no separate briefing to
remember or miss. The bar: only an obvious violation of the shared social
space — nudity, someone identifiable in a private moment, graphic violence,
hate symbols, exposed personal data, a shot meant to humiliate. Explicitly
*not* grounds: bad taste, bad photography, boring, off prompt, or "I don't like
it". Closing line: **when in doubt, publish.**

A confirmed ban asks for an optional free-text note ("what's wrong, and which
photo?") which is forwarded to the admin as-is.

Everything runs on the same one-minute tick, so a NAS reboot mid-evening
catches up, and every knob (`batch`, `round`, `quorum`, on/off) lives in the DB
and is changed from the admin chat via `/proofing`.

## 5. Users & onboarding

- Users join by opening the bot and sending `/start` (invite = just share the
  bot's `t.me/...` link).
- **Nobody joins unseen.** A newcomer is created as `pending` and the admin gets
  their card — name, @username, id, first seen — with two inline buttons,
  ✅ Approve / 🚫 Reject. This is the answer to the old open question: the game
  is small and almost family-sized, so notify-and-kick (letting a stranger in
  and removing them afterwards) was the wrong default.
  - While pending they are outside `active_user_ids()`, so **no** prompt,
    reminder, collage, poll or broadcast reaches them; every message they send
    gets the bilingual "you're on the list" note (`PENDING`) instead of being
    acted on. They can still pick a language, so the wait — and the welcome that
    follows — arrive in it.
  - ✅ flips them to `active` and greets them there and then: the welcome, plus
    today's prompt if a day is open. Someone approved before choosing a language
    gets the picker first, and the welcome follows their tap.
  - 🚫 marks them `kicked`, and they're told the door is closed. Both decisions
    are one tap and reversible with `/kick` / `/unkick`; the card is edited in
    place to say which, so a stale copy in a second admin's chat can't re-decide
    anything.
  - `/pending` re-sends the cards, buttons and all, for when the original has
    scrolled away. Pending users show as ⏳ in `/users`, and `/status` counts
    them when any are waiting.
  - Admins skip their own gate — they'd have nobody to let them in.
- `/stop` (or blocking the bot) marks a user inactive; `/start` reactivates.
  A *pending* user's `/stop` leaves them pending: 'inactive' would take them off
  the gate and the next `/start` would revive them straight into the game.
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
| `/users` | Pending/active/inactive/kicked list with join dates |
| `/pending` | Newcomers awaiting ✅, each with the Approve/Reject buttons again (§5) |
| `/addprompt`, `/prompts`, `/delprompt` | Library management (see §6) |
| `/times`, `/settimes` | Show / change the daily schedule (stored in DB, applies within a minute) |
| `/forceprompt` | Send today's prompt now (if the 09:00 job misfired) |
| `/forcecollage [date]` | Build & send the collage after review (this is the ONLY way it goes out) |
| `/delcollage [date]` | Delete a sent collage from every chat (≤48 h) and reset the day |
| `/preview` | Build the collage and send it **only to admin** — dry run (keeps the hi-res zoom file) |
| `/knocks [date]` | The knock tally (§11a), then the leader(s) as pictures with 💬 to ask that author. No date = yesterday *and* today, since last night's vote runs while today's photos are still coming in |
| `/proofers`, `/proofer <id\|@user>` | The standing trusted list a nightly batch is drawn from (§4a); adding is silent |
| `/proofing [key=val…\|on\|off]` | Proofing settings and tonight's state |
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
users   (tg_id PK, first_name, username, status TEXT       -- pending|active|
         , joined_at, kicked_at, lang, proofer INT,        -- inactive|kicked
         last_proofed_on)                                  -- pending = awaiting ✅ (§5)
prompts (id PK, text, source TEXT DEFAULT 'library', used_on DATE NULL,
         added_by, added_at)
days    (date PK, prompt_id FK, prompt_sent_at, collage_sent_at,
         skipped INT DEFAULT 0)
photos  (date FK, tg_id FK, file_path, submitted_at, file_id,  -- file_id: reused
         PRIMARY KEY (date, tg_id))                          -- resubmit = UPSERT
knocks  (date, tg_id, target_id, knocked_at,                 -- one knock each
         PRIMARY KEY (date, tg_id))                          -- (§11a), movable
collage_cells (date, idx, tg_id,                             -- frozen mosaic order
         PRIMARY KEY (date, idx))                            -- the carousel walks
ratings (date, tg_id, value TEXT, rated_at,                  -- fire|like|meh
         PRIMARY KEY (date, tg_id))                          -- revote = UPSERT
collage_messages (date, tg_id, message_id,                   -- per-user copy of the
         PRIMARY KEY (date, tg_id))                          -- collage, for live tallies
proof_asks (date, tg_id, round_no, message_id, asked_at,     -- pre-publish check (§4a);
         value TEXT, note, voted_at,                         -- value: approve|ban,
         PRIMARY KEY (date, tg_id))                          -- NULL until they decide
week_cards (week_end, tg_id, days, streak, status TEXT,      -- one perfect week
         file_id, offered_at, decided_at,                    -- (§12b); status:
         PRIMARY KEY (week_end, tg_id))                      -- offered|shared|kept
feedback    (id PK, tg_id, text, created_at)
suggestions (id PK, tg_id, text, status TEXT, created_at)    -- pending|approved|dismissed
```

## 11a. "Knock, knock" — the group picks the story of the day

Choosing whose photo gets asked used to be Nikita's taste alone (`/askstory N`).
Now the room nominates, and the machinery it feeds is the one §12a already
describes.

**Not a like.** Under the published collage sits one button, English for
everyone — `🚪 Knock, knock, who's there...` — a nursery rhyme rather than an
instruction, so it lands as the surprise it is. Tapping it opens a carousel of
the day's photos; you knock on the one whose story you want. Four things keep it
from being a like: it is addressed to a *person*, not to content; you get
**one** knock; there is **no live tally**, so nobody can bandwagon; and the
author's name only surfaces if they choose to answer.

**Why a carousel and not numbers.** Numbers drawn on the collage are ugly, and
two attempts at a numberless "shadow" keyboard mirroring the mosaic rows were
built and rejected in testing (`scripts/knock_lab.py` keeps both): Telegram
gives every button in a row the same width, so the strip never quite lines up
with photos of different aspect ratios. Flipping through the actual photos needs
no mapping at all.

**Cost.** A flip is one `editMessageMedia` referencing a stored `file_id` — no
image work, no upload. Measured: **3 ms CPU and ~100 ms latency per flip**, and
zero added RAM. `photos.file_id` is captured at submission, so a reader never
waits for an upload. This also retired the hi-res zoom companion for readers
(they can look closely in the carousel); it survives on `/preview` as the
admin's moderation aid.

**Nothing leaks.** The card carries no name, no filename (submissions are stored
as `u<telegram_id>.jpg`), and no position in the mosaic. Revealing the author is
the prize.

**The window** opens when the collage is published and closes at **12:00 the
next day**. Knocking is restricted to that day's submitters, never on your own
photo, and a knock can be *moved* while the window is open.

**Resolution is manual.** `/knocks [date]` prints the ranked tally, then the
leader as a picture captioned with their number, name and knock count. Tied
leaders come as a carousel — `‹ · 💬 Ask this one · ›` — so the choice is made
by looking at the photographs, not at a number. 💬 fires the existing
`/askstory` flow for that author; a copyable `/askstory <date> ` stem covers
reaching any other door.

The mosaic order is frozen into `collage_cells` at publish time. It used to be
derived from `hash(date)`, which Python salts per process — a collage rebuilt
after a restart would silently rearrange itself under anyone mid-flip; the seed
is now `crc32`.

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

## 12b. The week card — a streak leader, and a gift for everyone else

Every Sunday afternoon the people who showed up get their own week back as one
picture: their photos, in the order they were taken, on the collage's mat with
the collage's type. For the author it's a keepsake of the thing they showed up
for; for the group — if it's ever shown — it's the one view the daily collage
can never give: a week seen through one pair of eyes.

**One crown, many gifts.** The card goes to everyone with at least
`WEEK_MIN_PHOTOS` (5) of the window's days, but only the **streak leader** is
congratulated and asked whether the group should see theirs. Everyone else's
card carries *no buttons at all* — it's a gift, not a nomination, so there is
nothing to decide and nothing to feel second about. That split is what lets a
single winner exist without turning the other thirteen cards into consolation
prizes: they are not being ranked, they are being handed their own week.

**Ties rotate.** Two people who never miss are level forever, so a fixed
tie-break would crown one of them every single week and never once name the
other. Among everyone on the longest streak the crown therefore goes to whoever
was crowned **least recently** (never > longest ago), then the fuller week, the
longer history, and finally the id — always exactly one person, and over time
each of them gets their turn. Gift cards don't count as a crown.

**Days, not dates.** The window counts *collage days* inside the last seven
calendar days, so a skipped or empty day can't cost anyone their week; a week
with fewer than `WEEK_MIN_DAYS` (4) collage days is skipped entirely, because a
week that barely ran isn't a week worth handing anybody back. A card drawn from
a partial week says so: chips light up for the days that were filled and stay
dark for the ones that weren't, and the title drops from "the whole week" to
plainly "their week".

**The author decides.** The leader's card is sent to them alone, with «show
everyone» / «keep it». Only a tap on the first sends it to the rest of the game,
captioned with their streak and *"shared with the author's blessing"*. So the
public part of this is public consent, not a public congratulation nobody asked
for — the same instinct as §11a, where revealing the author is the author's to
give. `week_cards.status` (offered → shared | kept, or `gift` for everyone else)
is the record; the update is guarded on `status='offered'`, so a double tap
can't publish a week twice and a forged callback on a gift card decides nothing.
The shared copy is sent by `file_id`, so it costs no second upload.

**Timing.** `week_card_dow` @ `week_card_time` (default Sun 17:00), from the
same one-minute tick as everything else, and the window ends **the day before**
the run — so Sunday reads the week Sun–Sat and that morning's still-open
submissions are none of its business. It also keeps the card from naming the
author of a photo whose knock window (§11a) is still running: Saturday's knocks
close at Sunday noon, five hours before the card goes out. The job compares
against the last scheduled moment rather than "is it Sunday now?", so a weekend
reboot makes it run late instead of never; on first deploy it arms itself rather
than retro-celebrating a week that ended before the feature existed.

**Admin.** `/weekcard` (who qualifies, sends nothing), `/weekcard send [date]`,
`/weekcard me [date]` (only your own — the safe way to look at one), `/weekcard
reset [date]`, `/weekcards [date]` (what each author decided).
`scripts/weekcard_lab.py` rehearses the whole thing against a copy of the real
data: `render` writes every qualifying card to disk, `live` runs the real
handlers on the test bot with both fan-outs narrowed to one chat.

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
