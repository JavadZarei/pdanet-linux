"""Fixed locations of the installed CLI and system resources.

Overrides through environment variables are honoured only when
PDANET_GUI_TESTING=1, so a stray variable can never redirect the GUI to a
different privileged helper.
"""

from __future__ import annotations

import os
import shutil

_TESTING = os.environ.get("PDANET_GUI_TESTING") == "1"


def _path(name: str, default: str) -> str:
    if _TESTING and os.environ.get(name):
        return os.environ[name]
    return default


PDANET_CLI = _path("PDANET_GUI_CLI", "/usr/bin/pdanet")
PKEXEC = _path("PDANET_GUI_PKEXEC", "/usr/bin/pkexec")
GUI_HELPER = _path(
    "PDANET_GUI_HELPER", "/usr/lib/pdanet-linux/libexec/pdanet-gui-helper"
)
ADB = _path("PDANET_GUI_ADB", shutil.which("adb") or "/usr/bin/adb")
RUN_DIR = _path("PDANET_GUI_RUN_DIR", "/run/pdanet-usb")
SYSFS_NET = _path("PDANET_GUI_SYSFS_NET", "/sys/class/net")
PROC_DIR = _path("PDANET_GUI_PROC", "/proc")
IP_BIN = _path("PDANET_GUI_IP", shutil.which("ip") or "/usr/sbin/ip")
SYSTEMCTL = _path("PDANET_GUI_SYSTEMCTL", shutil.which("systemctl") or "/usr/bin/systemctl")
RESOLVECTL = _path("PDANET_GUI_RESOLVECTL", shutil.which("resolvectl") or "/usr/bin/resolvectl")

USB_IFACE = "pdanet0"
USB_DNS_SERVICE = "pdanet-usb-dnscrypt.service"
DNS_ENDPOINT = "127.0.0.1:5300"
PDANET_PORT = 8739
