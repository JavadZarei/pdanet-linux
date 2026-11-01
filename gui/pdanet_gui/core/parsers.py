"""Strict parsers for the output of `pdanet usb status`, `adb devices -l`, `ip`."""

from __future__ import annotations

import re
from dataclasses import dataclass


class ParseError(ValueError):
    """Command output did not have the expected shape."""


# ---------------------------------------------------------------- pdanet usb status
@dataclass(frozen=True)
class UsbStatus:
    enabled: bool
    device: str | None
    target: str | None
    forward_active: bool
    forward_port: int | None
    helper_running: bool
    helper_pid: int | None
    iface_present: bool
    routes_active: bool
    dns_active: bool


_HEADER = re.compile(r"^PdaNet USB:\s+(enabled|disabled)\s*$")
_FIELD = re.compile(r"^\s+([A-Za-z][A-Za-z ]*?):\s+(.*?)\s*$")
_REQUIRED = (
    "Device", "Phone target", "ADB forward", "Helper", "Interface", "Routes", "DNS service",
)


def parse_usb_status(text: str) -> UsbStatus:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ParseError("empty status output")
    # `pdanet status` prints Wi-Fi state first; locate the USB header.
    start = next((i for i, ln in enumerate(lines) if _HEADER.match(ln)), None)
    if start is None:
        raise ParseError("missing 'PdaNet USB:' header")
    enabled = _HEADER.match(lines[start]).group(1) == "enabled"  # type: ignore[union-attr]
    fields: dict[str, str] = {}
    for ln in lines[start + 1:]:
        match = _FIELD.match(ln)
        if match:
            fields[match.group(1)] = match.group(2)
    missing = [name for name in _REQUIRED if name not in fields]
    if missing:
        raise ParseError("missing status fields: " + ", ".join(missing))

    def none_or(value: str) -> str | None:
        return None if value == "none" else value

    forward = re.match(r"^(active|missing)(?:\s+\(127\.0\.0\.1:(\d+)\))?$", fields["ADB forward"])
    helper = re.match(r"^(running|stopped)(?:\s+\(PID (\d+)\))?$", fields["Helper"])
    iface = re.match(r"^\S+\s+\((present|missing)\)$", fields["Interface"])
    if not (forward and helper and iface):
        raise ParseError("unrecognised status field format")
    routes = fields["Routes"]
    if routes not in ("active", "inactive"):
        raise ParseError(f"unrecognised routes state: {routes!r}")
    return UsbStatus(
        enabled=enabled,
        device=none_or(fields["Device"]),
        target=none_or(fields["Phone target"]),
        forward_active=forward.group(1) == "active",
        forward_port=int(forward.group(2)) if forward.group(2) else None,
        helper_running=helper.group(1) == "running",
        helper_pid=int(helper.group(2)) if helper.group(2) else None,
        iface_present=iface.group(1) == "present",
        routes_active=routes == "active",
        dns_active=fields["DNS service"] == "active",
    )


# ---------------------------------------------------------------- adb devices -l
@dataclass(frozen=True)
class AdbDevice:
    serial: str
    state: str  # device | unauthorized | offline | no permissions | ...
    usb: bool
    model: str | None
    device: str | None
    product: str | None

    @property
    def authorized(self) -> bool:
        return self.state == "device"

    @property
    def display_name(self) -> str:
        return pretty_model(self.model) or self.device or self.serial


_STATES = (
    "device|unauthorized|offline|recovery|sideload|bootloader|authorizing|connecting|"
    "no permissions|host|rescue"
)
_DEVICE_LINE = re.compile(rf"^(\S+)\s+({_STATES})(?:\s+(.*))?$")


def pretty_model(model: str | None) -> str | None:
    if not model:
        return None
    match = re.match(r"^([A-Za-z]{2,3})_([A-Za-z0-9]+)$", model)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return model.replace("_", " ")


def parse_adb_devices(text: str) -> list[AdbDevice]:
    devices: list[AdbDevice] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        match = _DEVICE_LINE.match(line)
        if not match:
            continue
        serial, state, rest = match.group(1), match.group(2), match.group(3) or ""
        extras = dict(
            token.split(":", 1) for token in rest.split() if ":" in token and not token.startswith(":")
        )
        devices.append(
            AdbDevice(
                serial=serial,
                state=state,
                usb="usb" in extras,
                model=extras.get("model"),
                device=extras.get("device"),
                product=extras.get("product"),
            )
        )
    return sorted(devices, key=lambda d: d.serial)


# ---------------------------------------------------------------- iproute2
def parse_route_dev(text: str) -> str | None:
    """Return the `dev X` of the first line of `ip route get`/`ip route show` output."""
    for line in text.splitlines():
        match = re.search(r"\bdev\s+(\S+)", line)
        if match:
            return match.group(1)
    return None
