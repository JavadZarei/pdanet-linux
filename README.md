# PdaNet Linux — desktop application

> **Unofficial.** This project is not affiliated with, endorsed by, or sponsored by the makers of PdaNet+.
> "PdaNet" is used only to describe compatibility. You need the PdaNet+ app on your phone.

A native GTK4 / libadwaita front end for the existing, working `pdanet` USB
tunnel (ADB forward → PdaNet+ service on TCP 8739 → `pdanet0` TUN → DoH DNS via
`dnscrypt-proxy` on 127.0.0.1:5300). The USB protocol, packet framing, TUN,
routing and DNS logic are **unchanged**; the app only drives them.

Target: Ubuntu 24.04 LTS, amd64, GNOME (Wayland or X11).

## Status

Confirmed on real hardware (Ubuntu 24.04, Samsung Galaxy A54): package install, app launch, phone and
PdaNet+ service detection, privileged connect through polkit, diagnostics/logs, and clean rollback of a failed
activation. Full end-to-end connection depends on your mobile network letting the DNS-over-HTTPS check
through; see [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). Details and the list of what is still
unverified: [TESTING.md](TESTING.md).

## Install

```bash
sudo apt install ./pdanet-linux_1.0.0_amd64.deb     # resolves dependencies from Ubuntu
```

(Double-clicking the `.deb` in the file manager opens it in Software, which does the same.)
Then open **PdaNet** from the Applications grid. Nothing needs the terminal.

Installing never overwrites configuration and never touches a running tunnel:

* Existing `/etc/nftables-pdanet.nft`, `/etc/dnscrypt-proxy-pdanet*.toml`, `/etc/redsocks-pdanet.conf`
  are kept; defaults are copied only if a file is missing.
* An older `~/.local/bin/pdanet` is left alone. **The app always runs `/usr/bin/pdanet`.**
  Your shell may still find `~/.local/bin/pdanet` first; remove it when you are ready.
* If a tunnel started by the old install is running, the app and its privileged helper detect
  the helper process that is actually running and address it correctly, so
  Disconnect still works. For the smoothest first run, disconnect before installing anyway.

## Use

1. Phone: enable USB debugging, plug in the cable, accept the "Allow USB debugging?" prompt,
   open **PdaNet+** and turn on **USB Tether**.
2. In the app the phone appears in *Connection*. Press **Connect** and enter your password
   (polkit dialog; the app itself never runs as root and never stores a password).
3. The dashboard shows live status, public IPv4, active/tunnel interface, DNS routing, IPv6
   leak protection, uptime and traffic read from `/sys/class/net/pdanet0/statistics`.
4. **Disconnect** restores routes and DNS through `pdanet usb off`.

Closing the window does **not** disconnect: the tunnel belongs to the system, not the window.

### If the phone is unplugged
The helper dies, the TUN device and IPv4 routes vanish by themselves, but the IPv6 blackhole
routes and the DNS service remain. The app detects this, shows **"Network needs restoring"**
and a **Restore network** button (one password prompt). Optional auto-restore is in Settings.

### If connecting fails
The app explains the reason in plain language. The most common one on some carriers is
*"The phone link came up, but the Internet check through it failed"*. Nothing is left changed after a failed
attempt. See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for fixes, including switching the DoH provider.

### Tabs
* **Dashboard** – everything above.
* **Logs** – GUI events, `pdanet usb logs`, `pdanet logs`; *Copy logs*; *Run diagnostics* (ADB, service,
  route, DNS, IPv6 checks).
* **Settings** – language (System / English / فارسی, RTL), theme, launch at login, start minimized,
  auto-connect, auto-restore, public-IP lookup (contacts api.ipify.org / icanhazip.com; can be disabled),
  refresh interval, USB test (`pdanet usb test`, only while disconnected).

## Architecture

```
pdanet-gui (GTK, user)  ──argv arrays, timeouts──►  /usr/bin/pdanet usb status|logs|test   (unprivileged reads)
        │                                           adb devices -l / forward --list        (as the user)
        │  pkexec (polkit action org.pdanet.desktop.manage)
        └────────────►  /usr/lib/pdanet-linux/libexec/pdanet-gui-helper  connect SERIAL | disconnect | restore
                              └─► /usr/lib/pdanet-linux/bin/pdanet usb on|off   (the unchanged CLI, fixed env)
```

* `gui/pdanet_gui/core` – GTK-free logic: strict parsers, controller state machine, traffic monitor.
* `gui/pdanet_gui/ui` – libadwaita window and application.
* `libexec/pdanet-gui-helper` – the only code run as root by the GUI. It accepts exactly three
  commands, validates the ADB serial (`^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$`), passes the serial
  through the environment (never argv), and executes the CLI by absolute path with a minimal fixed environment.
* The GUI starts the **user's** ADB server first. A root `adb` client otherwise starts a root server whose
  key the phone has never authorised.

## Security notes

* No passwords stored; the GUI never runs as root; no shell strings anywhere (`subprocess` argv lists, timeouts).
* Dev/test path overrides (`PDANET_GUI_*`) are ignored unless `PDANET_GUI_TESTING=1`.
* Settings: `~/.config/pdanet-linux/settings.json`; autostart: `~/.config/autostart/org.pdanet.Desktop.desktop`.

## Removal

```bash
sudo apt remove pdanet-linux      # keeps configs; never stops an active tunnel
sudo apt purge pdanet-linux       # also removes only the config files this package itself created and that are unmodified
```

If a tunnel is active when you remove the package, run `pdanet usb off` (or disconnect in the app first).

## Build from source

```bash
./build-deb.sh        # runs unit tests, then builds dist/pdanet-linux_1.0.0_amd64.deb (needs dpkg-deb, python3)
python3 -m unittest discover -s tests/unit
```

Runtime dependencies are Ubuntu packages only: `python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 adb dnscrypt-proxy iproute2
curl gawk systemd-resolved pkexec` (Recommends `redsocks nftables` for the Wi-Fi proxy mode of the CLI).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports: use the issue template and remove serial numbers and IPs from logs.

## Licence

No licence has been chosen yet; until a `LICENSE` file is added, all rights are reserved by the author.
