# Season 3 gallery

`scripts/build_season3_site.py` builds a static gallery from the **finished**
Season 3 photo ZIP and the matching `season3-<id>-status.csv` sent by
`/season3siteexport`. The ZIP contains only this season's photos and a minimal
database, so the full bot backup is unnecessary.
Run it after checking the consent counts in `/season_admin`:

```bash
.venv/bin/python scripts/build_season3_site.py \
  '/path/to/season3-1-site-source.zip' '/path/to/season3-1-status.csv' \
  --output data/season3-site-build-1 \
  --links data/season3-site-links.json \
  --template finale-lab/season3 \
  --base-url 'https://what-do-you-see.art/season3/'
```

The output directory is the static web root. It must be **new** on every build;
the script refuses to replace an existing directory. The `--links` file is
reused across builds so personal links stay stable. Keep it outside the web
root and out of Git. `season3-delivery.csv` is written next to it and maps
Telegram IDs to their public or personal URL; it is also private admin data.

The root gallery contains only sequences whose status is `yes`. Contributors
with `no` or no answer get one unlisted page each under a random path. Each
private page contains only its own sequence; its photos are inside that random
path, use anonymous filenames, and are stripped of EXIF. One-photo submissions
are not published. Unlisted pages deter casual browsing but are not access
control: someone who has a link can share it. They use `noindex`, but that is
not a privacy guarantee.

Upload the generated web root as a **complete replacement**. Do not merge it
into an older upload: if someone changes their answer to Yes, their old
personal page must be removed. The generated `/private/index.html` prevents
directory listing of personal URLs on simple static servers.

Publishing the static directory and sending the links are separate actions.
After hosting, use `scripts/prepare_season3_delivery.py` with the latest status
and delivery CSV plus the real HTTPS gallery URL; it writes a private copy/paste
plan. The bot's `/season3publishat` command schedules the public homepage for
all active users, including people who did not participate, and the personal
page for the explicit No contributor. It checks consent again when it sends.
Rebuild and republish if a contributor changes their answer after initial
publication.

## Publishing day

1. Run `/season_admin` and `/season3siteexport` in the admin chat to get the
   latest consent status and season photo ZIP. Rebuild into a **new** output
   directory with the same `--links` file. Check the Yes, No, and unanswered
   counts. The site builder gives an unlisted page to each No or unanswered
   contributor with at least two photos; only Yes pages appear in the public
   gallery.
2. For the actual `what-do-you-see.art` site, follow
   `docs/season3-publishing.md`: replace its `public/season3/` directory, build
   and deploy a Sites version. The optional `package_season3_website.py` ZIP
   is for a plain static host and is not the deployment format of this Site.
3. Prepare copy/paste Telegram commands using the real public gallery URL:

   ```bash
   .venv/bin/python scripts/prepare_season3_delivery.py \
     '/path/to/season3-1-status.csv' data/season3-delivery.csv \
     --base-url 'https://what-do-you-see.art/season3/' \
     --home-url 'https://what-do-you-see.art/' \
     --schedule-at '2026-10-20 18:00' \
     --output data/season3-send-plan.txt
   ```

4. Review `data/season3-send-plan.txt`, then paste its one
   `/season3publishat` command into the admin chat before the chosen time.
   `/season3publishat status` checks it; `/season3publishat cancel` cancels
   it before sending begins. The plan also contains `/broadcast` and `/dm`
   commands as a manual fallback; use only one delivery path. Unanswered
   contributors are listed separately and are held for an explicit decision.
