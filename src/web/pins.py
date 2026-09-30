"""Raspberry Pi 40-pin header map and the user's wiring assignments.

The header layout is fixed and lives here. What is *connected* to it is the
user's business, and is read from ``data/pins.yaml``. When that file is absent
we write ``data/pins.example.yaml`` once at startup, pre-filled from the wiring
the README already documents, and report ``configured: false`` so the UI can
prompt.

Generating the example at startup rather than inside the GET keeps the endpoint
free of side effects.
"""

from __future__ import annotations

import paths

try:
    import yaml

    YAML_OK = True
except Exception:                                    # pragma: no cover
    yaml = None                                      # type: ignore[assignment]
    YAML_OK = False


# (pin number, BCM name or power rail, short function label)
HEADER: tuple[tuple[int, str, str], ...] = (
    (1, "3V3", "power"), (2, "5V", "power"),
    (3, "GPIO2", "I2C1 SDA"), (4, "5V", "power"),
    (5, "GPIO3", "I2C1 SCL"), (6, "GND", "ground"),
    (7, "GPIO4", "GPCLK0"), (8, "GPIO14", "UART TXD"),
    (9, "GND", "ground"), (10, "GPIO15", "UART RXD"),
    (11, "GPIO17", ""), (12, "GPIO18", "PCM CLK / PWM0"),
    (13, "GPIO27", ""), (14, "GND", "ground"),
    (15, "GPIO22", ""), (16, "GPIO23", ""),
    (17, "3V3", "power"), (18, "GPIO24", ""),
    (19, "GPIO10", "SPI0 MOSI"), (20, "GND", "ground"),
    (21, "GPIO9", "SPI0 MISO"), (22, "GPIO25", ""),
    (23, "GPIO11", "SPI0 SCLK"), (24, "GPIO8", "SPI0 CE0"),
    (25, "GND", "ground"), (26, "GPIO7", "SPI0 CE1"),
    (27, "GPIO0", "EEPROM SD"), (28, "GPIO1", "EEPROM SC"),
    (29, "GPIO5", ""), (30, "GND", "ground"),
    (31, "GPIO6", ""), (32, "GPIO12", "PWM0"),
    (33, "GPIO13", "PWM1"), (34, "GND", "ground"),
    (35, "GPIO19", "PCM FS / SPI1 MISO"), (36, "GPIO16", ""),
    (37, "GPIO26", ""), (38, "GPIO20", "PCM DIN / SPI1 MOSI"),
    (39, "GND", "ground"), (40, "GPIO21", "PCM DOUT / SPI1 SCLK"),
)

EXAMPLE = """\
# PIP-UI wiring map. Copy to data/pins.yaml and edit to match your build.
#
# Each assignment binds a physical header pin (1-40) to a label and an owner.
# `owner` groups pins in the UI and should match a tool id where it makes sense
# (pn532, ir, ...). Values below are the defaults the README documents -- check
# them against your actual wiring before trusting the display.

assignments:
  - pin: 1
    label: PN532 VCC
    owner: pn532
  - pin: 3
    label: PN532 SDA
    owner: pn532
  - pin: 5
    label: PN532 SCL
    owner: pn532
  - pin: 6
    label: PN532 GND
    owner: pn532

  - pin: 2
    label: IR TX VCC (5V)
    owner: ir
  - pin: 12
    label: IR TX data (GPIO18)
    owner: ir
  - pin: 16
    label: IR RX out (GPIO23)
    owner: ir

  # Add your own, for example a status LED or a hardware button:
  # - pin: 11
  #   label: Status LED
  #   owner: system
"""


def ensure_example() -> None:
    """Write the example file once, if no real config exists."""
    if paths.PINS_YAML.exists() or paths.PINS_EXAMPLE_YAML.exists():
        return
    try:
        paths.PINS_EXAMPLE_YAML.parent.mkdir(parents=True, exist_ok=True)
        paths.PINS_EXAMPLE_YAML.write_text(EXAMPLE, encoding="utf-8")
    except OSError:
        pass


def _load_assignments() -> tuple[dict[int, dict], str, bool]:
    if not paths.PINS_YAML.exists():
        return {}, "", False
    if not YAML_OK:
        return {}, "PyYAML is not installed; wiring map unavailable", False

    try:
        raw = yaml.safe_load(paths.PINS_YAML.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return {}, f"Could not parse pins.yaml: {exc}", False

    assignments: dict[int, dict] = {}
    for entry in raw.get("assignments") or []:
        if not isinstance(entry, dict):
            continue
        try:
            pin = int(entry.get("pin", 0))
        except (TypeError, ValueError):
            continue
        if 1 <= pin <= 40:
            assignments[pin] = {
                "label": str(entry.get("label", "")),
                "owner": str(entry.get("owner", "")),
            }
    return assignments, "", True


def snapshot() -> dict:
    assignments, error, configured = _load_assignments()
    pins = []
    for number, name, function in HEADER:
        assigned = assignments.get(number)
        pins.append(
            {
                "pin": number,
                "name": name,
                "function": function,
                "side": "left" if number % 2 else "right",
                "power": name in ("3V3", "5V"),
                "ground": name == "GND",
                "label": assigned["label"] if assigned else "",
                "owner": assigned["owner"] if assigned else "",
                "assigned": assigned is not None,
            }
        )
    return {
        "configured": configured,
        "error": error,
        "source": str(paths.PINS_YAML if configured else paths.PINS_EXAMPLE_YAML),
        "example_written": paths.PINS_EXAMPLE_YAML.exists(),
        "assigned_count": len(assignments),
        "pins": pins,
    }
