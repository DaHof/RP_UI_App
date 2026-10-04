# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary — the operator (technical).** Runs hands-on hardware/RF work at a physical workbench: reading and cloning NFC/RFID tags, Proxmark3 LF/HF research, capturing and replaying IR remotes, Bluetooth pairing, mmWave presence sensing, and a defined set of SDR/Wi-Fi tools (GNU Radio, GQRX, URH, SDRangel, rtl_433, Kismet, Wifite). Needs fast, unambiguous access to the full tool set and real hardware status at a glance, without digging through terminals.

**Secondary — a non-technical household user (durable persona).** Uses a small, fixed set of everyday tools only: scanning/reading an NFC tag, controlling a TV/AC over IR, and pairing Bluetooth devices. Has no interest in and should never need to understand the rest of the dashboard (SDR tools, Proxmark3, diagnostics, GPIO wiring). This is an ongoing audience, not a one-time accommodation — future work should keep this bar in mind by default, not just the pass that introduced it.

## Product Purpose

PIP-UI unifies a workbench's worth of otherwise-separate hardware and RF tools into one themed kiosk launcher on a Raspberry Pi touchscreen, so the operator never has to remember which terminal, app, or device controls which piece of hardware. Success is a single glance telling you what's plugged in and working, and one tap to get to it — for both the technical operator and a household member who just wants to scan a tag or change the channel.

## Positioning

Not a general-purpose home-automation or IoT dashboard. PIP-UI is purpose-built for one physical workbench's actual, specific hardware (a PN532 NFC reader, a Proxmark3 over USB, an IR transmitter/receiver wired to named GPIO pins, an HLK-LD2450 mmWave sensor, BlueZ, and an explicit allowlist of SDR/Wi-Fi tools) with a boot self-check against that real hardware and a deliberate two-tier audience split (full dashboard vs. Simple Home) baked into the same codebase. A neighboring generic dashboard product could not truthfully claim either of those.

## Operating Context

A touchscreen physically mounted at the user's workbench, running Chromium in kiosk mode on the Raspberry Pi — not accessed remotely from a phone or laptop over the LAN. The same codebase also runs in mock-hardware mode on a dev machine (this session: Windows) for development and testing. A legacy Tkinter desktop app (`src/ui/app.py`) lives in the same repo and talks to the same hardware/config; the web dashboard is the forward path and is intended to eventually replace it, though Tkinter is still functional today. PN532/mmWave/IR hardware is wired to specific documented GPIO pins (see README and the in-app GPIO Pins reference screen).

## Capabilities and Constraints

- `tools.yaml` is a strict allowlist: only a tool `id` declared there can ever be launched; `argv` is always a list, never a shell string, so nothing from a request reaches a command line. Adding a tool is a privilege decision (a config edit), not something the UI itself can do.
- Three non-`builtin` tile kinds: `launch` (a real local process this dashboard starts/stops), `service` (an externally-managed systemd unit, asked fresh from systemd every time rather than tracked in memory), and `link` (opens a URL for a tool running on a *different* physical machine — this dashboard cannot stop or verify it beyond reachability).
- Hardware channel status (PN532, Proxmark3, IR, mmWave, thermal, SDR, Wi-Fi) comes from one background health-monitor poll on a fixed cadence, never probed per-request, so a slow probe (opening a serial port, an RTL-SDR sweep) can't stall the dashboard.
- Two durable home-screen modes on the same data: the full dashboard (every tool, grouped by category, for the technical operator) and **Simple Home** (a per-device `localStorage` flag, independent of the shared server-side settings file) showing only tools marked `simple: true` as a handful of large plain tiles for the non-technical persona.
- Purely theme-token driven: 8 themes (default "Instrument Face," Night Vision, Phosphor, Amber CRT, Blueprint, Daylight, Bench Continuity, High-Contrast) swap entirely via `[data-theme]` CSS custom-property blocks — no structural CSS differs per theme, so a new theme costs a token block, not new markup.
- Undecided: whether more tools/categories get added to Simple Home over time, and whether/when the Tkinter app is formally retired rather than just fading from use.

## Brand Commitments

Product name **PIP-UI**. Explicit Fallout Pip-Boy-inspired instrument-panel aesthetic is already implemented across 8 themes and is a binding visual commitment, not a placeholder to be redesigned from scratch. No other logo, naming, or legal assets confirmed.

## Evidence on Hand

Working implementation at `src/web/static/index.html` (+ FastAPI backend in `src/web/*.py`); `src/web/tools.yaml` as the tool manifest and source of category/icon/availability truth; `README.md` with hardware wiring and deployment notes. A prior design critique is on file at `.impeccable/critique/2026-10-04T05-52-51Z__src-web-static-index-html.md` (27/40 at the time; its P0/P1 findings — text legibility/contrast, badge severity, touch-target sizing, tool clutter for the non-technical persona — have since been addressed and a re-critique is pending). No formal user research, testimonials, or usage metrics beyond the author's own and his wife's direct day-to-day use — state absence, don't fabricate either.

## Product Principles

1. **One operator, two skill levels, same device.** The full dashboard and Simple Home must both stay true to the same running hardware and data — they are two views of one product, never allowed to fork into separate products with separate truths.
2. **Never fabricate availability.** A tool whose binary or hardware is missing shows as absent/unreachable/failed, visibly and specifically — never silently hidden, and never assumed working.
3. **Legibility and plain language are not bargaining chips against the aesthetic.** The Pip-Boy theme carries the personality; body text, labels, and status badges stay readable and jargon-free regardless of which theme is active.
4. **Config is the privilege boundary, not code.** Exposing or launching a tool is a `tools.yaml` edit — a deliberate, auditable decision — never something reachable from the UI itself.
5. **Kiosk-first.** Designed to be touched on a mounted screen at arm's length by a finger, not driven by a mouse or shrunk to a phone.

## Accessibility & Inclusion

No formal, standards-based accessibility requirement has been confirmed (no stated screen-reader or motor-impairment need). The working bar instead is practical and self-imposed: a non-technical adult unfamiliar with the hardware must be able to operate Simple Home without guidance — enforced through plain language, ≥44×44px touch targets, and real (not merely thematic) contrast on body and label text, treated as a running design principle rather than a one-time fix.
