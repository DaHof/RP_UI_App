---
target: PIP-UI current state (task-based Simple Home + full dashboard + guided wizards)
total_score: 29
max_score: 40
na_heuristics: 
p0_count: 2
p1_count: 2
timestamp: 2026-10-08T06-29-35Z
slug: src-web-static-index-html
---
Method: dual-agent (A: a3714c42446d73f42 · B: ae9f250ab7938e92b)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Live badges, progress text, busy-disabled write buttons all work; the technical boot self-check list still flashes in full jargon before Simple Home appears |
| 2 | Match System / Real World | 2 | Excellent at the top ("Scan a card or tag," "Use a remote"), then collapses one tap later into "Gen1a magic card," GPIO/HID jargon, raw IR codes |
| 3 | User Control and Freedom | 2 | Confirm dialogs default to Cancel (good) — but Back skips a level in the new 3-level IA, and there's no way back to Simple Home from "Expert tools" |
| 4 | Consistency and Standards | 3 | confirmAction modal, Advanced `<details>` pattern, tile language all consistent |
| 5 | Error Prevention | 4 | This session's write/clone/erase confirmation + busy-disable guard verified live, holds up |
| 6 | Recognition Rather Than Recall | 3 | Step 2 of both wizards names blanks in buyable terms; undercut by raw IR codes shown with no explanation |
| 7 | Flexibility and Efficiency | 3 | Advanced/manual sections sit right under the guided flow without forcing anyone through it |
| 8 | Aesthetic and Minimalist Design | 3 | Full dashboard is dense and purposeful; Simple Home screens leave ~500-600px of black void below 3 tiles |
| 9 | Error Recognition/Diagnosis/Recovery | 4 | Best-executed heuristic — specific, actionable failures with concrete recovery actions throughout |
| 10 | Help and Documentation | 2 | The LED legend is genuinely plain language; the (i) "About" popovers are the single worst jargon offender in the product |
| **Total** | | **29/40** | **Good — strong engineering bones, but Simple Home's new task-based front door isn't finished behind its first tap** |

## Design Specificity Verdict

**LLM assessment**: Split verdict. The full dashboard is genuinely specific — a categorized grid naming real hardware (PN532, rtl_433, Kismet, GPIO Pins) with live per-tool badges; no generic dashboard template produces that tile set. The Simple Home task layer, by contrast, reads as a reskin that's only half-finished: the top-level framing ("What do you want to do?") is well-written and specific, but one tap deeper, most paths dump you into the exact same jargon-dense screens the full dashboard uses for its technical audience. It isn't one cohesive two-tier product yet — it's a good new front door bolted onto rooms that were never redecorated.

