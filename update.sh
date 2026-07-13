#!/bin/sh
# photobot auto-deploy — run on the NAS by DSM Task Scheduler (as root) every
# few minutes. Fetches from GitHub and, only when there are new commits,
# deploys them: container restart for code-only changes, full rebuild when
# requirements.txt / Dockerfile / docker-compose.yml changed.
# Exits silently when already up to date, so frequent scheduling is cheap.
# One-time setup: see "Updating on the NAS" in README.md.

PATH=/usr/local/bin:/usr/bin:/bin:/sbin
ROOT=/volume1/docker/photobot
LOGFILE="$ROOT/deploy.log"
BRANCH=main

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >>"$LOGFILE"; }

compose() {
    if command -v docker-compose >/dev/null 2>&1; then
        docker-compose "$@"
    else
        docker compose "$@"
    fi
}

main() {
    cd "$ROOT" || exit 1

    # Task Scheduler runs as root while the repo files may be owned by the
    # DSM user; without this newer git refuses with "dubious ownership".
    git config --global safe.directory "$ROOT" 2>/dev/null

    git fetch --quiet origin "$BRANCH" || { log "git fetch failed"; exit 1; }

    local_rev=$(git rev-parse HEAD)
    remote_rev=$(git rev-parse "origin/$BRANCH")
    [ "$local_rev" = "$remote_rev" ] && exit 0

    # keep the log from growing forever
    if [ -f "$LOGFILE" ] && [ "$(wc -l <"$LOGFILE")" -gt 1000 ]; then
        tail -n 500 "$LOGFILE" >"$LOGFILE.tmp" && mv "$LOGFILE.tmp" "$LOGFILE"
    fi

    changed=$(git diff --name-only "$local_rev" "$remote_rev")
    log "deploying $(git rev-parse --short "$local_rev") -> $(git rev-parse --short "$remote_rev")"
    log "changed: $(echo "$changed" | tr '\n' ' ')"

    # Overwrite the working tree with the pushed state. .env, data/ and
    # deploy.log are gitignored/untracked, so reset never touches them.
    git reset --hard "origin/$BRANCH" >/dev/null || { log "git reset failed"; exit 1; }

    # Version stamp for the bot: on startup it DMs the admins when the commit
    # changed, and /version reports it. `build` = commit count = free
    # monotonically increasing build number.
    {
        echo "commit=$(git rev-parse --short HEAD)"
        echo "build=$(git rev-list --count HEAD)"
        echo "subject=$(git log -1 --pretty=%s)"
        echo "deployed_at=$(date '+%Y-%m-%d %H:%M:%S')"
    } >data/deploy_info

    if echo "$changed" | grep -qE '^(requirements\.txt|Dockerfile|docker-compose\.yml)$'; then
        log "dependency/docker change -> full rebuild"
        compose up -d --build >>"$LOGFILE" 2>&1 || { log "rebuild FAILED"; exit 1; }
    else
        log "code-only change -> container restart"
        docker restart photobot >/dev/null || { log "restart FAILED"; exit 1; }
    fi
    log "done."
}

# update.sh may overwrite ITSELF during git reset; wrapping all logic in
# main() means the shell has already parsed the whole file before any of it
# runs, so a mid-run self-update can't corrupt execution.
main "$@"
