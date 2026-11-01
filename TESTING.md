# Test report — pdanet-linux 1.0.0

Everything below marked **PASS** was actually executed in the build sandbox (Debian-family Linux, dpkg 1.22.6,
Python 3.12). The sandbox has **no GTK4/libadwaita, no phone, no USB, no network, no polkit, no GNOME session**,
so anything needing those is listed under *NOT TESTED* and has to be verified on your Ubuntu 24.04 machine.

## Executed and passed

| Area | What was run | Result |
|---|---|---|
| Existing project tests | `tests/usb-selection.sh`, `pdanet-usb-helper --self-test` (run by `build-deb.sh` every build) | PASS |
| Unit tests | 66 tests, `python3 -m unittest discover -s tests/unit`, also with `-W error::ResourceWarning` | PASS |
| `pdanet usb status` parser | enabled / disabled / stale / Wi-Fi+USB combined / garbage / unknown field formats | PASS |
| Real CLI output → parser | the unmodified `bin/pdanet usb status` run unprivileged (fake adb/ip/systemctl) and parsed | PASS |
| ADB parsing | authorized, unauthorized, offline, "no permissions", daemon start lines, USB vs network serials | PASS |
| Traffic | rates from successive counter reads; counter reset on interface recreation; sysfs reader | PASS |
| Controller (fake system) | refresh states, connect/disconnect/restore via `pkexec <helper>`, failure-message mapping, auth cancelled, success-but-not-enabled detected, incomplete restore reported, hostile serial never reaches root, **duplicate attempts rejected while busy**, no password prompt when phone missing/unauthorized/service off | PASS |
| Unplug recovery (logic) | stale state (IPv6 blackhole + DNS service, no helper) detected → `NEEDS_RESTORE`; unexpected loss notifies, user disconnect doesn't; optional auto-restore fires once; auto-connect off by default, fires once when on | PASS |
| Root helper validation | accepts exactly `connect SERIAL` / `disconnect` / `restore`; 15 hostile/malformed argument vectors rejected; env is only PATH/LC_ALL/HOME(+serial); older-install helper path passed back to CLI; refuses to run unprivileged | PASS |
| Command safety | argv-only runner rejects strings; `$(…)`/backticks not interpreted; timeouts return cleanly; missing binary handled | PASS |
| Settings / autostart | round-trip, corrupt JSON, hostile values, XDG autostart entry create/remove | PASS |
| i18n | EN/FA key parity (128 keys), placeholder parity, every key used in code exists, RTL flag, system-locale resolution | PASS |
| UI logic with **stubbed** `gi` | window/app code executed: hero text/button states, phone-problem messages, connected view with real counters, stale banner, Persian rendering, settings persistence, window close stops polling, app startup/rebuild | PASS (see caveat) |
| Package integrity | `dpkg-deb` readable, md5sums verified, root:root ownership, no setuid/world-writable files | PASS |
| Package contents | CLI and USB helper **byte-identical** to your uploaded project; unit file identical; polkit policy + SVG well-formed XML; desktop entry has required keys and Icon matches installed file; 21 Python files compile; maintainer scripts pass `sh -n` | PASS |
| Installation (real `dpkg -i`) | installs; pre-existing customized config **kept**; identical pre-existing file not claimed; missing configs created; active `/run/pdanet-usb` untouched; postinst compiled bytecode; reinstall idempotent | PASS |
| Removal / purge (real `dpkg -r`, `-P`) | remove keeps configs and session state; purge removes only package-created **unmodified** configs; user-edited and pre-existing files survive | PASS |

A bug found by this testing and fixed before the final build: purge originally removed nothing, because the
shipped defaults are already gone by purge time. It now records a checksum at creation.

## Confirmed on real hardware (from the maintainer's own logs, Ubuntu 24.04, SM-A546E)

* `.deb` installs; `pdanet-gui` launches and renders; Logs, Copy logs and Run diagnostics work.
* The phone is detected over USB with model and serial; PdaNet+ service on port 8739 is detected as listening.
* Connect goes through pkexec and `pdanet-gui-helper`; the CLI runs as root and brings up `pdanet0`, routes and
  the DNS service.
* On a failed activation (DNS-over-HTTPS check failed through the phone) the CLI rolled everything back; the
  GUI diagnostics afterwards showed no `pdanet0`, no IPv6 block routes, DNS service inactive, normal Wi-Fi route.
* `sudo pdanet usb` from a terminal fails identically, so that failure is outside the GUI.

## NOT TESTED — please verify on the real machine

* A successful end-to-end connection (blocked so far by the DoH check on the tested mobile network), so also:
  live traffic numbers, public IP, uptime, DNS/IPv6 rows while connected, and disconnect after a real session.
* `tests/ui_smoke.py` (real GTK under Xvfb) is run by CI; it could not be executed in the build sandbox.
* Dark/light switching, Persian RTL layout and the icon in the Applications grid.
* Unplug recovery on real hardware (exercised only against simulated status output).
* The polkit dialog. The policy's `exec.path` points at the helper script. pkexec may resolve a `#!` script to
  its interpreter and then not match this action; the safe fallback is the generic "authentication required"
  prompt each time (no privilege is widened either way). Check which dialog you get.
* Live traffic numbers on `pdanet0`, public-IP lookup, uptime and DNS rows against your real tunnel.
* Migration with a tunnel started by `~/.local/bin/pdanet` (path-detection logic is unit-tested, not run live).
* `lintian` (not installable here); Ubuntu dependency resolution through `apt` (installed with `--force-depends`
  because the sandbox lacks those packages).
* Verify `command -v dnscrypt-proxy` resolves to `/usr/sbin/dnscrypt-proxy` (the shipped unit files hardcode it).
