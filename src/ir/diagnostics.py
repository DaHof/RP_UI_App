from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import shutil
import subprocess
from typing import Callable, Optional


@dataclass(frozen=True)
class DiagnosticStepResult:
    name: str
    status: str
    details: str = ""


@dataclass(frozen=True)
class DiagnosticResult:
    status: str
    steps: list[DiagnosticStepResult]
    devices: list[str]
    suggested_fixes: list[str]
    timestamp: str

    def summary_line(self) -> str:
        parts = []
        for step in self.steps:
            details = ""
            if step.details and step.status != "PASS":
                details = f" ({step.details})"
            parts.append(f"{step.name}: {step.status}{details}")
        return " / ".join(parts)


class IRDiagnosticService:
    def __init__(self, logger: Optional[Callable[[str], None]] = None) -> None:
        self._logger = logger or (lambda message: None)

    def run_boot_diagnostic(
        self,
        progress: Optional[Callable[[DiagnosticStepResult, int, int], None]] = None,
    ) -> DiagnosticResult:
        return self._run_diagnostic(
            mode="boot",
            include_rx_activity=False,
            prompt=None,
            progress=progress,
        )

    def run_settings_diagnostic(
        self,
        prompt: Optional[Callable[[str], None]] = None,
        progress: Optional[Callable[[DiagnosticStepResult, int, int], None]] = None,
    ) -> DiagnosticResult:
        return self._run_diagnostic(
            mode="settings",
            include_rx_activity=True,
            prompt=prompt,
            progress=progress,
        )

    def _run_diagnostic(
        self,
        mode: str,
        include_rx_activity: bool,
        prompt: Optional[Callable[[str], None]],
        progress: Optional[Callable[[DiagnosticStepResult, int, int], None]],
    ) -> DiagnosticResult:
        steps: list[DiagnosticStepResult] = []
        devices = self._detect_devices()
        rx_device = self._select_rx_device(devices)
        tx_device = self._select_tx_device(devices, rx_device)
        total_steps = 4 + (1 if include_rx_activity else 0)

        def record_step(step: DiagnosticStepResult) -> None:
            steps.append(step)
            if progress:
                progress(step, len(steps), total_steps)
            self._logger(f"{step.name}: {step.status} {step.details}".strip())

        presence_step = self._presence_check(devices)
        record_step(presence_step)

        driver_step = self._driver_check()
        record_step(driver_step)

        if include_rx_activity:
            if prompt:
                prompt("Press any remote buttons within 5 seconds to test RX activity.")
            rx_step = self._rx_activity_check(devices, rx_device)
            record_step(rx_step)
        else:
            rx_step = None

        tx_step = self._tx_send_check(devices, tx_device)
        record_step(tx_step)

        if mode == "settings" and prompt:
            prompt("Point the TX LED at the RX sensor to test loopback.")
        loopback_step = self._loopback_check(
            devices, rx_device, tx_device, tx_step.status == "PASS"
        )
        record_step(loopback_step)

        suggested_fixes = self._suggest_fixes(
            presence_step, driver_step, rx_step, tx_step, loopback_step
        )
        overall_status = self._overall_status(
            presence_step, driver_step, rx_step, tx_step, loopback_step
        )
        return DiagnosticResult(
            status=overall_status,
            steps=steps,
            devices=devices,
            suggested_fixes=suggested_fixes,
            timestamp=datetime.now().isoformat(timespec="seconds"),
        )

    def _detect_devices(self) -> list[str]:
        return sorted(str(path) for path in Path("/dev").glob("lirc*"))

    def _presence_check(self, devices: list[str]) -> DiagnosticStepResult:
        if devices:
            details = "Devices detected: " + ", ".join(devices)
            return DiagnosticStepResult("Presence Check", "PASS", details)
        return DiagnosticStepResult("Presence Check", "FAIL", "No /dev/lirc* devices found.")

    def _driver_check(self) -> DiagnosticStepResult:
        code, stdout, stderr = self._run_command(["ir-keytable"], timeout=2.0)
        combined_output = " ".join(filter(None, [stdout, stderr]))
        driver_detected = bool(re.search(r"Driver|rc\d|/sys/class/rc", combined_output, re.IGNORECASE))
        lsmod_code, lsmod_out, _ = self._run_command(["lsmod"], timeout=2.0)
        hints = self._extract_lsmod_hints(lsmod_out) if lsmod_code == 0 else ""
        details_parts = []
        if stdout:
            details_parts.append(f"ir-keytable: {stdout.splitlines()[0]}")
        if stderr:
            details_parts.append(f"ir-keytable err: {stderr.splitlines()[0]}")
        if hints:
            details_parts.append(f"lsmod: {hints}")
        details = " | ".join(details_parts)
        if driver_detected:
            return DiagnosticStepResult("Driver/Binding Check", "PASS", details)
        return DiagnosticStepResult("Driver/Binding Check", "WARN", details or "No driver info.")

    def _rx_activity_check(
        self, devices: list[str], rx_device: Optional[str]
    ) -> DiagnosticStepResult:
        if not devices:
            return DiagnosticStepResult("RX Activity Test", "WARN", "No /dev/lirc* devices.")
        if not rx_device:
            return DiagnosticStepResult(
                "RX Activity Test", "WARN", "No readable RX device detected."
            )
        if not shutil.which("mode2"):
            return DiagnosticStepResult("RX Activity Test", "WARN", "mode2 not available.")
        output = self._capture_mode2(rx_device, duration=5.0)
        if self._has_pulse(output):
            return DiagnosticStepResult("RX Activity Test", "PASS", "Pulse/space detected.")
        return DiagnosticStepResult("RX Activity Test", "WARN", "No pulse/space detected.")

    def _tx_send_check(
        self, devices: list[str], tx_device: Optional[str]
    ) -> DiagnosticStepResult:
        if not devices:
            return DiagnosticStepResult("TX Send Test", "FAIL", "No /dev/lirc* devices.")
        if not tx_device:
            return DiagnosticStepResult(
                "TX Send Test", "FAIL", "No writable TX device detected."
            )
        if not shutil.which("ir-ctl"):
            return DiagnosticStepResult("TX Send Test", "FAIL", "ir-ctl not available.")
        command = ["ir-ctl", "-d", tx_device, "-S", "nec:0x00ff00ff"]
        code, stdout, stderr = self._run_command(command, timeout=3.0)
        details_parts = []
        if stdout:
            details_parts.append(stdout.splitlines()[0])
        if stderr:
            details_parts.append(stderr.splitlines()[0])
        details = " | ".join(details_parts)
        if code == 0:
            return DiagnosticStepResult("TX Send Test", "PASS", details)
        return DiagnosticStepResult("TX Send Test", "FAIL", details or "ir-ctl failed.")

    def _loopback_check(
        self,
        devices: list[str],
        rx_device: Optional[str],
        tx_device: Optional[str],
        tx_succeeded: bool,
    ) -> DiagnosticStepResult:
        if not devices:
            return DiagnosticStepResult("Loopback Test", "WARN", "No /dev/lirc* devices.")
        if not rx_device or not tx_device:
            return DiagnosticStepResult(
                "Loopback Test", "WARN", "RX/TX device pairing unavailable."
            )
        if not shutil.which("mode2") or not shutil.which("ir-ctl"):
            return DiagnosticStepResult("Loopback Test", "WARN", "mode2/ir-ctl not available.")
        if not tx_succeeded:
            return DiagnosticStepResult("Loopback Test", "WARN", "Skipped due to TX failure.")
        output = self._loopback_capture(rx_device, tx_device)
        if self._has_pulse(output):
            return DiagnosticStepResult("Loopback Test", "PASS", "Pulse/space detected.")
        return DiagnosticStepResult("Loopback Test", "WARN", "No pulse/space detected.")

    def _suggest_fixes(
        self,
        presence: DiagnosticStepResult,
        driver: DiagnosticStepResult,
        rx_activity: Optional[DiagnosticStepResult],
        tx_send: DiagnosticStepResult,
        loopback: DiagnosticStepResult,
    ) -> list[str]:
        fixes: list[str] = []
        if presence.status == "FAIL":
            fixes.append(
                "Enable gpio-ir overlays/modules, verify kernel modules, check wiring, reboot."
            )
        if rx_activity and rx_activity.status == "WARN":
            fixes.append(
                "Check RX VCC (typically 3.3V), GND, OUT pin mapping, gpio_ir_recv loaded."
            )
        if tx_send.status == "FAIL":
            fixes.append(
                "Check TX device selection, permissions, gpio_ir_tx loaded, wiring/transistor."
            )
        if loopback.status == "WARN" and tx_send.status == "PASS":
            fixes.append(
                "TX may be underpowered (often needs 5V + transistor/resistor), "
                "ensure shared GND, align LED to sensor."
            )
        if driver.status == "WARN" and not fixes:
            fixes.append(
                "Verify ir-keytable sees a driver, check kernel modules and bindings."
            )
        return fixes

    def _overall_status(
        self,
        presence: DiagnosticStepResult,
        driver: DiagnosticStepResult,
        rx_activity: Optional[DiagnosticStepResult],
        tx_send: DiagnosticStepResult,
        loopback: DiagnosticStepResult,
    ) -> str:
        statuses = [presence.status, driver.status, tx_send.status, loopback.status]
        if rx_activity:
            statuses.append(rx_activity.status)
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        return "PASS"

    def _run_command(
        self, command: list[str], timeout: float
    ) -> tuple[int, str, str]:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return 127, "", "Command not found."
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else "Timed out."
            return 124, stdout, stderr
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def _capture_mode2(self, device: str, duration: float) -> str:
        try:
            result = subprocess.run(
                ["mode2", "-d", device],
                capture_output=True,
                text=True,
                timeout=duration,
            )
            return (result.stdout or "") + (result.stderr or "")
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return stdout + stderr

    def _loopback_capture(self, rx_device: str, tx_device: str) -> str:
        process = subprocess.Popen(
            ["mode2", "-d", rx_device],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            subprocess.run(
                ["ir-ctl", "-d", tx_device, "-S", "nec:0x00ff00ff"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            try:
                output, _ = process.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                output, _ = process.communicate(timeout=1.0)
            return output or ""
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=1.0)

    def _has_pulse(self, output: str) -> bool:
        return bool(re.search(r"\b(pulse|space)\b", output, re.IGNORECASE))

    def _select_rx_device(self, devices: list[str]) -> Optional[str]:
        if not devices or not shutil.which("mode2"):
            return None
        for device in devices:
            output = self._capture_mode2(device, duration=0.5)
            if "Invalid argument" in output or "invalid argument" in output:
                continue
            return device
        return None

    def _select_tx_device(
        self, devices: list[str], rx_device: Optional[str]
    ) -> Optional[str]:
        if not devices:
            return None
        if rx_device:
            for device in devices:
                if device != rx_device:
                    return device
        return devices[0]

    def _extract_lsmod_hints(self, output: str) -> str:
        lines = [
            line.strip()
            for line in output.splitlines()
            if re.search(r"\b(ir|lirc|gpio)\b", line)
        ]
        return ", ".join(lines[:3])
