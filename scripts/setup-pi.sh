#!/usr/bin/env bash
# One-shot first-time setup for a Pi that has nothing on it yet: clone, venv +
# deps, the pipui-web service, the sudo rule scripts/pipui-update.sh needs, and
# a smoke test. Every step checks before it acts, so it's also safe to re-run
# later (e.g. after a manual systemctl edit) to put things back to normal.
#
# Nothing cloned yet:
#   curl -fsSL https://raw.githubusercontent.com/DaHof/RP_UI_App/main/scripts/setup-pi.sh | bash
#   (reads before running are cheap -- `curl -fsSL ... -o setup-pi.sh && less setup-pi.sh`
#   first if you'd rather not pipe straight to bash)
#
# Already cloned:
#   cd ~/RP_UI_App && ./scripts/setup-pi.sh
#
# Override defaults with env vars, e.g. a fork or a non-default branch:
#   PIPUI_REPO_URL=... PIPUI_REPO_DIR=~/somewhere PIPUI_BRANCH=main ./scripts/setup-pi.sh
#
# This only gets the dashboard running as a service. For the touchscreen kiosk
# on top of it, run scripts/kiosk.sh afterwards (see README).

set -euo pipefail

REPO_URL="${PIPUI_REPO_URL:-https://github.com/DaHof/RP_UI_App.git}"
REPO="${PIPUI_REPO_DIR:-$HOME/RP_UI_App}"
BRANCH="${PIPUI_BRANCH:-}"

# --- 1. clone, if it isn't there already ------------------------------------
if [ -d "$REPO/.git" ]; then
  echo "Repo already at $REPO -- leaving it as is (run pipui-update.sh to update it)."
else
  echo "Cloning into $REPO..."
  git clone ${BRANCH:+--branch "$BRANCH"} "$REPO_URL" "$REPO"
fi
cd "$REPO"

# --- 2. venv + deps ----------------------------------------------------------
if [ ! -d .venv ]; then
  echo "Creating venv..."
  python3 -m pip install --quiet --upgrade virtualenv
  python3 -m virtualenv .venv
fi
echo "Installing dependencies (root + web)..."
.venv/bin/python3 -m pip install --quiet -r requirements.txt
.venv/bin/python3 -m pip install --quiet -r src/web/requirements.txt

# --- 3. pipui-web as a systemd service ---------------------------------------
echo "Installing pipui-web.service..."
sed -e "s|%USER%|$USER|g" -e "s|%REPO%|$REPO|g" \
    scripts/pipui-web.service | sudo tee /etc/systemd/system/pipui-web.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now pipui-web

# --- 4. passwordless sudo for the update script's restart step --------------
# Needed by scripts/pipui-update.sh (and anything that triggers it, like
# deploy.ps1 or the optional update timer) -- none of those have a terminal to
# type a password into.
SUDOERS=/etc/sudoers.d/pipui-update
RULE="$USER ALL=(root) NOPASSWD: $(command -v systemctl) restart pipui-web"
if [ -f "$SUDOERS" ] && sudo grep -qF "$RULE" "$SUDOERS" 2>/dev/null; then
  echo "Sudo rule already in place."
else
  echo "$RULE" | sudo tee "$SUDOERS" >/dev/null
  sudo chmod 440 "$SUDOERS"
  if ! sudo visudo -cf "$SUDOERS" >/dev/null; then
    echo "Bad sudoers syntax -- removing $SUDOERS." >&2
    sudo rm -f "$SUDOERS"
    exit 1
  fi
  echo "Sudo rule installed."
fi

# --- 5. smoke test ------------------------------------------------------------
echo "Waiting for the backend..."
for _ in $(seq 1 20); do
  curl -fsS --max-time 2 http://127.0.0.1:8080/api/health >/dev/null 2>&1 && break
  sleep 0.5
done
if curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "pipui-web is up: http://${IP:-127.0.0.1}:8080/"
else
  echo "Backend did not answer in time. Check: journalctl -u pipui-web -n 50" >&2
  exit 1
fi

cat <<EOF

Done. Next steps:
  - Try the update flow:              ./scripts/pipui-update.sh
  - Full screen on the touchscreen:   ./scripts/kiosk.sh
  - Push updates from your dev box:   scripts/deploy.ps1 (see its header)
EOF
