#!/usr/bin/python3
import os
import platform
from pathlib import Path
import subprocess
from html import escape

VERSION = Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip()
SERVICES = {"usbipd.service": "USB/IP", "lighttpd.service": "Web管理",
            "NetworkManager.service": "ネットワーク", "avahi-daemon.service": "機器名の公開",
            "wyse-usb-history.service": "接続履歴"}


# USB共有一覧・ネットワーク設定と同じ内容に保つ。
STYLE = """
:root { --accent: #0017c1; --accent-hover: #00118f; --accent-active: #000060; --accent-text: #fff;
 --info-bg: #e8f1fe; --accent-bg-hover: #d9e6ff; --text: #1a1a1a; --sub: #333; --muted: #666; --line: #ccc;
 --field: #666; --bg: #f2f2f2; --card: #fff; --visited: #5109ad; --link-active: #c74700; --focus: #ffd43d;
 --ok: #197a4b; --ok-bg: #e6f5ec; --busy: #c74700; --busy-bg: #ffeee2; --warn: #b78f00; --warn-bg: #fbf5e0;
 --error: #ce0000; --error-bg: #fdeeee; --unknown: #767676 }
* { box-sizing: border-box }
body { margin: 0; background: var(--bg); color: var(--sub); letter-spacing: .02em;
 font: 16px/1.7 system-ui, -apple-system, "Hiragino Sans", "Noto Sans JP", "Yu Gothic UI", Meiryo, sans-serif }
main { max-width: 48rem; margin: 0 auto; padding: 16px 16px 64px }
header { display: grid; gap: 8px; margin-bottom: 24px }
h1, h2 { color: var(--text); font-weight: 700; line-height: 1.5; letter-spacing: .01em }
h1 { font-size: 1.5rem; margin: 0 }
h2 { font-size: 1.25rem; margin: 0 0 8px }
p { margin: 8px 0 }
ul, ol { margin: 8px 0; padding-left: 1.5em }
li + li { margin-top: 4px }
a { color: var(--accent); text-decoration: underline; text-underline-offset: .2em }
a:visited { color: var(--visited) }
a:hover { color: var(--accent-hover); text-decoration-thickness: 3px }
a:active { color: var(--link-active) }
:focus-visible { outline: 4px solid #000; outline-offset: 2px; box-shadow: 0 0 0 2px var(--focus) }
a:focus-visible { background: var(--focus); color: #000 }
nav { display: flex; flex-wrap: wrap; border-bottom: 1px solid var(--line) }
nav a, nav a:visited { display: inline-flex; align-items: center; min-height: 44px; padding: 0 12px;
 color: var(--accent); border-bottom: 4px solid transparent; margin-bottom: -1px }
nav a[aria-current] { color: var(--text); font-weight: 700; text-decoration: none; border-bottom-color: var(--accent) }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px; margin-bottom: 24px }
.card > :first-child { margin-top: 0 }
.card > :last-child { margin-bottom: 0 }
.hint { color: var(--muted); font-size: .875rem }
.mono { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; letter-spacing: 0 }
.button, a.button:visited { display: inline-flex; align-items: center; justify-content: center; gap: 8px;
 min-height: 48px; padding: 8px 24px; border: 1px solid var(--accent); border-radius: 8px; background: var(--card);
 color: var(--accent); font: inherit; font-weight: 700; line-height: 1.3; text-decoration: none; cursor: pointer }
.button:hover { background: var(--accent-bg-hover); border-color: var(--accent-hover); color: var(--accent-hover);
 text-decoration: underline }
.button:active { background: var(--accent-bg-hover); border-color: var(--accent-active); color: var(--accent-active) }
.button.primary { background: var(--accent); color: var(--accent-text) }
.button.primary:hover { background: var(--accent-hover); color: var(--accent-text) }
.button.primary:active { background: var(--accent-active); color: var(--accent-text) }
.button:disabled, .button:disabled:hover { background: #e6e6e6; border-color: #b3b3b3; color: #767676;
 text-decoration: none; cursor: not-allowed }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 2px 12px; border: 2px solid var(--unknown);
 border-radius: 999px; background: var(--card); color: var(--text); font-size: .875rem; font-weight: 700;
 line-height: 1.5; white-space: nowrap }
.badge::before { content: ""; width: 10px; height: 10px; border-radius: 50%; background: var(--unknown) }
.badge.ok { border-color: var(--ok); background: var(--ok-bg) }
.badge.ok::before { background: var(--ok) }
.badge.busy { border-color: var(--busy); background: var(--busy-bg) }
.badge.busy::before { background: var(--busy) }
.badge.error { border-color: var(--error); background: var(--error-bg) }
.badge.error::before { background: var(--error) }
.notice { margin: 0 0 24px; padding: 16px; border: 2px solid var(--accent); border-left-width: 8px;
 border-radius: 12px; background: var(--info-bg); color: var(--text) }
.notice.ok { border-color: var(--ok); background: var(--ok-bg) }
.notice.busy { border-color: var(--warn); background: var(--warn-bg) }
.notice.error { border-color: var(--error); background: var(--error-bg) }
.card .notice { margin: 16px 0 }
.facts { display: grid; grid-template-columns: fit-content(12em) minmax(0, 1fr); gap: 8px 24px; margin: 16px 0 }
.facts dt { color: var(--muted) }
.facts dd { margin: 0; color: var(--text); overflow-wrap: anywhere }
.req { color: var(--error); font-size: .875rem; font-weight: 700; margin-left: 8px }
@media (min-width: 40rem) { main { padding-top: 24px } h1 { font-size: 1.75rem } .card { padding: 24px } }
"""

