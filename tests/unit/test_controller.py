import os
import threading
import time
import unittest

from _env import *  # noqa: F401,F403
import _env

from pdanet_gui.core.controller import Controller, State, classify_failure
from pdanet_gui.core.runner import CmdResult


def pk_calls():
    with open(os.path.join(_env.FAKE, "pkexec.log")) as fh:
        return [ln.strip() for ln in fh if ln.strip()]


class Base(unittest.TestCase):
    def setUp(self):
        _env.reset()
        self.c = Controller()


class Refresh(Base):
    def test_disconnected_with_ready_phone(self):
        s = self.c.refresh()
        self.assertEqual(s.state, State.DISCONNECTED)
        self.assertEqual(s.phone.display_name, "SM-A546E")
        self.assertTrue(s.phone.usb and s.phone.authorized)
        self.assertTrue(s.service_listening)
        self.assertFalse(s.stale)
        self.assertIsNone(s.error_key)

    def test_no_phone(self):
        _env.put("devices.txt", "")
        s = self.c.refresh()
        self.assertIsNone(s.phone)
        self.assertEqual(s.state, State.DISCONNECTED)

    def test_unauthorized_phone_is_reported_not_crashing(self):
        _env.put("devices.txt", _env.DEVICES_UNAUTH)
        s = self.c.refresh()
        self.assertEqual(s.phone.state, "unauthorized")
        self.assertFalse(s.phone.authorized)
        self.assertIsNone(s.service_listening)

    def test_service_not_listening(self):
        _env.put("svc_ss.txt", "LISTEN 0 50 127.0.0.1:5555 0.0.0.0:*\n")
        self.assertIs(self.c.refresh().service_listening, False)

    def test_connected_reads_real_counters_and_rates(self):
        _env.put("usb_status.txt", _env.ENABLED)
        _env.put("route_get.txt", "1.1.1.1 dev pdanet0 src 10.1.19.2 uid 1000\n")
        _env.put("dns_active.txt", "active\n")
        _env.put("resolvectl.txt", "Link 5 (pdanet0): 127.0.0.1:5300\n")
        _env.put("v6.txt", "unreachable ::/1 dev lo metric 5\nunreachable 8000::/1 dev lo metric 5\n")
        os.makedirs(_env.RUN, exist_ok=True)
        with open(os.path.join(_env.RUN, "helper-pid"), "w") as fh:
            fh.write("4242\n")
        _env.set_sysfs(1000, 200)
        s1 = self.c.refresh()
        self.assertEqual(s1.state, State.CONNECTED)
        self.assertEqual((s1.traffic.rx_bytes, s1.traffic.tx_bytes), (1000, 200))
        self.assertIsNone(s1.traffic.rx_rate)
        self.assertEqual(s1.net.active_iface, "pdanet0")
        self.assertTrue(s1.net.dns_routed and s1.net.ipv6_blocked and s1.net.dns_service)
        self.assertIsNotNone(s1.net.uptime)
        time.sleep(0.2)
        _env.set_sysfs(3000, 700)
        s2 = self.c.refresh()
        self.assertGreater(s2.traffic.rx_rate, 0)
        self.assertEqual(s2.traffic.total, 3700)

    def test_unexpected_unplug_leaves_stale_state_that_is_detected(self):
        # helper died: interface and v4 routes gone, but IPv6 blackhole + DNS service remain
        _env.put("usb_status.txt", _env.STALE)
        _env.put("dns_active.txt", "active\n")
        _env.put("v6.txt", "unreachable ::/1 dev lo metric 5\nunreachable 8000::/1 dev lo metric 5\n")
        s = self.c.refresh()
        self.assertEqual(s.state, State.NEEDS_RESTORE)
        self.assertTrue(s.stale)

    def test_garbage_cli_output_surfaces_error_not_exception(self):
        _env.put("usb_status.txt", "totally unexpected\n")
        s = self.c.refresh()
        self.assertEqual(s.error_key, "err.parse")
        self.assertEqual(s.state, State.DISCONNECTED)
        self.assertFalse(s.stale)


