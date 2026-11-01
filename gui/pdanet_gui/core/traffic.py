"""Live traffic statistics from the kernel's per-interface counters."""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class TrafficSample:
    rx_bytes: int | None
    tx_bytes: int | None
    rx_rate: float | None
    tx_rate: float | None

    @property
    def total(self) -> int | None:
        if self.rx_bytes is None or self.tx_bytes is None:
            return None
        return self.rx_bytes + self.tx_bytes


def read_counters(iface: str, sysfs: str | None = None) -> tuple[int, int] | None:
    """(rx_bytes, tx_bytes) of *iface* from sysfs, or None if it does not exist.

    The TUN device is created fresh for every session, so its counters are the
    session totals. rx = data the host received from the phone (download).
    """
    base = os.path.join(sysfs or config.SYSFS_NET, iface, "statistics")
    try:
        with open(os.path.join(base, "rx_bytes"), encoding="ascii") as fh:
            rx = int(fh.read().strip())
        with open(os.path.join(base, "tx_bytes"), encoding="ascii") as fh:
            tx = int(fh.read().strip())
    except (OSError, ValueError):
        return None
    return rx, tx


class TrafficMonitor:
    """Turns successive counter readings into per-second rates."""

    def __init__(self) -> None:
        self._last: tuple[float, int, int] | None = None

    def reset(self) -> None:
        self._last = None

    def update(self, now: float, counters: tuple[int, int] | None) -> TrafficSample:
        if counters is None:
            self._last = None
            return TrafficSample(None, None, None, None)
        rx, tx = counters
        rx_rate = tx_rate = None
        if self._last is not None:
            last_time, last_rx, last_tx = self._last
            elapsed = now - last_time
            # Counters going backwards means the interface was recreated.
            if elapsed > 0 and rx >= last_rx and tx >= last_tx:
                rx_rate = (rx - last_rx) / elapsed
                tx_rate = (tx - last_tx) / elapsed
        self._last = (now, rx, tx)
        return TrafficSample(rx, tx, rx_rate, tx_rate)
