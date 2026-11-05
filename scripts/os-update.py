#!/usr/bin/python3
"""Authenticated Web requests queue APT work; upgrades run on the real root after reboot."""
from collections import deque
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

VOLUME = Path("/var/lib/wyse-settings")
STATE = VOLUME / "os-update.json"
PROTECTION = VOLUME / "overlayroot.conf"
CHECK = Path("/run/wyse-apt-check.json")
LOCK = Path("/run/wyse-network-trial.lock")
OFF = 'overlayroot="disabled"\n'
ON = 'overlayroot="tmpfs:recurse=0,swap=0"\n'
ACTIVE = {"queued", "maintenance", "running", "rebooting"}
ENV = dict(os.environ, LC_ALL="C", DEBIAN_FRONTEND="noninteractive", NEEDRESTART_MODE="a")
APT = ["/usr/bin/apt-get", "-o", "Acquire::Retries=3", "-o", "Acquire::http::Timeout=20",
       "-o", "Acquire::https::Timeout=20", "-o", "DPkg::Lock::Timeout=60"]


def read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def atomic(path, text):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
            temporary.replace(path)
            fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temporary.unlink(missing_ok=True)


def save(path, data):
    atomic(path, json.dumps(data, ensure_ascii=False))


def stamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=30).strip()


def guard():
    if read(STATE).get("phase") in ACTIVE:
        raise ValueError("OS更新処理中です。完了してから操作してください")


def idle():
    if run("ss", "-Hnt", "state", "established", "( sport = :3240 )"):
        raise ValueError("USB/IPが使用中です。PC側で切断してから更新してください")
    checkpoints = run("busctl", "get-property", "org.freedesktop.NetworkManager",
                      "/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager", "Checkpoints")
    if checkpoints != "ao 0":
        raise ValueError("ネットワーク設定を試用中です。確定または復旧後に更新してください")


def root_fs():
    return run("findmnt", "-n", "-o", "FSTYPE", "--target", "/")


def result_status():
    check, update = read(CHECK), read(STATE)
    if check.get("phase") == "checking":
        if run("systemctl", "show", "--property=ActiveState", "--value", "wyse-apt-check.service") not in ("active", "activating"):
            check.update(phase="failed", message="更新確認が中断されました。もう一度確認してください")
    return {"check": check, "update": update}


def command(args, tail):
    # Keep bounded output in memory; never keep appending an unbounded disk log.
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          stdin=subprocess.DEVNULL, text=True, errors="replace", env=ENV) as process:
        for line in process.stdout:
            tail.append(line.rstrip()[:500])
        if process.wait():
            raise RuntimeError("APT処理に失敗しました。結果ログを確認してください")


def check_worker():
    save(CHECK, {"phase": "checking", "time": stamp(), "message": "更新一覧を取得しています"})
    tail = deque(maxlen=100)
    try:
        command(APT + ["update", "--error-on=any"], tail)
        plan = subprocess.check_output(APT + ["--simulate", "--with-new-pkgs", "--no-remove", "upgrade"],
                                       env=ENV, text=True, stderr=subprocess.STDOUT, timeout=120)
        packages = [line.split()[1] for line in plan.splitlines() if line.startswith("Inst ")]
        held = next((line for line in plan.splitlines() if "upgraded," in line and "not upgraded" in line), "")
        save(CHECK, {"phase": "ready", "time": stamp(), "count": len(packages),
                     "message": f"更新候補 {len(packages)}件", "packages": packages[:15], "summary": held})
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        save(CHECK, {"phase": "failed", "time": stamp(), "message": str(error)[:250],
                     "log": "\n".join(tail)[-2200:]})


def request(action):
    with LOCK.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        guard()
        if run("systemctl", "show", "--property=ActiveState", "--value", "wyse-apt-check.service") in ("active", "activating"):
            raise ValueError("更新確認中です。完了するまで待ってください")
        if action == "check":
            if result_status()["check"].get("phase") == "checking":
                raise ValueError("更新確認中です")
            run("systemctl", "start", "--no-block", "wyse-apt-check.service")
            return
        if read(CHECK).get("phase") != "ready":
            raise ValueError("先に「更新を確認」を実行してください")
        idle()
        run("/usr/local/sbin/wyse-network-trial", "check-settings")
        protection = PROTECTION.read_text()
        if protection not in (ON, OFF):
            raise ValueError("OS保護設定を判別できません")
        root = root_fs()
        if root not in ("overlay", "ext4"):
            raise ValueError("このルートファイルシステムには対応していません")
        if root == "overlay" and protection != ON:
            raise ValueError("OS保護の次回起動設定が変更済みです。先に再起動してください")
        target = "/media/root-ro" if root == "overlay" else "/"
        if shutil.disk_usage(target).free < 512 * 1024 * 1024:
            raise ValueError("OS領域の空き容量が512 MiB未満です")
        state = {"phase": "queued", "time": stamp(), "boot": boot_id(),
                 "protection": protection, "message": "更新を予約しました。まもなく開始します"}
        save(STATE, state)
        try:
            run("systemctl", "start", "--no-block", "wyse-os-update-prepare.service")
        except (OSError, subprocess.SubprocessError):
            state.update(phase="failed", message="更新処理を開始できませんでした")
            save(STATE, state)
            raise


