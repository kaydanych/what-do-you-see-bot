<h1 align="center">📸 photobot</h1>

<p align="center">
  <b>One prompt a day. One photo each. One collage back.</b><br>
  A quiet daily ritual for a closed circle of friends.
</p>

<p align="center">
  <a href="https://t.me/what_do_you_see_bot"><b>@what_do_you_see_bot</b></a> ·
  self-hosted Telegram bot · 🇬🇧 EN / 🇷🇺 RU ·
  <a href="DESIGN.md">design notes</a>
</p>

<p align="center">
  <img src="docs/collage-example.jpg" width="560"
       alt="A daily collage: ten photos of doors, sent back as one card">
</p>

<p align="center">
  <sub><i>Day 9 — “send a photo of a door you've never opened.” Ten people, ten
  doors, one card back. This copy went out in Russian; everyone gets the
  collage in their own language.</i></sub>
</p>

---

## Where the project lives

Photobot is one production loop across **GitHub → NAS ↔ Telegram**:

1. **GitHub (`main`) is the source of truth for code.** Development happens on
   the Mac, then a commit and push publish the next version.
2. **The Synology NAS is the runtime and data home.** Every five minutes it
   checks GitHub, resets its checkout to `origin/main`, then restarts the
   container for code-only changes or rebuilds it when dependencies changed.
   Its `data/` directory holds the SQLite database and photos and never belongs
   in Git.
3. **Telegram is the product surface.** The container long-polls the Telegram
   Bot API, receives commands and photos, and sends prompts, moderation views,
   collages and community interactions back to people's chats. No inbound NAS
   ports are exposed.

In short: **push code to GitHub; let the NAS deploy it; use and administer the
running bot through Telegram.** Never edit production code directly on the NAS,
because the next deploy deliberately overwrites it.

Every morning the bot sends everyone the same tiny creative prompt. Each person
replies with **one** photo before the evening deadline. Then the bot stitches
that day's photos into a single card and sends it back — **only to the people
who played**. Next morning, a new prompt.

No feed, no likes, no strangers. Just a reason to look a little closer at an
ordinary day, and the small pleasure of seeing what nine other people found.

## A day in the life

| | |
|---|---|
| **09:00** | A prompt from the curated bilingual library goes out to everyone at once |
| all day | People send photos. A new one replaces your old one, right up to the deadline |
| **19:00** | A gentle nudge — only to whoever hasn't played yet |
| **21:00** | Deadline. Late photos are politely turned away. You get a numbered contact sheet; two or three trusted players get the finished collage and one question: anything wrong? |
| 👍 | One of them says no and it publishes itself. Most evenings end here |
| every 10 min | Nobody tapped? It rolls to the next two or three |
| your call | Or someone bans it — then you moderate (`/exclude 3`, `/preview`) and press send |
| 🎉 | Everyone who played gets the card, a row of rating buttons, and the door to knock on |

Times are Europe/Berlin, live in the DB, and change from the admin chat with
`/settimes` — no restart, applies within a minute.

## The prompts

> Send a photo of something you almost threw away
> · a shadow that looks like something else
> · the oldest thing in your pocket
> · something broken but beautiful
> · a letter or number found in the wild
> · the most boring thing near you — make it interesting

The queue lives in the bot ([`prompts.txt`](prompts.txt) is the starter set).
Add one with `/addprompt`, reorder the whole thing by exporting a `.txt` and
re-uploading it, or let players pitch their own with `/suggest_prompt` — an
approved idea ships with the suggester's name baked in.

## What's in the box

- 🖼 **A card, not a grid** — a justified mosaic that adapts to however many
  photos came in, with the date, the prompt and the day number on it
- 🔍 **Tap through the originals** — the published collage opens a private
  carousel of that day's photos. A non-recompressed hi-res card is reserved
  for admin `/preview`, where it is useful for moderation without doubling
  every participant's delivery
- ❤️ **Ratings** — a row of emoji under each collage, tallies shared live
  across every copy
- 🔥 **Streaks** — your run of consecutive days comes back the moment you
  submit, as a private well-done
