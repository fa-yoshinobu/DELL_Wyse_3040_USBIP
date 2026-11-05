"""Simulated-NetworkManager tests for network-trial.py (not a substitute for on-device checks)."""
import sys, types
sys.dont_write_bytecode = True
try:
    import fcntl
except ImportError:  # Windows test host
    sys.modules.setdefault("fcntl", types.SimpleNamespace(flock=lambda *args: None, LOCK_EX=2))
import copy, importlib.util, io, json, subprocess, tempfile, unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from pathlib import Path

spec = importlib.util.spec_from_file_location("trial", Path(__file__).resolve().parent.parent / "scripts" / "network-trial.py")
T = importlib.util.module_from_spec(spec); spec.loader.exec_module(T)
AP, LAN = T.PROFILE, T.LAN_PROFILE
IFACE = {AP: "mlan0", LAN: "enp1s0"}


class FakeNM:
    def __init__(self, standalone=True):
        base = {AP: {"connection.autoconnect": "yes" if standalone else "no", "ipv4.addresses": "10.0.5.1/24",
                     "802-11-wireless.ssid": "myap", "ipv4.method": "manual"},
                LAN: {"connection.autoconnect": "yes", "ipv4.method": "manual", "ipv4.addresses": "192.168.0.80/24",
                      "ipv4.gateway": "", "ipv4.may-fail": "yes"}}
        self.disk = copy.deepcopy(base); self.runtime = copy.deepcopy(base)
        self.active = [LAN] + ([AP] if standalone else [])
        self.ip = {"enp1s0": "192.168.0.80/24", "mlan0": "10.0.5.1/24" if standalone else None}
        self.checkpoints = {}; self.sessions = ""; self.dhcp_ip = "192.168.0.123/24"
        self.fail_up = set(); self.fail_save = False; self.n = 0

    def snapshot(self):
        return copy.deepcopy((self.runtime, self.ip))

    def expire(self, cp):  # what NM does after the rollback timeout
        self.runtime, self.ip = self.checkpoints.pop(cp)

    def run(self, *c):
        if c[0] == "mountpoint":
            return ""
        if c[0] == "findmnt":
            return "ext4 rw,relatime"
        if c[0] == "busctl" and c[1] == "get-property":
            return "ao %d %s" % (len(self.checkpoints), " ".join(f'"{k}"' for k in self.checkpoints))
        if c[0] == "busctl" and "GetConnectionByUuid" in c:
            return f'o "/settings/{c[-1]}"'
        if c[0] == "busctl" and c[-1] == "Save":
            if self.fail_save:
                raise subprocess.CalledProcessError(1, c, stderr="save failed")
            uuid = c[3].rsplit("/", 1)[1]; self.disk[uuid] = copy.deepcopy(self.runtime[uuid]); return ""
        if c[0] == "busctl":
            method = c[5]
            if method == "CheckpointCreate":
                self.n += 1; cp = f"/cp/{self.n}"; self.checkpoints[cp] = self.snapshot()
                self.created_devices = c[8:8 + int(c[7])]; self.timeout = c[-2]; return f'o "{cp}"'
            if method == "CheckpointRollback":
                self.expire(c[-1]); return ""
            if method == "CheckpointDestroy":
                self.checkpoints.pop(c[-1]); return ""
            if method == "CheckpointAdjustRollbackTimeout":
                return ""
        if c[:3] == ("nmcli", "connection", "modify"):
            temp = c[3] == "--temporary"; rest = c[4:] if temp else c[3:]
            uuid, pairs = rest[1], rest[2:]
            for k, v in zip(pairs[0::2], pairs[1::2]):
                self.runtime[uuid][k] = v
                if not temp:
                    self.disk[uuid][k] = v
            return ""
        if c[:3] == ("nmcli", "--escape", "no"):
            return self.runtime[c[-1]].get(c[4], "")
        if c[:3] == ("nmcli", "-g", "UUID"):
            return "\n".join(self.active)
        if c[:3] == ("nmcli", "-g", "GENERAL.DBUS-PATH"):
            return "/dev/" + c[-1]
        if c[:4] == ("nmcli", "--wait", "15", "connection"):
            uuid = c[-1]
            if uuid in self.fail_up:
                raise subprocess.CalledProcessError(4, c, stderr="activation failed")
            r = self.runtime[uuid]
            self.ip[IFACE[uuid]] = self.dhcp_ip if r.get("ipv4.method") == "auto" else r["ipv4.addresses"]
            return ""
        if c[0] == "ip":
            v = self.ip.get(c[-3])
            if not v:
                return "[]"
            a, p = v.split("/"); return json.dumps([{"addr_info": [{"local": a, "prefixlen": int(p)}]}])
        if c[0] == "ss":
            return self.sessions
        raise AssertionError(c)


