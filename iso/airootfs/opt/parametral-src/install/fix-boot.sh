#!/usr/bin/env bash
# fix-boot.sh — repair the ESP and reinstall systemd-boot on an installed Parametral system.
#
# Use when the firmware refuses to boot: VirtualBox's EFI is strict about a dirty or
# oddly-clustered FAT, and an unclean poweroff leaves loader.conf truncated.
#   bash fix-boot.sh /dev/sda            (root and ESP partitions of that disk)
# Run from the live ISO with the installed root mounted at /mnt.
set -Eeuo pipefail
DISK="${1:-/dev/sda}"
ESP="${DISK}1"
ROOTDEV="${DISK}2"
BACKUP=/root/boot-backup

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
mountpoint -q /mnt || { echo "/mnt must be the mounted installed root" >&2; exit 1; }

echo "==> saving the current ESP contents to $BACKUP"
rm -rf "$BACKUP"; mkdir -p "$BACKUP"
mountpoint -q /mnt/boot || mount "$ESP" /mnt/boot
cp -a /mnt/boot/. "$BACKUP"/
sync

echo "==> reformatting the ESP (FAT32, 2 KiB clusters — the firmware-friendly layout)"
umount /mnt/boot
# 512-byte sectors, 4 sectors per cluster: keeps the FAT driver in every firmware happy
mkfs.fat -F32 -S 512 -s 4 -n PARAMETRAL "$ESP"
mount "$ESP" /mnt/boot

echo "==> restoring kernels and initramfs"
cp -a "$BACKUP"/. /mnt/boot/
sync

echo "==> reinstalling systemd-boot (no EFI variables: they are written below)"
arch-chroot /mnt bootctl --esp-path=/boot install --no-variables
install -Dm0644 /mnt/usr/lib/systemd/boot/efi/systemd-bootx64.efi /mnt/boot/EFI/BOOT/BOOTX64.EFI

echo "==> loader.conf"
cat > /mnt/boot/loader/loader.conf <<'EOF'
default  parametral.conf
timeout  4
console-mode keep
editor   no
EOF

echo "==> EFI boot entry"
if [ -d /sys/firmware/efi/efivars ] && [ -w /sys/firmware/efi/efivars ]; then
  efibootmgr --create --disk "$DISK" --part 1 --label Parametral \
             --loader '\EFI\BOOT\BOOTX64.EFI' || echo "WARN: efibootmgr failed (firmware may still use the fallback path)"
else
  echo "NOTE: efivars are read-only here (chroot) — the firmware will use \\EFI\\BOOT\\BOOTX64.EFI"
fi

sync
echo "==> unmounting cleanly (an unclean ESP is what breaks the next boot)"
umount /mnt/boot
sync
echo "==> done — power off and boot from the disk"
