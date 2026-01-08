# RP_UI_App

Touchscreen UI for a PN532-based NFC tool on Raspberry Pi.

## Quick start (mock mode)

```bash
cd /workspace/RP_UI_App
python3 -m venv .venv
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

Run with the hardware reader:

```bash
PN532_READER=adafruit python3 src/main.py
```

## Notes

* The library data is stored at `data/library.json`.
* Edit the UI flow in `src/ui/app.py`.
