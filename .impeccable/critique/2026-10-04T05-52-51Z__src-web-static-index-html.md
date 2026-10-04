---
target: PIP-UI web dashboard tool layout (src/web/static/index.html)
total_score: 27
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 3
timestamp: 2026-10-04T05-52-51Z
slug: src-web-static-index-html
---
Method: dual-agent (A: a39eae5ab613324f1 · B: aa71b1e1e0084fbd7)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Builtin tiles (NFC/RFID, Proxmark3, Bluetooth, mmWave) never show a status LED/ABSENT at grid level even when hardware is absent/mocked |
| 2 | Match System / Real World | 3 | Hacker-terminal vocabulary fits the product, but default theme dilutes it |
| 3 | User Control and Freedom | 3 | Back button everywhere, root launches show the literal command before running |
| 4 | Consistency and Standards | 2 | Three unexplained tap-behaviors (`builtin`/`link`/`launch`-`service`) share no visual grammar; ABSENT/UNREACHABLE/root all render as the same neutral grey `.tag` |
| 5 | Error Prevention | 3 | Root actions confirm with real argv; dead tiles toast a specific reason instead of silently failing |
| 6 | Recognition Rather Than Recall | 3 | Taglines truncate mid-phrase, hiding operationally important info (e.g. "(Kali)" on Solar Radar) |
| 7 | Flexibility and Efficiency | 2 | No pinning/favoriting — a field tool (NFC/RFID) sits at equal weight to a setup-time tool (Settings) |
| 8 | Aesthetic and Minimalist Design | 2 | Corroborated by detector: systemic 9–10.5px text, 2.8:1 contrast on `--ink-faint` on `--face-hi`; uneven density (Diagnostics tight, NFC/Proxmark3/Network Scanner ~60% dead space) |
| 9 | Error Recognition/Diagnosis/Recovery | 4 | Best score — Diagnostics gives precise, honest per-probe reasons ("vcgencmd is Linux-only; not available on this host") |
| 10 | Help and Documentation | 2 | Per-tile info modal exists, but no legend anywhere for LED/badge meaning, no onboarding |
| **Total** | | **27/40** | **Acceptable — functions well, but legibility and clarity need real work before a non-technical user is handed this** |

## Design Specificity Verdict

**LLM assessment**: The *bones* are genuinely authored for this product — 8 named CRT-era themes (Amber CRT, Phosphor, Night Vision — with an in-code comment reasoning about dark-adapted eyes), a live CPU/presence header readout, a boot self-check splash, and LED state encoded by shape *and* color (not just color) for colorblind/mono-theme users. That's real craft. But the **default theme** everyone actually sees is a neutral dark-graphite admin palette — amber is confined to buttons/LEDs/readout text. Most users who never open Themes will experience something indistinguishable from a generic IoT dashboard. Icon reuse compounds this: the same wifi glyph on all 4 Wi-Fi tiles, the same radar glyph on mmWave Radar *and* GQRX (unrelated), gauge shared between Diagnostics and rtl_433 — on a grid whose whole value proposition is instant recognition, that's a real cost.

**Deterministic scan**: `detect.mjs` on `src/web/static/index.html` → exit 2, **2 findings**, both `layout-transition` (warning/quality): `transition: height` at line 145, `transition: width` at line 303. Both genuine — animating layout properties causes repaint thrash where `transform`/`grid-template-rows` would be cheap; corroborated live by the browser pass firing on ~20 collapsible elements per view. Token hygiene is clean: every hex literal in the file lives inside the 8 theme `:root` blocks (lines 19–84); zero leakage into component CSS. `overused-font` and `repeating-stripes-gradient` fired in the browser pass but both assessors judge them intentional (single system font + mono token reserved for code; a near-invisible 1px pinstripe texture consistent with the instrument-panel aesthetic) — treat as false positives for this context.

**Visual overlays**: The browser overlay (live-server + injected detector) ran successfully across Home/NFC/Diagnostics but its own banner stole pointer events from the app header during navigation (a tooling artifact, not a PIP-UI bug) and its visibility check doesn't account for ancestor `display:none`, so raw per-view counts (73/78/93) are cumulative-DOM noise, not real per-screen totals. The genuine, non-duplicated findings are: `undersized-ui-text` (9–10.5px body/label text is systemic across every screen), `low-contrast` (2.8:1 for `--ink-faint #666c74` on `--face-hi #242830`, confirmed against the actual token values — a real AA failure, not a one-off), and `tiny-text` on Diagnostics' status-note copy. The overlay tab was closed at the end of Assessment B, so nothing is live in your browser right now — screenshots are the record.

## Overall Impression

The engineering is careful — theme system, LED semantics, error messages, root-action confirmation are all better than most hobbyist dashboards. But the thing actively working against your stated goal (**your wife using this simply**) is legibility and clutter, not missing features: 9px text, a 20-tile home screen where 8 items live in one undifferentiated "Hardware Tools" row, and a wall of ABSENT/UNREACHABLE pentesting tools (GNU Radio, Kismet, Wifite, rtl_433, Terminal, Claude Code) she will never use and that will read as broken or intimidating. The single biggest opportunity: reduce what she sees, not redesign what's there.

## What's Working

1. **Diagnostics screen** — 4-column dense layout, specific honest failure reasons instead of generic red X's. This is the template the rest of the app should follow for information density.
2. **LED shape+color state encoding** — filled circle / hollow ring / pulsing halo / rounded square per state, deliberately chosen (in-code comment reasons about colorblind users and the mono Night Vision theme). Rare level of care for a status dot.
3. **Theme system** — 8 real, flavor-appropriate skins implemented as a clean CSS-variable swap, each with a reasoned rationale in the code, not a decorative toggle.

