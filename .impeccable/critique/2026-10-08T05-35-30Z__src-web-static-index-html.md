---
target: src/web/static/index.html
total_score: 23
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
timestamp: 2026-10-08T05-35-30Z
slug: src-web-static-index-html
---
Method: dual-agent (A: /root/critique_design_a · B: /root/critique_evidence_b)

# Design Critique: `src/web/static/index.html`

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2/4 | Rich status vocabulary exists, but backend loss can become silent or visually healthy. |
| 2 | Match System / Real World | 2/4 | Expert terminology is authentic; Simple Home still asks household users to distinguish card technologies. |
| 3 | User Control and Freedom | 2/4 | Back, cancel, stop, and start-over paths exist; dialogs lack Escape and focus behavior. |
| 4 | Consistency and Standards | 3/4 | Tokens and components are cohesive, but WARN and Simple Home copy are semantically inconsistent. |
| 5 | Error Prevention | 3/4 | Risky writes and launches are guarded; some unavailable built-ins remain fully actionable. |
| 6 | Recognition Rather Than Recall | 3/4 | Tiles are labelled and described; touch and keyboard access to status meaning/help is weak. |
| 7 | Flexibility and Efficiency | 2/4 | Simple/full modes help, but there are no favorites, recent tools, search, or accelerators. |
| 8 | Aesthetic and Minimalist Design | 2/4 | Strong aesthetic; the header, full Home, and several action surfaces carry too much equal visual weight. |
| 9 | Error Recovery | 2/4 | Hardware wizards recover well; many other failures are transient toasts without persistent next steps. |
| 10 | Help and Documentation | 2/4 | Legend, descriptions, diagnostics, and GPIO help exist, but complex workflows need more contextual help. |
| **Total** | | **23/40** | **Acceptable — significant trust, accessibility, and IA work remains.** |

## Design Specificity Verdict

**LLM assessment:** Strongly product-specific, but unevenly expressed. The LED silhouettes, recessed readouts, CPU history, real hardware channels, mmWave scope, GPIO reference, physical-panel gradients, and eight token-driven themes create a credible Pip-Boy workbench instrument. Below the header, the full dashboard often falls back to an equal-weight app-card catalog. The visual identity says “mission control”; the task hierarchy still says “launcher grid.”

**Deterministic scan:** `detect.mjs` returned `[]` with exit code 0: zero findings, rules, locations, severities, or false positives. This agrees that the interface avoids common mechanical design slop, but it cannot detect the trust, accessibility, terminology, or task-prioritization problems below.

**Visual overlays:** No reliable user-visible overlay is available. Native browser automation was not exposed, and no installed Playwright/Puppeteer runtime was available. The fallback evidence was a clean CLI scan, successful HTTP 200 response, live API responses, source inspection, and rendered-DOM logic.

## Overall Impression

PIP-UI looks authored for its actual hardware bench, not skinned from a generic dashboard. Its best flows—boot self-check and card-cloning wizards—pair personality with clear operational guidance. Its biggest opportunity is to make truth and task priority as specific as the visual language: a hardware console must never imply healthy state when data is stale, and Simple Home should present household jobs rather than radio technologies.

## What’s Working

1. **The visual language earns its specificity.** Status LEDs use shape as well as hue, including thoughtful handling for the monochrome Night Vision theme. Eight themes share structural CSS rather than fragmenting the product.
2. **Safety and hardware truth are taken seriously in core workflows.** Missing launch tools remain represented; privileged launches explain consequences; stopping warns about data loss; boot performs a real self-check.
3. **The guided hardware workflows use unusually good plain-language recovery.** Proxmark and magstripe flows name physical remedies—check the cable, place the card flat, swipe again—and preserve “Start over” paths.

## Cognitive Load

**4 of 8 checks fail: high cognitive load overall.** Grouping, one-thing-at-a-time sequencing, and working-memory support are generally strong. Chunking, visual hierarchy, minimal choices, and progressive disclosure fail on the full dashboard and some tool surfaces.

Decision points above the four-item working-memory target include six Simple Home tools, roughly 22 Full Home tools, ten Hardware Tools, five SDR tools, eight themes, six Bluetooth device actions, and five settings-module switches. Simple Home is much calmer than Full Home, but its always-on telemetry header still competes with the current task.

## Emotional Journey

The boot self-check creates the right opening arc: anticipation followed by confidence. Large Simple Home tiles reduce intimidation, while the guided write/clone flows add reassurance at high-stakes moments. The emotional valley appears when a household user must choose among overlapping NFC/RFID, key-fob, magstripe, and library concepts. The weakest ending is connection loss or a failed action that disappears after a short toast; the interface can move from earned confidence to false reassurance without a durable explanation.

## Priority Issues

### [P1] Loss of backend truth can appear healthy

**Why it matters:** `paintPresence()` treats any value other than explicit `FAIL` or `WARN` as green. A failed boot request only changes temporary splash copy, and later polling failures are counted silently. After the splash disappears, the dashboard can imply fresh hardware truth when it has none—the most damaging possible failure for this product.

