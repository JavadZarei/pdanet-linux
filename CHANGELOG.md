# Changelog

## 1.0.0
- Native GTK4/libadwaita desktop app (English and Persian/RTL) for the existing PdaNet USB CLI.
- Dashboard with live status, network info and traffic read from kernel counters; logs, diagnostics, settings.
- Privileged operations through a polkit-guarded helper that accepts three validated commands.
- Detection and one-click recovery after an unexpected USB unplug.
- Debian package that never overwrites existing configuration and never stops an active tunnel.