PAGE_STYLE = """
@media (max-width: 26rem) { .facts { grid-template-columns: 1fr; gap: 0 } .facts dd { margin-bottom: 12px } }
"""


def read(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def status():
    rows = [("機器名", platform.node()), ("管理ソフト", "v" + VERSION),
            ("OS", "Debian " + (read("/etc/debian_version") or "不明")),
            ("カーネル", "Linux " + platform.release())]
    for label, interface in (("有線LAN IPv4", "enp1s0"), ("Wi-Fi IPv4", "mlan0")):
        try:
            ips = subprocess.check_output(["nmcli", "--escape", "no", "-g", "IP4.ADDRESS", "device", "show", interface], text=True, timeout=5).strip()
            rows.append((label, ", ".join(ips.splitlines()) or "未接続／IP未取得"))
        except (OSError, subprocess.SubprocessError):
            rows.append((label, "取得できません"))
    try:
        ssid = subprocess.check_output(["nmcli", "--escape", "no", "-g", "802-11-wireless.ssid", "connection", "show",
                                        "uuid", "12130d96-e908-42ce-9561-1ae5bd132282"], text=True, timeout=5).strip()
        rows.append(("Wi-Fi SSID（設定）", ssid or "未設定"))
    except (OSError, subprocess.SubprocessError):
        rows.append(("Wi-Fi SSID（設定）", "取得できません"))
    try:
        seconds = int(float(read("/proc/uptime").split()[0]))
        rows.append(("稼働時間", f"{seconds // 86400}日 {seconds // 3600 % 24}時間 {seconds // 60 % 60}分"))
    except (ValueError, IndexError):
        rows.append(("稼働時間", "取得できません"))
    try:
        memory = {line.split(":", 1)[0]: int(line.split()[1]) for line in read("/proc/meminfo").splitlines()}
        total, available = memory["MemTotal"], memory["MemAvailable"]
        rows.append(("RAM使用量", f"{(total - available) / 1024:.0f} / {total / 1024:.0f} MiB（{(total - available) / total:.0%}）"))
    except (ValueError, KeyError, IndexError, ZeroDivisionError):
        rows.append(("RAM使用量", "取得できません"))
    mounts = {parts[1]: parts for line in read("/proc/mounts").splitlines() if len(parts := line.split()) >= 4}
    root, lower = mounts.get("/"), mounts.get("/media/root-ro")
    if root and root[2] == "overlay":
        protection = "有効（OS領域は読み取り専用）" if lower and "ro" in lower[3].split(",") else "要確認（OS領域が読み取り専用ではありません）"
    else:
        protection = "無効" if root else "取得できません"
    rows.append(("OS書き込み保護", protection))
    try:
        result = subprocess.check_output(["systemctl", "show", "--property=Id,ActiveState", *SERVICES], text=True, timeout=5)
        states = {}
        for block in result.strip().split("\n\n"):
            fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            states[fields.get("Id")] = fields.get("ActiveState", "不明")
        rows.extend((label, "動作中" if states.get(unit) == "active" else states.get(unit, "取得できません"))
                    for unit, label in SERVICES.items())
    except (OSError, subprocess.SubprocessError):
        rows.append(("サービス状態", "取得できません"))
    return rows


def render(rows):
    host = os.environ.get("HTTP_HOST", "")
    host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    settings = "network.py" if os.environ.get("HTTPS") == "on" else f"https://{host}/network.py"
    facts = "".join(f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>" for label, value in rows)
    return f"""<!doctype html>
<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>システム状態 - Wyse USB/IP</title>
<style>{STYLE}{PAGE_STYLE}</style><main><header><div><h1>Wyse USB/IP</h1><p class="hint">管理ソフト v{escape(VERSION)}</p></div><nav><a href="usbip.py">USB共有</a>
<a href="{escape(settings)}">ネットワーク設定</a><a href="system.py" aria-current="page">システム状態</a></nav></header>
<section class="card"><h2>システム状態</h2><dl class="facts">{facts}</dl><a class="button" href="system.py">最新の状態に更新</a></section>
</main></html>"""


if __name__ == "__main__":
    print("Content-Type: text/html; charset=utf-8")
    print("Cache-Control: no-store")
    print()
    print(render(status()))
