# photobot — daily photo-prompt Telegram bot

Bot: @what_do_you_see_bot · GitHub: kaydanych/what-do-you-see-bot ·
Full design in `DESIGN.md`, ops/setup in `README.md`.

## Commands
```bash
.venv/bin/python -m photobot.main                 # run locally (long polling)
.venv/bin/python -m pytest tests/                 # tests
```

## Gotchas
- Secrets live in `.env` (`BOT_TOKEN`, `ADMIN_IDS`) — never commit, never
  print the token.
- `data/` holds the SQLite DB + photos; it survives rebuilds and is the only
  thing to back up. Don't wipe it casually.
- Schedule times (prompt/reminder/deadline/collage) are stored in the DB and
  changed via admin chat commands (`/settimes`), not in code — no restart
  needed.
- User-facing strings are bilingual RU|EN in `strings.py`; prompts use the
  `RU | EN` pipe format.
- Currently runs locally; Synology NAS deploy (docker-compose) is planned but
  not done yet.
