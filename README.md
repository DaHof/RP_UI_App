# RP_UI_App

Touchscreen UI for a PN532-based NFC tool on Raspberry Pi.

## Quick start (mock mode)

```bash
cd /workspace/RP_UI_App
python3 -m pip install --upgrade virtualenv
python3 -m virtualenv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 src/main.py
```

The UI starts in mock mode and includes a **Simulate Tag** tool for testing the flow.

## PN532 (I2C) setup

Install Adafruit CircuitPython PN532 and dependencies:

```bash
python3 -m pip install -r requirements.txt
```

If you see `No module named 'lgpio'`, ensure `lgpio` is installed (it is included in `requirements.txt`).
If you see `cannot open gpiochip`, run as a user with GPIO access (e.g., add to the `gpio` group or run with `sudo`).
If you see `No module named 'board'`, make sure you are using the same virtualenv where `adafruit-blinka` is installed (e.g., `sudo -E env PATH=\"$VIRTUAL_ENV/bin:$PATH\" PN532_READER=adafruit python3 src/main.py`).

Run with the hardware reader:

```bash
PN532_READER=adafruit python3 src/main.py
```

### I2C bus sanity check (pins 3/5)

The Raspberry Pi I2C header pins **3 (SDA)** and **5 (SCL)** map to **I2C bus 1**.
If you see messages like "No hardware on I2C 3,2" or "Valid i2c ports 1,3,2 0,1,0 10,45,44",
use `i2cdetect -l` to list buses and then scan **bus 1**:

```bash
sudo i2cdetect -l
sudo i2cdetect -y 1
```

You should see the PN532 address (often `0x24` or `0x48`) on bus 1 when the board is set to I2C
and wired to pins 3/5.
If you get `Error: Could not open file /dev/i2c-1`, enable I2C in the boot config and confirm your
user is in the `i2c` group (or run with `sudo`). On Raspberry Pi OS and Kali, this is typically:

```
dtparam=i2c_arm=on
```

Add it to `/boot/config.txt` or `/boot/firmware/config.txt` (location varies by image), then reboot.
Note: `i2cdetect` is a system tool (from `i2c-tools`) and does **not** come from the Python
virtualenv. Run it outside the venv, and install it if needed:

```bash
sudo apt-get update
sudo apt-get install -y i2c-tools
sudo modprobe i2c-dev
sudo i2cdetect -y 1
```

## Notes

* The library data is stored at `data/library.json`.
* Edit the UI flow in `src/ui/app.py`.

## IR (LIRC) setup (planned)

The IR UI is scaffolded and a LIRC client stub lives in `src/ir/lirc_client.py`. To prepare for
IR capture/send on Raspberry Pi with LIRC:

```bash
sudo apt-get update
sudo apt-get install -y lirc
```

If the install fails, verify the device has network access and the package lists are enabled,
then retry. On some images you may need to run `sudo apt update` first and confirm that
`/etc/apt/sources.list` (or `/etc/apt/sources.list.d/`) includes your distribution mirrors.

If you are using `ir-keytable`, you may prefer to install its dependencies instead of LIRC:

```bash
sudo apt-get update
sudo apt-get install -y v4l-utils ir-keytable
```

If `ir-keytable -p all` reports protocol errors (for example `protocol 'kaseikyo' 'sony' 'samsung32' 'rc6' not found`),
the IR driver for your receiver only supports a subset of protocols. Use `ir-keytable -p` with an explicit list of
supported protocols from `ir-keytable -p` (no args) or `ir-keytable --protocols`, or update your kernel/v4l-utils to
gain wider protocol support. Transmitting with `ir-ctl` does not require enabling receive protocols via
`ir-keytable -p` if you only need to send signals.

### IR wiring (V1221/V1222)

Default wiring targets the following Raspberry Pi pins (configurable in the UI Settings screen):

* Transmitter (V1221): GND → Pin 6 (GND), VCC → Pin 2 (5 V), DAT → GPIO18 (Pin 12)
* Receiver (V1222): GND → Pin 6 (GND), VCC → Pin 1 (3.3 V), OUT → GPIO23 (Pin 16)

LIRC uses `/etc/lirc/lircd.conf` for remote definitions and `/etc/lirc/lirc_options.conf`
for device configuration. Once configured, you can list remotes and send commands with:

```bash
irsend LIST "" ""
irsend SEND_ONCE <remote_name> <button_name>
```

### LIRC kernel overlays (gpio-ir)

For Raspberry Pi GPIO-based IR, add the overlays in `/boot/config.txt` (or the relevant boot
config for your image) and reboot:

```ini
dtoverlay=gpio-ir,gpio_pin=23
dtoverlay=gpio-ir-tx,gpio_pin=18
```

(`gpio_pin` wants the BCM GPIO number from the wiring table above -- GPIO23
for the receiver, GPIO18 for the transmitter -- not the header pin number.)

After rebooting, confirm the LIRC device node is present:

```bash
ls -l /dev/lirc*
```

## Bluetooth (BlueZ) setup (planned)

The Bluetooth UI is scaffolded and a BlueZ client stub lives in `src/bluetooth/bluez_client.py`.
To prepare for scanning/pairing and audio playback:

```bash
sudo apt-get update
sudo apt-get install -y bluez bluez-tools pulseaudio-module-bluetooth
```

