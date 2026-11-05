#!/usr/bin/python3
import os
import json
from html import escape
from pathlib import Path

VERSION = Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip()

DRIVER = Path("/sys/bus/usb/drivers/usbip-host")
# usbip_status: 1 = 共有中で未接続, 2 = クライアントが使用中, 3 = エラー
STATES = {"1": ("ok", "接続可能"), "2": ("busy", "使用中"), "3": ("error", "エラー")}
UNKNOWN = ("unknown", "不明")

# ネットワーク設定画面 (network-settings.py) と同じ内容に保つ。
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
.toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px;
 margin-bottom: 16px }
.toolbar p { margin: 0; color: var(--text); font-weight: 700 }
.toolbar .hint { font-weight: 400 }
.devices { list-style: none; margin: 0; padding: 0 }
.device { display: grid; grid-template-columns: 1fr auto; gap: 8px 16px; align-items: center; padding: 16px 0;
 border-top: 1px solid var(--line); margin: 0 }
.device:first-child { border-top: 0; padding-top: 0 }
.device:last-child { padding-bottom: 0 }
.device h2 { font-size: 1.125rem; margin: 0; overflow-wrap: anywhere }
.device dl { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 4px 24px; margin: 0 }
.device dt { display: inline; color: var(--muted); font-size: .875rem; margin-right: 8px }
.device dd { display: inline; margin: 0; color: var(--text) }
.empty { text-align: center; color: var(--muted); padding: 24px 0 }
"""


def read(device, name):
    try:
        return (device / name).read_text(errors="replace").strip()
    except OSError:
        return ""


def devices(driver):
    """Return (name, bus ID, USB ID, usbip_status) for each device bound to usbip-host."""
    found = []
    if driver.is_dir():
        for device in sorted(driver.iterdir()):
            if not device.is_symlink() or not (device / "idVendor").is_file():
                continue
            status = read(device, "usbip_status")
            if not status and not device.exists():
                continue
            name = " ".join(filter(None, (read(device, "manufacturer"), read(device, "product"))))
            ids = f"{read(device, 'idVendor')}:{read(device, 'idProduct')}"
            found.append((name or ids, device.name, ids, status))
    return found


def network_link():
    # 設定画面は 443 番の HTTPS だけで公開している。
    if os.environ.get("HTTPS") == "on":
        return "network.py"
    host = os.environ.get("HTTP_HOST", "")
    host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return f"https://{host}/network.py" if host else ""


def history_card(path=Path("/run/wyse-usb-history/history.json")):
    try:
        events = json.loads(path.read_text(encoding="utf-8"))["events"]
        rows = []
        for event in reversed(events[-200:]):
            rows.append('<li><strong>' + escape(event["event"]) + '</strong> '
                        + escape(event["name"]) + '<br><span class="hint">'
                        + escape(event["time"]) + ' · バスID ' + escape(event["bus"])
                        + ' · USB ID ' + escape(event["ids"]) + '</span></li>')
        content = '<ol>' + ''.join(rows) + '</ol>' if rows else '<p>まだ接続履歴はありません。</p>'
    except (OSError, ValueError, KeyError, TypeError):
        content = '<p>接続履歴を取得できません。記録サービスの状態を確認してください。</p>'
    return ('<section class="card"><h2>USB/IP接続履歴</h2>'
            '<p class="hint">新しい順に最大200件。RAM上に保存し、本体の再起動で消えます。'
            '0.5秒間隔の状態確認のため、ごく短い接続・切断は記録できない場合があります。'
            '「使用中を検出」は記録開始時点で接続済みの機器です。</p>' + content + '</section>')


def render(items, available=True, settings="", server=""):
    rows = []
    for name, bus_id, ids, status in items:
        kind, label = STATES.get(status, UNKNOWN)
        rows.append(f"""<li class="device"><h2>{escape(name)}</h2>
<span class="badge {kind}">{label}</span>
<dl><div><dt>バスID</dt><dd class="mono">{escape(bus_id)}</dd></div>
<div><dt>USB ID</dt><dd class="mono">{escape(ids)}</dd></div></dl></li>""")
    if not rows:
        message = ("共有中のUSB機器はありません。" if available
                   else "USB/IPドライバー (usbip-host) を利用できません。")
        rows.append(f'<li class="empty">{message}</li>')
    counts = {kind: sum(STATES.get(item[3], UNKNOWN)[0] == kind for item in items) for kind in ("ok", "busy")}
    wyse = f'<span class="mono">{escape(server)}</span>' if server else "この画面を開いているアドレス"
    nav_settings = f'<a href="{escape(settings)}">ネットワーク設定</a>' if settings else ""
    return f"""<!doctype html>
<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>USB共有一覧 - Wyse USB/IP</title>
<style>{STYLE}{PAGE_STYLE}</style>
<main>
<header><div><h1>Wyse USB/IP</h1><p class="hint">管理ソフト v{escape(VERSION)}</p></div>
<nav><a href="usbip.py" aria-current="page">USB共有</a>{nav_settings}<a href="system.py">システム状態</a></nav></header>
<section class="card">
<div class="toolbar"><p>共有中 {len(items)}台<span class="hint">（接続可能 {counts["ok"]}・使用中 {counts["busy"]}）</span></p>
<a class="button" href="usbip.py">最新の状態に更新</a></div>
<ul class="devices">{"".join(rows)}</ul>
</section>
{history_card()}
<section class="card">
<h2>Windowsから使う</h2>
<ol><li>PCに <strong>usbip-win2</strong> をインストールします。</li>
<li>usbip-win2 で、接続先にWyseのIP（{wyse}）を指定します。</li>
<li>表示された一覧から「接続可能」の機器を選んで接続します。</li></ol>
<p class="hint">「使用中」の機器は、使っているPCで切断するまで接続できません。</p>
</section>
<section class="card">
<h2>注意</h2>
<ul><li>キーボードやマウスなどのHID機器は、自動共有の対象外です。</li>
<li>バスIDは、機器の抜き差しやWyseの再起動で変わる場合があります。接続できないときは、この画面を更新して最新のバスIDを確認してください。</li></ul>
</section>
</main></html>"""


if __name__ == "__main__":
    print("Content-Type: text/html; charset=utf-8")
    print("Cache-Control: no-store")
    print()
    print(render(devices(DRIVER), DRIVER.is_dir(), network_link(), os.environ.get("SERVER_ADDR", "")))
