# photobot — daily photo-prompt Telegram bot

Bot: @what_do_you_see_bot · GitHub: kaydanych/what-do-you-see-bot ·
full product design in `DESIGN.md`, overview and setup in `README.md`, NAS
runbook in `docs/deploy-synology.md`.

## Production topology

- GitHub `main` is the source of truth for code. A commit and push is the
  production release action.
- The Synology NAS is the runtime and persistent data home. Its Container
  Manager project lives at `/volume1/docker/photobot`.
- A DSM Task Scheduler job runs `update.sh` every five minutes. It pulls
  `origin/main`, then restarts the container for code-only changes or rebuilds
  it when Docker or dependency files changed.
- Telegram is the product and admin surface. The NAS container communicates
  through long polling; no inbound application port is exposed.
- Never edit production code on the NAS: `update.sh` uses `git reset --hard`.
  The gitignored `.env` and `data/` directory are production-local state.

## Commands

```bash
.venv/bin/python -m photobot.main                 # run locally (long polling)
.venv/bin/python -m pytest tests/                 # tests
```

## Gotchas

- Secrets live in `.env` (`BOT_TOKEN`, `ADMIN_IDS`) — never commit them and
  never print the token.
- `data/` holds the SQLite DB and photos. It survives rebuilds, is the only
  production data to back up, and must not be wiped casually.
- Schedule times are stored in the DB and changed via `/settimes` in the admin
  chat, not in code. Changes apply within a minute without a restart.
- User-facing strings are bilingual RU/EN in `photobot/strings.py`. Prompt,
  poll and translated-story inputs use `EN | RU` (English primary/fallback),
  matching `parse_prompt_line`.
- Preserve the closed-circle privacy model: pending users receive no game
  content; daily collages go only to that day's submitters plus admins.
- Deploy only through a reviewed commit and push to `main`; the NAS will pick
  it up automatically.
