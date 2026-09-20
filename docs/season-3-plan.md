# Season 3 — returning to one place

Status: implemented locally; tests and production release still required.

## Product decision

Season 3 is a 28-day, individual photographic practice. Each participant chooses
one familiar place and returns to it throughout the season, looking for something
new. One photograph may be kept per participant per Berlin calendar day; sending
another on the same day replaces it. There is no daily deadline and no minimum
required to stay in the season. The suggested rhythm is 10–15 photographs across
the four weeks.

This is its own season mode. It must not create daily collage days or reuse the
Season 2 pair-chain model. The old daily game stays paused while Season 3 runs.

## Participant lifecycle

### Existing active users

When the announcement is sent, every approved active bot user is enrolled in the
season automatically. The intro contains one button: **Sit this season out**. It
does not contain an opt-in button.

Opting out only changes membership in the current season. It does not run `/stop`,
make the user inactive, or affect future seasons. The confirmation offers a
**Join Season 3 again** button.

### New users during the season

The existing approval gate remains: a newcomer chooses a language and waits for
admin approval. As soon as they are approved, if Season 3 is announced or live,
the bot automatically enrolls them and sends the appropriate intro:

- before the start: the normal intro with the start date;
- after the start: “Season 3 is already underway. You can begin today—there is
  nothing to catch up on.”

No missed prompts or reminders are backfilled. Their reminder clock begins when
the intro is successfully delivered.

### Returning and leaving

`/stop` continues to mean “leave the whole bot.” A separate `/season` view shows
the current season, the participant's photo count and last submission, with a
button to sit out or rejoin. If an opted-out participant sends a photo, the bot
does not silently re-enroll them: it asks them to tap **Join and keep this photo**.

## Timing

1. **Announcement:** preview and send the intro manually with the intended start
   date. This also pauses the daily collage game.
2. **Start:** run the separate manual start action whenever ready. This opens
   submissions, sends a short “we begin today” note and starts the 28-day clock;
   the announced date is informative and does not start the season by itself.
3. **Practice:** 28 calendar days, with submissions accepted all day.
4. **Finish:** accept photographs through 23:59 on the final day and send a warm
   closing note the following morning.

The dates and times live in the database and are changed in-bot. Announcement
and start sends are idempotent and can be retried after a restart without
duplicating messages already delivered.

## Reminders

The season has no morning prompt. An enrolled participant receives a gentle
reminder at 19:00 only when all of these are true:

- at least 48 hours have passed since their last Season 3 photo, or since their
  intro if they have not submitted yet;
- they have not already been reminded in the last 48 hours;
- they have not opted out, stopped the bot, or become unreachable;
- they have not ignored three consecutive reminders.

After three reminders without a submission, reminders auto-pause for that person
while their season membership remains active. A new submission resets the counter.
The participant can also mute/unmute season reminders from `/season` without
leaving the season.

This avoids a possible fourteen nudges over four weeks while preserving the
intended every-second-day rhythm for people who are participating intermittently.

## Photo handling

- Route a photo to Season 3 before considering the paused daily game.
- Store originals under a season-specific directory, separate from collage and
  correspondence photos.
- Keep one row per `(season_id, tg_id, local_date)`.
- A second photo on the same Berlin date replaces the first and says so clearly.
- Albums keep only the first image, matching the existing behaviour.
- Telegram download retries and image normalization reuse the proven daily-photo
  path.
- There is no public feed, live tally, streak, ranking, collage, or participant
  access to anyone else's photographs.
- At season end, photos remain private until the organizer deliberately publishes
  or shares the final work.

Every successful first submission receives a short, warm acknowledgement written
in the bot's own voice. Replacements receive only the replacement confirmation.

## Suggested intro copy

### English

> Hi, it’s been a while.
>
> I started a new job, and it’s taking a lot of my attention. But I don’t want
> that to stop me from doing the things I love. So—let’s talk about Season 3.
>
> We began by noticing together and making collective collages. Then we moved
> into intimate dialogues between pairs. This time, we’re coming back to
> ourselves.
>
> For Season 3, choose one place you see every day. It could be your desk, a tree
> you pass on your commute, a window, the inside of your bag—or even a place in
> your mind that you return to daily.
>
> Each time you come back to it, look for something you haven’t noticed before
> and try to catch it in a photograph. You can send one photo a day, but you
> don’t have to do it every day: around 10–15 over the season is plenty.
>
> We’ll keep returning to our places for four weeks. At the end, I’ll make
> something from what we have seen.
>
> We begin on {start_date}. You’re already included. If you’d rather sit this
> season out, use the button below—you can always come back later.

Button: **Sit this season out**

### Russian draft

> Привет!
>
> Я начал новую работу, и сейчас она забирает много моего внимания. Но я не хочу,
> чтобы из-за этого в моей жизни не осталось места для того, что я люблю. Поэтому
 поговорим о третьем сезоне.
>
> Сначала мы учились замечать вместе и собирали общие коллажи. Потом перешли к
> камерным диалогам в парах. А теперь пришло время вернуться к самим себе.
>
> В этом сезоне выберите одно место, которое вы видите каждый день. Это может
> быть ваш рабочий стол, дерево по дороге на работу, окно, содержимое вашей сумки — или
> даже место внутри себя, куда вы возвращаетесь изо дня в день.
>
> Возвращаясь к нему, попробуйте каждый раз заметить что-то новое и поймать это
> в фотографии. Можно присылать по одному снимку в день, но не обязательно делать
> это ежедневно: 10–15 фотографий за сезон будет вполне достаточно.
>
> Мы будем возвращаться к своим местам четыре недели. А в конце я соберу что-то
> из того, что нам удалось увидеть.
>
> Начинаем {start_date}. Вы уже участвуете. Если в этот раз хочется пропустить
> сезон, нажмите кнопку ниже — вернуться можно будет в любой момент.

