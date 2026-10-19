# Season 3 gallery

`scripts/build_season3_site.py` builds a static gallery from a **finished** NAS
backup and the latest `season3-<id>-status.csv` sent by `/season3export`.
Run it after checking the consent counts in `/season_admin`:

```bash
.venv/bin/python scripts/build_season3_site.py \
  '/path/to/photobot-backup.zip' '/path/to/season3-1-status.csv' \
  --output data/season3-site-build-1 \
  --links data/season3-site-links.json \
  --base-url 'https://your-published-site.example/'
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

Publishing the static directory and sending the links are separate actions.
The bot already has `/broadcast` and `/dm` for the final messages. Rebuild and
republish if a contributor changes their answer after the initial publication.
