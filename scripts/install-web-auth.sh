#!/bin/sh
set -eu
volume=/var/lib/wyse-settings
source=$volume/web-auth
target=/etc/lighttpd/wyse-auth
test "$(id -u)" -eq 0
mountpoint -q "$volume"
test "$(findmnt -n -o FSTYPE --mountpoint "$volume")" = ext4
install -d -o root -g www-data -m 750 "$source" "$target"
if [ ! -s "$source/htpasswd" ]; then
    test -s /etc/lighttpd/wyse.htpasswd
    install -o root -g www-data -m 640 /etc/lighttpd/wyse.htpasswd "$source/htpasswd"
fi
if ! grep -q '^/var/lib/wyse-settings/web-auth /etc/lighttpd/wyse-auth ' /etc/fstab; then
    printf '%s\n' '/var/lib/wyse-settings/web-auth /etc/lighttpd/wyse-auth none bind,x-systemd.requires-mounts-for=/var/lib/wyse-settings 0 0' >> /etc/fstab
fi
systemctl daemon-reload
mountpoint -q "$target" || mount "$target"
test "$(stat -c %d:%i "$source")" = "$(stat -c %d:%i "$target")"
sync
