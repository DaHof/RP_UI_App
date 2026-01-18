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
supported protocols from `ir-keytable -p` (no args), or update your kernel/v4l-utils to gain wider protocol support.
Transmitting with `ir-ctl` does not require enabling receive protocols via `ir-keytable -p` if you only need to send
signals.

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
dtoverlay=gpio-ir,gpio_pin=16
dtoverlay=gpio-ir-tx,gpio_pin=12
```

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



https://docs.flipper.net/zero/sub-ghz/read
https://github.com/flipperdevices/flipperzero-firmware/blob/dev/applications/main/infrared/resources/infrared/assets/tv.ir
