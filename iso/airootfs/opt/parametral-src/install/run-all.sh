#!/usr/bin/env bash
# run-all.sh — one-shot install for a throwaway test VM (no LUKS, known passwords).
#
#   PARAMETRAL_DESKTOP=kde|hyprland|both bash install/run-all.sh /dev/sda
#   PARAMETRAL_APPEARANCE=light ...            # optional, default dark
#
# A real install runs the same steps from docs/INSTALL-ARCH.md or uses the parametral-install
# wizard. This script only shortens the test loop; it is not the product installer.
set -Eeuo pipefail

DISK="${1:-/dev/sda}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="${PARAMETRAL_DESKTOP:-kde}"
APPEARANCE="${PARAMETRAL_APPEARANCE:-dark}"
PARAMETRAL_USER="${PARAMETRAL_USER:-operator}"

case "$DESKTOP" in
  kde|hyprland|both) ;;
  *) echo "PARAMETRAL_DESKTOP must be kde, hyprland or both" >&2; exit 2 ;;
esac

echo "=== 10 preflight"
bash "$SRC/install/10-preflight.sh" "$DISK" --yes
echo "=== 20 disk (no LUKS: test VM only)"
bash "$SRC/install/20-disk.sh" "$DISK" --yes --no-luks
echo "=== 30 bootstrap (both kernels, nix, no desktop yet)"
bash "$SRC/install/30-bootstrap.sh"
echo "=== 35 nix (package manager)"
bash "$SRC/install/35-nix.sh"

echo "=== payload into the installed system"
install -d /mnt/opt
rm -rf /mnt/opt/parametral-src
cp -a "$SRC" /mnt/opt/parametral-src

chroot_run() {
  local script="$1"; shift
  echo "=== $script (chroot)"
  arch-chroot /mnt env \
    SRC=/opt/parametral-src \
    PARAMETRAL_USER="$PARAMETRAL_USER" \
    PARAMETRAL_DESKTOP="$DESKTOP" \
    PARAMETRAL_APPEARANCE="$APPEARANCE" \
    bash -c "cd /opt/parametral-src && bash install/$script $(printf '%q ' "$@")"
}

chroot_run 40-users.sh --non-interactive
echo "=== 65 branding (splash + greeter theme)"
bash "$SRC/install/65-branding.sh"
chroot_run 74-desktop.sh
chroot_run 45-apps.sh
chroot_run 78-ai.sh
chroot_run 50-snapshots.sh
chroot_run 60-boot.sh
chroot_run 70-verify.sh

echo "=== clean unmount (a dirty ESP makes the firmware refuse to boot)"
sync
umount -R /mnt || true
sync
echo "=== INSTALL DONE (desktop: $DESKTOP, appearance: $APPEARANCE)"
echo "=== poweroff, detach the ISO, boot from the disk"
