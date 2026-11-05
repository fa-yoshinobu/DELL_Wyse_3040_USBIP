#!/usr/bin/python3
import base64
import hashlib
import ipaddress
import json
import os
import socket
import sys
from html import escape
from pathlib import Path

VERSION = Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip()
from urllib.parse import parse_qs

# USB共有一覧 (usbip-status.py) と同じ内容に保つ。
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
.update-log { white-space: pre-wrap; overflow-wrap: anywhere; font-size: .875rem }
.title { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px;
 margin-bottom: 8px }
.title h2 { margin: 0 }
form { display: grid; gap: 24px; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--line) }
label, fieldset { display: grid; gap: 8px; color: var(--text); font-weight: 700 }
label .hint { font-weight: 400 }
fieldset { border: 0; margin: 0; padding: 0; min-width: 0 }
legend { padding: 0; margin-bottom: 8px }
.choices { display: flex; flex-wrap: wrap; gap: 8px 16px }
.choice { display: flex; align-items: center; gap: 8px; min-height: 48px; padding: 8px 16px; font-weight: 400;
 border: 1px solid var(--field); border-radius: 8px; background: var(--card); cursor: pointer }
.choice:has(input:checked) { border: 2px solid var(--accent); padding: 7px 15px; background: var(--info-bg);
 font-weight: 700 }
input[type=radio], input[type=checkbox] { width: 24px; height: 24px; margin: 0; flex: none; accent-color: var(--accent) }
input:not([type=radio]):not([type=checkbox]) { width: 100%; min-height: 48px; padding: 8px 16px; font: inherit;
 letter-spacing: 0; color: var(--text); background: var(--card); border: 1px solid var(--field); border-radius: 8px }
