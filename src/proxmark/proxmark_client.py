from __future__ import annotations

class ProxmarkClient:
    """Minimal Proxmark client stub for future USB integration."""

    def connect(self) -> None:
        raise NotImplementedError("Proxmark integration not wired yet.")

    def device_info(self) -> None:
        raise NotImplementedError("Proxmark integration not wired yet.")

    def read_lf(self) -> None:
        raise NotImplementedError("Proxmark integration not wired yet.")

    def read_hf(self) -> None:
        raise NotImplementedError("Proxmark integration not wired yet.")
