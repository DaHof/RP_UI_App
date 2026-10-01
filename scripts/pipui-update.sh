#!/usr/bin/env bash
# Pull the latest PIP-UI code onto this device and restart the service running
# it. The Pi-side half of a push-to-deploy flow -- see scripts/deploy.ps1 (or
# the one-liner in its header) for the dev-machine half that triggers this
# over SSH, and scripts/pipui-update.timer for running it on a schedule
# instead of on demand.
#
#   ./scripts/pipui-update.sh              # pull, reinstall deps if changed, restart
#   ./scripts/pipui-update.sh --no-restart # just update, leave the service alone
#
# Never force-pushes or discards anything: the pull is --ff-only, so local
# commits or edits that conflict with origin stop the script instead of being
# silently thrown away. data/pins.yaml and the other on-device config files
# aren't tracked by git at all, so they're untouched either way.
#
# The restart needs passwordless sudo for that one command -- there's no
# terminal to type a password into when this runs over SSH or from a timer:
#
#   echo "$USER ALL=(root) NOPASSWD: $(command -v systemctl) restart pipui-web" \
#     | sudo tee /etc/sudoers.d/pipui-update
#   sudo chmod 440 /etc/sudoers.d/pipui-update

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

RESTART=1
[ "${1:-}" = "--no-restart" ] && RESTART=0

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "Updating $REPO (branch $BRANCH)..."
git fetch origin "$BRANCH"

BEFORE="$(git rev-parse HEAD)"
if ! git merge --ff-only "origin/$BRANCH"; then
  echo "Not a fast-forward -- this checkout has commits origin doesn't." >&2
  echo "Resolve by hand: git status / git log --oneline HEAD..origin/$BRANCH" >&2
  exit 1
fi
AFTER="$(git rev-parse HEAD)"

if [ "$BEFORE" = "$AFTER" ]; then
  echo "Already up to date (${BEFORE:0:7})."
  exit 0
fi
echo "Updated ${BEFORE:0:7} -> ${AFTER:0:7}"

# Reinstall deps only if a requirements file actually changed in this pull --
# pip install is the slowest step here and most updates won't touch it.
PY="$REPO/.venv/bin/python3"
if git diff --name-only "$BEFORE" "$AFTER" | grep -qE '(^|/)requirements\.txt$'; then
  echo "requirements.txt changed -- reinstalling..."
  "$PY" -m pip install -r requirements.txt
  "$PY" -m pip install -r src/web/requirements.txt
fi

if [ "$RESTART" = 1 ]; then
  echo "Restarting pipui-web..."
  sudo systemctl restart pipui-web
  sleep 1
  if systemctl is-active --quiet pipui-web; then
    echo "pipui-web is active."
  else
    echo "pipui-web failed to (re)start -- check: journalctl -u pipui-web -n 50" >&2
    exit 1
  fi
fi
