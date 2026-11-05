#!/usr/bin/python3
"""Try network changes in memory and commit them after reachability is confirmed."""

import argparse
import fcntl
import ipaddress
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time

PROFILE = "12130d96-e908-42ce-9561-1ae5bd132282"
LAN_PROFILE = "9f2e56cf-5d10-4d5b-a03e-efed733fd464"
TARGETS = {"wifi": (PROFILE, "mlan0"), "lan": (LAN_PROFILE, "enp1s0")}
# ネットワーク設定の初期値。Wi-Fiのセキュリティ、モード選択、Web/OS設定は対象外。
DEFAULTS = {"lan": ("dhcp", ""), "wifi": ("10.42.0.1/24", "wyse")}
NM = "org.freedesktop.NetworkManager"
ROOT = "/org/freedesktop/NetworkManager"
STATE = Path("/run/wyse-network-trial")


def run(*command, timeout=25):
    return subprocess.check_output(command, text=True, timeout=timeout, stderr=subprocess.PIPE).strip()


def call(method, signature, *args):
    return run("busctl", "call", NM, ROOT, NM, method, signature, *args)


def live_checkpoints():
    value = run("busctl", "get-property", NM, ROOT, NM, "Checkpoints")
    return shlex.split(value)[2:]


def connection_path(uuid):
    _, profile = shlex.split(run("busctl", "call", NM, ROOT + "/Settings",
                                 NM + ".Settings", "GetConnectionByUuid", "s", uuid))
    return profile


def setting(uuid, field):
    return run("nmcli", "--escape", "no", "-g", field, "connection", "show", "uuid", uuid)


def active_uuids():
    return run("nmcli", "-g", "UUID", "connection", "show", "--active").splitlines()