- 🗓 **The week card** — Sunday afternoon your own week comes back as one
  picture, chronological, yours to keep. The longest streak in the game gets
  congratulated and asked whether the group should see theirs; a tie rotates, so
  nobody is crowned forever and nobody is named in public without saying yes
- 🚪 **Knock, knock** — flip through the day's photos under the collage and
  knock on the one whose story you want; one knock each, tallies hidden
- 💬 **Story of the day** — the bot can ask one author why they chose their
  photo, and publish the answer to the whole group — in both languages if you
  pair it with a translation, with a ❤️ readers can leave on it
- 📊 **Polls** — ad-hoc 👍/👎 questions to the whole group, with a live tally
- 👀 **Proofing** — hand the nightly check to a few trusted players instead of
  being the bottleneck: one 👍 publishes, a double-confirmed 🚫 goes to fresh
  eyes, two park it for you. The bar for banning is written down, narrow, and
  ends with "when in doubt, publish"
- 🧹 **Moderation first** — nothing is published until somebody has looked at it
- 🌍 **Per-user language** — everyone reads the bot, and gets the collage, in
  EN or RU
- 🏠 **Yours** — long polling means no open ports, and the persistent photo
  archive stays on the NAS rather than a separate hosting or storage service

## Run it

```bash
cp .env.example .env      # BOT_TOKEN from @BotFather, ADMIN_IDS from @userinfobot
docker compose up -d
```

Or without Docker:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m photobot.main
```

Then in Telegram: `/start` the bot, `/admin` lists every admin command,
`/addprompt Send a photo of water | Пришли фото с водой`, `/forceprompt` to
fire it now, send a photo, `/preview` to see the collage.

Tests: `.venv/bin/python -m pytest tests/`

> **Running it for a private circle?** Anyone who finds the bot's @name can
> knock, but nobody gets in unseen: a newcomer is held on a waiting list and you
> get their card with **✅ Approve / 🚫 Reject** buttons. Until you tap ✅ they
> receive no prompt, reminder or collage — just a note saying they're on the
> list. `/pending` brings the cards back if one scrolls away.
> For a harder line, set `ALLOWED_IDS` to a comma-separated list of user ids and
> the bot ignores everyone else outright.

## Running it day to day

`/admin` prints the full list; the ones you'll actually use:

| | |
|---|---|
| `/status` | today at a glance — prompt sent? who's in? collage pending? |
| `/pending` | newcomers waiting to be let in — ✅ / 🚫 right there in the chat |
| `/exclude N` · `/include N` · `/ban N` | moderate the contact sheet |
| `/preview` · `/forcecollage` | see it, then send it |
| `/proofers` · `/proofer @who` · `/proofing` | who checks the collage for you, and how |
| `/delcollage` | unsend a collage everywhere (Telegram allows 48 h) and reset the day |
| `/settimes` · `/times` | move the day's clock |
| `/stats` · `/users` · `/feedback_all` | who's playing, what they think |
| `/weekcard` · `/weekcards` | Sunday's week cards — who qualifies, what they chose |
| `/errors` · `/version` | last log lines, which build is running |

Every crash is DM'd to the admins with a traceback, and a tick job every minute
compares the clock to the day's state — so a reboot or a runtime schedule
change can't silently kill a day.

## Deploying

Anywhere Docker runs. In production, GitHub `main` is the code source of truth,
the Synology NAS is the runtime and persistent data store, and Telegram is the
only user/admin interface. The NAS redeploys itself after `git push`; the exact
setup is written up in
**[docs/deploy-synology.md](docs/deploy-synology.md)**.

The DB and photos live only in the NAS `data/` directory, outside both the
container image and Git. That's the only thing to back up.

## Under the hood

Python 3.12 · [`python-telegram-bot`](https://python-telegram-bot.org) v21
(async, built-in JobQueue) · Pillow for the collage · SQLite · Docker.

Full design notes, including the collage layout algorithm and the catch-up
logic, in **[DESIGN.md](DESIGN.md)**.