input:not([type=radio]):not([type=checkbox]):hover { border-color: var(--text) }
form:has(#lan-dhcp:checked) .static-only { display: none }
form .button { justify-self: start }
.trial { border: 3px solid var(--accent); background: var(--info-bg) }
.target, .target:visited { display: block; margin: 8px 0; padding: 12px 16px; background: var(--card);
 border: 1px solid var(--line); border-radius: 8px; font-size: 1.125rem; font-weight: 700; overflow-wrap: anywhere }
.target small { display: block; font: 400 .875rem system-ui, sans-serif; color: var(--muted) }
.trial form { border-top: 0; padding-top: 0 }
.trial form .button { justify-self: stretch; min-height: 56px; font-size: 1.125rem }
.danger { border: 2px solid var(--error) }
.danger h2 { color: var(--error) }
.danger .button { border-color: var(--error); color: var(--error) }
.danger .button:hover { background: var(--error-bg); color: var(--error) }
.danger input[type=checkbox] { accent-color: var(--error) }
.agree { display: flex; align-items: flex-start; gap: 12px }
.agree input { margin-top: 2px }
details { margin: 8px 0 }
summary { cursor: pointer; color: var(--accent); min-height: 44px; display: flex; align-items: center }
@media (min-width: 40rem) { .trial form .button { justify-self: start; min-width: 16rem } }
"""

CSP_STYLE = "'sha256-" + base64.b64encode(
    hashlib.sha256((STYLE + PAGE_STYLE).encode()).digest()).decode() + "'"

NAMES = {"wifi": "Wi-Fi親機", "lan": "有線LAN"}
RESET_SSID = "wyse"
RESET_WIFI = "10.42.0.1/24"


def request(args):
    """Send one request to wyse-network-request (runs as root) and return its JSON reply."""
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(60)
        connection.connect("/run/wyse-network.sock")
        connection.sendall(json.dumps(args).encode() + b"\n")
        with connection.makefile() as response:
            return json.loads(response.readline(16384))


def current_status():
    try:
        result = request(("status",))
        return None if result["error"] else json.loads(result["output"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def url(address):
    return f"https://{address}/network.py"


def trial_card(trial, server):
    targets = trial["addresses"]
    reset = trial.get("reset")
    title = "ネットワーク設定の初期化を試用中です" if reset else (
        "、".join(NAMES.get(target, target) for target in targets) + "の新しい設定を試用中です")
    links = "".join(
        f'<a class="target mono" href="{escape(url(address))}"><small>{NAMES.get(target, "新しい接続先")}</small>'
        f"{escape(url(address))}</a>" for target, address in targets.items())
    if server in targets.values():
        return f"""<section class="card trial" id="confirm">
<h2>{title}</h2>
<p>新しい接続先で開けています。問題なければ<strong>「設定を確定」</strong>を押してください。</p>
{links}
<form method="post"><button class="button primary" name="action" value="confirm">設定を確定</button></form>
<p class="hint">確定するまでは保存されません。開始から120秒以内に確定しないと、自動で元の設定に戻ります。</p>
</section>"""
    steps = []
    if "wifi" in targets:
        ssid = f"「{RESET_SSID}」" if reset else "新しいSSID"
        steps.append(f"Wi-Fiで使う場合は、PC・スマホを{ssid}につなぎ直します。")
    if "lan" in targets:
        steps.append("有線LANで使う場合は、PCを同じLANにつないだままにします。")
    steps.append("上の新しい接続先を開きます（証明書の警告が出たら、これまでと同じ手順で進みます）。")
    steps.append("表示された画面で<strong>「設定を確定」</strong>を押します。")
    dhcp = ('<p class="hint">有線LANのIPはDHCPで決まります。開けない場合は、ルーターのDHCP割り当て一覧か、'
            'Wyse本体の画面に表示されるIPv4アドレスで新しいIPを確認し、'
            '<span class="mono">https://新しいIP/network.py</span> を開いてください。</p>'
            if "lan" in targets else "")
    return f"""<section class="card trial" id="confirm">
<h2>{title}</h2>
<p>新しい接続先</p>
{links}
<ol>{"".join(f"<li>{step}</li>" for step in steps)}</ol>
{dhcp}
<p><strong>開始から120秒以内に確定してください。</strong>確定しないと自動で元の設定に戻ります。
この画面（変更前の接続先）からは確定できません。</p>
</section>"""


def ips(values):
    return "、".join(escape(value) for value in values) if values else "なし"


def lan_card(state):
    lan = state and state["lan"]
    facts = ""
    if lan:
        setting = "DHCP（自動取得）" if lan["method"] == "auto" else f"固定 {escape(lan['configured'] or '未設定')}"
        badge = '<span class="badge ok">接続中</span>' if lan["active"] else '<span class="badge unknown">未接続</span>'
        facts = f"""<dl class="facts"><dt>現在のIP</dt><dd class="mono">{ips(lan["current"])}</dd>
<dt>設定</dt><dd>{setting}</dd>
<dt>固定IP用ゲートウェイ</dt><dd>{escape(lan.get("gateway", "") or "未設定")}</dd>
<dt>固定IP用DNS</dt><dd>{escape(lan.get("dns", "") or "未設定")}</dd></dl>"""
    else:
        badge = ""
    return f"""<section class="card">
<div class="title"><h2>有線LAN</h2>{badge}</div>
{facts}
<form method="post">
<fieldset><legend>IPアドレスの決め方</legend>
<div class="choices"><label class="choice"><input type="radio" id="lan-dhcp" name="method" value="dhcp" checked>
DHCP（自動取得）</label>
<label class="choice"><input type="radio" name="method" value="static">固定IPv4</label></div></fieldset>
<label class="static-only">固定IPv4アドレス <span class="hint">固定IPv4を選んだときだけ入力。例: 192.168.0.80/24</span>
<input name="address" placeholder="192.168.0.80/24" inputmode="decimal" autocapitalize="off" autocorrect="off"
 spellcheck="false"></label>
<label class="static-only">ゲートウェイ <span class="hint">例: 192.168.0.1。LAN内だけで使う場合は空欄にできます。</span>
<input name="gateway" placeholder="192.168.0.1" value="{escape(lan.get('gateway', '')) if lan else ''}"></label>
<label class="static-only">DNSサーバー <span class="hint">例: 192.168.0.1。複数は空白で区切ります。名前解決が不要なら空欄にできます。</span>
<input name="dns" placeholder="192.168.0.1" value="{escape(lan.get('dns', '')) if lan else ''}"></label>
<button class="button" name="action" value="begin-lan">有線LANの設定を試す</button>
</form>
</section>"""


def wifi_card(state):
    wifi = state and state["wifi"]
    facts = ""
    badge = ""
    if wifi:
        badge = ('<span class="badge ok">動作中</span>' if wifi["active"]
                 else '<span class="badge unknown">停止中</span>')
        facts = f"""<dl class="facts"><dt>SSID</dt><dd>{escape(wifi["ssid"] or "未設定")}</dd>
<dt>管理IP</dt><dd class="mono">{ips(wifi["current"]) if wifi["active"] else escape(wifi["configured"] or "未設定")}</dd></dl>"""
    stopped = ('<p class="notice info">既存LANモードのためWi-Fi親機は停止しています。設定を試すには、'
               '本体メニューで単独モードに切り替えてください。</p>' if wifi and not wifi["active"] else "")
    return f"""<section class="card">
<div class="title"><h2>Wi-Fi親機</h2>{badge}</div>
<p class="hint">単独モードで、このWyseが作るWi-FiのSSID・管理IP・WPA2パスワードを設定します。</p>
{facts}{stopped}
<form method="post">
<label><span>SSID（Wi-Fi名）<span class="req">※必須</span></span><input name="ssid" maxlength="32" autocapitalize="off" autocorrect="off" spellcheck="false"
 value="{escape(wifi["ssid"]) if wifi else ""}" required></label>
<label><span>管理IP<span class="req">※必須</span></span><span class="hint">Wi-Fi側でのWyseのIP。例: 10.42.0.1/24</span>
<input name="address" placeholder="10.42.0.1/24" inputmode="decimal" autocapitalize="off" autocorrect="off"
 spellcheck="false" value="{escape(wifi["configured"]) if wifi else ""}" required></label>
<label>新しいWPA2パスワード <span class="hint">8〜63文字。空欄なら現在のセキュリティ設定を維持します</span>
<input name="password" type="password" minlength="8" maxlength="63" autocomplete="new-password"></label>
<button class="button" name="action" value="begin">Wi-Fi親機の設定を試す</button>
</form>
</section>"""


def mode_card(state):
    mode = state and state["mode"]
    current = {"standalone": "単独モード", "lan": "既存LANモード"}.get(mode, "取得できません")
    return f"""<section class="card">
<div class="title"><h2>動作モード</h2><span class="badge {'ok' if mode else 'unknown'}">{current}</span></div>
<dl class="facts"><dt>単独モード</dt><dd>WyseがWi-Fi親機になり、つないだ機器にIPを配布します。</dd>
<dt>既存LANモード</dt><dd>既存のLANにつなぎ、Wyse側のIP配布を停止します。IPはLANのDHCPなどから受け取ります。</dd></dl>
<p class="hint">モードの切り替えは、Wyse本体につないだキーボードの矢印キーメニューで行います（この画面からは切り替えません）。</p>
</section>"""


def usb_sharing_card():
    driver = Path("/sys/bus/usb/drivers/usbip-host")
    paused = Path("/run/wyse-usb-paused")
    rows = []
    entries = set(driver.glob("*-*")) | set(paused.glob("*-*"))
    for bus in sorted({entry.name for entry in entries}):
        device = Path("/sys/bus/usb/devices") / bus
        try:
            number = (device / "devnum").read_text().strip()
            if (driver / bus).is_symlink():
                status = (device / "usbip_status").read_text().strip()
            elif (paused / bus).read_text().strip() == number:
                status = "paused"
            else:
                continue
            product = device / "product"
            name = product.read_text(errors="replace").strip() if product.exists() else bus
        except OSError:
            continue
        control = "クライアントから切断してください"
        if status in ("1", "paused", "3"):
            action, label = {"1": ("usb-pause", "共有を停止"), "paused": ("usb-resume", "共有を再開"),
                             "3": ("usb-recover", "共有を復旧")}[status]
            control = (f'<form method="post"><input type="hidden" name="bus" value="{escape(bus)}">'
                       f'<input type="hidden" name="number" value="{escape(number)}">'
                       f'<button class="button" name="action" value="{action}">{label}</button></form>')
        rows.append(f"<li>{escape(name)}（{escape(bus)}） {control}</li>")
    content = "<ul>" + "".join(rows) + "</ul>" if rows else "<p>対象の機器がありません。</p>"
    return ('<section class="card"><h2>USB共有の停止・再開</h2>'
            '<p class="hint">停止は抜き差しまたは再起動まで有効です。エラー状態の機器は「共有を復旧」で共有し直せます。</p>' + content + "</section>")


def hostname_card(state):
    name = escape((state or {}).get("hostname", ""), quote=True)
    return f"""<section class="card">
<h2>ネットワーク上の機器名</h2>
<form method="post">
<label><span>ホスト名<span class="req">※必須</span></span><input name="hostname" value="{name}" required maxlength="63"
 pattern="[a-z0-9](?:[a-z0-9\u005c-]{{0,61}}[a-z0-9])?"></label>
<p class="hint">例 wyse-usb。SSIDはWi-Fi親機の設定で変更できます。名前での接続可否はLANの名前解決設定によります。</p>
<button class="button" name="action" value="hostname">機器名を保存</button>
</form></section>"""


def reset_card(state):
    busy = ('<p class="notice busy">設定を試用中のため、今は初期化できません。確定するか、元に戻るまで待ってください。</p>'
            if state and state.get("trial") else "")
    return f"""<section class="card danger">
<h2>ネットワーク設定を初期化</h2>
<p>次の初期値に戻します。有線とWi-Fiは一つの変更として試用し、新しい接続先で120秒以内に確定したときだけ保存します。</p>
<dl class="facts"><dt>有線LAN</dt><dd>DHCP（自動取得）</dd>
<dt>Wi-Fi SSID</dt><dd class="mono">{RESET_SSID}</dd>
<dt>Wi-Fi管理IP</dt><dd class="mono">{RESET_WIFI}</dd></dl>
<p class="hint">そのまま保持するもの: Wi-Fiのパスワード（セキュリティ設定）、単独／既存LANモードの選択、
Web管理者パスワード、OS保護設定</p>
<ul class="hint"><li>実行するとネットワークが一時的に切れることがあります。</li>
<li>有線LANのIPがDHCPで変わった場合は、ルーターのDHCP割り当て一覧か、Wyse本体の画面に表示されるIPv4アドレスで新しいIPを確認し、
<span class="mono">https://新しいIP/network.py</span> を開いて確定してください。</li>
<li>確定しなかった場合や反映に失敗した場合は、有線・Wi-Fiとも操作前の設定に戻ります。</li>
<li>USB/IPクライアントの接続中や、別の設定の試用中は実行できません。</li></ul>
{busy}
<form method="post">
<label class="agree"><input type="checkbox" name="agree" value="yes" required>
初期値と、接続が一時的に切れる可能性を確認しました</label>
<button class="button" name="action" value="reset">ネットワーク設定を初期化</button>
</form>
</section>"""


def update_card():
    try:
        reply = request(("os-status",))
        if reply["error"]:
            raise ValueError(reply["error"])
        state = json.loads(reply["output"])
    except (OSError, ValueError, KeyError):
        return '<section class="card"><h2>OS・カーネル更新</h2><p>更新サービスを利用できません。</p></section>'
    labels = {"checking": "確認中", "ready": "確認済み", "queued": "更新予約済み", "maintenance": "保守起動へ移行中",
              "running": "更新中", "rebooting": "通常起動へ復帰中", "success": "更新完了", "failed": "処理失敗"}
    details = []
    busy = False
    for key, title in (("check", "更新確認"), ("update", "前回／現在の更新")):
        item = state.get(key, {})
        if not item:
            continue
        phase = item.get("phase", "")
        busy |= phase in ("checking", "queued", "maintenance", "running", "rebooting")
        details.append(f'<p><strong>{title}: {escape(labels.get(phase, phase))}</strong><br>'
                       f'{escape(item.get("time", ""))}<br>{escape(item.get("message", ""))}</p>')
        if item.get("packages"):
            details.append('<p class="hint">更新候補（先頭15件）: ' + escape("、".join(item["packages"])) + '</p>')
        if item.get("summary"):
            details.append('<p class="hint">' + escape(item["summary"]) + '</p>')
        if item.get("log"):
            details.append('<details><summary>処理結果ログ</summary><pre class="update-log">'
                           + escape(item["log"]) + '</pre></details>')
    disabled = " disabled" if busy else ""
    apply_disabled = " disabled" if busy or state.get("check", {}).get("phase") != "ready" else ""
    return f"""<section class="card"><h2>OS・カーネル更新</h2>
<p>Debian標準のAPTで、OS・カーネルとインストール済みパッケージを更新します。</p>
<p class="hint">管理ソフト自体は対象外です。Debianのメジャー版移行とパッケージ削除は行いません。</p>
{''.join(details)}
<form method="post"><button class="button" name="action" value="os-check"{disabled}>更新を確認</button></form>
<form method="post"><label class="agree"><input type="checkbox" name="agree" value="yes" required{apply_disabled}>
USB/IPを切断済みで、更新中に接続が切れて本体が再起動することを確認しました</label>
<button class="button primary" name="action" value="os-apply"{apply_disabled}>更新して再起動</button></form>
<p class="hint">OS保護中は保守起動と完了後の計2回再起動します。終了後は元の保護設定に戻します。
更新中は電源を切らず、数分待ってこの画面を開き直してください。失敗時も結果を表示します。</p>
<a href="network.py">更新状況を再読込</a></section>"""


def password_card():
    return """<section class="card"><h2>管理パスワード</h2>
<p>ユーザー名は <strong>admin</strong> です。SSHのパスワードは変更しません。</p>
<form method="post">
<label>現在のパスワード<input type="password" name="current_password" autocomplete="current-password" maxlength="128" required></label>
<label>新しいパスワード<input type="password" name="new_password" autocomplete="new-password" minlength="5" maxlength="64" required></label>
<label>新しいパスワード（確認）<input type="password" name="confirm_password" autocomplete="new-password" minlength="5" maxlength="64" required></label>
<p class="hint">半角英数字・記号5〜64文字（空白なし）。変更後は新しいパスワードでログインしてください。
忘れた場合は本体メニューの「Reset Web admin password」で初期化できます。</p>
<button class="button" name="action" value="web-password">管理パスワードを変更</button>
</form></section>"""


def page(message="", status="200 OK", kind="info", trial=None, authorized=True):
    print(f"Status: {status}")
    print("Content-Type: text/html; charset=utf-8")
    print("Cache-Control: no-store")
    print("Content-Security-Policy: default-src 'none'; style-src " + CSP_STYLE
          + "; form-action 'self'; frame-ancestors 'none'")
    print()
    notice = f'<p class="notice {kind}" role="status">{escape(message)}</p>' if message else ""
    body = ""
    if authorized:
        state = current_status()
        trial = (state and state.get("trial")) or trial
        server = os.environ.get("SERVER_ADDR", "")
        unknown = ("" if state else '<p class="notice busy">現在の設定を取得できませんでした。'
                   "しばらくしてから再読み込みしてください。</p>")
        confirm = "" if trial else """<section class="card">
<h2>設定の確定</h2>
<p class="hint">試用中の設定は、新しい接続先でこの画面を開き、120秒以内にここで確定します。</p>
<form method="post"><button class="button" name="action" value="confirm">設定を確定</button></form>
</section>"""
        body = (unknown + (trial_card(trial, server) if trial else "") + mode_card(state) + lan_card(state)
                + wifi_card(state) + hostname_card(state) + usb_sharing_card() + confirm + reset_card(state) + password_card() + update_card()
                + '<p class="hint">「試す」を押すと設定がすぐ反映されます。120秒以内に新しい接続先で確定しないと元に戻ります。</p>')
    print(f"""<!doctype html>
<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ネットワーク設定 - Wyse USB/IP</title>
<style>{STYLE}{PAGE_STYLE}</style>
<main>
<header><div><h1>Wyse USB/IP</h1><p class="hint">管理ソフト v{escape(VERSION)}</p></div>
<nav><a href="usbip.py">USB共有</a><a href="network.py" aria-current="page">ネットワーク設定</a><a href="system.py">システム状態</a></nav></header>
{notice}{body}
</main></html>""")


def parse(action, fields):
    """Return the request tuple for a submitted form, or raise ValueError with a message."""
    if action in ("os-check", "os-apply"):
        if action == "os-apply" and fields.get("agree") != ["yes"]:
            raise ValueError("更新・再起動の確認にチェックを入れてください")
        return (action,)
    if action == "begin":
        try:
            address = ipaddress.IPv4Interface(fields["address"][0])
        except (KeyError, ValueError):
            raise ValueError("管理IPは「10.42.0.1/24」の形式で入力してください。") from None
        if "ssid" not in fields:
            raise ValueError("SSIDを入力してください。")
        ssid, = fields["ssid"]
        password, = fields.get("password", [""])
        if password and not 8 <= len(password) <= 63:
            raise ValueError("WPA2パスワードは8〜63文字で入力してください。空欄なら現在の設定を維持します。")
        return ("begin", "wifi", str(address), ssid, password)
    if action == "begin-lan":
        method, = fields.get("method", ["dhcp"])
        if method == "dhcp":
            return ("begin", "lan", "dhcp", "", "")
        try:
            return ("begin", "lan", str(ipaddress.IPv4Interface(fields["address"][0])), "", "",
                    fields.get("gateway", [""])[0].strip(), fields.get("dns", [""])[0].strip())
        except (KeyError, ValueError):
            raise ValueError("固定IPv4を選んだときは、IPアドレスを「192.168.0.80/24」の形式で入力してください。") from None
    if action == "reset":
        if fields.get("agree") != ["yes"]:
            raise ValueError("初期化するには、確認のチェックを入れてから実行してください。")
        return ("reset",)
    if action == "web-password":
        current, = fields["current_password"]
        new, = fields["new_password"]
        confirmation, = fields["confirm_password"]
        if new != confirmation:
            raise ValueError("新しいパスワードと確認入力が一致しません。")
        if not 5 <= len(new) <= 64 or any(not 33 <= ord(c) <= 126 for c in new):
            raise ValueError("新しいパスワードは半角英数字・記号5〜64文字（空白なし）で入力してください。")
        return ("web-password", current, new, confirmation)
    if action == "hostname":
        name, = fields["hostname"]
        return ("hostname", name.strip().lower())
    if action in ("usb-pause", "usb-resume", "usb-recover"):
        bus, = fields["bus"]
        number, = fields["number"]
        return (action, bus, number)
    if action == "confirm":
        try:
            return ("confirm", str(ipaddress.IPv4Address(os.environ.get("SERVER_ADDR", ""))))
        except ValueError:
            raise ValueError("IPv4アドレス（https://新しいIP/network.py）で画面を開いて確定してください。") from None
    raise ValueError("この操作は受け付けられません。画面を再読み込みしてください。")


def main():
    if not os.environ.get("REMOTE_USER") or os.environ.get("HTTPS") != "on":
        page("HTTPS（https://WyseのIP/network.py）でログインしてから開いてください。",
             "403 Forbidden", "error", authorized=False)
        return
    if os.environ.get("REQUEST_METHOD") == "GET":
        page()
        return
    if (os.environ.get("REQUEST_METHOD") != "POST"
            or os.environ.get("HTTP_ORIGIN") != "https://" + os.environ.get("HTTP_HOST", "")):
        page("この設定画面を直接開き、画面内のボタンから送信してください。", "403 Forbidden", "error")
        return
    try:
        length = int(os.environ.get("CONTENT_LENGTH", "0"))
        if not 0 < length <= 2048:
            raise ValueError
        fields = parse_qs(sys.stdin.read(length), strict_parsing=True, max_num_fields=6)
        action, = fields["action"]
    except (KeyError, ValueError):
        page("送信内容を読み取れませんでした。画面を再読み込みして、もう一度操作してください。", "400 Bad Request", "error")
        return
    try:
        args = parse(action, fields)
    except (KeyError, ValueError) as error:
        page(str(error) if error.args else "入力内容が正しくありません。", "400 Bad Request", "error")
        return
    try:
        result = request(args)
    except (OSError, ValueError):
        page("設定サービスが応答しませんでした。少し待ってから再読み込みしてください。", "503 Service Unavailable", "error")
        return
    if result["error"]:
        prefix = "設定を確定できませんでした: " if action == "confirm" else "設定を反映できませんでした（元の設定のままです）: "
        if action == "web-password":
            prefix = "管理パスワードを変更できませんでした。現在のパスワード・確認入力・保存領域を確認してください: "
        if action.startswith("usb-"):
            prefix = "USB操作を完了できませんでした。現在の状態を確認してください: "
        page(prefix + result["error"], "409 Conflict", "error")
    elif action in ("os-check", "os-apply"):
        page("更新確認を開始しました。少し待って状況を再読込してください。" if action == "os-check" else
             "更新を予約しました。再起動後にこの画面で結果を確認してください。", kind="ok")
    elif action == "web-password":
        page("管理パスワードを変更しました。次のアクセスでは新しいパスワードでログインしてください。", kind="ok")
    elif action == "confirm":
        page("設定を確定し、保存しました。", kind="ok")
    elif action == "hostname":
        page("ネットワーク上の機器名を保存しました。", kind="ok")
    elif action in ("usb-pause", "usb-resume", "usb-recover"):
        page({"usb-pause": "USB共有を停止しました。", "usb-resume": "USB共有を再開しました。",
              "usb-recover": "USB共有を復旧しました。クライアントから再接続してください。"}[action], kind="ok")
    else:
        try:
            addresses = json.loads(result["output"])
        except ValueError:
            addresses = {args[1] if args[0] == "begin" else "lan": result["output"]}
        label = "ネットワーク設定の初期化" if action == "reset" else NAMES[args[1]] + "の設定"
        page(f"{label}を試用しています。120秒以内に新しい接続先で確定してください。", kind="ok",
             trial={"addresses": addresses, "reset": action == "reset"})


if __name__ == "__main__":
    main()
