#!/usr/bin/env bash
# 10-preflight.sh — refuse to start unless this really is a UEFI Arch ISO boot.
set -Eeuo pipefail
DISK="${1:-}"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
note() { printf '  ok  %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || fail "run as root (inside the Arch ISO)"
[ -d /sys/firmware/efi ] || fail "booted in BIOS mode; Parametral OS is UEFI-only"
[ -n "$DISK" ] || fail "usage: $0 /dev/nvme0n1   (the WHOLE disk — it will be erased)"
[ -b "$DISK" ] || fail "$DISK is not a block device"
[ "$(lsblk -no TYPE "$DISK" | head -1)" = "disk" ] || fail "$DISK is not a whole disk"
mountpoint -q /mnt 2>/dev/null && fail "/mnt is already mounted; unmount it first"

for tool in sgdisk mkfs.fat mkfs.btrfs pacstrap arch-chroot bootctl cryptsetup; do
  command -v "$tool" >/dev/null || fail "missing tool: $tool (pacman -Sy $tool)"
done

note "UEFI boot"
note "target disk: $DISK ($(lsblk -dno SIZE "$DISK"))"
note "all tools present"

cat <<EOF

About to DESTROY everything on $DISK:
  1 GiB EFI system partition, the rest LUKS + btrfs (@, @home, @var, @snapshots),
  archived kernels: linux (main) + linux-lts (backup)

Re-run with --yes as the second argument if that is what you want.
EOF

[ "${2:-}" = "--yes" ] || fail "not confirmed"

# a machine check that has saved people before
if [ -d /sys/firmware/efi ] && grep -q "$(basename "$DISK")" /proc/mounts; then
  fail "$DISK has mounted partitions; unmount before wiping"
fi
note "confirmation received — continue with 20-disk.sh $DISK --yes"
