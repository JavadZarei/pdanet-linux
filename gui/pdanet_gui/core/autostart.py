"""Launch-at-login via an XDG autostart entry in the user's config directory."""

from __future__ import annotations

import os

from .. import APP_ID

_TEMPLATE = """[Desktop Entry]
Type=Application
Name=PdaNet
Exec=pdanet-gui --background
Icon={app_id}
Terminal=false
X-GNOME-Autostart-enabled=true
"""


def autostart_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "autostart", f"{APP_ID}.desktop")


def is_enabled() -> bool:
    return os.path.isfile(autostart_path())


def set_enabled(enabled: bool) -> None:
    path = autostart_path()
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_TEMPLATE.format(app_id=APP_ID))
    else:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
