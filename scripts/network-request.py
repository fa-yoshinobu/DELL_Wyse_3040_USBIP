#!/usr/bin/python3
import json
import subprocess
import sys

REQUESTS = {(7, "begin"), (5, "begin"), (2, "confirm"), (1, "reset"), (1, "status"), (2, "hostname"), (4, "web-password")}
REQUESTS.update({(3, "usb-pause"), (3, "usb-resume"), (3, "usb-recover"), (1, "os-status"), (1, "os-check"), (1, "os-apply")})

try:
    args = json.loads(sys.stdin.readline(2048))
    if (not isinstance(args, list) or not all(isinstance(arg, str) for arg in args)
            or (len(args), args[0] if args else "") not in REQUESTS):
        raise ValueError("Invalid request")
    password = ""
    if args[0] == "begin":
        if len(args) == 5:
            args += ["", ""]
        _, target, address, ssid, password, gateway, dns = args
        args = ["begin", "--target", target, "--gateway=" + gateway, "--dns=" + dns, "--", address, ssid]
    elif args[0] == "web-password":
        password = json.dumps(args[1:])
        args = ["web-password"]
    elif args[0] == "hostname":
        args.insert(1, "--")
    elif args[0] in ("usb-pause", "usb-resume", "usb-recover"):
        args.insert(1, "--")
    command = (["/usr/local/sbin/wyse-os-update", args[0][3:]] if args[0].startswith("os-")
               else ["/usr/local/sbin/wyse-network-trial", *args])
    if args[0] == "web-password":
        command = ["/usr/local/sbin/wyse-web-password", "change"]
    result = subprocess.run(command,
                            input=password, capture_output=True, text=True, timeout=60)
    message = (result.stderr.strip() or "設定を反映できませんでした。") if result.returncode else ""
    output = result.stdout.strip()
except (OSError, ValueError, subprocess.TimeoutExpired):
    message = "要求が正しくないか、設定サービスを利用できません。"
    output = ""
print(json.dumps({"error": message[:512], "output": output[:8000]}))
