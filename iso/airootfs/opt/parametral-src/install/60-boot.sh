#!/usr/bin/env bash
# 60-boot.sh — systemd-boot with both kernels and a rolling fallback.
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
source /etc/parametral/snapshot.env
[ -n "${PARAMETRAL_DEV:-}" ] || { echo "PARAMETRAL_DEV missing from /etc/parametral/snapshot.env" >&2; exit 1; }

echo "==> installing systemd-boot on the ESP"
bootctl --path=/boot install

# The removable-media fallback: some firmware ignores EFI variables entirely and only
# boots \EFI\BOOT\BOOTX64.EFI. Without this copy such machines boot straight to setup.
install -Dm0644 /usr/lib/systemd/boot/efi/systemd-bootx64.efi /boot/EFI/BOOT/BOOTX64.EFI

if [ -d /sys/firmware/efi/efivars ] && [ -w /sys/firmware/efi/efivars ] && [ -n "${PARAMETRAL_DEV:-}" ]; then
  efibootmgr --create --disk "${PARAMETRAL_DEV%[0-9]}" --part 1 --label Parametral \
             --loader '\EFI\BOOT\BOOTX64.EFI' || \
    echo "WARN: efibootmgr could not write a boot entry — the fallback path is installed"
else
  echo "NOTE: no writable efivars (chroot?): firmware will use \EFI\BOOT\BOOTX64.EFI"
fi

cat > /boot/loader/loader.conf <<'EOF'
default  parametral.conf
timeout  4
console-mode max
editor   no
auto-entries yes
auto-firmware yes
EOF

CMDLINE_COMMON="rw add_efi_memmap quiet splash vt.global_cursor_default=0 nowatchdog"
if [ "${PARAMETRAL_LUKS:-0}" = "1" ]; then
  CMDLINE_COMMON="cryptdevice=UUID=${PARAMETRAL_LUKS_UUID}:cryptroot root=/dev/mapper/cryptroot $CMDLINE_COMMON"
else
  CMDLINE_COMMON="root=${PARAMETRAL_DEV} $CMDLINE_COMMON"
fi

write_entry() {
  local file="$1" title="$2" kernel="$3" initrd="$4"
  cat > "/boot/loader/entries/$file" <<EOF
title   $title
linux   /$kernel
initrd  /$initrd
options rootflags=subvol=@ $CMDLINE_COMMON
EOF
}

echo "==> services: network, audio, bluetooth"
systemctl enable NetworkManager.service
if pacman -Q bluez >/dev/null 2>&1; then
  systemctl enable bluetooth.service
fi

# SDDM is installed by 74-desktop.sh for both editions. If no edition was selected (a hand
# install that stopped early), do not enable a greeter that does not exist.
if [ -f /etc/parametral/desktop.conf ]; then
  # shellcheck disable=SC1091
  . /etc/parametral/desktop.conf
  echo "==> services: greeter (SDDM, ${PARAMETRAL_DESKTOP:-unknown} edition)"
  systemctl enable sddm.service
else
  echo "WARN: /etc/parametral/desktop.conf missing — run install/74-desktop.sh before 60-boot.sh" >&2
fi

echo "==> entries: main, backup kernel, fallback initramfs"
write_entry parametral.conf        "ParametralOS (linux)"      vmlinuz-linux     initramfs-linux.img
write_entry parametral-lts.conf    "ParametralOS — backup kernel (linux-lts)" vmlinuz-linux-lts initramfs-linux-lts.img
write_entry parametral-fallback.conf "ParametralOS (fallback initramfs)" vmlinuz-linux initramfs-linux-fallback.img

ls -l /boot/vmlinuz-* /boot/initramfs-* | sed 's/^/  /'
ls -l /boot/loader/entries | sed 's/^/  /'

echo "==> kernel command line for reference"
printf '  %s\n' "$CMDLINE_COMMON"