BlueZ can be controlled with `bluetoothctl` for scan/pair/trust/connect. Example:

```bash
bluetoothctl
# inside bluetoothctl
power on
agent on
default-agent
scan on
pair <MAC>
trust <MAC>
connect <MAC>
```

## Deploy to Raspberry Pi (Option A: clone on the device)

```bash
git clone <your_repo_url> ~/RP_UI_App
cd ~/RP_UI_App
python3 -m pip install --upgrade virtualenv
python3 -m virtualenv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 src/main.py
```

For the **web dashboard** specifically (rather than the Tkinter app above),
`scripts/setup-pi.sh` does the equivalent of this plus the dashboard's own
dependencies, its systemd service, and the sudo rule the update scripts below
need -- one command on a Pi that has nothing on it yet:

```bash
curl -fsSL https://raw.githubusercontent.com/DaHof/RP_UI_App/main/scripts/setup-pi.sh | bash
```

Every step checks before it acts, so it's also safe to re-run later. See its
own header for what each step does, and for running it against a fork or a
non-default branch.

`setup-pi.sh` only installs the dashboard process -- it deliberately does not
touch the external tools the tiles launch (GNU Radio, Kismet, GQRX, ...),
which otherwise show as "absent" until installed. `scripts/install-tools.sh`
covers those in one pass, including Kismet/Wifite (monitor mode, deauth,
cracking -- a deliberate `sudo` run, not something bundled silently) and the
I2C/IR/Bluetooth system enablement the builtin tiles need:

```bash
sudo ./scripts/install-tools.sh
```

See its own header for exactly what it installs and what it skips (Proxmark3
is built from source upstream, not apt-installed here).

### Updating

Three ways to get a later commit onto a Pi that's already set up, from
least to most hands-off:

* **By hand**, over SSH or on the device directly: `./scripts/pipui-update.sh`.
  Fetches, fast-forwards (never force -- a non-fast-forward stops and tells you
  to sort it out rather than discarding anything), reinstalls dependencies only
  if a `requirements.txt` changed, and restarts `pipui-web` if it's running as
  a service.

* **Push-to-deploy** from your dev machine: `./scripts/deploy.ps1` pushes the
  current branch to GitHub, then SSHes in and runs the script above for you --
  one command to ship a change. Needs SSH key auth to the Pi set up already;
  see the script's own header.

* **Scheduled autoupdate**, no push required: install `scripts/pipui-update.timer`
  alongside `pipui-update.service` and the Pi checks GitHub on its own (every
  15 minutes by default). Off by default -- both unit files explain how to turn
  it on, and what it trades off (an update mid-session restarts the dashboard).

All three end up running the same script, so only `pipui-update.sh` has the
actual update logic; the other two just trigger it differently. All three also
need the passwordless-sudo rule in that script's header, since none of them
have a terminal to type a password into.

## Web dashboard

A second front end lives in `src/web/` — a FastAPI app serving a single
self-contained page. It shares the engine with the Tkinter app and does not
modify it; both can run at the same time (though only one can hold the I2C bus
if you are using the real PN532).

```bash
python3 -m pip install -r src/web/requirements.txt
python3 src/web/app.py                      # http://127.0.0.1:8080
```

It binds `127.0.0.1` only. The mock PN532 reader is the default, so everything
works with no hardware attached.

### Simulation mode

Nearly every probe the dashboard runs (`i2cdetect`, `vcgencmd`, `rtl_test`,
`pm3`, `iw`) only exists on a Pi. `PIPUI_SIM` feeds canned output through the
real parsers so the UI can be driven anywhere:

```bash
PIPUI_SIM=mixed python3 src/web/app.py      # off | pass | fail | mixed
```

### Run full screen (kiosk)

```bash
sudo apt-get install -y chromium-browser unclutter
./scripts/kiosk.sh
```

`scripts/kiosk.sh` starts the backend if nothing is already answering, waits
for it to come up (otherwise Chromium races the server and shows an error page
that `--kiosk` gives you no way to reload), disables screen blanking, and
launches Chromium full screen with a dedicated profile. Press **Ctrl+Alt+F2**
or ssh in to get out; `Alt+F4` closes it.

There is also a fullscreen button in the dashboard header, for when the page is
opened in an ordinary browser window or from a laptop.

**Start it on boot.** The two halves install separately, so you can run the API
as a service without committing to kiosk mode:

```bash
# backend as a systemd service
sed -e "s|%USER%|$USER|g" -e "s|%REPO%|$HOME/RP_UI_App|g" \
    scripts/pipui-web.service | sudo tee /etc/systemd/system/pipui-web.service
sudo systemctl daemon-reload && sudo systemctl enable --now pipui-web

# browser on desktop login
mkdir -p ~/.config/autostart
sed "s|%REPO%|$HOME/RP_UI_App|g" scripts/pipui-kiosk.desktop \
  > ~/.config/autostart/pipui-kiosk.desktop
```

Both files carry their own install notes. Nothing autostarts the Tkinter app,
so adding the kiosk will not clash with it — but do not autostart both, since
they would fight over the touchscreen.

Logs: `journalctl -u pipui-web -f`.


https://docs.flipper.net/zero/sub-ghz/read
https://github.com/flipperdevices/flipperzero-firmware/blob/dev/applications/main/infrared/resources/infrared/assets/tv.ir
