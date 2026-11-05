#!/usr/bin/env python3
import curses
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

AP_PROFILE = "12130d96-e908-42ce-9561-1ae5bd132282"
TRIAL_STATE = Path("/run/wyse-network-trial")
PROTECTION = Path("/var/lib/wyse-settings/overlayroot.conf")
PROTECTION_ON = 'overlayroot="tmpfs:recurse=0,swap=0"\n'
PROTECTION_OFF = 'overlayroot="disabled"\n'


def run(*command):
    return subprocess.check_output(command, text=True, timeout=20, stderr=subprocess.STDOUT)


def saved_mode():
    enabled = run("nmcli", "-g", "connection.autoconnect", "con", "show", "uuid", AP_PROFILE)
    return "Standalone" if enabled.strip() == "yes" else "Existing LAN"


def saved_protection():
    if not PROTECTION.parent.is_mount():
        return "settings volume unavailable"
    try:
        value = PROTECTION.read_text()
    except FileNotFoundError:
        return "disabled"
    if value == PROTECTION_ON:
        return "enabled"
    if value == PROTECTION_OFF:
        return "disabled"
    return "invalid settings"


def save_protection(enabled):
    with TRIAL_STATE.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        os_update_guard()
        if not PROTECTION.parent.is_mount():
            raise ValueError("Settings volume unavailable")
        with tempfile.NamedTemporaryFile(mode="w", dir=PROTECTION.parent, delete=False) as temporary:
            path = Path(temporary.name)
            try:
                temporary.write(PROTECTION_ON if enabled else PROTECTION_OFF)
                temporary.flush()
                os.fsync(temporary.fileno())
                path.replace(PROTECTION)
                directory = os.open(PROTECTION.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                path.unlink(missing_ok=True)


def apply_mode(standalone):
    with TRIAL_STATE.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if TRIAL_STATE.exists():
            trial = json.loads(TRIAL_STATE.read_text())
            nm = "org.freedesktop.NetworkManager"
            checkpoints = run("busctl", "get-property", nm,
                              "/org/freedesktop/NetworkManager", nm, "Checkpoints")
            if f'"{trial["checkpoint"]}"' in checkpoints:
                raise ValueError("Finish the Web network trial before switching modes")
        if run("ss", "-Hnt", "state", "established", "( sport = :3240 )").strip():
            raise ValueError("Detach active USB/IP clients before switching modes")
        set_mode(standalone)


def set_mode(standalone):
    run("/usr/local/sbin/wyse-network-trial", "check-settings",
        *(["--standalone"] if standalone else []))
    previous = saved_mode() == "Standalone"
    run("nmcli", "con", "modify", "uuid", AP_PROFILE, "connection.autoconnect",
        "yes" if standalone else "no")
    try:
        active = AP_PROFILE in run("nmcli", "-g", "UUID", "con", "show", "--active").splitlines()
        if active != standalone:
            run("nmcli", "--wait", "15", "con", "up" if standalone else "down", "uuid", AP_PROFILE)
    except (OSError, subprocess.SubprocessError):
        run("nmcli", "con", "modify", "uuid", AP_PROFILE, "connection.autoconnect",
            "yes" if previous else "no")
        raise


def os_update_guard():
    # wyse-os-update reports in Japanese, which the Linux text console cannot show.
    try:
        run("/usr/local/sbin/wyse-os-update", "guard")
    except subprocess.CalledProcessError:
        raise ValueError("An OS update is in progress. Wait until it finishes.") from None


def usbip_clients():
    return run("ss", "-Hnt", "state", "established", "( sport = :3240 )").strip()


def reboot():
    os_update_guard()
    run("systemctl", "reboot")


def status():
    """Return status rows as (label, [values], style) for the console screen."""
    devices = json.loads(run("ip", "-j", "-4", "address", "show", "scope", "global"))
    addresses = [
        f"{device['ifname']:<7}{address['local']}/{address['prefixlen']}"
        for device in devices
        for address in device.get("addr_info", [])
    ]
    active = run("nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active")
    connections = [line.replace(":", " (", 1) + ")" for line in active.splitlines() if ":" in line]
    root_fs = run("findmnt", "-n", "-o", "FSTYPE", "/").strip()
    current = "enabled" if root_fs == "overlay" else "disabled"
    upcoming = saved_protection()
    mode = saved_mode()
    clients = len(usbip_clients().splitlines())
    rows = [
        ("Network mode", [mode + (" (Wi-Fi AP + DHCP)" if mode == "Standalone" else " (external DHCP)")], "normal"),
        ("IPv4", addresses or ["waiting for an address"], "normal" if addresses else "warn"),
        ("Connections", connections or ["none"], "normal" if connections else "warn"),
        ("USB/IP clients", [f"{clients} connected" if clients else "none"], "normal"),
        ("OS protection", ["ON (OS is read-only)" if current == "enabled" else "OFF (OS is writable)"],
         "ok" if current == "enabled" else "warn"),
    ]
    if upcoming in ("enabled", "disabled"):
        planned = "ON" if upcoming == "enabled" else "OFF"
        if upcoming == current:
            rows.append(("Next boot", [planned + " (no change)"], "normal"))
        else:
            rows.append(("Next boot", [planned + " - reboot to apply"], "warn"))
    else:
        rows.append(("Next boot", [upcoming], "error"))
    return rows


ITEMS = (
    ("standalone", "Standalone mode (Wi-Fi AP + DHCP)"),
    ("lan", "Existing LAN mode (external DHCP)"),
    ("protect-on", "OS protection ON at next boot"),
    ("protect-off", "OS protection OFF at next boot"),
    ("web-password-reset", "Reset Web admin password"),
    ("reboot", "Reboot now"),
    ("refresh", "Refresh status"),
    ("exit", "Exit"),
)


def confirmation(action, rows):
    """Return (title, lines) for actions that need a Y/N confirmation, else None."""
    values = {label: values for label, values, _ in rows}
    clients = values.get("USB/IP clients", ["none"])[0] != "none"
    if action in ("standalone", "lan"):
        name = "Standalone" if action == "standalone" else "Existing LAN"
        lines = [f"Switch to {name} mode now?", "The network connection may drop for a moment."]
        if action == "lan":
            lines.append("The Wi-Fi AP and its DHCP service will stop.")
        return "Switch network mode", lines
    if action == "web-password-reset":
        return "Reset Web password", ["Replace the Web admin password?", "A new password will be shown on this screen.", "The old Web password will stop working.", "SSH and network settings will not change."]
    if action == "reboot":
        lines = ["Reboot the Wyse now?", "Web and USB/IP are unavailable for about a minute."]
        if clients:
            lines.append("Connected USB/IP clients will be disconnected.")
        upcoming = values.get("Next boot", [""])[0]
        if "reboot to apply" in upcoming:
            lines.append("OS protection will be " + upcoming.split(" ")[0] + " after the reboot.")
        return "Reboot", lines
    return None


def layout(rows, selected, current_mode, message, dialog, width, height):
    """Return drawing commands (y, x, text, style) using ASCII only."""
    width = max(width, 40)
    out = []
    title = " Wyse USB/IP"
    out.append((0, 0, title.ljust(width - 1), "title"))
    y = 2

    def section(name):
        nonlocal y
        out.append((y, 1, name, "heading"))
        out.append((y, 2 + len(name), "-" * max(0, width - len(name) - 4), "rule"))
        y += 1

    section("STATUS")
    for label, values, style in rows:
        if height < 27 and label == "Connections":
            continue
        for index, value in enumerate(values):
            if y >= height - len(ITEMS) - 5:
                break
            out.append((y, 3, (label if index == 0 else "").ljust(16), "label"))
            out.append((y, 20, value[:max(0, width - 22)], style))
            y += 1
    y += 1
    section("ACTIONS")
    for index, (action, text) in enumerate(ITEMS):
        if y >= height - 2:
            break
        mark = "  [current]" if action == current_mode else ""
        line = (" > " if index == selected else "   ") + text + mark
        out.append((y, 2, line.ljust(min(width - 4, 48)), "selected" if index == selected else "item"))
        y += 1
    if message and y < height - 2:
        y += 1
        style, text = message
        out.append((min(y, height - 3), 3, text[:max(0, width - 5)], style))
    keys = " Up/Down: select   Enter: run   R: refresh"
    if dialog:
        keys = " Y: yes   N or Esc: cancel"
    out.append((height - 1, 0, keys.ljust(width - 1), "footer"))
    if dialog:
        title, lines = dialog
        inner = max(len(title) + 4, max(len(line) for line in lines) + 4, 32)
        inner = min(inner, width - 4)
        top = max(1, (height - len(lines) - 6) // 2)
        left = max(1, (width - inner - 2) // 2)
        border = "+" + "-" * inner + "+"
        body = [f" {title} ", ""] + lines + ["", "[Y] Yes    [N] No"]
        out.append((top, left, border, "dialog"))
        for offset, line in enumerate(body, 1):
            style = "dialog-title" if offset == 1 else "dialog"
            out.append((top + offset, left, "|" + (" " + line).ljust(inner)[:inner] + "|", style))
        out.append((top + len(body) + 1, left, border, "dialog"))
    return out


def styles():
    plain = {"title": curses.A_REVERSE | curses.A_BOLD, "heading": curses.A_BOLD, "rule": curses.A_DIM,
             "label": curses.A_NORMAL, "normal": curses.A_BOLD, "ok": curses.A_BOLD, "warn": curses.A_BOLD,
             "error": curses.A_BOLD | curses.A_UNDERLINE, "item": curses.A_NORMAL,
             "selected": curses.A_REVERSE | curses.A_BOLD, "footer": curses.A_REVERSE,
             "dialog": curses.A_REVERSE, "dialog-title": curses.A_REVERSE | curses.A_BOLD}
    if not curses.has_colors():
        return plain
    curses.start_color()
    pairs = {"title": (curses.COLOR_WHITE, curses.COLOR_BLUE), "heading": (curses.COLOR_CYAN, curses.COLOR_BLACK),
             "ok": (curses.COLOR_GREEN, curses.COLOR_BLACK), "warn": (curses.COLOR_YELLOW, curses.COLOR_BLACK),
             "error": (curses.COLOR_RED, curses.COLOR_BLACK), "selected": (curses.COLOR_WHITE, curses.COLOR_BLUE),
             "footer": (curses.COLOR_BLACK, curses.COLOR_WHITE), "dialog": (curses.COLOR_BLACK, curses.COLOR_WHITE)}
    result = dict(plain)
    for number, (name, (fg, bg)) in enumerate(pairs.items(), 1):
        curses.init_pair(number, fg, bg)
        result[name] = curses.color_pair(number) | (curses.A_BOLD if name not in ("footer", "dialog") else 0)
    result["dialog-title"] = result["dialog"] | curses.A_BOLD
    return result


def run_action(action):
    """Run one menu action and return (style, message)."""
    try:
        if action in ("standalone", "lan"):
            apply_mode(action == "standalone")
            return "ok", "Network mode applied and saved."
        if action in ("protect-on", "protect-off"):
            save_protection(action == "protect-on")
            return "ok", "OS protection setting saved. Choose 'Reboot now' to apply it."
        if action == "web-password-reset":
            password = run("/usr/local/sbin/wyse-web-password", "reset").strip()
            return "ok", "Web login: admin / " + password + "  (R to clear)"
        if action == "reboot":
            reboot()
            return "ok", "Rebooting..."
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        detail = (getattr(error, "output", "") or str(error)).strip().splitlines()
        detail = detail[0] if detail else ""
        if not detail.isascii():
            detail = "see the Web settings page for details"
        return "error", "Failed: " + detail
    return "", ""


def menu(screen):
    screen.keypad(True)
    screen.timeout(1000)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    attrs = styles()
    selected = 0
    rows = [("Status", ["reading..."], "normal")]
    mode = ""
    next_refresh = 0
    message = None
    dialog = None

    while True:
        if time.monotonic() >= next_refresh:
            try:
                rows = status()
                mode = "standalone" if rows[0][1][0].startswith("Standalone") else "lan"
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                rows = [("Status", [f"unavailable: {error}".splitlines()[0]], "error")]
            next_refresh = time.monotonic() + 3

        screen.erase()
        height, width = screen.getmaxyx()
        prompt = confirmation(ITEMS[selected][0], rows) if dialog else None
        for y, x, text, style in layout(rows, selected, mode, message, prompt, width, height):
            if 0 <= y < height and x < width - 1:
                try:
                    screen.addnstr(y, x, text, width - 1 - x, attrs.get(style, curses.A_NORMAL))
                except curses.error:
                    pass
        screen.refresh()

        key = screen.getch()
        if dialog:
            if key in (ord("y"), ord("Y")):
                dialog = None
                message = run_action(ITEMS[selected][0])
                next_refresh = 0
            elif key in (ord("n"), ord("N"), 27):
                dialog = None
                message = ("warn", "Cancelled.")
            continue
        if key == curses.KEY_UP:
            selected = (selected - 1) % len(ITEMS)
        elif key == curses.KEY_DOWN:
            selected = (selected + 1) % len(ITEMS)
        elif key in (ord("r"), ord("R")):
            message, next_refresh = None, 0
        elif key in (10, 13, curses.KEY_ENTER):
            action = ITEMS[selected][0]
            if action == "exit":
                return
            if action == "refresh":
                message, next_refresh = None, 0
            elif action == mode:
                message = ("warn", "Already in this mode.")
            elif confirmation(action, rows):
                dialog = action
            else:
                message = run_action(action)
                next_refresh = 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] in ("standalone", "lan"):
        apply_mode(sys.argv[1] == "standalone")
    else:
        curses.wrapper(menu)
