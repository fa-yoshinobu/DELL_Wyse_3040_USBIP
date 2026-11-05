import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.dont_write_bytecode = True


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent.parent / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H = load("history", "usbip-history.py")
W = load("web", "usbip-status.py")


def device(status="2", number="1"):
    return {"number": number, "status": status, "name": "USB <test>", "ids": "1234:5678"}


class HistoryTests(unittest.TestCase):
    def test_connect_disconnect_and_no_duplicates(self):
        idle, busy = {"2-1": device("1")}, {"2-1": device()}
        self.assertEqual(H.changes(idle, busy, "now")[0]["event"], "接続")
        self.assertEqual(H.changes(busy, idle, "now")[0]["event"], "切断")
        self.assertEqual(H.changes(busy, busy, "now"), [])
        self.assertEqual(H.changes({}, idle, "now"), [])

    def test_unplug_and_replacement(self):
        before = {"2-1": device()}
        self.assertEqual(H.changes(before, {}, "now")[0]["event"], "切断")
        events = H.changes(before, {"2-1": device(number="2")}, "now")
        self.assertEqual([event["event"] for event in events], ["切断", "接続"])

    def test_initial_connection_is_not_claimed_as_new(self):
        self.assertEqual(H.changes({}, {"2-1": device()}, "now", initial=True)[0]["event"], "使用中を検出")

    def test_bounded_history_and_html_escaping(self):
        with tempfile.TemporaryDirectory() as directory:
            H.STATE = Path(directory) / "history.json"
            events = H.changes({}, {"2-1": device()}, "now") * 205
            H.save(events, {})
            self.assertEqual(len(json.loads(H.STATE.read_text(encoding="utf-8"))["events"]), 200)
            html = W.history_card(H.STATE)
            self.assertIn("USB &lt;test&gt;", html)
            self.assertNotIn("USB <test>", html)
            self.assertEqual(html.count("<li>"), 200)
            self.assertFalse(H.STATE.with_suffix(".tmp").exists())

    def test_one_incomplete_device_does_not_block_other_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); driver = root / "driver"; driver.mkdir()
            for bus, status in (("2-1", "invalid"), ("2-2", "2")):
                d = root / bus; d.mkdir(); (driver / bus).symlink_to(d)
                for key, value in {"devnum": "1", "usbip_status": status,
                                   "idVendor": "1234", "idProduct": "5678"}.items():
                    (d / key).write_text(value)
            previous = {"2-1": device(), "2-2": device("1")}
            current = H.snapshot(driver, previous)
            self.assertEqual(current["2-1"], previous["2-1"])
            events = H.changes(previous, current, "now")
            self.assertEqual([(e["bus"], e["event"]) for e in events], [("2-2", "接続")])
            (root / "2-1/usbip_status").write_text("1")
            recovered = H.snapshot(driver, current)
            self.assertEqual(H.changes(current, recovered, "now")[0]["event"], "切断")
            (root / "2-1/devnum").write_text("2")
            (root / "2-1/usbip_status").write_text("invalid")
            self.assertNotIn("2-1", H.snapshot(driver, previous))
            (driver / "2-1").unlink()
            self.assertNotIn("2-1", H.snapshot(driver, previous))

    def test_missing_history(self):
        self.assertIn("取得できません", W.history_card(Path("nonexistent-history.json")))


if __name__ == "__main__":
    unittest.main()