**Deterministic scan**: `detect.mjs` static pass → 0 findings, but this is a near-meaningless result for this app specifically: every view is an empty `<section>` in markup, built entirely by JS at runtime, so the static engine has nothing to analyze. The live-browser pass is the real evidence here. After stripping two confirmed self-contamination artifacts (the injected detector script matching its own source text for `marquee` and `theater-slop-phrase` — not real findings) and one confirmed false-positive class (`low-contrast` on headings, caused by `body`'s background being set via gradient-only `background` shorthand with no `background-color` fallback, so the checker defaults to assuming white — real contrast is ~15:1), the genuine findings are: header status chips and dashboard tile subtitles at 10-10.5px (pre-existing, not new to the restructure), Settings toggle helper text at 11px, and 6 instances of nested card-in-card framing on the MSR605X wizard's expanded Advanced section. The new Simple Home task-tile code itself is clean — no sub-10px text, no hardcoded hex, all touch targets ≥44px, no new icon duplication (it correctly reuses the existing `card` icon rather than introducing a new one).

## Overall Impression

The hard engineering problem — don't let a careless click destroy data on a physical card — is solved and verified. The product problem — "does Simple Home actually protect a first-timer from the technical surface" — is only solved for Proxmark3 and MSR605X (both got a real guided wizard with user-facing copy written for Jordan), and not yet for NFC or Infrared, which Simple Home routes to unchanged. Two regressions also slipped in during the last round of edits: the Back button no longer matches the IA it's navigating, and the dedicated "return to Simple Home" button that existed as of commit `fb64552` is gone from the current file — likely lost in one of the merge commits between then and now, the same class of silent-overwrite collision flagged earlier this session.

## What's Working

1. **The Proxmark3/MSR605X "Clone a card" wizards** — step 1→2→3, "what you need" buying guidance in plain terms, auto-verify, concrete recoverable errors. The best-finished part of the recent work.
2. **Error messaging product-wide** — specific and actionable ("No card reader detected — check the USB cable," exact UID mismatches) instead of generic failures. Strongest heuristic score in the review (Error Recovery, 4/4).
3. **Today's confirmation-dialog work holds up under live testing** — the Write button disables itself during the write+verify round-trip on both wizards, no double-submit path found, Cancel is the safe default focus.

## Priority Issues

**[P0] The Back button skips a level in the new 3-level Simple Home IA.** `$("#back").onclick = () => go("home")` (index.html:810) is hardcoded to always jump to the top, not "one screen up." Verified live: Simple Home → "Scan a card or tag" → "Tap cards & tags" → the NFC screen; tapping Back jumps straight past "What are you using?" back to the very first screen. A user wanting a sibling option has to re-enter the task from scratch. **Fix**: a small view-stack, or at minimum special-case nfc/proxmark/msr → cards. **Suggested command**: `/impeccable harden`

**[P0] There is no way back to Simple Home from the full dashboard.** The dedicated header button for this existed (commit `fb64552`: a home-icon button, hidden only when it'd be a no-op) but is confirmed gone from the current file — zero matches for `simpleBtn`/`paintSimpleBtn`. Tapping "Expert tools" from Simple Home is a single, unconfirmed tap that permanently switches that device to full-dashboard mode with no visible way back except finding Settings → Simple Home on your own. For the exact persona Simple Home exists to protect, that's a one-way door. **Fix**: restore the header button (it's a known-good prior implementation, not new design work), or make "Expert tools" not persist the mode change. **Suggested command**: `/impeccable harden`

**[P1] Simple Home's "About" popovers are the worst jargon offender in the product.** They reuse `tools.yaml`'s `desc` field verbatim — written for the operator. The Proxmark3 one includes an unformatted developer implementation note ("...are wired up to the real `proxmark3` client; dump and sniff are not implemented yet") as end-user help copy, reachable by tapping the exact (i) icon a confused first-timer would tap for help. **Fix**: a second, plain-language description field for `simple: true` tools, used only by Simple Home's popovers. **Suggested command**: `/impeccable clarify`

**[P1] NFC and Infrared never got the simplification Proxmark3/MSR605X got.** Tapping into them from Simple Home lands on the literal same screen the full dashboard uses — for IR, a 5-tab bar (Universal/Saved/Learn/Settings/Self-test) with raw IR codes shown next to buttons. Two of Simple Home's three top-level tasks are only simplified on the surface. **Fix**: either a lightweight guided version matching the card wizards' treatment, or gate the jargon-heavy panels behind Advanced the way NFC's reader status/memory dump already are. **Suggested command**: `/impeccable distill`

**[P2] The Saved Cards empty state names a server file path.** "Saved tags are stored in `data/library.json`" means nothing to Jordan and reads as faintly alarming. **Fix**: "Nothing saved yet — scan or swipe something first." **Suggested command**: `/impeccable clarify`

**[P3] Both wizards head their failure screen "Clone a card — done."** Verified live by forcing a write failure: "DONE" sits directly above a red failure message. **Fix**: branch the heading on `w.result.ok`, or use a neutral "— result". **Suggested command**: `/impeccable clarify`

## Persona Red Flags

**Jordan (first-timer, Simple Home)**: taps the (i) "About" icon on "Key fobs" out of genuine curiosity and is handed a sentence with `proxmark3` in backticks and "dump and sniff are not implemented yet" — the single most damaging moment in the product for her trust that this screen was built for her. If she ever taps "Expert tools" (visible right on her home screen, one unconfirmed tap away), she's stuck in the full dashboard with no way back she'd discover on her own.

**Alex (power user, full dashboard)**: no real friction found. Dense, accurately labeled (ABSENT/UNREACHABLE badges are honest about this dev box's actual state), Advanced sections give direct manual control without detouring through the guided flow.

**Riley (stress-tester, wizards)**: the busy/disabled-during-write guard held up under a forced-failure test; "Try writing again" and "Start over"/"Clone another card" both work correctly from the failure state.

## Minor Observations

- The destructive Write/Clone button in the confirm dialog is outlined red, not filled — reads slightly less urgent than a filled button would on the dark theme, though the dialog copy itself carries enough weight that this is minor.
- 6 instances of card-in-card nesting on the MSR605X wizard's expanded Advanced section (confirmed by screenshot and detector).
- Header status chips (10px) and dashboard tile subtitles (10.5px) remain below an ideal floor — pre-existing, not introduced by the recent restructure, so not re-listed as a fresh priority issue, but worth folding into a future typeset pass.
- Two detector findings were confirmed false positives from the review method itself (the injected detector script matching its own source text) and one confirmed false-positive class (`low-contrast` on headings, caused by a gradient-only `background` shorthand with no solid fallback tricking the contrast checker) — noted so they aren't mistaken for real issues later.

## Questions to Consider

- Given Proxmark3 and MSR605X just got genuine guided-wizard treatment, is NFC/Infrared parity the next deliberate milestone, or is "scan a card" meant to stay the flagship task and the others stay lighter-weight?
- Is "Expert tools" meant to be a permanent mode switch at all, or was the one-tap, no-confirmation version always supposed to be temporary scaffolding?
