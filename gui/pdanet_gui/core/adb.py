"""Read-only ADB queries, always run as the normal user (never as root)."""

from __future__ import annotations

import os
import re

from . import config
from .parsers import AdbDevice, parse_adb_devices
from .runner import CmdResult, run


def adb_available() -> bool:
    return os.path.isfile(config.ADB) and os.access(config.ADB, os.X_OK)


def list_devices(timeout: float = 15.0) -> tuple[list[AdbDevice], CmdResult]:
    """`adb devices -l` as the user; also starts the user's ADB server if needed.

    Starting the server here matters: a root `adb` client would otherwise start a
    root server whose key the phone has never authorised.
    """
    result = run([config.ADB, "devices", "-l"], timeout)
    devices = parse_adb_devices(result.stdout) if result.ok else []
    return devices, result


def service_listening(serial: str, timeout: float = 10.0) -> bool | None:
    """Is the PdaNet+ USB service reachable on the phone? None when unknown."""
    shell_ss = run([config.ADB, "-s", serial, "shell", "ss", "-H", "-ltn"], timeout)
    if shell_ss.ok:
        for line in shell_ss.stdout.splitlines():
            cols = line.split()
            if len(cols) >= 4 and cols[3].endswith(f":{config.PDANET_PORT}"):
                return True
    unix = run([config.ADB, "-s", serial, "shell", "cat", "/proc/net/unix"], timeout)
    if unix.ok:
        if re.search(r"(^|[@/])pdanet(\s|$)", unix.stdout, re.MULTILINE):
            return True
        return False if shell_ss.ok else None
    return None if not shell_ss.ok else False


def forward_list(timeout: float = 10.0) -> CmdResult:
    return run([config.ADB, "forward", "--list"], timeout)


def version(timeout: float = 10.0) -> CmdResult:
    return run([config.ADB, "version"], timeout)
