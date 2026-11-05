#!/bin/sh
set -eu

test "$(findmnt -n -o FSTYPE -T /)" = overlay || exit 0
mount -o remount,rw overlayroot /
# util-linux cannot reapply OverlayFS layer paths on a remount.
sed -i -E '/^[^#]+[[:space:]]+\/[[:space:]]+overlay[[:space:]]/ s/[[:space:]]+lowerdir=[^[:space:]]+/ defaults/' /etc/fstab
