import curses
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("console_ui", Path(__file__).resolve().parents[1] / "scripts/console.py")
C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
ROWS = [("Network mode", ["Standalone (Wi-Fi AP + DHCP)"], "normal"),
        ("IPv4", ["enp1s0 192.0.2.10/24", "mlan0 10.42.0.1/24"], "normal"),
        ("Connections", ["wyse (mlan0)", "wyse-lan (enp1s0)"], "normal"),
        ("USB/IP clients", ["none"], "normal"), ("OS protection", ["ON"], "ok"),
        ("Next boot", ["ON (no change)"], "normal")]

class ConsoleTests(unittest.TestCase):
    def test_layout_actions_fit_80x24(self):
        rows = C.layout(ROWS, 0, "standalone", None, None, 80, 24)
        for _, text in C.ITEMS:
            self.assertTrue(any(text in row[2] for row in rows), text)
        self.assertTrue(any("[current]" in row[2] for row in rows))
        self.assertTrue(all(0 <= row[0] < 24 for row in rows))

    def test_color_and_monochrome(self):
        with patch.object(C.curses, "has_colors", return_value=False):
            self.assertTrue(C.styles()["selected"] & curses.A_REVERSE)
        with patch.object(C.curses, "has_colors", return_value=True), patch.object(C.curses, "start_color"), \
             patch.object(C.curses, "init_pair") as init, patch.object(C.curses, "color_pair", side_effect=lambda n:n*256):
            self.assertTrue(C.styles()["selected"] & curses.A_BOLD)
            self.assertEqual(init.call_count, 8)

    def test_no_selection_does_not_apply_settings(self):
        class Screen:
            keys = iter([-1, curses.KEY_UP, 10])
            def keypad(self, value): pass
            def timeout(self, value): pass
            def erase(self): pass
            def getmaxyx(self): return 24, 80
            def addnstr(self, *args): pass
            def refresh(self): pass
            def getch(self): return next(self.keys)
        with patch.object(C, "status", return_value=ROWS), \
             patch.object(C.curses, "has_colors", return_value=False), patch.object(C.curses, "curs_set"), \
             patch.object(C, "run_action") as action:
            C.menu(Screen())
            action.assert_not_called()

    def test_reboot_and_network_change_require_confirmation(self):
        self.assertIsNotNone(C.confirmation("reboot", ROWS))
        self.assertIsNotNone(C.confirmation("lan", ROWS))
        self.assertIsNone(C.confirmation("refresh", ROWS))

if __name__ == "__main__": unittest.main()
