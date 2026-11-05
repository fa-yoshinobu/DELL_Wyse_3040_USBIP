#!/bin/sh
set -eu

volume=/var/lib/wyse-settings
profiles=/etc/NetworkManager/system-connections
settings=/dev/disk/by-label/WYSECFG

test "$(id -u)" -eq 0
test -b "$settings"
test "$(blkid -s TYPE -o value "$settings")" = ext4
test "$(findmnt -n -o FSTYPE /)" = ext4
test -f /etc/overlayroot.conf

install -d -m 700 "$volume"
if ! grep -q '^LABEL=WYSECFG ' /etc/fstab; then
    printf '%s\n' 'LABEL=WYSECFG /var/lib/wyse-settings ext4 nofail,x-systemd.device-timeout=30s 0 2' >> /etc/fstab
fi
mountpoint -q "$volume" || mount "$volume"
chmod 700 "$volume"
install -d -m 700 "$volume/system-connections"
if ! mountpoint -q "$profiles"; then
    cp -an "$profiles/." "$volume/system-connections/"
fi
if ! grep -q '^/var/lib/wyse-settings/system-connections ' /etc/fstab; then
    printf '%s\n' '/var/lib/wyse-settings/system-connections /etc/NetworkManager/system-connections none bind,nofail,x-systemd.requires-mounts-for=/var/lib/wyse-settings 0 0' >> /etc/fstab
fi
mountpoint -q "$profiles" || mount "$profiles"

install -d -m 755 /etc/systemd/system/NetworkManager.service.d
unit=$(systemd-escape --path --suffix=mount "$profiles")
printf '[Unit]\nWants=%s\nAfter=%s\n' "$unit" "$unit" > /etc/systemd/system/NetworkManager.service.d/wyse-settings.conf

if [ ! -e "$volume/overlayroot.conf" ]; then
    umask 077
    printf 'overlayroot="disabled"\n' > "$volume/overlayroot.conf"
fi
printf 'overlayroot="disabled"\noverlayroot_cfgdisk="LABEL=WYSECFG"\n' > /etc/overlayroot.local.conf
systemctl daemon-reload
nmcli connection reload
sync
