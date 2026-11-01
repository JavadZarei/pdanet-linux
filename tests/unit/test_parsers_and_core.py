import os
import time
import unittest

from _env import *  # noqa: F401,F403  (sets up the fake system first)
import _env

from pdanet_gui.core import autostart, config, netinfo, settings
from pdanet_gui.core.fmt import human_bytes, human_duration, human_rate
from pdanet_gui.core.parsers import ParseError, parse_adb_devices, parse_route_dev, parse_usb_status, pretty_model
from pdanet_gui.core.runner import run
from pdanet_gui.core.traffic import TrafficMonitor, read_counters


class UsbStatusParser(unittest.TestCase):
    def test_enabled(self):
        s = parse_usb_status(_env.ENABLED)
        self.assertTrue(s.enabled)
        self.assertEqual((s.device, s.target, s.forward_port, s.helper_pid),
                         ("R5CWC1234", "tcp:8739", 41234, 4242))
        self.assertTrue(all([s.forward_active, s.helper_running, s.iface_present,
                             s.routes_active, s.dns_active]))

    def test_disabled(self):
        s = parse_usb_status(_env.DISABLED)
        self.assertFalse(s.enabled)
        self.assertIsNone(s.device)
        self.assertIsNone(s.forward_port)
        self.assertFalse(s.helper_running or s.iface_present or s.routes_active or s.dns_active)

    def test_wifi_status_before_usb_block(self):
        text = "PdaNet proxy: disabled\n  Interface:    none\n\n" + _env.ENABLED
        self.assertTrue(parse_usb_status(text).enabled)

    def test_rejects_garbage(self):
        for bad in ("", "hello", "PdaNet USB: maybe\n", "PdaNet USB: enabled\n  Device: x\n"):
            with self.assertRaises(ParseError):
                parse_usb_status(bad)

    def test_rejects_unknown_field_formats(self):
        bad = _env.ENABLED.replace("running (PID 4242)", "exploded")
        with self.assertRaises(ParseError):
            parse_usb_status(bad)


class AdbParser(unittest.TestCase):
    def test_devices(self):
        text = ("* daemon not running; starting now at tcp:5037\n* daemon started successfully\n"
                "List of devices attached\n"
                "R5CWC1234              device usb:1-2 product:a54xnsxx model:SM_A546E device:a54x transport_id:3\n"
                "emulator-5554          offline\n"
                "ZX1                    unauthorized usb:1-3 transport_id:4\n"
                "ZX2                    no permissions (user in plugdev group; are your udev rules wrong?)\n")
        devs = {d.serial: d for d in parse_adb_devices(text)}
        self.assertEqual(set(devs), {"R5CWC1234", "emulator-5554", "ZX1", "ZX2"})
        self.assertTrue(devs["R5CWC1234"].authorized and devs["R5CWC1234"].usb)
        self.assertEqual(devs["R5CWC1234"].display_name, "SM-A546E")
        self.assertFalse(devs["emulator-5554"].authorized)
        self.assertEqual(devs["ZX1"].state, "unauthorized")
        self.assertEqual(devs["ZX2"].state, "no permissions")

    def test_pretty_model(self):
        self.assertEqual(pretty_model("SM_A546E"), "SM-A546E")
        self.assertEqual(pretty_model("Pixel_7_Pro"), "Pixel 7 Pro")
        self.assertIsNone(pretty_model(None))

    def test_route_dev(self):
        self.assertEqual(parse_route_dev("1.1.1.1 dev pdanet0 src 10.1.19.2 uid 1000"), "pdanet0")
        self.assertIsNone(parse_route_dev(""))


class Traffic(unittest.TestCase):
    def test_rates_and_reset(self):
        m = TrafficMonitor()
        first = m.update(100.0, (1000, 500))
        self.assertIsNone(first.rx_rate)
        s = m.update(102.0, (5000, 1500))
        self.assertEqual((s.rx_rate, s.tx_rate, s.total), (2000.0, 500.0, 6500))
        s = m.update(103.0, (10, 10))  # interface recreated: counters went backwards
        self.assertIsNone(s.rx_rate)
        s = m.update(104.0, None)
        self.assertEqual((s.rx_bytes, s.rx_rate), (None, None))

    def test_read_counters(self):
        _env.set_sysfs(123, 456)
        self.assertEqual(read_counters("pdanet0"), (123, 456))
        self.assertIsNone(read_counters("does-not-exist"))


