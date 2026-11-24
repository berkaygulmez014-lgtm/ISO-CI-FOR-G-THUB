#!/usr/bin/env bash
# 45-apps — the applications a desktop is expected to have on first boot.
#
# Kept deliberately small: a browser, an image viewer, a PDF reader, a text editor beyond
# Kate's scope, and the archive tool. Everything else is meant to come from Nix, per app,
# per profile. Firefox is here because a machine without a browser is not usable on day one.
set -eu

SRC="${SRC:-$(cd "$(dirname "$0")/.." && pwd)}"

[ "${1:-}" = "--help" ] && { echo "usage: 45-apps.sh"; exit 0; }

echo "==> temel uygulamalar"
# Konsole and Dolphin are in both editions on purpose: the Hyprland keybinds (SUPER+Return,
# SUPER+E) name them, and a tiling session with no terminal is not a working desktop.
pacman -S --noconfirm --needed \
  firefox \
  konsole \
  dolphin \
  gwenview \
  okular \
  ark \
  spectacle \
  ffmpegthumbs \
  kdegraphics-thumbnailers \
  xdg-utils

echo "==> Parametral uygulamaları (payload'da derlenmişse)"
install -d /usr/share/applications
for app in parametral-snapshots parametral-calculator; do
  built="$SRC/apps/$app/target/release/$app"
  if [ -x "$built" ]; then
    install -m 0755 "$built" "/usr/local/bin/$app"
    echo "    $app kuruldu"
  else
    echo "    $app: payload'da derlenmiş ikili yok"
  fi
done
for entry in parametral-snapshots.desktop; do
  [ -f "$SRC/branding/apps/$entry" ] && install -m 0644 "$SRC/branding/apps/$entry" /usr/share/applications/
done

echo "==> Firefox varsayılan tarayıcı"
if command -v xdg-settings >/dev/null 2>&1; then
  xdg-settings set default-web-browser firefox.desktop 2>/dev/null || true
fi

echo "==> done"