**Fix:** Introduce explicit `disconnected` and `stale` states; keep a persistent banner visible; show last-successful-update time; suppress green until fresh data arrives; and preserve the last known values as visibly stale rather than current.

**Suggested command:** `$impeccable harden src/web/static/index.html`

### [P1] Simple Home no longer matches its audience or its own copy

**Why it matters:** Settings says Simple Home contains “Just NFC / RFID, Infrared, and Bluetooth,” but six tools are marked simple, including RFID & Key Fobs, Magstripe Cards, and Card Library. A non-technical household user must classify card technologies before choosing a job.

**Fix:** Recast Simple Home as a task launcher: “Scan a card or tag,” “Use a remote,” and “Connect Bluetooth.” Put saved cards inside the card task, and keep research, cloning, and technology distinctions behind contextual progressive disclosure or Expert mode. Update Settings copy to match reality.

**Suggested command:** `$impeccable distill src/web/static/index.html`

### [P1] Critical feedback and dialogs are not accessible or durable

**Why it matters:** The confirmation modal lacks dialog semantics, initial focus, focus trapping/return, and Escape handling. Toasts lack live-region semantics and disappear after 2.2 seconds. Custom switches use `aria-pressed` instead of `aria-checked`, and tile info is a clickable span nested inside the tile button. Keyboard and screen-reader users cannot reliably perceive or operate core confirmations, status changes, or help.

**Fix:** Implement an accessible dialog primitive; add `role="status"`/`aria-live` to feedback; persist actionable failures; use correct switch semantics; split tile help into a separate real button; and add consistent `:focus-visible` treatment.

**Suggested command:** `$impeccable audit src/web/static/index.html`

### [P2] Arm’s-length legibility and touch sizing remain inconsistent

**Why it matters:** A mounted kiosk is read at distance, yet many labels and telemetry values sit at 10–12.5px. The 48px header packs six hardware chips, an LCD, and three controls into one row. The tile-info target is about 33px, while the Wi-Fi Clients control explicitly drops to 26px.

**Fix:** Raise the kiosk typography floor; simplify or wrap the header at realistic Pi breakpoints; make every independent control at least 44×44px; and test the eight themes at physical viewing distance rather than relying on token equivalence.

**Suggested command:** `$impeccable adapt src/web/static/index.html`

### [P2] Home polling disrupts interaction and feedback is too transient

**Why it matters:** Every successful five-second poll rerenders Home wholesale, which can destroy keyboard focus, reset tab position, and shift tiles. Launch/save failures often exist only as brief toasts.

**Fix:** Patch changed status values in place; preserve focus and scroll position; show pending state on the initiating control; and keep actionable errors visible until dismissed or resolved.

**Suggested command:** `$impeccable harden src/web/static/index.html`

## Persona Red Flags

### Alex — technical power user

- Ten equal Hardware tiles give settings, diagnostics, daily tools, and wiring reference the same priority.
- There are no favorites, recent tools, search, or keyboard accelerators.
- Five-second wholesale rerenders can interrupt keyboard use.
- Launch actions lack a durable “starting” state while Alex waits for the next poll.

### Sam — keyboard, screen-reader, or low-vision user

- Dialogs do not announce themselves or manage focus.
- Toast state changes are silent to assistive technology.
- Custom switches expose the wrong state property.
- Tile help is not independently keyboard-focusable.
- Small typography and inconsistent focus treatment undermine arm’s-length and keyboard use.
- `user-scalable=no` blocks zoom; global `user-select:none` blocks copying hardware IDs and diagnostic details.

### Morgan — non-technical household user

- The first screen asks Morgan to distinguish NFC/RFID, RFID & Key Fobs, Magstripe Cards, and Card Library.
- Research, clone, emulate, and card-technology vocabulary appears before a plain task choice.
- Fault status depends on a small LED whose legend is behind an icon-only header button.
- “More tools” opens the expert catalog without clearly signalling the change in vocabulary and risk.
- Built-in tools remain tappable when their hardware channel is failing, delaying the explanation until deeper in the flow.

## Minor Observations

- `WARN` means both a degraded condition and “running right now,” weakening the status language.
- The Simple Home empty state says to enable a tool in Settings, but individual membership is actually controlled in YAML.
- Several status details rely on `title`, which is effectively unavailable on a touchscreen.
- Full Home lacks operationally useful “Active now” and “Needs attention” groupings.
- Global text-selection disabling prevents copying UIDs, BSSIDs, commands, and error details.
- The header power LED lacks accompanying accessible status text.

## Questions to Consider

1. If Simple Home is for a non-technical household user, why expose technologies instead of the three jobs they came to do?
2. Should the dashboard ever show green when it cannot prove backend or hardware data is fresh?
3. Is Full Home meant to answer “What can I launch?” or “What needs my attention right now?”
4. Are all eight themes tested at arm’s length, or is token consistency being mistaken for usability equivalence?
5. Should “More tools” be a quiet escape hatch or an intentional transition into Expert mode?
