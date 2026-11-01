"""Reusable libadwaita building blocks."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

_LEVELS = {
    "ok": ("emblem-ok-symbolic", "success"),
    "warn": ("dialog-warning-symbolic", "warning"),
    "bad": ("dialog-error-symbolic", "error"),
    "off": ("media-record-symbolic", "dim-label"),
}
_ALL_CLASSES = ("success", "warning", "error", "dim-label")


class StatusRow(Adw.ActionRow):
    """A row with a value (subtitle) and a coloured status icon."""

    def __init__(self, title: str) -> None:
        super().__init__(title=title, subtitle="—")
        self.dot = Gtk.Image()
        self.add_suffix(self.dot)
        self.set_activatable(False)
        self.set_subtitle_selectable(True)
        self.update("—", "off")

    def update(self, value: str, level: str = "off") -> None:
        icon, css = _LEVELS[level]
        self.set_subtitle(value)
        self.dot.set_from_icon_name(icon)
        for name in _ALL_CLASSES:
            self.dot.remove_css_class(name)
        self.dot.add_css_class(css)


class ValueRow(Adw.ActionRow):
    """A row with just a selectable value."""

    def __init__(self, title: str) -> None:
        super().__init__(title=title, subtitle="—")
        self.set_activatable(False)
        self.set_subtitle_selectable(True)

    def update(self, value: str) -> None:
        self.set_subtitle(value)


class StatCard(Gtk.Box):
    def __init__(self, caption: str, small: bool = False) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.add_css_class("card")
        self.add_css_class("stat-card")
        self.caption = Gtk.Label(label=caption, xalign=0)
        self.caption.add_css_class("dim-label")
        self.caption.add_css_class("caption")
        self.value = Gtk.Label(label="—", xalign=0)
        self.value.add_css_class("stat-value-sm" if small else "stat-value")
        self.value.set_ellipsize(3)  # Pango.EllipsizeMode.END
        self.append(self.caption)
        self.append(self.value)

    def update(self, text: str) -> None:
        self.value.set_text(text)
