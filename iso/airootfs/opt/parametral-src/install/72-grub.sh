#!/usr/bin/env bash
# 72-grub — brand the boot menu. GRUB is the first surface a user sees.
set -eu

[ "${1:-}" = "--help" ] && { echo "usage: 72-grub.sh"; exit 0; }

SRC="${SRC:-/opt/parametral-src}"
THEME_DIR=/boot/grub/themes/parametral

echo "==> GRUB teması"
install -d "$THEME_DIR"
install -m 0644 "$SRC/branding/grub/theme.txt" "$THEME_DIR/theme.txt"
install -m 0644 "$SRC/branding/wallpapers/parametral-dark.png" "$THEME_DIR/background.png"

# point GRUB at it without clobbering the rest of /etc/default/grub
if grep -q '^GRUB_THEME=' /etc/default/grub 2>/dev/null; then
  sed -i "s|^GRUB_THEME=.*|GRUB_THEME=\"$THEME_DIR/theme.txt\"|" /etc/default/grub
else
  echo "GRUB_THEME=\"$THEME_DIR/theme.txt\"" >> /etc/default/grub
fi

echo "==> grub.cfg yeniden üretiliyor"
grub-mkconfig -o /boot/grub/grub.cfg >/dev/null

echo "==> done"
