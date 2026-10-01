#!/usr/bin/env bash
# Installs the external tools and system packages this project's tiles and
# hardware probes actually need -- everything setup-pi.sh deliberately does
# NOT touch, because setup-pi.sh is scoped to the dashboard process itself,
# not the RF tool suite it launches. This is the other half: "every tile in
# the interface that isn't already handled by the normal app setup."
#
# Covers, in one pass, without asking per-tool:
#   - SDR tools:        gnuradio, gqrx, urh, sdrangel, rtl-sdr + rtl_433
#   - Wi-Fi tools:       kismet, wifite (these do monitor mode / deauth /
#                        cracking -- installing them is a deliberate choice,
#                        which is why this script asks for it explicitly
#                        rather than being folded into setup-pi.sh)
#   - Hardware enablement: i2c-tools + I2C overlay (PN532), lirc + IR overlays
#                        (the two IR modules), bluez (Bluetooth), iw +
#                        CAP_NET_ADMIN via setcap (the Network Scanner tile),
#                        group membership for i2c/gpio/dialout/bluetooth (the
#                        last one is what lets the LD2450 mmWave reader open
#                        /dev/serial0 without root)
#   - Kiosk deps:        chromium, unclutter
#   - btop, a terminal emulator (whatever provides x-terminal-emulator)
#   - Claude Code CLI:   Node.js 20.x (via NodeSource, if nothing recent is
#                        already there) + `npm install -g @anthropic-ai/claude-code`.
#                        Skipped on 32-bit ARM -- no build exists for it.
#
# NOT covered: Proxmark3. The Iceman client is built from source against a
# specific firmware, not a simple apt package -- see
# https://github.com/RfidResearchGroup/proxmark3 directly.
#
# A single missing apt package is reported and skipped, not fatal -- ARM
# repos don't always carry everything, and one gap shouldn't abort the rest.
# Every step is idempotent; re-running is safe.
#
#   sudo ./scripts/install-tools.sh
#   sudo REBOOT=1 ./scripts/install-tools.sh   # also reboot if config.txt changed

set -uo pipefail   # not -e: one failed apt-get must not stop the rest

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi
REAL_USER="${SUDO_USER:-$USER}"
export DEBIAN_FRONTEND=noninteractive

FAILED=()
apt_install() {
  echo "--- apt install: $* ---"
  apt-get install -y "$@" || FAILED+=("$*")
}

echo "Updating package lists..."
apt-get update

# --- 1. SDR tools -------------------------------------------------------------
apt_install gnuradio gr-osmosdr
apt_install gqrx-sdr
apt_install urh
apt_install sdrangel
apt_install rtl-sdr rtl-433

# --- 2. Wi-Fi tools (monitor mode / deauth / cracking) -------------------------
apt_install kismet
apt_install wifite

# --- 3. hardware enablement ----------------------------------------------------
apt_install i2c-tools
apt_install lirc
apt_install bluez bluez-tools pulseaudio-module-bluetooth
apt_install iw

usermod -aG i2c,gpio,dialout,bluetooth "$REAL_USER" 2>/dev/null || true

# Lets the Network Scanner tile (src/web/wifiscan.py) trigger `iw scan` as the
# dashboard's normal non-root user -- without this it fails with "Operation
# not permitted". Scoped to the iw binary only, not a blanket sudo rule.
IW_BIN="$(readlink -f "$(command -v iw)" 2>/dev/null || true)"
if [ -n "$IW_BIN" ]; then
  setcap cap_net_admin,cap_net_raw+eip "$IW_BIN" \
    && echo "Granted CAP_NET_ADMIN to $IW_BIN for Wi-Fi scanning." \
    || FAILED+=("setcap on $IW_BIN")
else
  FAILED+=("setcap (iw not found -- install iw/wireless-tools first)")
fi

CONFIG_TXT=/boot/firmware/config.txt
[ -f "$CONFIG_TXT" ] || CONFIG_TXT=/boot/config.txt
NEEDS_REBOOT=0
add_overlay_line() {
  local line="$1"
  if [ -f "$CONFIG_TXT" ] && ! grep -qF "$line" "$CONFIG_TXT"; then
    echo "$line" >> "$CONFIG_TXT"
    echo "Added to $CONFIG_TXT: $line"
    NEEDS_REBOOT=1
  fi
}
add_overlay_line "dtparam=i2c_arm=on"
# gpio_pin= wants the BCM GPIO number, not a header pin number. This matches
# the wiring table in README.md (receiver -> GPIO23, transmitter -> GPIO18) --
# not the README's own overlay example, which used the header pin numbers
# (16/12) instead and looks like a pre-existing documentation bug.
add_overlay_line "dtoverlay=gpio-ir,gpio_pin=23"
add_overlay_line "dtoverlay=gpio-ir-tx,gpio_pin=18"

# --- 4. kiosk / browser ---------------------------------------------------------
apt_install chromium unclutter || apt_install chromium-browser unclutter

# --- 5. misc tiles ---------------------------------------------------------------
apt_install btop
command -v x-terminal-emulator >/dev/null 2>&1 || apt_install xterm

# --- 6. Claude Code CLI ----------------------------------------------------------
# Needs a current Node -- Raspberry Pi OS's own nodejs package is usually too
# old, so this pulls Node 20.x from NodeSource if nothing recent is already
# there. No build exists for 32-bit ARM (armv7l/armhf, still the default on
# some older Pi images), so this is skipped rather than installed broken --
# a 64-bit image (aarch64) is needed for it.
ARCH="$(uname -m)"
if [ "$ARCH" = "armv7l" ] || [ "$ARCH" = "armv6l" ]; then
  echo "Skipping Claude Code -- no build for 32-bit ARM ($ARCH). Needs a 64-bit (aarch64) OS."
else
  NODE_MAJOR="$(command -v node >/dev/null 2>&1 && node -v | sed -E 's/^v([0-9]+).*/\1/')"
  if [ -z "${NODE_MAJOR:-}" ] || [ "$NODE_MAJOR" -lt 18 ]; then
    echo "Installing Node.js 20.x (NodeSource) for Claude Code..."
    if curl -fsSL https://deb.nodesource.com/setup_20.x | bash -; then
      apt_install nodejs
    else
      FAILED+=("nodejs (NodeSource setup script failed)")
    fi
  fi
  if command -v npm >/dev/null 2>&1; then
    echo "Installing Claude Code CLI..."
    npm install -g @anthropic-ai/claude-code || FAILED+=("@anthropic-ai/claude-code (npm)")
  else
    FAILED+=("@anthropic-ai/claude-code (no npm available)")
  fi
fi

echo
if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "Some packages failed to install (ARM repos don't always have" >&2
  echo "everything) -- the rest still went in. Missing:" >&2
  printf '  %s\n' "${FAILED[@]}" >&2
fi

echo
echo "Proxmark3 was skipped -- it's built from source, not apt-installed:"
echo "  https://github.com/RfidResearchGroup/proxmark3"

if [ "$NEEDS_REBOOT" = 1 ]; then
  echo
  echo "I2C/IR overlays were added to $CONFIG_TXT -- they need a reboot to"
  echo "take effect."
  if [ "${REBOOT:-0}" = 1 ]; then
    echo "Rebooting now (REBOOT=1 was set)..."
    reboot
  else
    echo "Reboot when ready: sudo reboot"
  fi
fi

echo
echo "Also needs a fresh login (or that same reboot) to take effect: the"
echo "i2c/gpio/dialout/bluetooth group membership just added for $REAL_USER."
