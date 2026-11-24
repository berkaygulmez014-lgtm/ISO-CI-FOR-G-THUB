#!/usr/bin/env bash
# 65-branding.sh — boot splash (plymouth) and login screen (SDDM).
# Run after 30-bootstrap (needs the base system) and before 70-verify.
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
mountpoint -q /mnt || { echo "/mnt is not mounted — run 20-disk.sh first" >&2; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> plymouth (boot splash)"
pacstrap /mnt plymouth

install -d /mnt/usr/share/plymouth/themes/parametral
cp -r "$SRC/branding/plymouth/parametral/." /mnt/usr/share/plymouth/themes/parametral/
arch-chroot /mnt plymouth-set-default-theme parametral

echo "==> mkinitcpio: plymouth hook after udev (idempotent)"
if ! grep -q 'plymouth' /mnt/etc/mkinitcpio.conf; then
  sed -i 's/^HOOKS=(\(base udev\) /HOOKS=(\1 plymouth /' /mnt/etc/mkinitcpio.conf
fi
grep -q 'plymouth' /mnt/etc/mkinitcpio.conf || {
  echo "could not add the plymouth hook to /etc/mkinitcpio.conf" >&2; exit 1; }
arch-chroot /mnt mkinitcpio -P

echo "==> SDDM theme"
install -d /mnt/usr/share/sddm/themes/parametral
cp -r "$SRC/branding/sddm/parametral/." /mnt/usr/share/sddm/themes/parametral/
install -d /mnt/etc/sddm.conf.d
cat > /mnt/etc/sddm.conf.d/10-parametral.conf <<'EOF'
[Theme]
Current=parametral

[General]
Numlock=on
HaltCommand=/usr/bin/systemctl poweroff
RebootCommand=/usr/bin/systemctl reboot
EOF

echo "==> branding installed"
echo "    splash : /usr/share/plymouth/themes/parametral (default theme)"
echo "    login  : /usr/share/sddm/themes/parametral"