Button: **Пропустить этот сезон**

The Russian text needs a final human tone pass before release.

## Acknowledgements

Plain acknowledgements should carry most of the flow, for example:

- “I have it. Another small piece of your place is safe with me.”
- “Photo {count}. The place is the same; the seeing has changed.”
- “Kept. Thank you for looking again.”
- “Something new in somewhere familiar. I have it.”
- “Saved. See you here again when something catches your eye.”

## Admin surface

`/season_admin` is the normal Season 3 operating surface. It should show a small
button-based dashboard:

- **Season status** — phase, dates, day N/28, total photos, photos today, active,
  opted out, reminder-muted, auto-paused and unreachable counts.
- **Participants** — one line per person: name, photo count, last photo date,
  reminder state and membership state; quietest/most recent first toggles are
  unnecessary.
- **Send message** — bilingual message to current Season 3 participants.
- **Export** — CSV manifest plus a season archive organized by participant and
  date; never changes or deletes stored photos.
- **Settings** — start/end date, reminder time and reminder interval.
- **Finish season** — preview recipient counts, then require explicit
  confirmation.

The bot should send the admin one automatic weekly summary and immediate alerts
only for actionable failures (for example, a broadcast that could not reach some
users). It should not send a notification for every participant photo.

Suggested typed commands behind the buttons:

```text
/season_admin
/season3announce YYYY-MM-DD [yes]
/season3start yes
/season3people
/season3broadcast <EN> | <RU>
/season3export
/season3finish yes
```

The `season3…` names avoid colliding with Season 2 recovery commands, which stay
available but hidden from Telegram's command menu.

## Command cleanup

The problem is primarily discoverability, not executable handlers. Do not delete
working recovery tools immediately. Remove them from the visible menu and normal
help, keep them as hidden compatibility commands for one release, and delete only
after a production cycle without use.

### Participant menu during Season 3

Keep only:

```text
/season   current season, progress, reminders, leave/rejoin
/lang     language
/feedback send a private note to the organizer
/stop     leave the bot entirely
```

`/start` remains functional but need not occupy a menu slot. Hide `/today`,
`/reminders` and `/suggest_prompt`; they belong to the daily-prompt game. Their
handlers can remain as compatibility aliases with a Season 3-aware explanation.

### Admin menu

Keep visible:

```text
/admin
/season_admin
/status
/users
/pending
/dm
/broadcast
/errors
/version
```

Add the five Season 3 operations above to `/season_admin`, mostly as buttons
rather than Telegram command-menu entries. Keep `/admin` as the small general
system and archive dashboard.

Archive from normal help while Season 3 runs:

- prompt queue and daily controls: `/prompts`, `/exportprompts`, `/addprompt`,
  `/setru`, `/delprompt`, `/times`, `/settimes`, `/forceprompt`, `/skipday`,
  `/pause`, `/resume`;
- collage moderation/proofing: `/preview`, `/exclude`, `/include`, `/ban`,
  `/forcecollage`, `/delcollage`, `/proofers`, `/proofer`, `/proofing`;
- collage community features: `/photos`, `/knocks`, `/askstory`, `/stories`,
  `/editstory`, `/publishstory`, `/dismissstory`, `/weekcard`, `/weekcards`;
- Season 2 correspondence machinery: all pairing, retry, publication and
  introduction commands;
- prompt suggestions: `/suggestions`, `/approve`, `/dismiss`;
- polls and surveys unless a concrete Season 3 use appears.

Keep `/kick` and `/unkick` available but hidden behind the user card in `/users`.
Keep `/stats`, renamed in the dashboard to **Archive stats**, so it is not confused
with live Season 3 progress. Replace `/feedback_all` with a **Feedback** button in
`/admin`. Remove the enormous `/shortcuts` response and route `/shortcuts` to the
small general `/admin` dashboard instead; retain `/shortcuts legacy` for emergency
discovery during one compatibility release.

## Reliability and test rehearsal

Before production release, the following must pass on the private test bot:

1. Existing active users receive one intro; opted-out, pending, inactive and
   kicked users do not.
2. Opt-out and rejoin survive a restart and never change global user status.
3. A late-approved user receives the live intro once and can submit immediately.
4. One photo is stored per local date; replacement is explicit and does not
   increment the season count.
5. Reminder eligibility is correct at 47:59 and 48:00, after restart, after
   submission, after mute, and after three ignored reminders.
6. Intro, start, reminder, weekly admin report and finish sends are idempotent.
7. A Telegram failure for one recipient does not stop the remaining fan-out and
   appears in admin status.
8. Daily collage and Season 2 routing cannot claim a Season 3 photo.
9. End-of-season export contains every database row and every existing file, and
   reports missing files without crashing.
10. The accelerated rehearsal can compress announcement, start, reminders and
    finish into minutes without using different production code paths.

## Deliberately deferred

Music is a good fit but should not be automated in the first release. A wrong or
broken link, regional availability and message frequency add avoidable operational
surface. For this season, use the bilingual Season 3 broadcast action to send a
carefully chosen track manually once or twice. If it feels valuable, a curated
local track list and its own cadence can be added later.
