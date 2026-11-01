"""System network facts: routes, DNS, IPv6 protection, helper detection, public IP."""

from __future__ import annotations

import ipaddress
import os
import re
import urllib.request

from . import config
from .parsers import parse_route_dev
from .runner import run


def active_interface() -> str | None:
    """Interface the kernel would use to reach the Internet right now."""
    res = run([config.IP_BIN, "-4", "route", "get", "1.1.1.1"], 5)
    return parse_route_dev(res.stdout) if res.ok else None


def underlying_interface() -> str | None:
    """Interface of the normal (non-tunnel) default route, e.g. Wi-Fi."""
    res = run([config.IP_BIN, "-4", "route", "show", "default"], 5)
    if not res.ok:
        return None
    for line in res.stdout.splitlines():
        match = re.search(r"\bdev\s+(\S+)", line)
        if match and match.group(1) != config.USB_IFACE:
            return match.group(1)
    return None


def ipv6_blocked() -> bool:
    """Both IPv6 blackhole routes installed by `pdanet usb` are present."""
    res = run([config.IP_BIN, "-6", "route", "show"], 5)
    if not res.ok:
        return False
    has_low = re.search(r"^unreachable\s+::/1\b", res.stdout, re.MULTILINE) is not None
    has_high = re.search(r"^unreachable\s+8000::/1\b", res.stdout, re.MULTILINE) is not None
    return has_low and has_high


def dns_routed() -> bool:
    """System resolver for the tunnel link points at the local DoH proxy."""
    res = run([config.RESOLVECTL, "dns", config.USB_IFACE], 5)
    return res.ok and config.DNS_ENDPOINT in res.stdout


def service_active(unit: str = config.USB_DNS_SERVICE) -> bool:
    res = run([config.SYSTEMCTL, "is-active", unit], 5)
    return res.stdout.strip() == "active"


def detect_running_helper(run_dir: str | None = None, proc_dir: str | None = None) -> str | None:
    """Path of the USB helper actually running (e.g. one started by an older
    ~/.local install), taken from the root-created pid file and /proc.

    The CLI recognises its helper by exact path, so status calls made against a
    tunnel started by a different install must pass this path back to it.
    """
    run_dir = run_dir or config.RUN_DIR
    proc_dir = proc_dir or config.PROC_DIR
    try:
        with open(os.path.join(run_dir, "helper-pid"), encoding="ascii") as fh:
            pid = fh.readline().strip()
        if not pid.isdigit():
            return None
        with open(os.path.join(proc_dir, pid, "cmdline"), "rb") as fh:
            parts = fh.read().split(b"\0")
    except OSError:
        return None
    for raw in parts:
        arg = raw.decode("utf-8", "replace")
        if os.path.basename(arg) == "pdanet-usb-helper" and arg.startswith("/"):
            return arg
    return None


def uptime_seconds(now: float, run_dir: str | None = None) -> float | None:
    """Connection age from the mtime of the pid file written at connect time."""
    run_dir = run_dir or config.RUN_DIR
    try:
        return max(0.0, now - os.stat(os.path.join(run_dir, "helper-pid")).st_mtime)
    except OSError:
        return None


_IP_SOURCES = ("https://api.ipify.org", "https://icanhazip.com")


def fetch_public_ip(timeout: float = 8.0) -> str | None:
    """Public IPv4 as seen from the Internet (goes through the tunnel when up)."""
    for url in _IP_SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pdanet-linux"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https URLs)
                text = resp.read(64).decode("ascii", "ignore").strip()
            return str(ipaddress.IPv4Address(text))
        except (OSError, ValueError):
            continue
    return None
