import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "scripts"
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SRC / file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module
T = load("recover_trial", "network-trial.py")
W = load("recover_web", "network-settings.py")

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = lambda p: self.root / str(p).lstrip("/")
        self.device = self.path("/sys/bus/usb/devices/2-1"); self.device.mkdir(parents=True)
        (self.device / "devnum").write_text("5")
        (self.device / "usbip_status").write_text("3")
        (self.device / "product").write_text("Test USB")
        self.path("/run").mkdir()
        for module in (T, W):
            patcher = patch.object(module, "Path", self.path); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(T, "run", side_effect=self.command_run)
        self.command = patcher.start(); self.addCleanup(patcher.stop)

    def command_run(self, *args, **kwargs):
        if args[:2] == ("systemctl", "show"): return "frozen"
        if args[:2] == ("/usr/sbin/usbip", "unbind"):
            (self.device / "usbip_status").unlink()
        if args[0] == "/usr/local/sbin/usbip-auto-share":
            (self.device / "usbip_status").write_text("1")
            self.path("/run/wyse-usb-paused/2-1").unlink()
        return ""

    def test_recover_error_only_and_resume(self):
        T.change_usb_share("usb-recover", "2-1", "5")
        self.assertEqual((self.device / "usbip_status").read_text(), "1")
        self.assertIn(("systemctl", "thaw", "usbipd.service"), [c.args for c in self.command.call_args_list])

    def test_busy_and_idle_are_rejected_without_unbind(self):
        for status in ("1", "2"):
            (self.device / "usbip_status").write_text(status)
            with self.assertRaises(ValueError): T.change_usb_share("usb-recover", "2-1", "5")
        self.assertFalse(any(c.args[0] == "/usr/sbin/usbip" for c in self.command.call_args_list))

    def test_changed_device_is_rejected(self):
        with self.assertRaises(ValueError): T.change_usb_share("usb-recover", "2-1", "4")
        self.assertFalse(any(c.args[0] == "/usr/sbin/usbip" for c in self.command.call_args_list))

    def test_failed_rebind_stays_paused_for_retry(self):
        def fail(*args, **kwargs):
            if args[0] == "/usr/local/sbin/usbip-auto-share": raise OSError("bind failed")
            return self.command_run(*args, **kwargs)
        self.command.side_effect = fail
        with self.assertRaises(OSError): T.change_usb_share("usb-recover", "2-1", "5")
        self.assertEqual(self.path("/run/wyse-usb-paused/2-1").read_text().strip(), "5")

    def test_web_button_only_for_error_and_parse(self):
        driver = self.path("/sys/bus/usb/drivers/usbip-host"); driver.mkdir(parents=True)
        (driver / "2-1").symlink_to(self.device)
        self.assertIn('value="usb-recover"', W.usb_sharing_card())
        (self.device / "usbip_status").write_text("2")
        self.assertNotIn('value="usb-recover"', W.usb_sharing_card())
        self.assertEqual(W.parse("usb-recover", {"bus": ["2-1"], "number": ["5"]}), ("usb-recover", "2-1", "5"))

if __name__ == "__main__": unittest.main()
