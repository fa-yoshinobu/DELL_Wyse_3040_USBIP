import importlib.util
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "scripts"
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SRC / file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module
P = load("passwords", "web-password.py")
W = load("password_web", "network-settings.py")
C = load("password_console", "console.py")

class PasswordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        patcher = patch.object(P, "DIRECTORY", Path(self.temp.name)); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(P, "check_storage"); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(P.os, "fchown"); patcher.start(); self.addCleanup(patcher.stop)
        self.old = "Test-old-1234"
        self.file = P.DIRECTORY / "htpasswd"
        self.file.write_text("admin:" + P.password_hash(self.old, "apr1") + "\n")

    def test_change_migrates_hash_and_rejects_old_password(self):
        P.change(self.old, "Test-new-5678", "Test-new-5678")
        encoded = self.file.read_text().strip().split(":", 1)[1]
        self.assertTrue(encoded.startswith("$6$"))
        self.assertTrue(P.verify("Test-new-5678", encoded))
        self.assertFalse(P.verify(self.old, encoded))
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o640)
        self.assertNotIn("Test-new-5678", self.file.read_text())

    def test_wrong_old_mismatch_and_invalid_new_do_not_change_file(self):
        before = self.file.read_bytes()
        for args in [("wrong", "new-12345", "new-12345"), (self.old, "new-12345", "other-123"),
                     (self.old, "four", "four"), (self.old, "space pass", "space pass")]:
            with self.assertRaises(ValueError): P.change(*args)
            self.assertEqual(self.file.read_bytes(), before)

    def test_password_length_boundaries(self):
        for password in ["Ab1!?", "a" * 64]:
            with self.subTest(length=len(password)):
                self.file.write_text("admin:" + P.password_hash(self.old, "apr1") + "\n")
                P.change(self.old, password, password)
                self.assertTrue(P.verify(password, self.file.read_text().strip().split(":", 1)[1]))
                W.parse("web-password", {"current_password": [self.old], "new_password": [password], "confirm_password": [password]})
        for password in ["four", "a" * 65, "あいうえお", "ab cd"]:
            with self.subTest(password=password):
                with self.assertRaises(ValueError): P.change(self.old, password, password)
                with self.assertRaises(ValueError):
                    W.parse("web-password", {"current_password": [self.old], "new_password": [password], "confirm_password": [password]})
        self.assertEqual(W.password_card().count('minlength="5"'), 2)

    def test_storage_failure_leaves_password_unchanged(self):
        before = self.file.read_bytes()
        with patch.object(P, "check_storage", side_effect=ValueError("read-only")):
            with self.assertRaises(ValueError): P.change(self.old, "new-12345", "new-12345")
        self.assertEqual(self.file.read_bytes(), before)

    def test_reset_generates_password_without_storing_plaintext(self):
        password = P.reset()
        self.assertGreaterEqual(len(password), 16)
        self.assertTrue(P.verify(password, self.file.read_text().strip().split(":", 1)[1]))
        self.assertNotIn(password, self.file.read_text())
        self.assertEqual(len(list(P.DIRECTORY.iterdir())), 1)

    def test_request_passes_secrets_only_on_stdin(self):
        args = ["web-password", self.old, "new-12345", "new-12345"]
        with patch("sys.stdin", io.StringIO(json.dumps(args))), patch("sys.stdout", io.StringIO()), \
             patch("subprocess.run") as run:
            run.return_value.returncode = 0; run.return_value.stdout = ""; run.return_value.stderr = ""
            runpy.run_path(str(SRC / "network-request.py"), run_name="password_request")
            self.assertEqual(run.call_args.args[0], ["/usr/local/sbin/wyse-web-password", "change"])
            self.assertEqual(json.loads(run.call_args.kwargs["input"]), args[1:])

    def test_web_cannot_request_reset(self):
        with patch("sys.stdin", io.StringIO('["web-password-reset"]')), patch("sys.stdout", io.StringIO()), \
             patch("subprocess.run") as run:
            runpy.run_path(str(SRC / "network-request.py"), run_name="reset_request")
            run.assert_not_called()

    def test_form_and_console_confirmation(self):
        html = W.password_card()
        self.assertEqual(html.count('type="password"'), 3)
        with self.assertRaises(ValueError):
            W.parse("web-password", {"current_password": [self.old], "new_password": ["new-12345"], "confirm_password": ["mismatch"]})
        self.assertIsNotNone(C.confirmation("web-password-reset", []))

if __name__ == "__main__": unittest.main()
