"""Exercise window.py / app.py logic with a stubbed `gi`.

This does NOT validate real GTK behaviour (GTK4/libadwaita are unavailable in the
build sandbox). It catches typos, bad attribute names, wrong state transitions,
settings handling and RTL switching in our own code.
"""

import sys
import time
import types
import unittest

from _env import *  # noqa: F401,F403
import _env


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _make(name)


_cache: dict = {}


def _make(name):
    if name not in _cache:
        _cache[name] = _Meta(name, (Stub,), {})
    return _cache[name]


class Stub(metaclass=_Meta):
    def __init__(self, *args, **kwargs):
        self.__dict__["_calls"] = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def method(*args, **kwargs):
            self.__dict__.setdefault("_calls", []).append((name, args))
            return Stub()
        return method

    def last(self, name):
        for call, args in reversed(self.__dict__.get("_calls", [])):
            if call == name:
                return args[0] if args else None
        raise AssertionError(f"{name} never called")


class _GLib:
    SOURCE_CONTINUE = True
    SOURCE_REMOVE = False

    @staticmethod
    def idle_add(fn, *args):
        fn(*args)
        return 1

    @staticmethod
    def timeout_add_seconds(_s, _fn, *a):
        return 1

    @staticmethod
    def source_remove(_id):
        return True


