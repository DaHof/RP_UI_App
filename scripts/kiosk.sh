#!/usr/bin/env bash
# Run the PIP-UI dashboard full screen on the Pi's touchscreen.
#
#   ./scripts/kiosk.sh              # start the backend if needed, then Chromium
#   PIPUI_SIM=mixed ./scripts/kiosk.sh    # with synthetic hardware readings
#
# Safe to run when the backend is already up (systemd, or another terminal):
# it reuses whatever is answering on the port instead of starting a second one.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PIPUI_PORT:-8080}"
URL="http://127.0.0.1:${PORT}/"
STARTED_BACKEND=0

health() { curl -fsS --max-time 2 "${URL}api/health" >/dev/null 2>&1; }

# --- 1. backend ------------------------------------------------------------
if health; then
  echo "Backend already answering on :${PORT}"
else
  PY=""
  for candidate in "$REPO/.venv/bin/python3" "$REPO/.venv/Scripts/python.exe" \
                   "$(command -v python3 || true)"; do
    [ -n "$candidate" ] && [ -x "$candidate" ] && { PY="$candidate"; break; }
  done
  if [ -z "$PY" ]; then
    echo "No python3 found. Create the venv first (see README)." >&2
    exit 1
  fi

  # Check the deps up front. Without this a missing uvicorn only shows up as a
  # traceback, and the script then waits out the whole health-check budget for
  # a backend that already died.
  if ! "$PY" -c "import uvicorn, fastapi" >/dev/null 2>&1; then
    echo "$PY cannot import uvicorn/fastapi. Install them with:" >&2
    echo "  $PY -m pip install -r $REPO/src/web/requirements.txt" >&2
    exit 1
  fi

  echo "Starting backend: $PY src/web/app.py"
  PIPUI_PORT="$PORT" "$PY" "$REPO/src/web/app.py" &
  BACKEND_PID=$!
  STARTED_BACKEND=1
  # Only kill the backend if this script started it.
  trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM
fi

# --- 2. wait for it --------------------------------------------------------
# Without this Chromium races the server, loses, and shows its own error page --
# which in --kiosk there is no way to reload from.
for _ in $(seq 1 30); do
  # If we started it and it has already died, stop waiting -- the exit status
  # is more useful than another 20 seconds of polling.
  if [ "$STARTED_BACKEND" = 1 ] && ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "Backend exited during startup. Run it directly to see why:" >&2
    echo "  $PY $REPO/src/web/app.py" >&2
    exit 1
  fi
  health && break
  sleep 0.4
done
if ! health; then
  echo "Backend did not answer on :${PORT} within ~20s" >&2
  [ "$STARTED_BACKEND" = 1 ] && exit 1
fi

# --- 3. keep the screen awake ---------------------------------------------
if [ -n "${DISPLAY:-}" ] && command -v xset >/dev/null 2>&1; then
  xset s off -dpms s noblank || true
fi
if command -v unclutter >/dev/null 2>&1; then
  unclutter -idle 0 >/dev/null 2>&1 &
fi

# --- 4. browser ------------------------------------------------------------
# The binary is named differently across Raspberry Pi OS, Kali and Debian.
BROWSER=""
for candidate in chromium-browser chromium chromium-freeworld google-chrome; do
  if command -v "$candidate" >/dev/null 2>&1; then BROWSER="$candidate"; break; fi
done
if [ -z "$BROWSER" ]; then
  echo "No Chromium found. Install it with:" >&2
  echo "  sudo apt-get install -y chromium-browser unclutter" >&2
  exit 1
fi

# A dedicated profile keeps the kiosk away from the user's own Chromium
# session, and stops the "Restore pages?" bubble appearing after a hard power
# cut -- which on a kiosk nobody can dismiss.
PROFILE="${PIPUI_KIOSK_PROFILE:-$HOME/.pipui-kiosk}"
mkdir -p "$PROFILE"

echo "Launching $BROWSER in kiosk mode -> $URL"
exec "$BROWSER" \
  --kiosk \
  --user-data-dir="$PROFILE" \
  --window-position=0,0 \
  --window-size=800,480 \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=TranslateUI,Translate \
  --disable-translate \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --touch-events=enabled \
  --autoplay-policy=no-user-gesture-required \
  --check-for-update-interval=31536000 \
  "${URL}?kiosk=1"