## Priority Issues

**[P0] Core UI text is too small and too low-contrast for a casual, non-technical user.** Tile titles ~12px, but badges, taglines, and section labels sit at 7.5–10.5px, and `--ink-faint` on `--face-hi` measures 2.8:1 — both reviewers independently confirmed this (detector math + direct screenshot read). For a wife who isn't going to lean in and squint, this is the difference between "I can use this" and "I can't read half of it." **Fix**: raise the floor — section labels and badges to ≥12px, tagline/body text to ≥13px, and either swap `--ink-faint` for a token that clears 4.5:1 on `--face-hi` or stop using it for anything that carries real meaning (status words, not just decorative dividers). **Suggested command**: `/impeccable typeset`

**[P1] The home screen shows her 20 tools, most of which she'll never touch, with no way to tell "this matters to you" from "this is a pentesting tool that's ABSENT anyway."** Hardware Tools alone is 8 items (double the ~4-item working-memory comfort zone) and mixes real field tools (NFC/RFID, Infrared) with setup-only screens (Settings, GPIO Pins) at identical visual weight. SDR (GNU Radio, GQRX, URH, SDRangel, rtl_433) and most of System (Terminal, Claude Code) will be permanently ABSENT/irrelevant to her and just add noise and "is this broken?" anxiety. **Fix**: for her use, either (a) a simple-mode toggle that shows only the 2–4 tools she actually uses, full-size, nothing else, or (b) collapse SDR/System behind a "More tools (advanced)" disclosure so the home screen she sees is short and calm. **Suggested command**: `/impeccable distill`

**[P1] Status badges don't distinguish severity, and the taxonomy is unexplained.** ABSENT, UNREACHABLE, and the informational "root" badge are all the same neutral-grey `.tag` (line ~256) — `.tag.warn` (red) exists but is only used for Wi-Fi security flags. A first-time user has no way to tell "this doesn't exist here" from "this needs a password" from "this is fine." There's also no legend anywhere for what the LED colors/shapes mean. **Fix**: route unavailability states through `.tag.warn` (already red, already built), and add a one-time or persistent tiny legend/tooltip near the header LEDs. **Suggested command**: `/impeccable clarify`

**[P1] Touch targets fall under the 44×44pt minimum everywhere except the tile itself.** `.btn` (38px), `.tabs` (32px), `.pill` (34px), and — worst — Settings' on/off switch (46×26px, and it's the *only* clickable part of its row; the label text next to it does nothing). On a touchscreen, for a user who isn't going to be precise, that's mis-taps and frustration, concentrated exactly on the one screen (Settings) that's all binary toggles. **Fix**: raise `min-height` to 44px on `.btn`/`.tabs button`/`.pill`/`input,select`, and make the entire toggle row clickable, not just the 26px switch. **Suggested command**: `/impeccable adapt`

**[P2] Icon reuse undercuts at-a-glance recognition.** Same wifi icon on all 4 Wi-Fi tiles, same radar icon on mmWave Radar and GQRX, same gauge on Diagnostics and rtl_433. For someone pattern-matching by shape rather than reading labels (exactly how a non-technical user navigates a tile grid), this removes the one shortcut that would otherwise help her. **Fix**: assign distinct icons per tool from the existing unused sprite set (antenna, signal, external, activity, etc.). **Suggested command**: `/impeccable clarify`

## Persona Red Flags

**Jordan (First-Timer)** — this is effectively your wife's persona, and it's where the app currently fails hardest. No legend anywhere for LED colors or badge meaning; three different tap-behaviors (opens a screen / launches an external window / links to another machine) with no visual cue distinguishing them ahead of the tap; Settings copy like "Wi-Fi: Kismet / Wifite tiles are not gated by this flag" assumes she already understands the gating system it's describing. She'd have to learn this by trial and error, which is exactly what you're trying to avoid.

**Casey (Distracted/thumb-use analog for "not going to be careful or patient")** — the 24×24px info/open-link icon sits flush against the much larger tile tap target, a classic mis-tap trap; Settings' 26px-tall toggle switch, the only clickable element in a touch-first screen made entirely of toggles, is the single worst control in the app for someone who isn't going to aim precisely.

## Minor Observations

- Invalid hash routes (e.g. `#pm3` instead of `#proxmark`) silently fall back to home with no error — fine for you, but would be confusing if she ever ends up on a stale bookmark/link.
- Taglines truncate mid-phrase on longer strings, and in one case ("WiFi presence sensing (Kali)") the truncated part is the operationally important bit — that tool lives on a different machine entirely, and tapping it won't do anything on this Pi. Worth fixing regardless of audience.
- The boot splash correctly lingers longer when self-checks fail rather than a fixed delay — a good honest touch, but with no indication of *which* check is slow, a first-timer can't tell "still working" from "stuck."
- Grid math (`minmax(148px,1fr)`) was tested at a 1280×800 dev viewport; on an actual ~800px-wide kiosk touchscreen the arithmetic suggests Hardware Tools alone wraps to 2 rows and the full 20-tile home screen likely needs scrolling — worth confirming on the real hardware before finalizing any layout fix.

## Questions to Consider

- If the goal is "my wife can use this," does she need the full 20-tool launcher at all, or would a dedicated "simple home" with just her 2–3 tools (as big, bright tiles) serve her better than any amount of polish on the current grid?
- The default theme is the muted one; the characterful ones (Amber CRT, Phosphor) are opt-in. Would a *bolder* default actually read as more approachable to a non-technical user (clearer signal of "this is a fun gadget") rather than less?
- Does she need to see ABSENT pentesting tools (GNU Radio, Kismet, Terminal, Claude Code) at all, or is their only audience you?
