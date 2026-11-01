"""Shared fake system for the unit tests. Import this BEFORE any pdanet_gui module."""

import os
import shutil
import stat
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "gui"))

TMP = tempfile.mkdtemp(prefix="pdanet-gui-test-")
FAKE = os.path.join(TMP, "state")
BIN = os.path.join(TMP, "bin")
SYSFS = os.path.join(TMP, "sys-class-net")
PROC = os.path.join(TMP, "proc")
RUN = os.path.join(TMP, "run-pdanet-usb")
for d in (FAKE, BIN, SYSFS, PROC):
    os.makedirs(d, exist_ok=True)

ENABLED = """PdaNet USB: enabled
  Device:       R5CWC1234
  Phone target: tcp:8739
  ADB forward:  active (127.0.0.1:41234)
  Helper:       running (PID 4242)
  Interface:    pdanet0 (present)
  Routes:       active
  DNS service:  active
"""
DISABLED = """PdaNet USB: disabled
  Device:       none
  Phone target: none
  ADB forward:  missing
  Helper:       stopped
  Interface:    pdanet0 (missing)
  Routes:       inactive
  DNS service:  inactive
"""
STALE = """PdaNet USB: disabled
  Device:       R5CWC1234
  Phone target: tcp:8739
  ADB forward:  missing
  Helper:       stopped
  Interface:    pdanet0 (missing)
  Routes:       inactive
  DNS service:  active
"""
DEVICES_OK = ("R5CWC1234\tdevice usb:1-2 product:a54xnsxx model:SM_A546E "
              "device:a54x transport_id:3\n")
DEVICES_UNAUTH = "R5CWC1234\tunauthorized usb:1-2 transport_id:3\n"


def script(name: str, body: str) -> str:
    path = os.path.join(BIN, name)
    with open(path, "w") as fh:
        fh.write("#!/usr/bin/env bash\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


def put(name: str, text: str) -> None:
    with open(os.path.join(FAKE, name), "w") as fh:
        fh.write(text)


def remove(name: str) -> None:
    try:
        os.unlink(os.path.join(FAKE, name))
    except FileNotFoundError:
        pass


def reset() -> None:
    for name in os.listdir(FAKE):
        os.unlink(os.path.join(FAKE, name))
    shutil.rmtree(RUN, ignore_errors=True)
    shutil.rmtree(os.path.join(SYSFS, "pdanet0"), ignore_errors=True)
    put("usb_status.txt", DISABLED)
    put("usb_status_enabled.txt", ENABLED)
    put("usb_status_disabled.txt", DISABLED)
    put("devices.txt", DEVICES_OK)
    put("svc_ss.txt", "LISTEN 0 50 127.0.0.1:8739 0.0.0.0:*\n")
    put("route_get.txt", "1.1.1.1 via 192.168.1.1 dev wlp2s0 src 192.168.1.20 uid 1000\n")
    put("default_route.txt", "default via 192.168.1.1 dev wlp2s0 proto dhcp metric 600\n")
    put("v6.txt", "fe80::/64 dev wlp2s0 proto kernel metric 1024 pref medium\n")
    put("dns_active.txt", "inactive\n")
    put("resolvectl.txt", "Link 5 (pdanet0):\n")
    put("pkexec.log", "")


def set_sysfs(rx: int, tx: int) -> None:
    d = os.path.join(SYSFS, "pdanet0", "statistics")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "rx_bytes"), "w") as fh:
        fh.write(f"{rx}\n")
    with open(os.path.join(d, "tx_bytes"), "w") as fh:
        fh.write(f"{tx}\n")


script("pdanet", r'''
D="$FAKE_DIR"
if [[ "$1 $2" == "usb status" ]]; then cat "$D/usb_status.txt"
elif [[ "$1 $2" == "usb logs" ]]; then
  if [[ -f "$D/helper.log" ]]; then cat "$D/helper.log"; else echo "  ERROR  No PdaNet USB helper log exists." >&2; exit 1; fi
elif [[ "$1 $2" == "usb test" ]]; then
  echo "PdaNet USB isolated test"
  if [[ -f "$D/test_fail" ]]; then echo "  ERROR  The isolated USB protocol test failed." >&2; exit 1; fi
  echo "  OK  USB protocol, phone forwarding, and response decoding passed."
elif [[ "$1" == "logs" ]]; then echo "journal: pdanet-cli enabled"
else exit 2; fi
''')
script("pkexec", r'''
D="$FAKE_DIR"
echo "$*" >> "$D/pkexec.log"
[[ -f "$D/pkexec_delay" ]] && sleep "$(cat "$D/pkexec_delay")"
if [[ -f "$D/pkexec_rc" ]]; then cat "$D/pkexec_out" >&2 2>/dev/null; exit "$(cat "$D/pkexec_rc")"; fi
case "$2" in
  connect) cp "$D/usb_status_enabled.txt" "$D/usb_status.txt" ;;
  disconnect|restore) cp "$D/usb_status_disabled.txt" "$D/usb_status.txt" ;;
esac
''')
script("adb", r'''
D="$FAKE_DIR"
if [[ "$1" == "devices" ]]; then echo "List of devices attached"; cat "$D/devices.txt"
elif [[ "$1" == "version" ]]; then echo "Android Debug Bridge version 1.0.41"
elif [[ "$1" == "forward" ]]; then echo "R5CWC1234 tcp:41234 tcp:8739"
elif [[ "$1" == "-s" && "$3" == "shell" && "$4" == "ss" ]]; then cat "$D/svc_ss.txt"
elif [[ "$1" == "-s" && "$3" == "shell" && "$4" == "cat" ]]; then cat "$D/svc_unix.txt" 2>/dev/null; exit 0
else exit 1; fi
''')
script("ip", r'''
D="$FAKE_DIR"
case "$*" in
  "-4 route get 1.1.1.1") cat "$D/route_get.txt" ;;
  "-4 route show default") cat "$D/default_route.txt" ;;
  "-6 route show") cat "$D/v6.txt" ;;
  *) echo "pdanet0 UP 10.1.19.2/24" ;;
esac
''')
script("systemctl", r'''cat "$FAKE_DIR/dns_active.txt"''')
script("resolvectl", r'''cat "$FAKE_DIR/resolvectl.txt"''')
script("helper-stub", "exit 0\n")

os.environ.update({
    "PDANET_GUI_TESTING": "1",
    "FAKE_DIR": FAKE,
    "PDANET_GUI_CLI": os.path.join(BIN, "pdanet"),
    "PDANET_GUI_PKEXEC": os.path.join(BIN, "pkexec"),
    "PDANET_GUI_HELPER": os.path.join(BIN, "helper-stub"),
    "PDANET_GUI_ADB": os.path.join(BIN, "adb"),
    "PDANET_GUI_IP": os.path.join(BIN, "ip"),
    "PDANET_GUI_SYSTEMCTL": os.path.join(BIN, "systemctl"),
    "PDANET_GUI_RESOLVECTL": os.path.join(BIN, "resolvectl"),
    "PDANET_GUI_RUN_DIR": RUN,
    "PDANET_GUI_SYSFS_NET": SYSFS,
    "PDANET_GUI_PROC": PROC,
    "XDG_CONFIG_HOME": os.path.join(TMP, "config"),
})
reset()
