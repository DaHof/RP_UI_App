---
target: PIP-UI web dashboard tool layout (src/web/static/index.html) -- re-critique after fixes
total_score: 33
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 0
timestamp: 2026-10-04T06-46-07Z
slug: src-web-static-index-html
---
Method: dual-agent (A: af2508e8cf5467c07 · B: ad0b48e312ded91b4), synthesis includes a further fix batch applied after both assessments ran.

## Design Health Score

Both assessments independently verified the claimed fixes rather than taking them on faith, and both found the fixes real but incomplete. Assessment A scored **~30/40** at the moment it ran. A further batch of fixes (below) was applied immediately after, addressing most of what remained — this snapshot records both the verified baseline and what's changed since.

| # | Heuristic | Score (at assessment) | After this session's follow-up batch |
|---|-----------|------|------|
| 1 | Visibility of System Status | 3 | unchanged — hw-status LEDs confirmed real and correctly scoped (only NFC/RFID, Proxmark3, Infrared, mmWave Radar) |
| 2 | Match System / Real World | 3 | unchanged |
| 3 | User Control and Freedom | 3 | unchanged |
| 4 | Consistency and Standards | 3 | GQRX/URH icon near-duplicate fixed (URH → refresh icon) |
| 5 | Error Prevention | 3 | unchanged |
| 6 | Recognition Rather Than Recall | 2 | Simple Home is now default-on for any device with no stored preference, closing the "only fixed if Casey pre-configured it" gap A flagged |
| 7 | Flexibility and Efficiency | 3 | unchanged |
| 8 | Aesthetic and Minimalist Design | 2 | header icon buttons raised 32→44px; red `.tag.warn` contrast fixed in the one theme that missed 4.5:1 (default, 4.02→4.51:1 against `--face-hi`); night theme's separate `--ink-dim` defect B found (3.05:1, untouched by the original fix) corrected to 4.52:1; mmWave scope range labels raised 7.5px→~11px rendered |
| 9 | Error Recognition/Diagnosis/Recovery | 3 | unchanged |
| 10 | Help and Documentation | 3 | unchanged — legend is accurate but still opt-in; not re-addressed this round |
| **Total** | | **~30/40** | **Estimated ~33-34/40 — not independently re-verified; recommend one more critique pass to confirm** |

## What the two assessments confirmed vs. refuted

**Confirmed solid, no further action taken:**
- `layout-transition` fully eliminated (detector: 0 findings, both statically and via live override-injection test that exercised the actual transform math with synthetic data)
- `--ink-faint` contrast fix genuinely applied per-theme, not cosmetic (git-history diffed, default 2.79→4.53:1)
- Simple Home is real, working, correctly filtered to `simple: true` tools, exit link functional
- Badge routing (ABSENT/UNREACHABLE → red, root → neutral) confirmed both in code and in the legend's own copy
- Touch targets ≥44px confirmed via `getBoundingClientRect()` for all in-content controls (`.btn`, `.tabs`, `.pill`, `.toggle` rows) — zero stragglers found there
- hw-status LED feature confirmed scoped exactly as claimed (4 tools, not a blanket rollout)

**Refuted or found incomplete — now addressed in this session's follow-up:**
- Header icon buttons (Back, legend, fullscreen, theme) were still 32×32px, missed entirely by the original touch-target pass → **fixed, now 44×44px** (header grew 46px→48px to fit)
- Simple Home was opt-in with no on-ramp from the full grid, so the clutter problem was "only fixed for pre-configured devices" → **fixed, now the default for any device with no stored preference** (this also happens to be exactly what you asked for mid-session)
- Red `.tag.warn` badge computed ~4.0:1 against the default theme's tile background — short of the 4.5:1 the rest of the pass achieved → **fixed** (`--red` nudged #e2565c→#e4666c, the only one of 8 themes that needed it)
- A **new, previously-unflagged** contrast defect: night theme's `--ink-dim` (a different token than the one originally fixed) measured 3.05-3.16:1, visible on Diagnostics panel headers → **fixed**, #a8342b→#b95c55
- GQRX and URH shared near-identical ascending-bar icon glyphs within the same SDR category → **fixed**, URH moved to a refresh icon

**Still open, not addressed this round (flagged, not silently dropped):**
- Legend (header ⓘ) is accurate but still opt-in — nothing on first load prompts a first-timer to tap it
- Tile corner info/open-link buttons remain ~33×33px (under 44px) — constrained by the tile's own ~70-80px height; a clean fix needs a tile-height increase, not attempted here
- Header presence chips (PN532/SDR/PM3/WIFI, 10px abbreviations) have no legend coverage — jargon to a first-timer

## Persona re-check

**Jordan (first-timer):** now lands on Simple Home by default on any fresh device — the main structural complaint from the last round. Residual risk Assessment A raised still stands: Infrared's red FAIL square (this dev box has no real IR hardware) renders on her simplified screen with no inline reassurance it's expected. Worth a follow-up if this matters on the real Pi hardware too.

**Casey (imprecise/rushed tapping):** header buttons were the single worst miss-tap risk for one-handed kiosk use — now fixed at 44×44px, same floor as everything else in the app.

## Minor Observations

- Two themes (bench 4.50:1, daylight-vs-recess 4.56:1) sit right at the 4.5:1 boundary with almost no margin — fragile to any future token tweak, not broken today.
- `.mod .cmd` tile tagline text sits at ~4.59:1 — passes, but with little headroom.

Wrote `.impeccable/critique/` snapshot for this run. Full trend below.
