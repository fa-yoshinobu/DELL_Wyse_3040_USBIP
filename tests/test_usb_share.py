"""Linux tests with temporary sysfs fixtures; never touches real USB devices."""
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader("share", str(Path(__file__).resolve().parents[1] / "scripts/usbip-auto-share"))
spec = importlib.util.spec_from_loader(loader.name, loader)
S = importlib.util.module_from_spec(spec)
loader.exec_module(S)


class ShareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        for key in ("DEVICES", "BLOCKS", "PAUSED"):
            path = self.root / key
            path.mkdir()
            patcher = patch.object(S, key, path)
            patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(S, "LOCK", self.root / "lock")
        patcher.start(); self.addCleanup(patcher.stop)
        self.device = S.DEVICES / "2-1"
        self.device.mkdir()
        for key, value in {"devnum": "5", "bDeviceClass": "00", "bNumInterfaces": "1"}.items():
            (self.device / key).write_text(value)
        interface = self.device / "2-1:1.0"
        interface.mkdir(); (interface / "bInterfaceClass").write_text("08")
        self.calls = []
        patcher = patch.object(S.subprocess, "run", side_effect=self.bind)
        self.command = patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(S.time, "sleep")
        self.sleep = patcher.start(); self.addCleanup(patcher.stop)

    def bind(self, *args, **kwargs):
        self.calls.append(args[0])
        (self.device / "driver").symlink_to(self.root / "usbip-host")
        (self.device / "usbip_status").write_text("1")

    def test_transient_bind_failure_retries(self):
        def operation(*args, **kwargs):
            if self.command.call_count == 1:
                raise subprocess.CalledProcessError(1, "usbip")
            self.bind(*args, **kwargs)
        self.command.side_effect = operation
        S.share("2-1")
        self.assertEqual(self.command.call_count, 2)
        self.sleep.assert_called_once_with(1)

    def test_already_bound_without_interfaces_is_healthy(self):
        self.bind(["usbip", "bind"])
        (self.device / "2-1:1.0/bInterfaceClass").unlink()
        self.command.reset_mock()
        S.share("2-1")
        self.command.assert_not_called()
        self.sleep.assert_not_called()

    def test_retry_limit(self):
        self.command.side_effect = OSError("temporary failure")
        with self.assertRaises(OSError): S.share("2-1")
        self.assertEqual(self.command.call_count, 6)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [1, 2, 4, 8, 16])

    def test_descriptors_become_ready(self):
        (self.device / "bNumInterfaces").write_text("2")
        def ready(delay): (self.device / "bNumInterfaces").write_text("1")
        self.sleep.side_effect = ready
        S.share("2-1")
        self.assertEqual(self.command.call_count, 1)
        self.sleep.assert_called_once()

    def test_hid_and_composite_hid_are_excluded(self):
        for field in (self.device / "bDeviceClass", self.device / "2-1:1.0/bInterfaceClass"):
            field.write_text("03")
            S.share("2-1")
            field.write_text("00")
        self.command.assert_not_called()

    def test_paused_is_not_retried(self):
        (S.PAUSED / "2-1").write_text("5")
        S.share("2-1")
        self.command.assert_not_called()

    def test_old_pause_does_not_block_new_device(self):
        (S.PAUSED / "2-1").write_text("4")
        S.share("2-1")
        self.command.assert_called_once()

    def test_resume_removes_marker_only_after_success(self):
        marker = S.PAUSED / "2-1"; marker.write_text("5")
        S.share("2-1", "5")
        self.assertFalse(marker.exists())

    def test_replacement_during_resume_is_not_success(self):
        marker = S.PAUSED / "2-1"; marker.write_text("5")
        def replaced(*args, **kwargs):
            self.bind(*args, **kwargs)
            (self.device / "devnum").write_text("6")
        self.command.side_effect = replaced
        with self.assertRaises(OSError): S.share("2-1", "5")
        self.assertTrue(marker.exists())
        self.sleep.assert_not_called()

    def test_replacement_before_resume_is_rejected(self):
        (S.PAUSED / "2-1").write_text("4")
        with self.assertRaises(ValueError): S.share("2-1", "4")
        self.command.assert_not_called()

    def test_mounted_disk_is_excluded(self):
        block = self.device / "block/sda"; block.mkdir(parents=True)
        (S.BLOCKS / "sda").symlink_to(block)
        with patch.object(S.subprocess, "check_output", return_value="/mnt/data"):
            S.share("2-1")
        self.command.assert_not_called()

    def test_pause_between_retries_is_honored(self):
        self.command.side_effect = OSError("temporary failure")
        self.sleep.side_effect = lambda delay: (S.PAUSED / "2-1").write_text("5")
        S.share("2-1")
        self.command.assert_called_once()

    def test_concurrent_share_binds_only_once(self):
        # Separate opens of flock serialize independent callers, including threads.
        errors = []
        def call():
            try: S.share("2-1")
            except Exception as error: errors.append(error)
        threads = [threading.Thread(target=call) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.command.assert_called_once()


if __name__ == "__main__":
    unittest.main()