def reboot():
    run("systemctl", "reboot", "--no-block")


def prepare():
    import time
    time.sleep(5)  # Let the Web response finish before a reboot.
    with LOCK.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read(STATE)
        if state.get("phase") != "queued":
            return
        frozen = False
        try:
            if run("systemctl", "show", "--property=ActiveState", "--value", "usbipd.service") == "active":
                run("systemctl", "freeze", "usbipd.service")
                frozen = True
                for _ in range(20):
                    if run("systemctl", "show", "--property=FreezerState", "--value", "usbipd.service") == "frozen":
                        break
                    time.sleep(0.05)
                else:
                    raise ValueError("USB/IPの新規接続を一時停止できませんでした")
            idle()
            state.update(phase="maintenance", message="更新用に再起動しています")
            save(STATE, state)
            if root_fs() == "overlay":
                atomic(PROTECTION, OFF)
                reboot()
            else:
                run("systemctl", "start", "--no-block", "wyse-os-update.service")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            atomic(PROTECTION, state["protection"])
            state.update(phase="failed", message=str(error)[:250])
            save(STATE, state)
            if frozen:
                run("systemctl", "thaw", "usbipd.service")


def worker():
    state = read(STATE)
    phase = state.get("phase")
    if phase == "rebooting":
        if state["protection"] == ON and root_fs() != "overlay":
            state.update(phase="failed", message="更新後のOS保護が有効になっていません。本体設定を確認してください")
        else:
            state.update(phase=state["result"], message=state["result_message"])
        save(STATE, state)
        return
    if phase not in ("maintenance", "running", "queued"):
        return
    if phase in ("running", "queued"):
        # A power loss is not authorization to repeat an interrupted package transaction.
        atomic(PROTECTION, state["protection"])
        state.update(phase="failed", message="更新が中断されました。パッケージ状態を確認してから再試行してください")
        save(STATE, state)
        if root_fs() == "ext4" and state["protection"] == ON:
            reboot()
        return
    if root_fs() != "ext4":
        atomic(PROTECTION, state["protection"])
        state.update(phase="failed", message="書き込み可能なOSで起動できなかったため、更新を中止しました")
        save(STATE, state)
        return
    # Restore next-boot protection before APT starts, including if power is lost.
    atomic(PROTECTION, state["protection"])
    state.update(phase="running", message="APTでOS・カーネルを更新しています", time=stamp())
    save(STATE, state)
    tail = deque(maxlen=100)
    result, message = "success", "APT更新が完了しました。OS保護設定を元に戻しました"
    try:
        run("systemctl", "stop", "apt-daily.timer", "apt-daily-upgrade.timer")
        audit = run("dpkg", "--audit")
        if audit:
            raise RuntimeError("未完了のパッケージ処理があります。SSHでdpkgの状態を確認してください")
        command(APT + ["update", "--error-on=any"], tail)
        command(APT + ["-y", "--with-new-pkgs", "--no-remove",
                       "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold", "upgrade"], tail)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        result, message = "failed", str(error)[:250]
    state.update(phase="rebooting", result=result, result_message=message,
                 message="処理を終了し、通常起動へ戻しています", time=stamp(), log="\n".join(tail)[-2200:])
    save(STATE, state)
    os.sync()
    try:
        reboot()
    except (OSError, subprocess.SubprocessError):
        state.update(phase="failed", message="再起動できませんでした。本体を再起動してください")
        save(STATE, state)


def main():
    action, = sys.argv[1:]
    if action == "status":
        print(json.dumps(result_status(), ensure_ascii=False))
    elif action == "guard":
        guard()
    elif action in ("check", "apply"):
        request(action)
    elif action == "check-worker":
        check_worker()
    elif action == "prepare":
        prepare()
    elif action == "worker":
        worker()
    else:
        raise ValueError("Unknown action")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
