#!/usr/bin/env bash
# parametral-reset-look — put this account back on the Parametral identity.
#
# The theme is deliberately not locked (users may change anything, including through the AI),
# so there has to be a one-click way back. This is that way: it is offered in the application
# menu as "Parametral görünümüne dön".
set -eu

cfg="${XDG_CONFIG_HOME:-$HOME/.config}"
mkdir -p "$cfg"

kwriteconfig6 --file kdeglobals --group General --key ColorScheme Parametral
kwriteconfig6 --file kdeglobals --group KDE --key LookAndFeelPackage org.parametral.desktop
kwriteconfig6 --file kdeglobals --group KDE --key widgetStyle Breeze
kwriteconfig6 --file kdeglobals --group Icons --key Theme breeze-dark
kwriteconfig6 --file plasmarc --group Theme --key name breeze-dark
kwriteconfig6 --file konsolerc --group "Desktop Entry" --key DefaultProfile Parametral.profile
kwriteconfig6 --file kscreenlockerrc --group Greeter --group Wallpaper --group org.kde.image \
  --group General --key Image /usr/share/wallpapers/Parametral/contents/images/2560x1440.png

if command -v plasma-apply-wallpaperimage >/dev/null 2>&1; then
  plasma-apply-wallpaperimage /usr/share/wallpapers/Parametral/contents/images/2560x1440.png \
    >/dev/null 2>&1 || true
fi

# plasmashell rereads the palette on restart; do not restart kwin on X11 (it drops the session)
if systemctl --user is-active --quiet plasma-plasmashell.service 2>/dev/null; then
  systemctl --user restart plasma-plasmashell.service 2>/dev/null || true
fi

if command -v notify-send >/dev/null 2>&1; then
  notify-send -a "Parametral OS" "Parametral görünümü geri yüklendi" \
    "Renkler, simgeler, imleç ve duvar kağıdı varsayılana döndü."
fi
