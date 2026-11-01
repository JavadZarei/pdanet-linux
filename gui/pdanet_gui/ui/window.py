"""Main window: dashboard, logs and settings pages."""

from __future__ import annotations

import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk  # noqa: E402

from .. import i18n  # noqa: F401
from ..core import autostart, settings as settings_mod
from ..core.controller import ActionResult, Controller, Snapshot, State
from ..core.fmt import human_bytes, human_duration, human_rate
from ..core.netinfo import fetch_public_ip
from ..i18n import tr as _
from .widgets import StatCard, StatusRow, ValueRow

_IP_REFRESH_SECONDS = 120


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, controller: Controller, settings: settings_mod.Settings) -> None:
        super().__init__(application=app)
        self.app = app
        self.ctrl = controller
        self.cfg = settings
        self._alive = True
        self._refreshing = False
        self._ui_busy = False
        self._snap: Snapshot | None = None
        self._intentional = False       # user asked for the last disconnect
        self._auto_attempted: str | None = None
        self._loading = False           # suppress settings handlers while populating
        self._devices_key: tuple = ()
        self._public_ip: str | None = None
        self._ip_time = 0.0
        self._ip_pending = False
        self._logs_loading = False
        self._last_log_text = ""
        self._timer_id = 0
        self._banner_timer = 0

        self.set_title(_("app.title"))
        self.set_default_size(620, 820)
        self.set_size_request(360, 480)

        self.toasts = Adw.ToastOverlay()
        self.stack = Adw.ViewStack()
        self._build_dashboard()
        self._build_logs()
        self._build_settings()

        header = Adw.HeaderBar()
        switcher = Adw.ViewSwitcher(policy=Adw.ViewSwitcherPolicy.WIDE, stack=self.stack)
        header.set_title_widget(switcher)
        header.pack_end(self._build_menu())

        self.error_banner = Adw.Banner(title="")
        self.error_banner.set_button_label(_("tab.logs"))
        self.error_banner.connect("button-clicked", lambda *_a: self.stack.set_visible_child_name("logs"))
        self.restore_banner = Adw.Banner(title=_("banner.restore"))
        self.restore_banner.set_button_label(_("btn.restore"))
        self.restore_banner.connect("button-clicked", lambda *_a: self._start_disconnect(restore=True))

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(self.error_banner)
        body.append(self.restore_banner)
        self.stack.set_vexpand(True)
        body.append(self.stack)
        self.toasts.set_child(body)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.toasts)
        self.set_content(view)

        self.connect("close-request", self._on_close)
        self._populate_settings()
        self.request_refresh()
        self._restart_timer()

    # ================================================================ building
    def _build_menu(self) -> Gtk.MenuButton:
        from gi.repository import Gio
        menu = Gio.Menu()
        menu.append(_("menu.about"), "app.about")
        button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        return button

    @staticmethod
    def _page(child: Gtk.Widget) -> Gtk.ScrolledWindow:
        clamp = Adw.Clamp(maximum_size=680, tightening_threshold=520, child=child)
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scrolled.set_child(clamp)
        return scrolled

    def _build_dashboard(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                      margin_top=18, margin_bottom=24, margin_start=14, margin_end=14)

        # ---- hero
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.FILL)
        hero.add_css_class("card")
        hero.add_css_class("hero")
        self.hero_icon = Gtk.Image(icon_name="network-offline-symbolic", pixel_size=72)
        self.hero_spinner = Gtk.Spinner(spinning=False, visible=False)
        self.hero_spinner.set_size_request(64, 64)
        self.hero_state = Gtk.Label(label=_("state.disconnected"))
        self.hero_state.add_css_class("hero-state")
        self.hero_sub = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.hero_sub.add_css_class("dim-label")
        self.primary = Gtk.Button(label=_("btn.connect"), halign=Gtk.Align.CENTER)
        self.primary.add_css_class("pill")
        self.primary.add_css_class("big-button")
        self.primary.add_css_class("suggested-action")
        self.primary.connect("clicked", self._on_primary)
        for widget in (self.hero_icon, self.hero_spinner, self.hero_state, self.hero_sub, self.primary):
            hero.append(widget)
        box.append(hero)

        # ---- connection group
        group = Adw.PreferencesGroup(title=_("group.connection"))
        self.phone_choice = Adw.ComboRow(title=_("row.choose_phone"), visible=False)
        self.phone_choice.connect("notify::selected", self._on_phone_chosen)
        self.row_phone = StatusRow(_("row.phone"))
        self.row_usb = StatusRow(_("row.usb"))
        self.row_adb = StatusRow(_("row.adb"))
        self.row_service = StatusRow(_("row.service"))
        self.row_tun = StatusRow(_("row.tun"))
        self.row_dns_service = StatusRow(_("row.dns"))
        for row in (self.phone_choice, self.row_phone, self.row_usb, self.row_adb,
                    self.row_service, self.row_tun, self.row_dns_service):
            group.add(row)
        box.append(group)

        # ---- network group
        net = Adw.PreferencesGroup(title=_("group.network"))
        self.row_ip = ValueRow(_("row.public_ip"))
        self.row_active = ValueRow(_("row.active_iface"))
        self.row_tunnel = ValueRow(_("row.tunnel_iface"))
        self.row_dns = StatusRow(_("row.dns_status"))
        self.row_ipv6 = StatusRow(_("row.ipv6"))
        self.row_uptime = ValueRow(_("row.uptime"))
        for row in (self.row_ip, self.row_active, self.row_tunnel, self.row_dns,
                    self.row_ipv6, self.row_uptime):
            net.add(row)
        box.append(net)

        # ---- traffic
        title = Gtk.Label(label=_("group.traffic"), xalign=0)
        title.add_css_class("heading")
        box.append(title)
        grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        self.card_down_speed = StatCard(_("stat.down_speed"))
        self.card_up_speed = StatCard(_("stat.up_speed"))
        self.card_down = StatCard(_("stat.downloaded"), small=True)
        self.card_up = StatCard(_("stat.uploaded"), small=True)
        self.card_total = StatCard(_("stat.total"), small=True)
        grid.attach(self.card_down_speed, 0, 0, 3, 1)
        grid.attach(self.card_up_speed, 3, 0, 3, 1)
        grid.attach(self.card_down, 0, 1, 2, 1)
        grid.attach(self.card_up, 2, 1, 2, 1)
        grid.attach(self.card_total, 4, 1, 2, 1)
        box.append(grid)

        self.stack.add_titled_with_icon(
            self._page(box), "dashboard", _("tab.dashboard"), "utilities-system-monitor-symbolic")

    def _build_logs(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                      margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        bar = Gtk.Box(spacing=6)
        for label, handler in (
            (_("btn.refresh"), lambda *_a: self._load_logs(force=True)),
            (_("btn.copy_logs"), self._copy_logs),
            (_("btn.diagnostics"), self._run_diagnostics),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", handler)
            bar.append(button)
        box.append(bar)
        self.log_buffer = Gtk.TextBuffer()
        self.log_view = Gtk.TextView(buffer=self.log_buffer, editable=False, cursor_visible=False,
                                     monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                     vexpand=True)
        self.log_view.add_css_class("log-view")
        self.log_scroll = Gtk.ScrolledWindow(vexpand=True)
        self.log_scroll.set_child(self.log_view)
        frame = Gtk.Frame()
        frame.set_child(self.log_scroll)
        frame.set_vexpand(True)
        box.append(frame)
        self.stack.add_titled_with_icon(
            box, "logs", _("tab.logs"), "text-x-generic-symbolic")
        self.stack.connect("notify::visible-child-name", self._on_page_changed)

    def _build_settings(self) -> None:
        page = Adw.PreferencesPage()

        look = Adw.PreferencesGroup(title=_("settings.appearance"))
        self.opt_language = Adw.ComboRow(title=_("settings.language"))
        self.opt_language.set_model(Gtk.StringList.new([
            _("settings.language.system"), _("settings.language.en"), _("settings.language.fa")]))
        self.opt_theme = Adw.ComboRow(title=_("settings.theme"))
        self.opt_theme.set_model(Gtk.StringList.new([
            _("settings.theme.system"), _("settings.theme.light"), _("settings.theme.dark")]))
        look.add(self.opt_language)
        look.add(self.opt_theme)
        page.add(look)

        startup = Adw.PreferencesGroup(title=_("settings.startup"))
        self.opt_login = Adw.SwitchRow(title=_("settings.launch_at_login"),
                                       subtitle=_("settings.launch_at_login.sub"))
        self.opt_minimized = Adw.SwitchRow(title=_("settings.start_minimized"))
        startup.add(self.opt_login)
        startup.add(self.opt_minimized)
        page.add(startup)

        behavior = Adw.PreferencesGroup(title=_("settings.behavior"))
        self.opt_auto_connect = Adw.SwitchRow(title=_("settings.auto_connect"),
                                              subtitle=_("settings.auto_connect.sub"))
        self.opt_auto_restore = Adw.SwitchRow(title=_("settings.auto_restore"),
                                              subtitle=_("settings.auto_restore.sub"))
        self.opt_public_ip = Adw.SwitchRow(title=_("settings.public_ip"),
                                           subtitle=_("settings.public_ip.sub"))
        self.opt_poll = Adw.ComboRow(title=_("settings.poll"), subtitle=_("settings.poll.sub"))
        self.opt_poll.set_model(Gtk.StringList.new(["1 s", "2 s", "5 s"]))
        for row in (self.opt_auto_connect, self.opt_auto_restore, self.opt_public_ip, self.opt_poll):
            behavior.add(row)
        page.add(behavior)

        diag = Adw.PreferencesGroup(title=_("settings.diagnostics"))
        run_row = Adw.ActionRow(title=_("btn.diagnostics"), subtitle=_("settings.diag.run"))
        run_button = Gtk.Button(label=_("btn.diagnostics"), valign=Gtk.Align.CENTER)
        run_button.connect("clicked", self._run_diagnostics)
        run_row.add_suffix(run_button)
        test_row = Adw.ActionRow(title=_("btn.test"), subtitle=_("settings.diag.test"))
        self.test_button = Gtk.Button(label=_("btn.test"), valign=Gtk.Align.CENTER)
        self.test_button.connect("clicked", self._run_usb_test)
        test_row.add_suffix(self.test_button)
        diag.add(run_row)
        diag.add(test_row)
        page.add(diag)

        self.stack.add_titled_with_icon(
            page, "settings", _("tab.settings"), "emblem-system-symbolic")

        for row, signal in (
            (self.opt_language, "notify::selected"), (self.opt_theme, "notify::selected"),
            (self.opt_poll, "notify::selected"),
            (self.opt_login, "notify::active"), (self.opt_minimized, "notify::active"),
            (self.opt_auto_connect, "notify::active"), (self.opt_auto_restore, "notify::active"),
            (self.opt_public_ip, "notify::active"),
        ):
            row.connect(signal, self._on_setting_changed)

    def _populate_settings(self) -> None:
        self._loading = True
        cfg = self.cfg
        self.opt_language.set_selected(settings_mod.LANGUAGES.index(cfg.language))
        self.opt_theme.set_selected(settings_mod.THEMES.index(cfg.theme))
        self.opt_poll.set_selected(settings_mod.POLL_CHOICES.index(cfg.poll_seconds))
        self.opt_login.set_active(autostart.is_enabled())
        self.opt_minimized.set_active(cfg.start_minimized)
        self.opt_auto_connect.set_active(cfg.auto_connect)
        self.opt_auto_restore.set_active(cfg.auto_restore)
        self.opt_public_ip.set_active(cfg.lookup_public_ip)
        self._loading = False

    # ================================================================ settings
    def _on_setting_changed(self, *_args) -> None:
        if self._loading:
            return
        cfg = self.cfg
        old_language = cfg.language
        cfg.language = settings_mod.LANGUAGES[self.opt_language.get_selected()]
        cfg.theme = settings_mod.THEMES[self.opt_theme.get_selected()]
        cfg.poll_seconds = settings_mod.POLL_CHOICES[self.opt_poll.get_selected()]
        cfg.start_minimized = self.opt_minimized.get_active()
        cfg.launch_at_login = self.opt_login.get_active()
        cfg.auto_connect = self.opt_auto_connect.get_active()
        cfg.auto_restore = self.opt_auto_restore.get_active()
        cfg.lookup_public_ip = self.opt_public_ip.get_active()
        try:
            autostart.set_enabled(cfg.launch_at_login)
            settings_mod.save(cfg)
        except OSError as exc:
            self.toast(str(exc))
        self.app.apply_theme()
        self._restart_timer()
        if cfg.language != old_language:
            GLib.idle_add(self.app.rebuild_window)

    def _restart_timer(self) -> None:
        if self._timer_id:
            GLib.source_remove(self._timer_id)
        self._timer_id = GLib.timeout_add_seconds(self.cfg.poll_seconds, self._tick)

    def _tick(self) -> bool:
        if not self._alive:
            self._timer_id = 0
            return GLib.SOURCE_REMOVE
        self.request_refresh()
        if self.stack.get_visible_child_name() == "logs":
            self._load_logs()
        return GLib.SOURCE_CONTINUE

    # ================================================================ refresh
    def request_refresh(self) -> None:
        if self._refreshing or not self._alive:
            return
        self._refreshing = True

        def worker() -> None:
            try:
                snap = self.ctrl.refresh()
            except Exception as exc:  # never let the poller thread die silently
                self.ctrl.log(f"Status refresh failed: {exc}")
                snap = None
            GLib.idle_add(self._apply_snapshot, snap)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_snapshot(self, snap: Snapshot | None) -> bool:
        self._refreshing = False
        if not self._alive or snap is None:
            return GLib.SOURCE_REMOVE
        prev, self._snap = self._snap, snap
        self._render(snap)
        self._handle_transitions(prev, snap)
        return GLib.SOURCE_REMOVE

    # ================================================================ rendering
    def _render(self, snap: Snapshot) -> None:
        state = snap.state
        phone = snap.phone
        usb = snap.usb
        busy = self._ui_busy or state in (State.CONNECTING, State.DISCONNECTING)
        name = phone.display_name if phone else ""

        # ---- hero
        icon, css = {
            State.CONNECTED: ("network-transmit-receive-symbolic", "success"),
            State.NEEDS_RESTORE: ("dialog-warning-symbolic", "warning"),
        }.get(state, ("network-offline-symbolic", "dim-label"))
        self.hero_icon.set_from_icon_name(icon)
        for cls in ("success", "warning", "dim-label"):
            self.hero_icon.remove_css_class(cls)
        self.hero_icon.add_css_class(css)
        self.hero_icon.set_visible(not busy)
        self.hero_spinner.set_visible(busy)
        self.hero_spinner.set_spinning(busy)
        self.hero_state.set_text(_({
            State.CONNECTED: "state.connected",
            State.DISCONNECTED: "state.disconnected",
            State.CONNECTING: "state.connecting",
            State.DISCONNECTING: "state.disconnecting",
            State.NEEDS_RESTORE: "state.needs_restore",
        }[state]))
        self.hero_sub.set_text(self._hero_subtitle(snap, busy, name))

        for cls in ("suggested-action", "destructive-action"):
            self.primary.remove_css_class(cls)
        if state == State.CONNECTED:
            self.primary.set_label(_("btn.disconnect"))
            self.primary.add_css_class("destructive-action")
            self.primary.set_sensitive(not busy)
        elif state == State.NEEDS_RESTORE:
            self.primary.set_label(_("btn.restore"))
            self.primary.add_css_class("suggested-action")
            self.primary.set_sensitive(not busy)
        else:
            self.primary.set_label(_("btn.connect"))
            self.primary.add_css_class("suggested-action")
            ready = bool(phone and phone.authorized and snap.adb_ok and snap.cli_ok
                         and snap.service_listening is not False)
            self.primary.set_sensitive(ready and not busy)
        self.restore_banner.set_revealed(state == State.NEEDS_RESTORE and not busy)
        self.test_button.set_sensitive(state == State.DISCONNECTED and not busy)

        # ---- connection rows
        if phone:
            level = "ok" if phone.authorized else "warn"
            detail = phone.display_name + (
                "" if phone.authorized else f" — {_('val.unauthorized') if phone.state == 'unauthorized' else _('val.offline')}")
            self.row_phone.update(f"{detail}  ({phone.serial})", level)
            self.row_usb.update(_("val.connected") if phone.usb else _("val.not_connected"),
                                "ok" if phone.usb else "warn")
        else:
            self.row_phone.update(_("val.not_detected"), "off")
            self.row_usb.update(_("val.not_connected"), "off")
        if not snap.adb_ok:
            self.row_adb.update(_("val.not_installed"), "bad")
        elif phone and phone.authorized:
            self.row_adb.update(_("val.authorized"), "ok")
        elif phone:
            self.row_adb.update(_("val.unauthorized") if phone.state == "unauthorized"
                                else _("val.offline"), "warn")
        else:
            self.row_adb.update(_("val.ready"), "off")
        svc = snap.service_listening
        self.row_service.update(
            _("val.listening") if svc else _("val.not_listening") if svc is False else _("val.unknown"),
            "ok" if svc else "warn" if svc is False else "off")
        present = bool(usb and usb.iface_present)
        self.row_tun.update(f"{snap.net.tunnel_iface} — " + (_("val.up") if present else _("val.down")),
                            "ok" if present else "off")
        dns_on = bool(usb and usb.dns_active)
        self.row_dns_service.update(_("val.running") if dns_on else _("val.stopped"),
                                    "ok" if dns_on else "off")
        self._update_phone_choice(snap)

        # ---- network rows
        connected = state == State.CONNECTED
        net = snap.net
        self.row_active.update(net.active_iface or "—")
        self.row_tunnel.update(f"{net.tunnel_iface}  {'(up)' if present else ''}".strip())
        if connected:
            self.row_dns.update(_("val.routed") if net.dns_routed else _("val.not_routed"),
                                "ok" if net.dns_routed else "warn")
        else:
            self.row_dns.update(_("val.not_routed"), "off")
        self.row_ipv6.update(_("val.protected") if net.ipv6_blocked else _("val.not_protected"),
                             "ok" if net.ipv6_blocked else "off")
        self.row_uptime.update(human_duration(net.uptime) if connected else "—")
        self._render_public_ip(connected)

        # ---- traffic (real kernel counters)
        t = snap.traffic
        self.card_down_speed.update(human_rate(t.rx_rate))
        self.card_up_speed.update(human_rate(t.tx_rate))
        self.card_down.update(human_bytes(t.rx_bytes))
        self.card_up.update(human_bytes(t.tx_bytes))
        self.card_total.update(human_bytes(t.total))

        if snap.error_key and not busy and self._snap_error_visible_ok(snap):
            self.show_error(_(snap.error_key))

    def _snap_error_visible_ok(self, snap: Snapshot) -> bool:
        return snap.error_key in ("err.cli_missing", "err.parse", "err.status_failed")

    def _hero_subtitle(self, snap: Snapshot, busy: bool, name: str) -> str:
        state = snap.state
        if state == State.CONNECTED:
            return _("hero.connected", phone=name or "—")
        if state == State.NEEDS_RESTORE:
            return _("hero.needs_restore")
        if busy:
            return _("hero.busy")
        if not snap.adb_ok:
            return _("hero.no_adb")
        phone = snap.phone
        if phone is None:
            return _("hero.no_phone")
        if phone.state == "unauthorized":
            return _("hero.unauthorized")
        if not phone.authorized:
            return _("hero.offline")
        if snap.service_listening is False:
            return _("hero.no_service")
        return _("hero.ready", phone=name)

    def _update_phone_choice(self, snap: Snapshot) -> None:
        authorized = [d for d in snap.devices if d.authorized]
        show = len(authorized) > 1 and snap.state == State.DISCONNECTED
        self.phone_choice.set_visible(show)
        key = tuple(d.serial for d in authorized)
        if show and key != self._devices_key:
            self._loading = True
            self.phone_choice.set_model(Gtk.StringList.new(
                [f"{d.display_name} ({d.serial})" for d in authorized]))
            current = snap.phone.serial if snap.phone else None
            self.phone_choice.set_selected(key.index(current) if current in key else 0)
            self._loading = False
        self._devices_key = key if show else ()

    def _on_phone_chosen(self, row, _pspec) -> None:
        if self._loading or not self._snap:
            return
        authorized = [d for d in self._snap.devices if d.authorized]
        index = row.get_selected()
        if 0 <= index < len(authorized):
            self.ctrl.selected_serial = authorized[index].serial

    def _render_public_ip(self, connected: bool) -> None:
        if not connected:
            self.row_ip.update("—")
            self._public_ip = None
            self._ip_time = 0.0
            return
        if not self.cfg.lookup_public_ip:
            self.row_ip.update(_("val.lookup_off"))
            return
        if self._public_ip:
            self.row_ip.update(self._public_ip)
        elif self._ip_pending:
            self.row_ip.update(_("val.checking"))
        if (not self._ip_pending
                and time.monotonic() - self._ip_time > (_IP_REFRESH_SECONDS if self._public_ip else 10)):
            self._ip_pending = True
            self._ip_time = time.monotonic()
            if not self._public_ip:
                self.row_ip.update(_("val.checking"))

            def worker() -> None:
                ip = fetch_public_ip()
                GLib.idle_add(self._set_public_ip, ip)

            threading.Thread(target=worker, daemon=True).start()

    def _set_public_ip(self, ip: str | None) -> bool:
        self._ip_pending = False
        if not self._alive:
            return GLib.SOURCE_REMOVE
        if ip:
            self._public_ip = ip
            self.row_ip.update(ip)
        elif not self._public_ip:
            self.row_ip.update(_("val.unavailable"))
        return GLib.SOURCE_REMOVE

    # ================================================================ transitions
    def _handle_transitions(self, prev: Snapshot | None, snap: Snapshot) -> None:
        phone_ready = bool(snap.phone and snap.phone.authorized)
        if not phone_ready:
            self._auto_attempted = None
            if snap.state == State.DISCONNECTED:
                self._intentional = False

        unexpected = (prev is not None and prev.state == State.CONNECTED
                      and snap.state in (State.NEEDS_RESTORE, State.DISCONNECTED)
                      and not self._intentional)
        if unexpected:
            self.ctrl.log("Phone link lost unexpectedly")
            self.show_error(_("banner.unplug"))
            self.app.notify_unplug()
            if self.cfg.auto_restore and snap.state == State.NEEDS_RESTORE:
                self._start_disconnect(restore=True)
                return

        if snap.state == State.CONNECTED:
            self.error_banner.set_revealed(False)

        if (self.cfg.auto_connect and snap.state == State.DISCONNECTED and phone_ready
                and snap.service_listening and not self._ui_busy and not self._intentional
                and snap.phone is not None and snap.phone.serial != self._auto_attempted):
            self._auto_attempted = snap.phone.serial
            self.ctrl.log("Auto-connect: authorized phone with USB Tether detected")
            self._start_connect()

    # ================================================================ actions
    def _on_primary(self, _button) -> None:
        if self._ui_busy or not self._snap:
            return
        state = self._snap.state
        if state == State.CONNECTED:
            self._intentional = True
            self._start_disconnect()
        elif state == State.NEEDS_RESTORE:
            self._start_disconnect(restore=True)
        elif state == State.DISCONNECTED:
            self._intentional = False
            self._start_connect()

    def _run_action(self, work, done) -> None:
        if self._ui_busy:
            return
        self._ui_busy = True
        self.error_banner.set_revealed(False)
        if self._snap:
            self._render(self._snap)

        def worker() -> None:
            try:
                result = work()
            except Exception as exc:
                self.ctrl.log(f"Unexpected error: {exc}")
                result = ActionResult(False, "err.unknown", str(exc))
            GLib.idle_add(self._action_finished, result, done)

        threading.Thread(target=worker, daemon=True).start()

    def _action_finished(self, result: ActionResult, done) -> bool:
        self._ui_busy = False
        if self._alive:
            done(result)
            self.request_refresh()
        return GLib.SOURCE_REMOVE

    def _start_connect(self) -> None:
        def done(result: ActionResult) -> None:
            if result.ok:
                self.toast(_("toast.connected"))
            elif not result.cancelled:
                self.show_error(_(result.key or "err.unknown"))
        self._run_action(self.ctrl.connect, done)

    def _start_disconnect(self, restore: bool = False) -> None:
        if not restore:
            self._intentional = True

        def done(result: ActionResult) -> None:
            if result.ok:
                self.toast(_("toast.disconnected"))
            elif not result.cancelled:
                self.show_error(_(result.key or "err.unknown"))
        self._run_action(lambda: self.ctrl.disconnect(restore=restore), done)

    def _run_usb_test(self, _button) -> None:
        def done(result: ActionResult) -> None:
            if result.ok:
                self.toast(_("toast.test_ok"))
            else:
                self.show_error(_(result.key or "err.unknown"))
            self._load_logs(force=True)
        self._run_action(self.ctrl.run_usb_test, done)

    def _run_diagnostics(self, _button) -> None:
        def worker() -> None:
            text = self.ctrl.diagnostics()
            self.ctrl.log("Diagnostics:\n" + text)
            GLib.idle_add(self._diagnostics_done)
        threading.Thread(target=worker, daemon=True).start()

    def _diagnostics_done(self) -> bool:
        self.toast(_("toast.diag_done"))
        self.stack.set_visible_child_name("logs")
        self._load_logs(force=True)
        return GLib.SOURCE_REMOVE

    # ================================================================ logs
    def _on_page_changed(self, *_args) -> None:
        if self.stack.get_visible_child_name() == "logs":
            self._load_logs(force=True)

    def _load_logs(self, force: bool = False) -> None:
        if self._logs_loading:
            return
        self._logs_loading = True

        def worker() -> None:
            text = self.ctrl.read_logs()
            GLib.idle_add(self._set_logs, text)

        threading.Thread(target=worker, daemon=True).start()

    def _set_logs(self, text: str) -> bool:
        self._logs_loading = False
        if not self._alive or text == self._last_log_text:
            return GLib.SOURCE_REMOVE
        adj = self.log_scroll.get_vadjustment()
        at_bottom = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 24
        self._last_log_text = text
        self.log_buffer.set_text(text or _("log.empty"))
        if at_bottom:
            GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()) and False)
        return GLib.SOURCE_REMOVE

    def _copy_logs(self, _button) -> None:
        text = self._last_log_text or self.ctrl.read_logs()
        value = GObject.Value()
        value.init(GObject.TYPE_STRING)
        value.set_string(text)
        self.get_clipboard().set_content(Gdk.ContentProvider.new_for_value(value))
        self.toast(_("toast.copied"))

    # ================================================================ helpers
    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(text))

    def show_error(self, text: str) -> None:
        self.error_banner.set_title(text)
        self.error_banner.set_revealed(True)
        if self._banner_timer:
            GLib.source_remove(self._banner_timer)
        self._banner_timer = GLib.timeout_add_seconds(20, self._hide_error)

    def _hide_error(self) -> bool:
        self._banner_timer = 0
        self.error_banner.set_revealed(False)
        return GLib.SOURCE_REMOVE

    def _on_close(self, *_args) -> bool:
        # Closing the window never touches the tunnel: the connection is owned
        # by the system (helper process and routes), not by this GUI.
        self._alive = False
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0
        if self._banner_timer:
            GLib.source_remove(self._banner_timer)
            self._banner_timer = 0
        return False