class Base(unittest.TestCase):
    standalone = True

    def setUp(self):
        self.samefile = patch.object(Path, "samefile", return_value=True)
        self.samefile.start()
        self.addCleanup(self.samefile.stop)
        self.nm = FakeNM(self.standalone)
        self.tmp = tempfile.TemporaryDirectory()
        T.STATE = Path(self.tmp.name) / "wyse-network-trial"
        T.run = self.nm.run; T.set_password_in_memory = lambda p: None; T.time.sleep = lambda s: None

    def tearDown(self):
        self.tmp.cleanup()

    def out(self, fn, *a):
        buf = io.StringIO()
        with redirect_stdout(buf):
            fn(*a)
        return buf.getvalue()


class Standalone(Base):
    def test_wifi_trial_then_confirm(self):
        self.assertEqual(json.loads(self.out(T.begin, "wifi", "10.42.9.1/24", "new", "")), {"wifi": "10.42.9.1"})
        self.assertEqual(self.nm.timeout, "120")
        self.assertEqual(self.nm.disk[AP]["802-11-wireless.ssid"], "myap")  # not saved yet
        with self.assertRaisesRegex(ValueError, "新しい接続先"):
            T.finish("10.0.5.1")
        T.finish("10.42.9.1")
        self.assertEqual(self.nm.disk[AP]["802-11-wireless.ssid"], "new")
        self.assertFalse(T.STATE.exists()); self.assertFalse(self.nm.checkpoints)

    def test_lan_timeout_restores(self):
        self.out(T.begin, "lan", "dhcp", "", "")
        self.nm.expire("/cp/1")
        with self.assertRaisesRegex(ValueError, "120秒"):
            T.finish("192.168.0.123")
        self.assertEqual(self.nm.runtime[LAN]["ipv4.method"], "manual")
        self.assertEqual(self.nm.disk[LAN]["ipv4.method"], "manual"); self.assertFalse(T.STATE.exists())

    def test_reset_one_checkpoint_confirm_via_wifi(self):
        self.assertEqual(json.loads(self.out(T.reset)), {"lan": "192.168.0.123", "wifi": "10.42.0.1"})
        self.assertEqual(self.nm.created_devices, ("/dev/enp1s0", "/dev/mlan0"))
        self.assertEqual(len(self.nm.checkpoints), 1)
        self.assertTrue(json.loads(self.out(T.status))["trial"]["reset"])
        T.finish("10.42.0.1")
        self.assertEqual(self.nm.disk[AP]["802-11-wireless.ssid"], "wyse")
        self.assertEqual(self.nm.disk[AP]["ipv4.addresses"], "10.42.0.1/24")
        self.assertEqual(self.nm.disk[AP]["connection.autoconnect"], "yes")  # mode kept
        self.assertEqual(self.nm.disk[LAN]["ipv4.method"], "auto")
        self.assertEqual(self.nm.disk[LAN]["ipv4.addresses"], "")

    def test_reset_confirm_via_new_dhcp_ip(self):
        self.out(T.reset)
        T.finish("192.168.0.123")
        self.assertEqual(self.nm.disk[LAN]["ipv4.method"], "auto")

    def test_reset_timeout_restores_both(self):
        self.out(T.reset); before = copy.deepcopy(self.nm.disk)
        self.nm.expire("/cp/1")
        self.assertEqual(self.nm.runtime, before)
        with self.assertRaises(ValueError):
            T.finish("10.42.0.1")
        self.assertEqual(self.nm.disk, before)
        self.assertIsNone(json.loads(self.out(T.status))["trial"])

    def test_reset_activation_failure_rolls_back_both(self):
        before = copy.deepcopy(self.nm.runtime); self.nm.fail_up.add(AP)
        with self.assertRaises(subprocess.CalledProcessError):
            self.out(T.reset)
        self.assertEqual(self.nm.runtime, before); self.assertFalse(T.STATE.exists())
        self.assertFalse(self.nm.checkpoints)

    def test_reset_without_dhcp_address_rolls_back(self):
        before = copy.deepcopy(self.nm.runtime); self.nm.dhcp_ip = None
        with self.assertRaisesRegex(ValueError, "IPv4"):
            self.out(T.reset)
        self.assertEqual(self.nm.runtime, before)

    def test_reset_rejected_with_usbip_client(self):
        self.nm.sessions = "ESTAB 0 0 192.168.0.80:3240 192.168.0.5:5000"
        with self.assertRaisesRegex(ValueError, "USB/IP"):
            self.out(T.reset)
        self.assertFalse(self.nm.checkpoints)

    def test_reset_rejected_during_trial(self):
        self.out(T.begin, "wifi", "10.42.9.1/24", "x", "")
        with self.assertRaisesRegex(ValueError, "試用中"):
            self.out(T.reset)
        self.assertEqual(len(self.nm.checkpoints), 1)

    def test_status(self):
        st = json.loads(self.out(T.status))
        self.assertEqual(st["mode"], "standalone")
        self.assertEqual(st["wifi"]["ssid"], "myap"); self.assertEqual(st["lan"]["current"], ["192.168.0.80/24"])


