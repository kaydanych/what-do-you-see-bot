#!/bin/sh
# Pull the latest code from git and rebuild the photobot container.
# Run from the NAS:  sudo /volume1/docker/photobot/update.sh
# (Container Manager's docker socket is root-owned, hence sudo.)
set -e
cd "$(dirname "$0")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

log "pulling latest code..."
git pull --ff-only

log "rebuilding container..."
docker compose up -d --build

log "done."
