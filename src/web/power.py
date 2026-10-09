"""Device power controls: screen backlight idle-off, and a full shutdown.

Screen power goes through ``vcgencmd display_power``, not X11 DPMS/``xset``.
``kiosk.sh`` already claims ``xset`` for the opposite job -- turning X's own
screensaver *off* so the dashboard never blanks mid-use on its own
(``xset s off -dpms s noblank``). ``vcgencmd`` is a separate, lower-level knob
on the actual display power, works with no X session at all, and so doesn't
fight that setting: kiosk.sh's "never blank" stays true, this just also turns
the backlight off/on independently of whether X thinks it should.

This also means it works from ``pipui-web.service``, which the README
describes as running with "no display needed" -- there is no ``$DISPLAY`` or
``$XAUTHORITY`` for ``xset`` to use there even if it were the right tool.

Shutdown needs root. Add a passwordless-sudo rule for it, same pattern as the
one ``scripts/pipui-update.sh`` documents for restarting the service:

    echo "$USER ALL=(root) NOPASSWD: /sbin/shutdown" | sudo tee /etc/sudoers.d/pipui-power
    sudo chmod 440 /etc/sudoers.d/pipui-power

``shutdown()`` is a real, one-way side effect, so unlike every probe in
``sim.py`` it is deliberately NOT given a canned result there -- same as
``launcher.py``'s own ``sudo systemctl ...`` calls for root-gated tools.
Without the sudoers rule above, ``sudo`` just fails (no passwordless rule,
no TTY to prompt), so this is still safe to hit on a dev machine.
"""

from __future__ import annotations

import shell


def screen_off() -> tuple[bool, str]:
    result = shell.run(["vcgencmd", "display_power", "0"], timeout=3.0)
    if not result.ok:
        return False, result.detail
    return True, "Screen off"


def screen_on() -> tuple[bool, str]:
    result = shell.run(["vcgencmd", "display_power", "1"], timeout=3.0)
    if not result.ok:
        return False, result.detail
    return True, "Screen on"


def screen_state() -> dict:
    """Best-effort read. ``on`` is ``None`` when the state can't be determined
    (not a Pi, ``vcgencmd`` missing, simulation off) -- there's nothing to
    probe, not a false "off"."""
    result = shell.run(["vcgencmd", "display_power"], timeout=2.0)
    if not result.ok:
        return {"available": False, "on": None, "detail": result.detail}
    # Real firmware answers "display_power=1" (sometimes "=1 0" -- one digit per
    # display on multi-output builds; the first is the one this board drives).
    digit = result.stdout.rsplit("=", 1)[-1].split()[0] if "=" in result.stdout else ""
    return {"available": True, "on": digit == "1", "detail": result.stdout}


def shutdown() -> tuple[bool, str]:
    result = shell.run(["sudo", "shutdown", "-h", "now"], timeout=5.0)
    if not result.ok:
        return False, result.detail
    return True, "Shutting down…"
