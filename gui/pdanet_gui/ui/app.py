"""Adw.Application: language/theme setup and window lifecycle."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import APP_ID, __version__, i18n
from ..core import settings as settings_mod
from ..core.controller import Controller
from ..i18n import tr as _
from .style import CSS
from .window import MainWindow


class PdaNetApp(Adw.Application):
    def __init__(self, background: bool = False) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.background = background
        self.settings = settings_mod.load()
        self.controller = Controller()
        self.window: MainWindow | None = None
        self._css_loaded = False

    # ---------------------------------------------------------------- lifecycle
    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._show_about)
        self.add_action(about)
        self.apply_language()
        self.apply_theme()
        self._load_css()

    def do_activate(self) -> None:
        first = self.window is None
        if first:
            self.window = MainWindow(self, self.controller, self.settings)
        self.window.present()
        if first and (self.background or self.settings.start_minimized):
            self.window.minimize()

    # ---------------------------------------------------------------- appearance
    def apply_language(self) -> None:
        i18n.set_language(self.settings.language)
        Gtk.Widget.set_default_direction(
            Gtk.TextDirection.RTL if i18n.is_rtl() else Gtk.TextDirection.LTR)

    def apply_theme(self) -> None:
        scheme = {
            "system": Adw.ColorScheme.DEFAULT,
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }[self.settings.theme]
        Adw.StyleManager.get_default().set_color_scheme(scheme)

    def _load_css(self) -> None:
        if self._css_loaded:
            return
        from gi.repository import Gdk
        provider = Gtk.CssProvider()
        if hasattr(provider, "load_from_string"):
            provider.load_from_string(CSS)
        else:
            provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._css_loaded = True

    def rebuild_window(self) -> bool:
        """Re-create the window so a new language and text direction take effect."""
        self.apply_language()
        old = self.window
        self.window = MainWindow(self, self.controller, self.settings)
        self.window.present()
        if old is not None:
            old.destroy()
        return GLib.SOURCE_REMOVE

    # ---------------------------------------------------------------- misc
    def notify_unplug(self) -> None:
        note = Gio.Notification.new(_("notify.unplug.title"))
        note.set_body(_("notify.unplug.body"))
        self.send_notification("pdanet-unplug", note)

    def _show_about(self, *_args) -> None:
        cls = getattr(Adw, "AboutDialog", None)
        if cls is not None:
            dialog = cls(application_name=_("app.title"), application_icon=APP_ID,
                         version=__version__, comments=_("about.comments"))
            dialog.present(self.window)
        else:
            dialog = Adw.AboutWindow(application_name=_("app.title"), application_icon=APP_ID,
                                     version=__version__, comments=_("about.comments"),
                                     transient_for=self.window)
            dialog.present()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    background = "--background" in argv
    argv = [a for a in argv if a != "--background"]
    return PdaNetApp(background=background).run(argv)
