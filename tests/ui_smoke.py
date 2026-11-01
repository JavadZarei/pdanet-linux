"""Smoke test with REAL GTK4/libadwaita. Run under a display, e.g. `xvfb-run -a python3 tests/ui_smoke.py`.

Uses the fake system from tests/unit/_env.py, so it needs no phone, adb or root.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "unit"))
import _env  # noqa: E402,F401  (installs fake adb/pdanet/ip and env overrides)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from pdanet_gui import i18n  # noqa: E402
from pdanet_gui.ui.app import PdaNetApp  # noqa: E402


def pump(seconds: float) -> None:
    ctx = GLib.MainContext.default()
    end = time.time() + seconds
    while time.time() < end:
        while ctx.iteration(False):
            pass
        time.sleep(0.02)


def check(cond: bool, message: str) -> None:
    if not cond:
        print("FAIL:", message)
        sys.exit(1)
    print("ok:", message)


app = PdaNetApp()
app.register(Gio.Cancellable())
app.activate()
pump(2.0)
check(app.window is not None, "main window created with real widgets")
check(app.window.hero_state.get_text() == "Disconnected", "dashboard shows Disconnected from fake system")
check(app.window.primary.get_sensitive(), "Connect is enabled for an authorized phone with USB Tether")
check("SM-A546E" in app.window.row_phone.get_subtitle(), "phone model shown")

app.settings.language = "fa"
app.rebuild_window()
pump(2.0)
check(Gtk.Widget.get_default_direction() == Gtk.TextDirection.RTL, "RTL direction in Persian")
check(app.window.hero_state.get_text() == "قطع", "Persian strings rendered")

i18n.set_language("en")
print("UI smoke test passed")