def addresses(interface):
    try:
        devices = json.loads(run("ip", "-j", "-4", "address", "show", "dev", interface, "scope", "global"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    return [f"{info['local']}/{info['prefixlen']}" for device in devices for info in device.get("addr_info", [])]


def live_trial():
    """Return the trial state while its checkpoint can still roll back, else None."""
    if not STATE.exists():
        return None
    trial = json.loads(STATE.read_text())
    return trial if trial["checkpoint"] in live_checkpoints() else None


def set_password_in_memory(password):
    import dbus

    proxy = dbus.SystemBus().get_object(NM, connection_path(PROFILE))
    connection = dbus.Interface(proxy, NM + ".Settings.Connection")
    try:
        settings = connection.GetSettings(timeout=10)
        security = settings.setdefault("802-11-wireless-security", dbus.Dictionary(signature="sv"))
        security["key-mgmt"] = dbus.String("wpa-psk")
        security["psk"] = dbus.String(password)
        security["psk-flags"] = dbus.UInt32(0)
        connection.Update2(settings, dbus.UInt32(2), dbus.Dictionary(signature="sv"), timeout=10)
    except dbus.DBusException:
        raise ValueError("Wi-Fiのセキュリティ設定をNetworkManagerが受け付けませんでした") from None


def ensure_settings():
    volume = Path("/var/lib/wyse-settings")
    profiles = Path("/etc/NetworkManager/system-connections")
    try:
        for path in (volume, profiles):
            run("mountpoint", "-q", str(path))
            fs, options = run("findmnt", "-n", "-o", "FSTYPE,OPTIONS", "--mountpoint", str(path)).split()
            if fs != "ext4" or "rw" not in options.split(","):
                raise ValueError
        if not profiles.samefile(volume / "system-connections"):
            raise ValueError
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ValueError("設定保存領域を利用できません。設定は変更していません") from None


def check_overlap(overrides=None):
    overrides = overrides or {}
    networks = {}
    for target, (uuid, interface) in TARGETS.items():
        if target in overrides:
            values = [] if overrides[target] == "dhcp" else [str(overrides[target])]
        else:
            configured = setting(uuid, "ipv4.addresses")
            values = configured.split(",") if configured else []
            values += addresses(interface)
        networks[target] = [ipaddress.IPv4Interface(value.strip()).network for value in values]
    if any(a.overlaps(b) for a in networks["lan"] for b in networks["wifi"]):
        raise ValueError("有線LANとWi-Fiのアドレス帯が重複しています。別のネットワークを指定してください")


def validate(target, address, ssid, password="", gateway="", dns=""):
    """Return (normalized address, nmcli changes) for one interface."""
    if target == "wifi" and (not 1 <= len(ssid.encode()) <= 32 or any(ord(char) < 32 for char in ssid)):
        raise ValueError("SSIDは1〜32バイトで、制御文字を含めないでください")
    dhcp = address == "dhcp" and target == "lan"
    if not dhcp:
        address = ipaddress.IPv4Interface(address)
        if (address.ip in (address.network.network_address, address.network.broadcast_address)
                or address.ip.is_multicast or address.ip.is_loopback or address.ip.is_unspecified):
            raise ValueError("IPアドレスは「192.168.0.80/24」のように、ホストのアドレスとプレフィックスで入力してください")
    if password and (not 8 <= len(password) <= 63 or any(not 32 <= ord(c) <= 126 for c in password)):
        raise ValueError("WPA2パスワードは半角英数記号8〜63文字で入力してください")
    if target == "wifi":
        return address, ("ipv4.addresses", str(address), "802-11-wireless.ssid", ssid)
    if gateway:
        gateway_ip = ipaddress.IPv4Address(gateway)
        if dhcp or gateway_ip not in address.network or gateway_ip in (
                address.ip, address.network.network_address, address.network.broadcast_address):
            raise ValueError("ゲートウェイは固定IPと同じネットワーク内の別のホストを指定してください")
    servers = [ipaddress.IPv4Address(value) for value in dns.replace(",", " ").split()]
    if any(ip.is_unspecified or ip.is_multicast or ip.is_loopback or int(ip) == 0xffffffff for ip in servers):
        raise ValueError("DNSサーバーのIPv4アドレスが正しくありません")
    return address, ("ipv4.method", "auto" if dhcp else "manual",
                     "ipv4.addresses", "" if dhcp else str(address), "ipv4.gateway", "" if dhcp else gateway,
                     "ipv4.dns", "" if dhcp else ",".join(map(str, servers)),
                     "ipv4.ignore-auto-dns", "no",
                     "ipv4.may-fail", "no")


def ensure_idle():
    if live_trial():
        raise ValueError("別のネットワーク設定を試用中です。確定するか、120秒後に元に戻るまで待ってください")
    if run("ss", "-Hnt", "state", "established", "( sport = :3240 )"):
        raise ValueError("USB/IPクライアントが接続中です。PC側で機器を切断してから、もう一度操作してください")


def wait_address(interface, address):
    expected = None if address == "dhcp" else str(address.ip)
    for _ in range(16):
        found = [value.split("/")[0] for value in addresses(interface)]
        management = (found[0] if found else None) if expected is None else (
            expected if expected in found else None)
        if management:
            return management
        time.sleep(0.5)
    raise ValueError("IPv4アドレスを取得できなかったため、元の設定に戻しました")


def start(plan, deferred=(), password="", reset=False):
    """Apply plan [(target, address, changes)] under one checkpoint.

    deferred holds changes for inactive profiles; they are written only on confirmation.
    """
    ensure_settings()
    overrides = {target: address for target, address, _ in plan}
    for item in deferred:
        target = next(key for key, value in TARGETS.items() if value[0] == item["uuid"])
        overrides[target] = dict(zip(item["changes"][::2], item["changes"][1::2]))["ipv4.addresses"]
    check_overlap(overrides)
    devices = [run("nmcli", "-g", "GENERAL.DBUS-PATH", "device", "show", TARGETS[target][1])
               for target, _, _ in plan]
    _, checkpoint = shlex.split(call("CheckpointCreate", "aouu", str(len(devices)), *devices, "120", "0"))
    try:
        for target, _, changes in plan:
            run("nmcli", "connection", "modify", "--temporary", "uuid", TARGETS[target][0], *changes)
            if target == "wifi" and password:
                set_password_in_memory(password)
        for target, _, _ in plan:
            run("nmcli", "--wait", "15", "connection", "up", "uuid", TARGETS[target][0])
        management = {target: wait_address(TARGETS[target][1], address) for target, address, _ in plan}
        # DHCP addresses are only known after activation. Roll back a conflict too.
        check_overlap({key: value for key, value in overrides.items()
                       if key not in management})
        STATE.write_text(json.dumps({
            "checkpoint": checkpoint, "addresses": management, "reset": reset,
            "uuids": [TARGETS[target][0] for target, _, _ in plan], "deferred": list(deferred)}))
        print(json.dumps(management))
    except (OSError, ValueError, subprocess.SubprocessError):
        call("CheckpointRollback", "o", checkpoint)
        raise


def begin(target, address, ssid, password, gateway="", dns=""):
    address, changes = validate(target, address, ssid, password, gateway, dns)
    ensure_idle()
    if TARGETS[target][0] not in active_uuids():
        raise ValueError(("Wi-Fi親機が動作していません。単独モードに切り替えてから設定してください"
                          if target == "wifi" else "有線LANが接続されていません"))
    start([(target, address, changes)], password=password)


def reset():
    ensure_idle()
    active = active_uuids()
    plan, deferred = [], []
    for target, (address, ssid) in DEFAULTS.items():
        address, changes = validate(target, address, ssid)
        uuid = TARGETS[target][0]
        if uuid in active:
            plan.append((target, address, changes))
        else:
            fields = changes[0::2]
            original = [value for field in fields for value in (field, setting(uuid, field))]
            deferred.append({"uuid": uuid, "changes": list(changes), "original": original})
    if not plan:
        raise ValueError("有効なネットワーク接続がないため初期化できません")
    start(plan, deferred, reset=True)


def finish(address):
    ensure_settings()
    trial = json.loads(STATE.read_text())
    checkpoint = trial["checkpoint"]
    management = trial.get("addresses") or {"": trial["address"]}
    if str(address) not in management.values():
        raise ValueError("新しい接続先 (" + "、".join(management.values()) + ") で画面を開いて確定してください")
    # Verify the checkpoint is still live before persisting the in-memory profile.
    if checkpoint not in live_checkpoints():
        STATE.unlink()
        raise ValueError("120秒を過ぎたため、元の設定に戻りました。もう一度試してください")
    deferred_addresses = {}
    for item in trial.get("deferred", []):
        target = next(key for key, value in TARGETS.items() if value[0] == item["uuid"])
        deferred_addresses[target] = dict(zip(item["changes"][::2], item["changes"][1::2]))["ipv4.addresses"]
    check_overlap(deferred_addresses)
    call("CheckpointAdjustRollbackTimeout", "ou", checkpoint, "30")
    applied = []
    try:
        for item in trial.get("deferred", []):
            run("nmcli", "connection", "modify", "uuid", item["uuid"], *item["changes"])
            applied.append(item)
        for uuid in trial.get("uuids", [trial.get("uuid", PROFILE)]):
            run("busctl", "call", NM, connection_path(uuid), NM + ".Settings.Connection", "Save")
    except (OSError, ValueError, subprocess.SubprocessError):
        for item in applied:
            run("nmcli", "connection", "modify", "uuid", item["uuid"], *item["original"])
        raise
    call("CheckpointDestroy", "o", checkpoint)
    STATE.unlink()


def change_hostname(name):
    import os
    import re
    import tempfile

    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", name):
        raise ValueError("機器名は英小文字・数字・ハイフンの1〜63文字で、先頭と末尾は英数字にしてください")
    volume = Path("/var/lib/wyse-settings")
    if not volume.is_mount():
        raise ValueError("設定保存領域を利用できません")
    with tempfile.NamedTemporaryFile(mode="w", dir=volume, delete=False) as temporary:
        path = Path(temporary.name)
        try:
            temporary.write(name + "\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            run("hostnamectl", "set-hostname", name)
            path.replace(volume / "hostname")
            directory = os.open(volume, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            run("systemctl", "try-restart", "avahi-daemon.service")
        finally:
            path.unlink(missing_ok=True)


def change_usb_share(action, bus, number):
    import re

    if not re.fullmatch(r"[0-9]+-[0-9]+(?:\.[0-9]+)*", bus) or not number.isdecimal():
        raise ValueError("USB機器の識別子が正しくありません")
    if action == "usb-resume":
        run("/usr/local/sbin/usbip-auto-share", bus, "--resume", number, timeout=25)
        return
    with Path("/run/wyse-usb-share.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pause_usb_share(bus, number, recover=action == "usb-recover")
    if action == "usb-recover":
        run("/usr/local/sbin/usbip-auto-share", bus, "--resume", number, timeout=25)


def pause_usb_share(bus, number, recover=False):
    device = Path("/sys/bus/usb/devices") / bus
    paused = Path("/run/wyse-usb-paused")
    paused.mkdir(mode=0o755, exist_ok=True)
    marker = paused / bus
    # Freeze the listener and its workers so an attach cannot race with unbind.
    try:
        run("systemctl", "freeze", "usbipd.service", timeout=5)
        for _ in range(20):
            if run("systemctl", "show", "-p", "FreezerState", "--value", "usbipd.service", timeout=2) == "frozen":
                break
            time.sleep(0.05)
        else:
            raise ValueError("USB/IPの新規接続を一時停止できませんでした")
        if (device / "devnum").read_text().strip() != number:
            raise ValueError("USB機器が変わりました。画面を再読み込みしてください")
        expected = "3" if recover else "1"
        if (device / "usbip_status").read_text().strip() != expected:
            raise ValueError("復旧できるのはエラー状態の機器だけです。画面を再読み込みしてください" if recover else
                             "使用中の機器は停止できません。クライアントから切断してください")
        marker.write_text(number + "\n")
        try:
            run("/usr/sbin/usbip", "unbind", "-b", bus, timeout=5)
        except (OSError, subprocess.SubprocessError):
            marker.unlink(missing_ok=True)
            raise
    finally:
        run("systemctl", "thaw", "usbipd.service", timeout=5)


def status():
    active = active_uuids()
    trial = live_trial()
    print(json.dumps({
        "hostname": socket.gethostname(),
        "mode": "standalone" if setting(PROFILE, "connection.autoconnect") == "yes" else "lan",
        "lan": {"active": LAN_PROFILE in active, "method": setting(LAN_PROFILE, "ipv4.method"),
                "configured": setting(LAN_PROFILE, "ipv4.addresses"), "current": addresses("enp1s0"),
                "gateway": setting(LAN_PROFILE, "ipv4.gateway"), "dns": setting(LAN_PROFILE, "ipv4.dns")},
        "wifi": {"active": PROFILE in active, "ssid": setting(PROFILE, "802-11-wireless.ssid"),
                 "configured": setting(PROFILE, "ipv4.addresses"), "current": addresses("mlan0")},
        "trial": trial and {"addresses": trial.get("addresses") or {"wifi": trial["address"]},
                            "reset": trial.get("reset", False)},
    }, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    actions = parser.add_subparsers(dest="action", required=True)
    start_parser = actions.add_parser("begin")
    start_parser.add_argument("address")
    start_parser.add_argument("ssid", nargs="?", default="")
    start_parser.add_argument("--target", choices=("wifi", "lan"), default="wifi")
    start_parser.add_argument("--gateway", default="")
    start_parser.add_argument("--dns", default="")
    check = actions.add_parser("check-settings")
    check.add_argument("--standalone", action="store_true")
    actions.add_parser("reset")
    actions.add_parser("status")
    hostname_parser = actions.add_parser("hostname")
    hostname_parser.add_argument("name")
    for action in ("usb-pause", "usb-resume", "usb-recover"):
        usb_parser = actions.add_parser(action)
        usb_parser.add_argument("bus")
        usb_parser.add_argument("number")
    confirm = actions.add_parser("confirm")
    confirm.add_argument("address", type=ipaddress.IPv4Address)
    args = parser.parse_args()
    if args.action == "check-settings":
        run("/usr/local/sbin/wyse-os-update", "guard")
        ensure_settings()
        if args.standalone:
            check_overlap()
        return
    if args.action == "status":
        status()
        return
    with STATE.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        run("/usr/local/sbin/wyse-os-update", "guard")
        if args.action == "begin":
            password = "" if sys.stdin.isatty() else sys.stdin.read(64)
            begin(args.target, args.address, args.ssid, password, args.gateway, args.dns)
        elif args.action == "reset":
            reset()
        elif args.action == "hostname":
            change_hostname(args.name)
        elif args.action in ("usb-pause", "usb-resume", "usb-recover"):
            change_usb_share(args.action, args.bus, args.number)
        else:
            finish(args.address)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(getattr(error, "stderr", "") or str(error), file=sys.stderr)
        sys.exit(1)