class _Repo(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _GLib if name == "GLib" else _make(name)


def setUpModule():
    gi = types.ModuleType("gi")
    gi.require_version = lambda *a, **k: None
    repo = _Repo("gi.repository")
    gi.repository = repo
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repo


def tearDownModule():
    for name in [m for m in sys.modules if m == "gi" or m.startswith("gi.")
                 or m.startswith("pdanet_gui.ui")]:
        del sys.modules[name]


def pklog():
    with open(_env.FAKE + "/pkexec.log") as fh:
        return fh.read()


def wait_for(cond, timeout=4.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class FakeApp:
    def __init__(self):
        self.notified = 0
        self.theme = 0

    def notify_unplug(self):
        self.notified += 1

    def apply_theme(self):
        self.theme += 1

    def rebuild_window(self):
        return False


class WindowLogic(unittest.TestCase):
    def make(self, **cfg):
        from pdanet_gui import i18n
        from pdanet_gui.core import settings as S
        from pdanet_gui.core.controller import Controller
        from pdanet_gui.ui.window import MainWindow
        i18n.set_language("en")
        _env.reset()
        self.i18n = i18n
        self.app = FakeApp()
        self.ctrl = Controller()
        settings = S.Settings(**cfg)
        win = MainWindow(self.app, self.ctrl, settings)
        wait_for(lambda: not win._refreshing)
        return win

    def snap(self, win):
        return self.ctrl.refresh()

    def test_disconnected_ready(self):
        win = self.make()
        win._apply_snapshot(self.snap(win))
        self.assertEqual(win.hero_state.last("set_text"), "Disconnected")
        self.assertEqual(win.hero_sub.last("set_text"), "SM-A546E is ready")
        self.assertTrue(win.primary.last("set_sensitive"))
        self.assertEqual(win.primary.last("set_label"), "Connect")
        self.assertIn("SM-A546E", win.row_phone.last("set_subtitle"))

    def test_phone_problems_disable_connect_with_clear_message(self):
        win = self.make()
        _env.put("devices.txt", _env.DEVICES_UNAUTH)
        win._apply_snapshot(self.snap(win))
        self.assertFalse(win.primary.last("set_sensitive"))
        self.assertEqual(win.hero_sub.last("set_text"), "Allow USB debugging on the phone")
        _env.put("devices.txt", "")
        win._apply_snapshot(self.snap(win))
        self.assertEqual(win.hero_sub.last("set_text"), "Connect your phone with a USB cable")
        _env.put("devices.txt", _env.DEVICES_OK)
        _env.put("svc_ss.txt", "")
        win._apply_snapshot(self.snap(win))
        self.assertFalse(win.primary.last("set_sensitive"))
        self.assertEqual(win.hero_sub.last("set_text"), "Turn on USB Tether in the PdaNet+ app")

    def test_connected_view_uses_real_counters(self):
        win = self.make(lookup_public_ip=False)
        _env.put("usb_status.txt", _env.ENABLED)
        _env.set_sysfs(2048, 1024)
        win._apply_snapshot(self.snap(win))
        self.assertEqual(win.hero_state.last("set_text"), "Connected")
        self.assertEqual(win.primary.last("set_label"), "Disconnect")
        self.assertEqual(win.card_down.value.last("set_text"), "2.00 KiB")
        self.assertEqual(win.card_up.value.last("set_text"), "1.00 KiB")
        self.assertEqual(win.card_total.value.last("set_text"), "3.00 KiB")
        self.assertEqual(win.row_ip.last("set_subtitle"), "Lookup disabled")

    def test_stale_state_shows_restore(self):
        win = self.make()
        _env.put("usb_status.txt", _env.STALE)
        _env.put("dns_active.txt", "active\n")
        win._apply_snapshot(self.snap(win))
        self.assertEqual(win.primary.last("set_label"), "Restore network")
        self.assertTrue(win.restore_banner.last("set_revealed"))
        self.assertEqual(win.hero_state.last("set_text"), "Network needs restoring")

    def test_unexpected_unplug_notifies_but_user_disconnect_does_not(self):
        win = self.make()
        _env.put("usb_status.txt", _env.ENABLED)
        win._apply_snapshot(self.snap(win))
        _env.put("usb_status.txt", _env.STALE)
        _env.put("dns_active.txt", "active\n")
        win._apply_snapshot(self.snap(win))
        self.assertEqual(self.app.notified, 1)
        self.assertEqual(win.error_banner.last("set_title"), "The phone was disconnected unexpectedly.")

        win2 = self.make()
        _env.put("usb_status.txt", _env.ENABLED)
        win2._apply_snapshot(self.snap(win2))
        win2._intentional = True
        _env.put("usb_status.txt", _env.DISABLED)
        win2._apply_snapshot(self.snap(win2))
        self.assertEqual(self.app.notified, 0)

    def test_auto_restore_runs_privileged_restore_once(self):
        win = self.make(auto_restore=True)
        _env.put("usb_status.txt", _env.ENABLED)
        win._apply_snapshot(self.snap(win))
        _env.put("usb_status.txt", _env.STALE)
        _env.put("dns_active.txt", "active\n")
        win._apply_snapshot(self.snap(win))
        self.assertTrue(wait_for(lambda: "restore" in pklog()))
        self.assertEqual(pklog().count("restore"), 1)

    def test_auto_connect_is_off_by_default_and_fires_once_when_on(self):
        win = self.make()
        win._apply_snapshot(self.snap(win))
        self.assertEqual(pklog(), "")

        win = self.make(auto_connect=True)
        win._apply_snapshot(self.snap(win))
        self.assertTrue(wait_for(lambda: "connect R5CWC1234" in pklog()))
        wait_for(lambda: not win._ui_busy)
        _env.put("usb_status.txt", _env.DISABLED)   # user's session ended; phone still attached
        win._apply_snapshot(self.snap(win))
        time.sleep(0.2)
        self.assertEqual(pklog().count("connect"), 1)

    def test_primary_button_ignored_while_busy(self):
        win = self.make()
        win._apply_snapshot(self.snap(win))
        win._ui_busy = True
        win._on_primary(None)
        self.assertEqual(pklog(), "")

    def test_cancelled_auth_shows_no_error_banner(self):
        win = self.make()
        win._apply_snapshot(self.snap(win))
        _env.put("pkexec_rc", "126")
        win._on_primary(None)
        self.assertTrue(wait_for(lambda: "connect" in pklog()))
        wait_for(lambda: not win._ui_busy)
        with self.assertRaises(AssertionError):
            win.error_banner.last("set_title")

    def test_failed_connect_shows_translated_error(self):
        win = self.make()
        win._apply_snapshot(self.snap(win))
        _env.put("pkexec_rc", "1")
        _env.put("pkexec_out", "  ERROR  PdaNet USB is not listening.\n")
        win._on_primary(None)
        self.assertTrue(wait_for(lambda: not win._ui_busy and win.error_banner._calls))
        self.assertIn("USB Tether", win.error_banner.last("set_title"))

    def test_persian_rendering(self):
        win = self.make()
        self.i18n.set_language("fa")
        win._apply_snapshot(self.snap(win))
        self.assertEqual(win.hero_state.last("set_text"), "قطع")
        self.assertEqual(win.primary.last("set_label"), "اتصال")
        self.i18n.set_language("en")

    def test_close_stops_polling(self):
        win = self.make()
        win._on_close()
        self.assertFalse(win._alive)
        win.request_refresh()
        self.assertFalse(win._refreshing)

    def test_settings_handler_persists_and_triggers_theme(self):
        from pdanet_gui.core import settings as S
        win = self.make()
        win.opt_language.get_selected = lambda: 2
        win.opt_theme.get_selected = lambda: 2
        win.opt_poll.get_selected = lambda: 2
        for name in ("opt_login", "opt_minimized", "opt_auto_connect", "opt_auto_restore", "opt_public_ip"):
            getattr(win, name).get_active = lambda: True
        win._on_setting_changed()
        saved = S.load()
        self.assertEqual((saved.language, saved.theme, saved.poll_seconds), ("fa", "dark", 5))
        self.assertTrue(saved.auto_connect and saved.launch_at_login)
        self.assertEqual(self.app.theme, 1)
        from pdanet_gui.core import autostart
        self.assertTrue(autostart.is_enabled())
        autostart.set_enabled(False)


class AppLogic(unittest.TestCase):
    def test_app_startup_activate_rebuild(self):
        from pdanet_gui import i18n
        from pdanet_gui.ui.app import PdaNetApp
        app = PdaNetApp(background=True)
        app.settings.language = "fa"
        app.do_startup()
        self.assertTrue(i18n.is_rtl())
        app.do_activate()
        first = app.window
        self.assertIsNotNone(first)
        app.rebuild_window()
        self.assertIsNot(app.window, first)
        app.notify_unplug()
        app._show_about()
        i18n.set_language("en")


if __name__ == "__main__":
    unittest.main()
