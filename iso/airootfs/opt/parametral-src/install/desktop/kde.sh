#!/usr/bin/env bash
# desktop/kde.sh — the KDE Plasma edition.
#
# Called by install/74-desktop.sh in the installed system (arch-chroot). This file owns the
# Plasma-specific packages and the identity shipped by 75-desktop.sh; the session/greeter
# wiring is deliberately in the dispatcher so both editions follow one path.
#
#   bash install/desktop/kde.sh --plan     print what would be installed, touch nothing
#   bash install/desktop/kde.sh            install (root, installed system)
set -Eeuo pipefail

SRC="${SRC:-$(cd "$(dirname "$0")/../.." && pwd)}"
APPEARANCE="${PARAMETRAL_APPEARANCE:-dark}"

PACKAGES=(
  plasma-meta
  sddm
  konsole
  dolphin
  kate
  breeze-gtk
  kde-gtk-config
  plasma-nm
  plasma-pa
  powerdevil
  bluedevil
  xdg-desktop-portal-kde
  polkit-kde-agent
  qt6-wayland
)

if [ "${1:-}" = "--plan" ]; then
  cat <<EOF
edition=kde
session=plasma
session-file=/usr/share/wayland-sessions/plasma.desktop
packages=${PACKAGES[*]}
EOF
  exit 0
fi

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
case "$APPEARANCE" in
  dark|light) ;;
  *) echo "PARAMETRAL_APPEARANCE must be dark or light" >&2; exit 2 ;;
esac

echo "==> KDE Plasma paketleri"
pacman -S --needed --noconfirm "${PACKAGES[@]}"

echo "==> KDE kimliği (duvar kağıdı, palet, Dolphin, Konsole, giriş ekranı)"
PARAMETRAL_APPEARANCE="$APPEARANCE" bash "$SRC/install/75-desktop.sh"

# The stock Plasma wayland session is the session entry. Do not write a second one: two
# identical entries in SDDM make "Plasma" appear twice and the second one is always wrong
# after an upgrade.
PLASMA_SESSION=""
for candidate in \
  /usr/share/wayland-sessions/plasma.desktop \
  /usr/share/xsessions/plasma.desktop; do
  [ -f "$candidate" ] && PLASMA_SESSION="$candidate" && break
done
if [ -z "$PLASMA_SESSION" ]; then
  echo "WARN: Plasma session entry not found — the package layout changed?" >&2
fi

echo "==> done (KDE)"
