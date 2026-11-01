import ast
import glob
import importlib.machinery
import importlib.util
import os
import re
import unittest

from _env import *  # noqa: F401,F403
import _env

from pdanet_gui import i18n

HELPER = os.path.join(_env.ROOT, "libexec", "pdanet-gui-helper")
loader = importlib.machinery.SourceFileLoader("pdanet_gui_helper", HELPER)
spec = importlib.util.spec_from_loader("pdanet_gui_helper", loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)


class RootHelper(unittest.TestCase):
    def plan(self, *argv):
        return helper.build_plan(list(argv), run_dir="/nonexistent", proc_dir="/nonexistent")

    def test_connect(self):
        cmd, env, cleanup = self.plan("connect", "R5CWC1234")
        self.assertEqual(cmd, ["/usr/lib/pdanet-linux/bin/pdanet", "usb", "on"])
        self.assertEqual(env["PDANET_ADB_SERIAL"], "R5CWC1234")
        self.assertFalse(cleanup)
        self.assertNotIn("PDANET_USB_HELPER", env)

    def test_disconnect_and_restore(self):
        cmd, _env_, cleanup = self.plan("disconnect")
        self.assertEqual(cmd[1:], ["usb", "off"])
        self.assertFalse(cleanup)
        self.assertTrue(self.plan("restore")[2])

    def test_rejects_everything_else(self):
        bad = [
            (), ("connect",), ("connect", ""), ("connect", "a b"), ("connect", "a;b"),
            ("connect", "$(id)"), ("connect", "../x"), ("connect", "x" * 65),
            ("connect", "ok", "extra"), ("connect", "-s"), ("disconnect", "now"),
            ("status",), ("usb", "on"), ("sh", "-c", "id"), ("connect", "a\nb"),
        ]
        for argv in bad:
            with self.assertRaises(helper.UsageError, msg=str(argv)):
                self.plan(*argv)

    def test_serial_shapes_accepted(self):
        for ok in ("R5CWC1234", "emulator-5554", "192.168.1.5:5555", "abc.def_1"):
            self.assertEqual(self.plan("connect", ok)[1]["PDANET_ADB_SERIAL"], ok)

    def test_environment_is_minimal_and_fixed(self):
        os.environ["LD_PRELOAD"] = "/evil.so"
        try:
            _, env, _c = self.plan("connect", "X1")
        finally:
            del os.environ["LD_PRELOAD"]
        self.assertEqual(set(env) - {"PDANET_ADB_SERIAL"}, {"PATH", "LC_ALL", "HOME"})

    def test_older_install_helper_path_is_passed_back_to_cli(self):
        os.makedirs(_env.RUN, exist_ok=True)
        os.makedirs(os.path.join(_env.PROC, "88"), exist_ok=True)
        with open(os.path.join(_env.RUN, "helper-pid"), "w") as fh:
            fh.write("88\n")
        old = "/home/user/.local/bin/../libexec/pdanet-usb-helper"
        with open(os.path.join(_env.PROC, "88", "cmdline"), "wb") as fh:
            fh.write(b"/usr/bin/python3\0" + old.encode() + b"\0--connect\0127.0.0.1:1\0")
        _, env, _c = helper.build_plan(["disconnect"], run_dir=_env.RUN, proc_dir=_env.PROC)
        self.assertEqual(env["PDANET_USB_HELPER"], old)

    def test_main_refuses_to_run_unprivileged(self):
        if os.geteuid() != 0:
            self.assertEqual(helper.main(["disconnect"]), 2)
        self.assertEqual(helper.main(["bogus"]), 2)


class Translations(unittest.TestCase):
    def test_en_fa_have_identical_keys_and_placeholders(self):
        self.assertEqual(set(i18n.EN), set(i18n.FA))
        for key, en in i18n.EN.items():
            self.assertEqual(sorted(re.findall(r"{(\w+)}", en)),
                             sorted(re.findall(r"{(\w+)}", i18n.FA[key])), key)
            self.assertTrue(i18n.FA[key].strip(), key)

    def test_every_key_used_in_code_exists(self):
        pattern = re.compile(r"^(?:app|tab|menu|state|btn|hero|banner|group|row|stat|val|err|"
                             r"settings|toast|notify|about|log)\.[a-z_.]+$")
        used = set()
        for path in glob.glob(os.path.join(_env.ROOT, "gui", "pdanet_gui", "**", "*.py"), recursive=True):
            if path.endswith("i18n.py"):
                continue
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and pattern.match(node.value):
                    used.add(node.value)
        used -= {"app.about", "settings.json"}  # GIO action name and a filename, not UI strings
        self.assertTrue(len(used) > 60)
        self.assertEqual(sorted(k for k in used if k not in i18n.EN), [])

    def test_language_switch_and_rtl(self):
        self.assertEqual(i18n.set_language("fa"), "fa")
        self.assertTrue(i18n.is_rtl())
        self.assertEqual(i18n.tr("btn.connect"), "اتصال")
        self.assertIn("SM-A546E", i18n.tr("hero.ready", phone="SM-A546E"))
        self.assertEqual(i18n.set_language("en"), "en")
        self.assertFalse(i18n.is_rtl())
        self.assertEqual(i18n.tr("no.such.key"), "no.such.key")
        os.environ["LANG"] = "fa_IR.UTF-8"
        os.environ.pop("LC_ALL", None)
        os.environ.pop("LC_MESSAGES", None)
        self.assertEqual(i18n.resolve_language("system"), "fa")
        os.environ["LANG"] = "en_US.UTF-8"
        self.assertEqual(i18n.resolve_language("system"), "en")


if __name__ == "__main__":
    unittest.main()