class ExistingLan(Base):
    standalone = False

    def test_wifi_begin_rejected(self):
        with self.assertRaisesRegex(ValueError, "単独モード"):
            self.out(T.begin, "wifi", "10.42.9.1/24", "x", "")

    def test_reset_defers_inactive_wifi_until_confirm(self):
        self.assertEqual(json.loads(self.out(T.reset)), {"lan": "192.168.0.123"})
        self.assertEqual(self.nm.created_devices, ("/dev/enp1s0",))
        self.assertEqual(self.nm.runtime[AP]["802-11-wireless.ssid"], "myap")
        T.finish("192.168.0.123")
        self.assertEqual(self.nm.disk[AP]["802-11-wireless.ssid"], "wyse")
        self.assertEqual(self.nm.disk[AP]["ipv4.addresses"], "10.42.0.1/24")
        self.assertEqual(self.nm.disk[AP]["connection.autoconnect"], "no")  # mode kept

    def test_reset_timeout_leaves_wifi_untouched(self):
        self.out(T.reset); self.nm.expire("/cp/1")
        with self.assertRaises(ValueError):
            T.finish("192.168.0.123")
        self.assertEqual(self.nm.disk[AP]["802-11-wireless.ssid"], "myap")

    def test_save_failure_restores_deferred_wifi(self):
        self.out(T.reset); self.nm.fail_save = True
        with self.assertRaises(subprocess.CalledProcessError):
            T.finish("192.168.0.123")
        self.assertEqual(self.nm.disk[AP]["802-11-wireless.ssid"], "myap")
        self.assertEqual(self.nm.disk[AP]["ipv4.addresses"], "10.0.5.1/24")


