# Season 3 publishing on what-do-you-see.art

The domain is an existing **Sites** project on Cloudflare, not the photobot NAS.
Its project ID is `appgprj_6a8dee6ba79c81919d1a89484f5c10ad`. Season 3
version 8, source commit `86e9d911cd6201a3cf8884453371a5ca06ee76cb`,
was deployed on 2026-10-20 as `appgdep_6ad714ece2a48191871383e97240b891`.
The live homepage has both Season 2 and Season 3 cards. The Sites source
checkout for this task is gitignored under
`data/what-do-you-see-hosted-source/`.

The actual site uses Vinext. The homepage card lives in `app/page.tsx` and
`public/styles.css`; Season 3's generated static files live in
`public/season3/`. Use explicit `index.html` URLs on this host: the tested
`/season3/` route returns 404, while `/season3/index.html` and
`/season3/private/<token>/index.html` return 200.

## On publishing day

1. Run `/season_admin`, then `/season3export` in the bot's admin chat. Use
   the new status CSV to check every Yes/No/unanswered answer. The 40 MB
   `data/season3-site-source-2026-10-19.zip` can be reused because the season
   is closed and all 77 photos were included. If its photo counts ever disagree
   with the new CSV, run `/season3siteexport` and use that new photo ZIP.
2. Rebuild with `scripts/build_season3_site.py`, a **new** output directory,
   `--template finale-lab/season3`, and the same
   `--links data/season3-site-links.json`. Only explicit Yes sequences enter
   the public gallery. No and unanswered sequences get unlisted pages, but
   unanswered links must not be sent yet.
3. Compare the build counts with `/season_admin`. Replace the entire
   `data/what-do-you-see-hosted-source/public/season3/` directory with the new
   generated output so a previously unlisted page cannot linger after its
   owner changes consent. Build the Vinext project. Save a new Sites version
   through the Sites source workflow, then deploy that version to the existing
   public Site. If consent has not changed and the website draft is unchanged,
   version 8 is already deployed; no new deployment is needed for unchanged
   consent or photos. The 2026-10-20 09:14 Berlin export matched it exactly:
   12 Yes, 1 No, and 2 unanswered among 15 eligible contributors.
4. On the real domain, check `/`, `/season2/`,
   `/season3/index.html`, and the No recipient's explicit personal URL.
   `/season3/private/` must not list links. Check a public image and a private
   image load.
5. Generate a fresh private send plan:

   ```bash
   .venv/bin/python scripts/prepare_season3_delivery.py \
     '/path/to/new-season3-1-status.csv' data/season3-delivery.csv \
     --base-url 'https://what-do-you-see.art/season3/' \
     --home-url 'https://what-do-you-see.art/' \
     --schedule-at '2026-10-20 18:00' \
     --output data/season3-send-plan.txt
   ```

6. Paste the plan's single `/season3publishat` command into the bot's admin
   chat. The bot stores it in SQLite, sends the public homepage to all active
   users at the specified Berlin time, and sends the private page only to the
   explicit No contributor. It checks the full eligible consent fingerprint
   immediately before delivery; a changed answer blocks the send and alerts
   admins. `/season3publishat status` checks it, and `/season3publishat cancel`
   cancels it before delivery begins. The plan also contains `/broadcast` and
   `/dm` as a manual fallback; never use both paths. Unanswered personal links
   stay unsent until those contributors answer.

The schedule command must be pasted into the bot before its requested send
time; generating the plan alone schedules nothing. Keep the status CSV,
identity-to-link map, and send plan under `data/`; none belongs on the website.
