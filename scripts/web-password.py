#!/usr/bin/python3
"""Change Web Basic-auth credentials; reset is available only to the root console."""
import argparse
import fcntl
import grp
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

VOLUME = Path("/var/lib/wyse-settings")
DIRECTORY = Path("/etc/lighttpd/wyse-auth")
LOCK = Path("/run/wyse-network-trial.lock")


def check_storage():
    for directory in (VOLUME, DIRECTORY):
        result = subprocess.check_output(["findmnt", "-n", "-o", "FSTYPE,VFS-OPTIONS", "--mountpoint", str(directory)], text=True).split()
        if len(result) != 2 or result[0] != "ext4" or "rw" not in result[1].split(","):
            raise ValueError("Password storage is unavailable or read-only")
    if not DIRECTORY.samefile(VOLUME / "web-auth"):
        raise ValueError("Password storage is not persistent")


def password_hash(password, algorithm="6", salt=None):
    command = ["openssl", "passwd", "-" + algorithm, "-stdin"]
    if salt is not None:
        command += ["-salt", salt]
    return subprocess.check_output(command, input=password + "\n", text=True,
                                   stderr=subprocess.PIPE, timeout=10).strip()


def validate(password):
    if not isinstance(password, str) or not 5 <= len(password) <= 64 or any(not 33 <= ord(c) <= 126 for c in password):
        raise ValueError("Use 5-64 printable ASCII characters without spaces")


def verify(password, encoded):
    if not isinstance(password, str) or any(c in password for c in "\r\n\x00") or len(password) > 128:
        return False
    parts = encoded.split("$")
    if len(parts) != 4 or parts[1] not in ("apr1", "6"):
        raise ValueError("Unsupported password hash format")
    return hmac.compare_digest(password_hash(password, parts[1], parts[2]), encoded)


def save(encoded):
    gid = grp.getgrnam("www-data").gr_gid
    with tempfile.NamedTemporaryFile(mode="w", dir=DIRECTORY, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            os.fchmod(stream.fileno(), 0o640)
            os.fchown(stream.fileno(), 0, gid)
            stream.write("admin:" + encoded + "\n")
            stream.flush(); os.fsync(stream.fileno())
            temporary.replace(DIRECTORY / "htpasswd")
            descriptor = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
        finally:
            temporary.unlink(missing_ok=True)


def change(current, new, confirmation):
    validate(new)
    if new != confirmation:
        raise ValueError("New passwords do not match")
    check_storage()
    username, encoded = (DIRECTORY / "htpasswd").read_text().strip().split(":", 1)
    if username != "admin" or not verify(current, encoded):
        raise ValueError("Current password is incorrect")
    save(password_hash(new))


def reset():
    check_storage()
    password = secrets.token_urlsafe(12)
    save(password_hash(password))
    return password


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("change", "reset"))
    args = parser.parse_args()
    with LOCK.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        subprocess.run(["/usr/local/sbin/wyse-os-update", "guard"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if args.action == "reset":
            print(reset())
        else:
            values = json.loads(sys.stdin.read(2048))
            if not isinstance(values, list) or len(values) != 3:
                raise ValueError("Invalid password request")
            change(*values)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError):
        # Do not put submitted passwords or subprocess arguments in logs/responses.
        print("Password update failed. Check the current password, matching new passwords and persistent storage.", file=sys.stderr)
        sys.exit(1)