class Regression(Base):
    def test_fixed_gateway_dns_saved_only_on_confirm(self):
        self.out(T.begin, "lan", "192.168.0.90/24", "", "", "192.168.0.1", "192.168.0.1 1.1.1.1")
        self.assertEqual(self.nm.disk[LAN]["ipv4.gateway"], "")
        T.finish("192.168.0.90")
        self.assertEqual(self.nm.disk[LAN]["ipv4.gateway"], "192.168.0.1")
        self.assertEqual(self.nm.disk[LAN]["ipv4.dns"], "192.168.0.1,1.1.1.1")

    def test_gateway_outside_subnet_rejected(self):
        with self.assertRaises(ValueError):
            T.begin("lan", "192.168.0.90/24", "", "", "192.168.1.1", "")
        self.assertFalse(self.nm.checkpoints)

    def test_overlap_rejected_before_activation(self):
        for target, ip, ssid in (("wifi", "192.168.0.1/24", "x"), ("lan", "10.0.5.2/24", "")):
            with self.assertRaisesRegex(ValueError, "重複"):
                T.begin(target, ip, ssid, "")
        self.assertFalse(self.nm.checkpoints)

    def test_dhcp_overlap_rolls_back(self):
        before = self.nm.snapshot()
        self.nm.dhcp_ip = "10.0.5.2/24"
        with self.assertRaisesRegex(ValueError, "重複"):
            self.out(T.begin, "lan", "dhcp", "", "")
        self.assertEqual(self.nm.snapshot(), before)
        self.assertFalse(self.nm.checkpoints)

    def test_reset_dhcp_overlap_rolls_back(self):
        before = self.nm.snapshot()
        self.nm.dhcp_ip = "10.42.0.22/24"
        with self.assertRaisesRegex(ValueError, "重複"):
            self.out(T.reset)
        self.assertEqual(self.nm.snapshot(), before)

    def test_missing_or_readonly_volume_blocks_changes(self):
        real_run = self.nm.run
        for failure in ("missing", "readonly"):
            def run(*args):
                if args[0] == "mountpoint" and failure == "missing":
                    raise subprocess.CalledProcessError(1, args)
                if args[0] == "findmnt":
                    return "ext4 ro,relatime"
                return real_run(*args)
            with patch.object(T, "run", side_effect=run), self.assertRaisesRegex(ValueError, "保存領域"):
                T.begin("lan", "dhcp", "", "")
        self.assertFalse(self.nm.checkpoints)

    def test_wrong_bind_blocks_changes(self):
        with patch.object(Path, "samefile", return_value=False), self.assertRaisesRegex(ValueError, "保存領域"):
            T.begin("lan", "dhcp", "", "")
        self.assertFalse(self.nm.checkpoints)

    def test_volume_lost_before_confirmation_does_not_save(self):
        self.out(T.begin, "lan", "dhcp", "", "")
        before = copy.deepcopy(self.nm.disk)
        with patch.object(Path, "samefile", return_value=False), self.assertRaisesRegex(ValueError, "保存領域"):
            T.finish("192.168.0.123")
        self.assertEqual(self.nm.disk, before)
        self.assertTrue(self.nm.checkpoints)  # NM timeout can still roll back


class WebAndConsole(unittest.TestCase):
    def test_static_form_and_parser(self):
        spec = importlib.util.spec_from_file_location("web", Path(T.__file__).with_name("network-settings.py"))
        web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
        self.assertIn('name="gateway"', web.lan_card(None))
        self.assertIn('name="dns"', web.lan_card(None))
        fields = {"method": ["static"], "address": ["192.168.0.90/24"],
                  "gateway": ["192.168.0.1"], "dns": ["192.168.0.1 1.1.1.1"]}
        args = web.parse("begin-lan", fields)
        self.assertEqual(args[-2:], ("192.168.0.1", "192.168.0.1 1.1.1.1"))
        # Exercise the actual six-field CGI parser and root broker argument forwarding.
        from urllib.parse import urlencode
        import runpy
        body = urlencode({key: value[0] for key, value in fields.items()} | {"action": "begin-lan"})
        env = {"REMOTE_USER": "admin", "HTTPS": "on", "REQUEST_METHOD": "POST",
               "HTTP_ORIGIN": "https://test:8443", "HTTP_HOST": "test:8443", "CONTENT_LENGTH": str(len(body))}
        with patch.dict(web.os.environ, env, clear=True), patch.object(web.sys, "stdin", io.StringIO(body)), \
                patch.object(web, "request", return_value={"error": "test", "output": ""}) as request, \
                patch.object(web, "page"):
            web.main()
        request.assert_called_once_with(args)
        with patch.object(sys, "stdin", io.StringIO(json.dumps(args) + "\n")), \
                patch.object(subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout="", stderr="")) as run, \
                redirect_stdout(io.StringIO()):
            runpy.run_path(str(Path(T.__file__).with_name("network-request.py")))
        self.assertIn("--gateway=192.168.0.1", run.call_args.args[0])
        self.assertIn("--dns=192.168.0.1 1.1.1.1", run.call_args.args[0])

    def test_mode_change_stops_when_storage_check_fails(self):
        sys.modules.setdefault("curses", types.ModuleType("curses"))
        spec = importlib.util.spec_from_file_location("console", Path(T.__file__).with_name("console.py"))
        console = importlib.util.module_from_spec(spec); spec.loader.exec_module(console)
        with patch.object(console, "run", side_effect=subprocess.CalledProcessError(1, "check")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                console.set_mode(True)
        run.assert_called_once_with("/usr/local/sbin/wyse-network-trial", "check-settings", "--standalone")


if __name__ == "__main__":
    unittest.main()