class Connect(Base):
    def test_success_goes_through_pkexec_helper_with_serial_only(self):
        r = self.c.connect()
        self.assertTrue(r.ok, r)
        calls = pk_calls()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("helper-stub connect R5CWC1234"), calls)
        self.assertEqual(self.c.refresh().state, State.CONNECTED)

    def test_no_pkexec_prompt_when_phone_missing_or_unauthorized_or_service_off(self):
        _env.put("devices.txt", "")
        self.assertEqual(self.c.connect().key, "err.no_device")
        _env.put("devices.txt", _env.DEVICES_UNAUTH)
        self.assertEqual(self.c.connect().key, "err.unauthorized")
        _env.put("devices.txt", "R5CWC1234\toffline\n")
        self.assertEqual(self.c.connect().key, "err.offline")
        _env.put("devices.txt", _env.DEVICES_OK)
        _env.put("svc_ss.txt", "")
        self.assertEqual(self.c.connect().key, "err.no_service")
        self.assertEqual(pk_calls(), [])

    def test_hostile_serial_is_never_passed_to_root(self):
        _env.put("devices.txt", "a;reboot\tdevice usb:1-2 model:X\n")
        r = self.c.connect()
        self.assertEqual(r.key, "err.bad_serial")
        self.assertEqual(pk_calls(), [])

    def test_auth_dialog_cancelled(self):
        _env.put("pkexec_rc", "126")
        r = self.c.connect()
        self.assertFalse(r.ok)
        self.assertTrue(r.cancelled)
        self.assertEqual(r.key, "err.auth_cancelled")

    def test_cli_failure_message_is_mapped(self):
        _env.put("pkexec_rc", "1")
        _env.put("pkexec_out", "  ERROR  PdaNet USB is not listening. Enable USB Tether in the phone app first.\n")
        self.assertEqual(self.c.connect().key, "err.no_service")
        _env.put("pkexec_out", "  ERROR  Wi-Fi proxy mode is active. Run 'pdanet off' before enabling USB mode.\n")
        self.assertEqual(self.c.connect().key, "err.wifi_mode")
        _env.put("pkexec_out", "  !!  A route for 0.0.0.0/1 already exists; refusing to replace it.\n")
        self.assertEqual(self.c.connect().key, "err.route_conflict")

    def test_success_exit_but_status_not_enabled_is_an_error(self):
        _env.put("usb_status_enabled.txt", _env.DISABLED)
        r = self.c.connect()
        self.assertFalse(r.ok)
        self.assertEqual(r.key, "err.unknown")

    def test_duplicate_attempts_are_rejected_while_busy(self):
        _env.put("pkexec_delay", "1")
        results = []
        t = threading.Thread(target=lambda: results.append(self.c.connect()))
        t.start()
        time.sleep(0.4)
        self.assertEqual(self.c.busy_action, "connect")
        self.assertEqual(self.c.refresh().state, State.CONNECTING)
        dup = self.c.connect()
        self.assertEqual(dup.key, "err.busy")
        self.assertEqual(self.c.disconnect().key, "err.busy")
        t.join()
        self.assertTrue(results[0].ok)
        self.assertIsNone(self.c.busy_action)
        self.assertEqual(len(pk_calls()), 1)


class Disconnect(Base):
    def test_disconnect_and_restore_use_the_helper(self):
        _env.put("usb_status.txt", _env.ENABLED)
        self.assertTrue(self.c.disconnect().ok)
        self.assertTrue(self.c.disconnect(restore=True).ok)
        calls = pk_calls()
        self.assertTrue(calls[0].endswith("helper-stub disconnect"))
        self.assertTrue(calls[1].endswith("helper-stub restore"))

    def test_incomplete_restore_is_reported_never_silent(self):
        _env.put("usb_status_disabled.txt", _env.ENABLED)  # helper "refuses" to stop
        r = self.c.disconnect()
        self.assertFalse(r.ok)
        self.assertEqual(r.key, "err.restore_incomplete")


class UsbTest(Base):
    def test_runs_isolated_test_when_disconnected(self):
        r = self.c.run_usb_test()
        self.assertTrue(r.ok, r)
        self.assertEqual(pk_calls(), [])  # unprivileged

    def test_refused_while_connected(self):
        _env.put("usb_status.txt", _env.ENABLED)
        self.assertEqual(self.c.run_usb_test().key, "err.test_while_connected")

    def test_failure_reported(self):
        _env.put("test_fail", "1")
        self.assertFalse(self.c.run_usb_test().ok)


class Logs(Base):
    def test_logs_and_diagnostics_collect_real_outputs(self):
        _env.put("helper.log", "pdanet-usb-helper: connected; forwarding IPv4 packets on pdanet0\n")
        self.c.log("hello")
        text = self.c.read_logs()
        self.assertIn("forwarding IPv4 packets", text)
        self.assertIn("journal: pdanet-cli enabled", text)
        self.assertIn("hello", text)
        diag = self.c.diagnostics()
        for needle in ("adb devices -l", "SM_A546E", "pdanet usb status", "IPv6 block routes"):
            self.assertIn(needle, diag)

    def test_missing_helper_log_is_shown_not_raised(self):
        self.assertIn("No PdaNet USB helper log", self.c.read_logs())


class Classify(unittest.TestCase):
    def test_table(self):
        def res(rc, out="", **kw):
            return CmdResult(("x",), rc, out, "", **kw)
        self.assertEqual(classify_failure(res(124, timed_out=True))[0], "err.timeout")
        self.assertEqual(classify_failure(res(127, error="not-found"))[0], "err.pkexec_missing")
        self.assertEqual(classify_failure(res(126))[0], "err.auth_cancelled")
        self.assertEqual(classify_failure(res(127, "Error: Not authorized"))[0], "err.auth_cancelled")
        self.assertEqual(classify_failure(res(1, "ERROR  No authorized ADB device found."))[0], "err.no_device")
        self.assertEqual(classify_failure(res(1, "something odd"))[0], "err.unknown")
        self.assertEqual(classify_failure(res(1, "  ERROR  USB activation failed. Check the phone and run 'pdanet usb test'."))[0],
                         "err.activation_failed")


if __name__ == "__main__":
    unittest.main()