class Formatting(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(human_bytes(0), "0 B")
        self.assertEqual(human_bytes(1536), "1.50 KiB")
        self.assertEqual(human_bytes(None), "—")
        self.assertEqual(human_rate(2048), "2.00 KiB/s")
        self.assertEqual(human_duration(3725), "01:02:05")
        self.assertEqual(human_duration(None), "—")


class Settings(unittest.TestCase):
    def test_roundtrip_and_validation(self):
        path = os.path.join(_env.TMP, "s", "settings.json")
        s = settings.Settings(language="fa", theme="dark", poll_seconds=5, auto_connect=True)
        settings.save(s, path)
        self.assertEqual(settings.load(path), s)

    def test_corrupt_and_hostile_values(self):
        path = os.path.join(_env.TMP, "bad.json")
        with open(path, "w") as fh:
            fh.write('{"language": "klingon", "poll_seconds": 999, "auto_connect": "yes", "x": 1}')
        s = settings.load(path)
        self.assertEqual((s.language, s.poll_seconds, s.auto_connect), ("system", 2, False))
        with open(path, "w") as fh:
            fh.write("not json")
        self.assertEqual(settings.load(path), settings.Settings())
        self.assertEqual(settings.load(os.path.join(_env.TMP, "missing.json")), settings.Settings())


class Autostart(unittest.TestCase):
    def test_enable_disable(self):
        autostart.set_enabled(False)
        self.assertFalse(autostart.is_enabled())
        autostart.set_enabled(True)
        self.assertTrue(autostart.is_enabled())
        with open(autostart.autostart_path()) as fh:
            text = fh.read()
        self.assertIn("Exec=pdanet-gui --background", text)
        autostart.set_enabled(False)
        self.assertFalse(autostart.is_enabled())


class Runner(unittest.TestCase):
    def test_timeout_notfound_and_validation(self):
        r = run(["sleep", "5"], timeout=0.3)
        self.assertTrue(r.timed_out and not r.ok)
        self.assertEqual(run(["/nonexistent/prog"], 2).error, "not-found")
        with self.assertRaises(TypeError):
            run("ls -l; rm -rf /", 2)
        with self.assertRaises(TypeError):
            run([], 2)

    def test_no_shell_interpretation(self):
        r = run(["echo", "$(id) ; `id` | cat"], 5)
        self.assertEqual(r.stdout.strip(), "$(id) ; `id` | cat")


class NetInfo(unittest.TestCase):
    def setUp(self):
        _env.reset()

    def test_ipv6_blocked_detection(self):
        self.assertFalse(netinfo.ipv6_blocked())
        _env.put("v6.txt", "unreachable ::/1 dev lo metric 5 pref medium\n"
                           "unreachable 8000::/1 dev lo metric 5 pref medium\n")
        self.assertTrue(netinfo.ipv6_blocked())
        _env.put("v6.txt", "unreachable ::/1 dev lo metric 5 pref medium\n")
        self.assertFalse(netinfo.ipv6_blocked())

    def test_interfaces_and_dns(self):
        self.assertEqual(netinfo.active_interface(), "wlp2s0")
        self.assertEqual(netinfo.underlying_interface(), "wlp2s0")
        _env.put("route_get.txt", "1.1.1.1 dev pdanet0 src 10.1.19.2 uid 1000\n")
        self.assertEqual(netinfo.active_interface(), "pdanet0")
        self.assertFalse(netinfo.dns_routed())
        _env.put("resolvectl.txt", "Link 5 (pdanet0): 127.0.0.1:5300\n")
        self.assertTrue(netinfo.dns_routed())

    def test_detect_running_helper(self):
        os.makedirs(_env.RUN, exist_ok=True)
        os.makedirs(os.path.join(_env.PROC, "777"), exist_ok=True)
        with open(os.path.join(_env.RUN, "helper-pid"), "w") as fh:
            fh.write("777\n")
        old = "/home/user/.local/bin/../libexec/pdanet-usb-helper"
        with open(os.path.join(_env.PROC, "777", "cmdline"), "wb") as fh:
            fh.write(b"/usr/bin/python3\0" + old.encode() + b"\0--connect\0127.0.0.1:41234\0")
        self.assertEqual(netinfo.detect_running_helper(), old)
        with open(os.path.join(_env.RUN, "helper-pid"), "w") as fh:
            fh.write("../../etc/passwd\n")
        self.assertIsNone(netinfo.detect_running_helper())
        self.assertIsNone(netinfo.detect_running_helper(run_dir="/nonexistent"))

    def test_uptime_from_pidfile(self):
        os.makedirs(_env.RUN, exist_ok=True)
        pidfile = os.path.join(_env.RUN, "helper-pid")
        with open(pidfile, "w") as fh:
            fh.write("1\n")
        os.utime(pidfile, (time.time() - 90, time.time() - 90))
        up = netinfo.uptime_seconds(time.time())
        self.assertTrue(89 <= up <= 92)


if __name__ == "__main__":
    unittest.main()
