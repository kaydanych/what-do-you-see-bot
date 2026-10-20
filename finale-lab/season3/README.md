# Season 3 gallery

This is the exhibition design Nikita chose: anonymous places, each opening into
a chronological photographic sequence. It keeps the Season 2 dark palette and
serif typography, with RU/EN text, keyboard navigation, responsive photographs,
and a sticky next-place control.

Open `index.html` directly to see the current **public** collection. Its
`season-data.js` and `assets/` contain only the 12 explicitly consented
sequences (63 photographs), including the October 19 submission. The old
all-participant design snapshot is saved at `../season3-draft-snapshot/` and
must not be published.

## Complete local preview

The generated static web root is `data/season3-publish-preview-v2/`. It adds
three separate unlisted personal pages for the No and unanswered contributors;
one-photo contributors have no page. It is currently served at
<http://127.0.0.1:4174/>. Each personal page opens directly into that person's
sequence and has no navigation to other people. The private pages use random
paths, anonymous image filenames, stripped EXIF, and `noindex`. A person with
the link can still share it.

The actual hosted Vinext site preview is <http://127.0.0.1:4176/>; its Season 3 pages use
explicit `/season3/index.html` URLs. Version 8 is deployed on
<https://what-do-you-see.art/>. The 2026-10-20 09:14 Berlin consent export
matched the live gallery: 12 Yes, 1 No, and 2 unanswered eligible contributors.
Follow `docs/season3-publishing.md` for later consent changes and delivery.

To rebuild from a fresh photo ZIP and status CSV, run
`scripts/build_season3_site.py` with `--template finale-lab/season3` and a new
`--output` directory. Keep `--links` outside the web root so personal URLs
remain stable across builds. Publish **only the generated web root**, after
checking the latest consent choices. The link map and delivery CSV under
gitignored `data/` are private admin files.
