#!/usr/bin/python3
"""Keep the last 200 observed USB/IP connection changes in /run (RAM)."""
from datetime import datetime
import json
import os
from pathlib import Path
import time

DRIVER = Path("/sys/bus/usb/drivers/usbip-host")
STATE = Path("/run/wyse-usb-history/history.json")
LIMIT = 200


def snapshot(driver=DRIVER, previous=None):
    result = {}
    previous = previous or {}
    if not driver.exists():
        return result
    for device in driver.iterdir():
        if not device.is_symlink():
            continue
        number = None
        try:
            number = (device / "devnum").read_text().strip()
            status = (device / "usbip_status").read_text().strip()
            if status not in ("1", "2", "3"):
                raise OSError("USB status temporarily unavailable")
            name = " ".join((device / field).read_text(errors="replace").strip()
                            for field in ("manufacturer", "product") if (device / field).exists())
            ids = ":".join((device / field).read_text().strip() for field in ("idVendor", "idProduct"))
            result[device.name] = {"number": number, "status": status, "name": name or ids, "ids": ids}
        except OSError:
            before = previous.get(device.name)
            if device.exists() and before and (number is None or number == before["number"]):
                result[device.name] = before  # Keep only this device until a complete read succeeds.
    return result


def changes(previous, current, timestamp, initial=False):
    events = []
    for bus in sorted(previous.keys() | current.keys()):
        before, after = previous.get(bus), current.get(bus)
        same = before and after and before["number"] == after["number"]
        if before and before["status"] == "2" and not (same and after["status"] == "2"):
            events.append({"time": timestamp, "event": "切断", "bus": bus,
                           "name": before["name"], "ids": before["ids"]})
        if after and after["status"] == "2" and not (same and before["status"] == "2"):
            events.append({"time": timestamp, "event": "使用中を検出" if initial else "接続",
                           "bus": bus, "name": after["name"], "ids": after["ids"]})
    return events


def save(events, devices):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"events": events[-LIMIT:], "devices": devices}, ensure_ascii=False), encoding="utf-8")
    os.chmod(temporary, 0o644)
    temporary.replace(STATE)


def main():
    try:
        saved = json.loads(STATE.read_text(encoding="utf-8"))
        previous, events = saved["devices"], saved["events"][-LIMIT:]
        initial = False
    except (OSError, ValueError, KeyError):
        previous, events, initial = {}, [], True
    while True:
        try:
            current = snapshot(previous=previous)
        except OSError:
            time.sleep(0.5)
            continue
        events.extend(changes(previous, current, datetime.now().astimezone().isoformat(timespec="seconds"), initial))
        events = events[-LIMIT:]
        if initial or current != previous or not STATE.exists():
            save(events, current)
        previous, initial = current, False
        time.sleep(0.5)


if __name__ == "__main__":
    main()
