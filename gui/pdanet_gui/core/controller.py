"""Connection controller: GTK-free logic that drives the pdanet CLI.

Rules enforced here:
  * every external command is an argv list with a timeout (see runner.py);
  * privileged work goes only through `pkexec <pdanet-gui-helper> ...`;
  * one action at a time (duplicate attempts are rejected, not queued);
  * status and counters are read from the system, never simulated.
"""

from __future__ import annotations

import collections
import enum
import re
import threading
import time
from dataclasses import dataclass, field

from . import adb, config, netinfo
from .parsers import AdbDevice, ParseError, UsbStatus, parse_usb_status
from .runner import CmdResult, run
from .traffic import TrafficMonitor, TrafficSample, read_counters

_SERIAL_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,63}$")


class State(enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    NEEDS_RESTORE = "needs_restore"


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    key: str | None = None      # i18n key of the user-facing message on failure
    detail: str = ""            # raw tool output for the log / details
    cancelled: bool = False     # user dismissed the authentication dialog


@dataclass
class NetworkInfo:
    active_iface: str | None = None
    underlying_iface: str | None = None
    tunnel_iface: str | None = None
    dns_routed: bool = False
    dns_service: bool = False
    ipv6_blocked: bool = False
    uptime: float | None = None


@dataclass
class Snapshot:
    state: State = State.DISCONNECTED
    busy_action: str | None = None
    usb: UsbStatus | None = None
    devices: list[AdbDevice] = field(default_factory=list)
    phone: AdbDevice | None = None
    service_listening: bool | None = None
    adb_ok: bool = True
    cli_ok: bool = True
    error_key: str | None = None
    net: NetworkInfo = field(default_factory=NetworkInfo)
    traffic: TrafficSample = field(default_factory=lambda: TrafficSample(None, None, None, None))
    stale: bool = False
    timestamp: float = 0.0


def classify_failure(result: CmdResult) -> tuple[str, str]:
    """Map a failed CLI/pkexec result to (i18n key, detail)."""
    detail = result.output
    if result.timed_out:
        return "err.timeout", detail
    if result.error == "not-found":
        return "err.pkexec_missing", detail
    text = detail
    rules = (
        ("No authorized ADB device", "err.no_device"),
        ("ADB device is not available or authorized", "err.unauthorized"),
        ("PdaNet USB is not listening", "err.no_service"),
        ("Wi-Fi proxy mode is active", "err.wifi_mode"),
        ("refusing to replace", "err.route_conflict"),
        ("USB activation failed", "err.activation_failed"),
        ("Missing required command", "err.missing_dep"),
        ("Missing executable USB helper", "err.missing_dep"),
    )
    for needle, key in rules:
        if needle in text:
            return key, detail
    if result.returncode in (126, 127) and not text.strip():
        return "err.auth_cancelled", detail
    if result.returncode in (126, 127) and "Not authorized" in text:
        return "err.auth_cancelled", detail
    return "err.unknown", detail


class Controller:
    CONNECT_TIMEOUT = 150
    DISCONNECT_TIMEOUT = 90

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._action: str | None = None
        self._monitor = TrafficMonitor()
        self._events: collections.deque[str] = collections.deque(maxlen=500)
        self.selected_serial: str | None = None
        self.last: Snapshot = Snapshot()

    # ------------------------------------------------------------ bookkeeping
    @property
    def busy_action(self) -> str | None:
        return self._action

    def log(self, message: str) -> None:
        self._events.append(f"{time.strftime('%H:%M:%S')}  {message}")

    def event_log(self) -> str:
        return "\n".join(self._events)

    def _begin(self, name: str) -> bool:
        with self._lock:
            if self._action is not None:
                return False
            self._action = name
            return True

    def _end(self) -> None:
        with self._lock:
            self._action = None

    # ------------------------------------------------------------ status
    def _status_env(self) -> dict[str, str] | None:
        helper = netinfo.detect_running_helper()
        return {"PDANET_USB_HELPER": helper} if helper else None

    def read_usb_status(self) -> tuple[UsbStatus | None, str | None]:
        res = run([config.PDANET_CLI, "usb", "status"], 20, self._status_env())
        if res.error == "not-found":
            return None, "err.cli_missing"
        if not res.ok:
            return None, "err.status_failed"
        try:
            return parse_usb_status(res.stdout), None
        except ParseError:
            return None, "err.parse"

    def choose_device(self, devices: list[AdbDevice]) -> AdbDevice | None:
        authorized = [d for d in devices if d.authorized]
        for dev in authorized:
            if dev.serial == self.selected_serial:
                return dev
        usb_first = sorted(authorized, key=lambda d: (not d.usb, d.serial))
        if usb_first:
            return usb_first[0]
        # No authorised phone: surface the first device so the UI can explain why.
        return devices[0] if devices else None

    def refresh(self) -> Snapshot:
        """Collect a complete, real snapshot. Blocking; call from a worker thread."""
        snap = Snapshot(timestamp=time.monotonic(), busy_action=self._action)
        usb, err = self.read_usb_status()
        snap.usb = usb
        snap.cli_ok = err != "err.cli_missing"
        snap.error_key = err
        snap.adb_ok = adb.adb_available()

        connected = bool(usb and usb.enabled)
        if snap.adb_ok and not connected:
            snap.devices, listing = adb.list_devices()
            if not listing.ok and not snap.error_key:
                snap.error_key = "err.adb_failed"
            snap.phone = self.choose_device(snap.devices)
            if snap.phone and snap.phone.authorized:
                snap.service_listening = adb.service_listening(snap.phone.serial)
        elif connected:
            snap.devices = list(self.last.devices)
            snap.phone = self.last.phone
            if usb and usb.device and (snap.phone is None or snap.phone.serial != usb.device):
                devices, _ = adb.list_devices() if snap.adb_ok else ([], None)
                snap.devices = devices
                snap.phone = next((d for d in devices if d.serial == usb.device), None)
            snap.service_listening = True

        net = snap.net
        net.tunnel_iface = config.USB_IFACE
        net.dns_service = bool(usb and usb.dns_active)
        net.ipv6_blocked = netinfo.ipv6_blocked()
        counters = read_counters(config.USB_IFACE)
        snap.traffic = self._monitor.update(snap.timestamp, counters)
        if connected:
            net.active_iface = netinfo.active_interface()
            net.underlying_iface = netinfo.underlying_interface()
            net.dns_routed = netinfo.dns_routed()
            net.uptime = netinfo.uptime_seconds(time.time())
        else:
            net.active_iface = netinfo.active_interface()
            net.underlying_iface = net.active_iface

        run_dir_exists = _exists(config.RUN_DIR)
        snap.stale = bool(
            not connected
            and snap.busy_action is None
            and usb is not None
            and (run_dir_exists or usb.dns_active or net.ipv6_blocked
                 or usb.helper_running or usb.iface_present)
        )
        if snap.busy_action == "connect":
            snap.state = State.CONNECTING
        elif snap.busy_action in ("disconnect", "restore"):
            snap.state = State.DISCONNECTING
        elif connected:
            snap.state = State.CONNECTED
        elif snap.stale:
            snap.state = State.NEEDS_RESTORE
        else:
            snap.state = State.DISCONNECTED
        self.last = snap
        return snap

    # ------------------------------------------------------------ actions
    def _privileged(self, *args: str, timeout: float) -> CmdResult:
        argv = [config.PKEXEC, config.GUI_HELPER, *args]
        self.log("$ " + " ".join(argv[1:]))
        res = run(argv, timeout)
        for line in res.output.splitlines():
            self.log("  " + line)
        return res

    def connect(self) -> ActionResult:
        if not self._begin("connect"):
            return ActionResult(False, "err.busy")
        try:
            return self._connect_locked()
        finally:
            self._end()

    def _connect_locked(self) -> ActionResult:
        if not adb.adb_available():
            return ActionResult(False, "err.adb_missing")
        devices, listing = adb.list_devices()
        if not listing.ok:
            return ActionResult(False, "err.adb_failed", listing.output)
        phone = self.choose_device(devices)
        if phone is None:
            return ActionResult(False, "err.no_device")
        if not phone.authorized:
            key = "err.unauthorized" if phone.state == "unauthorized" else "err.offline"
            return ActionResult(False, key, f"{phone.serial}: {phone.state}")
        if not _SERIAL_OK.match(phone.serial):
            return ActionResult(False, "err.bad_serial", phone.serial)
        if adb.service_listening(phone.serial) is False:
            return ActionResult(False, "err.no_service")
        self.log(f"Connecting via {phone.display_name} ({phone.serial})")
        res = self._privileged("connect", phone.serial, timeout=self.CONNECT_TIMEOUT)
        if not res.ok:
            key, detail = classify_failure(res)
            self.log(f"Connect failed: {key}")
            return ActionResult(False, key, detail, cancelled=key == "err.auth_cancelled")
        usb, _ = self.read_usb_status()
        if not (usb and usb.enabled):
            self.log("Helper reported success but status is not 'enabled'")
            return ActionResult(False, "err.unknown", res.output)
        self.log("Connected")
        self._monitor.reset()
        return ActionResult(True)

    def disconnect(self, restore: bool = False) -> ActionResult:
        name = "restore" if restore else "disconnect"
        if not self._begin(name):
            return ActionResult(False, "err.busy")
        try:
            res = self._privileged(name, timeout=self.DISCONNECT_TIMEOUT)
            if not res.ok:
                key, detail = classify_failure(res)
                self.log(f"{name.capitalize()} failed: {key}")
                return ActionResult(False, key, detail, cancelled=key == "err.auth_cancelled")
            usb, _ = self.read_usb_status()
            if usb and (usb.enabled or usb.helper_running or usb.iface_present):
                return ActionResult(False, "err.restore_incomplete", res.output)
            self._monitor.reset()
            self.log("Network settings restored")
            return ActionResult(True)
        finally:
            self._end()

    def run_usb_test(self) -> ActionResult:
        """`pdanet usb test`: isolated, changes no routes or DNS. Disallowed while connected."""
        if not self._begin("test"):
            return ActionResult(False, "err.busy")
        try:
            usb, _ = self.read_usb_status()
            if usb and (usb.enabled or usb.helper_running):
                return ActionResult(False, "err.test_while_connected")
            devices, _res = adb.list_devices()
            phone = self.choose_device(devices)
            if phone is None or not phone.authorized or not _SERIAL_OK.match(phone.serial):
                return ActionResult(False, "err.no_device")
            self.log("$ pdanet usb test")
            res = run([config.PDANET_CLI, "usb", "test"], 90, {"PDANET_ADB_SERIAL": phone.serial})
            for line in res.output.splitlines():
                self.log("  " + line)
            if res.ok:
                return ActionResult(True, detail=res.output)
            key, detail = classify_failure(res)
            return ActionResult(False, key, detail)
        finally:
            self._end()

    # ------------------------------------------------------------ logs & diagnostics
    def read_logs(self) -> str:
        parts = ["== GUI events ==", self.event_log() or "(none yet)"]
        helper = run([config.PDANET_CLI, "usb", "logs", "200"], 15, self._status_env())
        parts += ["", "== USB helper log (pdanet usb logs) ==",
                  helper.output or "(empty)"]
        journal = run([config.PDANET_CLI, "logs", "100"], 20, self._status_env())
        parts += ["", "== Services (pdanet logs) ==",
                  journal.output if journal.ok else
                  "(unavailable: " + (journal.output.splitlines()[-1] if journal.output
                                      else f"exit {journal.returncode}") + ")"]
        return "\n".join(parts)

    def diagnostics(self) -> str:
        out: list[str] = []

        def section(title: str, res: CmdResult | str) -> None:
            body = res if isinstance(res, str) else (res.output or f"(no output, exit {res.returncode})")
            out.extend([f"== {title} ==", body, ""])

        section("adb version", adb.version() if adb.adb_available() else "adb not installed")
        devices, listing = adb.list_devices()
        section("adb devices -l", listing)
        phone = self.choose_device(devices)
        if phone and phone.authorized:
            svc = adb.service_listening(phone.serial)
            section("PdaNet+ service on phone (port 8739)",
                    {True: "listening", False: "NOT listening — enable USB Tether in PdaNet+",
                     None: "unknown"}[svc])
        elif phone:
            section("Phone state", f"{phone.serial}: {phone.state}")
        section("adb forward --list", adb.forward_list())
        section("pdanet usb status", run([config.PDANET_CLI, "usb", "status"], 20, self._status_env()))
        section("Interface", run([config.IP_BIN, "-br", "address", "show", "dev", config.USB_IFACE], 5))
        section("Active route to 1.1.1.1", run([config.IP_BIN, "-4", "route", "get", "1.1.1.1"], 5))
        section("IPv6 block routes", f"blocked: {netinfo.ipv6_blocked()}")
        section("Tunnel DNS (resolvectl)", run([config.RESOLVECTL, "dns", config.USB_IFACE], 5))
        section("DNS service", f"{config.USB_DNS_SERVICE}: "
                + ("active" if netinfo.service_active() else "inactive"))
        return "\n".join(out).rstrip() + "\n"


def _exists(path: str) -> bool:
    import os
    return os.path.isdir(path)
