import sys
import types
sys.dont_write_bytecode = True
try:
    import fcntl
except ImportError:  # Windows test host
    sys.modules.setdefault("fcntl", types.SimpleNamespace(flock=lambda *args: None, LOCK_EX=2))
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parent.parent / "scripts"
spec = importlib.util.spec_from_file_location("update", SRC / "os-update.py")
U = importlib.util.module_from_spec(spec); spec.loader.exec_module(U)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in {"STATE": self.root / "state.json", "CHECK": self.root / "check.json",
                            "PROTECTION": self.root / "overlayroot.conf", "LOCK": self.root / "lock"}.items():
            patcher = patch.object(U, name, value); patcher.start(); self.addCleanup(patcher.stop)
        self.original = U.ON
        U.PROTECTION.write_text(self.original)
        for name, replacement in (("atomic", lambda path, text: path.write_text(text, encoding="utf-8")),
                                  ("boot_id", lambda: "boot1"), ("root_fs", lambda: "ext4")):
            patcher = patch.object(U, name, replacement); patcher.start(); self.addCleanup(patcher.stop)
        self.runner = patch.object(U, "run", return_value=""); self.run = self.runner.start(); self.addCleanup(self.runner.stop)
        self.cmd = patch.object(U, "command"); self.command = self.cmd.start(); self.addCleanup(self.cmd.stop)
        self.sync = patch.object(U.os, "sync", create=True); self.sync.start(); self.addCleanup(self.sync.stop)

    def state(self, phase):
        U.save(U.STATE, {"phase": phase, "protection": self.original, "boot": "boot1"})

    def test_update_restores_protection_before_apt_and_reboots(self):
        self.state("maintenance"); U.PROTECTION.write_text(U.OFF)
        def command(*args):
            self.assertEqual(U.PROTECTION.read_text(), U.ON)
            self.assertEqual(U.read(U.STATE)["phase"], "running")
        self.command.side_effect = command
        U.worker()
        data = U.read(U.STATE)
        self.assertEqual(data["phase"], "rebooting"); self.assertEqual(data["result"], "success")
        commands = [call.args[0] for call in self.command.call_args_list]
        self.assertIn("--error-on=any", commands[0])
        self.assertIn("--no-remove", commands[1]); self.assertIn("--with-new-pkgs", commands[1])
        self.run.assert_any_call("systemctl", "reboot", "--no-block")
        with patch.object(U, "root_fs", return_value="overlay"):
            U.worker()
        self.assertEqual(U.read(U.STATE)["phase"], "success")

    def test_apt_failure_restores_protection_and_records_failure(self):
        self.state("maintenance"); self.command.side_effect = RuntimeError("fetch failed")
        U.worker()
        self.assertEqual(U.PROTECTION.read_text(), U.ON)
        self.assertEqual(U.read(U.STATE)["result"], "failed")
        self.assertEqual(self.command.call_count, 1)

    def test_power_loss_never_repeats_transaction(self):
        self.state("running")
        U.worker()
        self.command.assert_not_called()
        self.assertEqual(U.read(U.STATE)["phase"], "failed")
        self.assertEqual(U.PROTECTION.read_text(), U.ON)

    def test_overlay_boot_refuses_real_upgrade(self):
        self.state("maintenance")
        with patch.object(U, "root_fs", return_value="overlay"):
            U.worker()
        self.command.assert_not_called(); self.assertEqual(U.read(U.STATE)["phase"], "failed")

    def test_missing_protection_after_reboot_reports_failure(self):
        self.state("rebooting")
        U.worker()
        self.assertEqual(U.read(U.STATE)["phase"], "failed")

    def test_idle_boot_does_nothing(self):
        U.worker(); self.command.assert_not_called(); self.run.assert_not_called()

    def test_active_update_blocks_other_changes(self):
        for phase in U.ACTIVE:
            self.state(phase)
            with self.assertRaises(ValueError): U.guard()

    def test_usb_client_blocks_update(self):
        self.run.return_value = "ESTAB"
        with self.assertRaisesRegex(ValueError, "USB/IP"): U.idle()

    def test_trial_blocks_update(self):
        self.run.side_effect = ["", 'ao 1 "/checkpoint/1"']
        with self.assertRaisesRegex(ValueError, "試用中"): U.idle()

    def test_check_parses_candidates_without_installing(self):
        plan = "Inst linux-image-test (1 Debian)\nInst test [1] (2 Debian)\n2 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.\n"
        with patch.object(U.subprocess, "check_output", return_value=plan): U.check_worker()
        result = U.read(U.CHECK)
        self.assertEqual(result["phase"], "ready"); self.assertEqual(result["count"], 2)
        self.assertEqual(self.command.call_count, 1)
        self.assertIn("update", self.command.call_args.args[0])

    def test_check_failure_is_not_ready(self):
        self.command.side_effect = RuntimeError("offline")
        U.check_worker(); self.assertEqual(U.read(U.CHECK)["phase"], "failed")

    def test_apply_requires_a_completed_check(self):
        with self.assertRaisesRegex(ValueError, "更新を確認"):
            U.request("apply")
        self.assertFalse(U.STATE.exists())

    def test_apply_rejects_busy_usb_without_changing_protection(self):
        U.save(U.CHECK, {"phase": "ready"})
        with patch.object(U, "idle", side_effect=ValueError("USB/IP busy")):
            with self.assertRaisesRegex(ValueError, "USB/IP"):
                U.request("apply")
        self.assertFalse(U.STATE.exists())
        self.assertEqual(U.PROTECTION.read_text(), U.ON)

    def test_apply_queues_once_and_preserves_original_protection(self):
        U.save(U.CHECK, {"phase": "ready"})
        with patch.object(U, "idle"), patch.object(U.shutil, "disk_usage", return_value=types.SimpleNamespace(free=1024**3)):
            U.request("apply")
            with self.assertRaisesRegex(ValueError, "更新処理中"):
                U.request("apply")
        self.assertEqual(U.read(U.STATE)["phase"], "queued")
        self.assertEqual(U.read(U.STATE)["protection"], U.ON)
        self.assertEqual(U.PROTECTION.read_text(), U.ON)
        self.run.assert_any_call("systemctl", "start", "--no-block", "wyse-os-update-prepare.service")

    def test_prepare_sets_maintenance_then_reboots(self):
        self.state("queued")
        with patch.object(U, "idle"), patch.object(U, "root_fs", return_value="overlay"), patch("time.sleep"):
            U.prepare()
        self.assertEqual(U.read(U.STATE)["phase"], "maintenance")
        self.assertEqual(U.PROTECTION.read_text(), U.OFF)
        self.run.assert_any_call("systemctl", "reboot", "--no-block")

    def test_prepare_failure_does_not_leave_protection_disabled(self):
        self.state("queued")
        with patch.object(U, "idle", side_effect=ValueError("busy")), patch("time.sleep"):
            U.prepare()
        self.assertEqual(U.PROTECTION.read_text(), U.ON)
        self.assertEqual(U.read(U.STATE)["phase"], "failed")


if __name__ == "__main__": unittest.main()
