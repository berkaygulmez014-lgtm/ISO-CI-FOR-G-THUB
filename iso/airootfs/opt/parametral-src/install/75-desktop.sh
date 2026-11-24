#!/usr/bin/env bash
# 75-desktop.sh — the desktop identity: wallpaper, KDE palette, Dolphin, splash assets.
# Run inside the installed system (arch-chroot) after 40-users.sh; needs no network.
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> wallpapers"
install -d /usr/share/wallpapers/Parametral/contents/images
# one file per resolution: the bar plate is drawn into the wallpaper, so the file the shell uses
# has to be the screen's own size (see branding/hypr/parametral-wallpaper)
for size in 2560x1440 2560x1440-light 1920x1080 1920x1080-light 1280x800 1280x800-light; do
  install -m 0644 "$SRC/branding/wallpapers/$size.png" \
    "/usr/share/wallpapers/Parametral/contents/images/$size.png"
done
install -m 0755 "$SRC/branding/hypr/parametral-wallpaper" /usr/local/bin/parametral-wallpaper
# per-session wallpaper copy: the image tree stays root-owned, the shell reads this one
printf 'd /run/parametral 1777 root root -\n' > /usr/lib/tmpfiles.d/parametral-wallpaper.conf
cat > /usr/share/wallpapers/Parametral/metadata.json <<'EOF'
{"KPlugin": {"Id": "Parametral", "Name": "Parametral"}, "X-KDE-PluginInfo-Name": "Parametral"}
EOF

echo "==> KDE colour scheme"
install -d /usr/share/color-schemes
install -m 0644 "$SRC/branding/kde/Parametral.colors" /usr/share/color-schemes/Parametral.colors
install -m 0644 "$SRC/branding/kde/ParametralLight.colors" /usr/share/color-schemes/ParametralLight.colors


echo "==> cursor theme (Parametral, built from branding/cursors)"
if [ -d "$SRC/branding/cursors/Parametral" ]; then
  rm -rf /usr/share/icons/Parametral
  cp -r "$SRC/branding/cursors/Parametral" /usr/share/icons/Parametral
  # Installed as an option only: the default pointer stays Breeze unless the user picks it.
  printf '[Icon Theme]\nInherits=breeze\n' > /usr/share/icons/default/index.theme
fi


echo "==> app icons (paneldeki varsayılan uygulamalar bizim paletle)"
if [ -d "$SRC/branding/icons/apps" ]; then
  for svg in "$SRC/branding/icons/apps"/*.svg; do
    name="$(basename "$svg")"
    while IFS= read -r target; do
      [ -f "$target.orig" ] || cp "$target" "$target.orig"
      cp "$svg" "$target"
    done < <(find /usr/share/icons/breeze /usr/share/icons/breeze-dark -name "$name" 2>/dev/null)
  done
  gtk-update-icon-cache -f /usr/share/icons/breeze >/dev/null 2>&1 || true
  gtk-update-icon-cache -f /usr/share/icons/breeze-dark >/dev/null 2>&1 || true
fi

echo "==> KDE global theme (Parametral görünümü Sistem Ayarları'nda)"
install -d /usr/share/plasma/look-and-feel
rm -rf /usr/share/plasma/look-and-feel/org.parametral.desktop
cp -r "$SRC/branding/kde/look-and-feel/org.parametral.desktop" \
      /usr/share/plasma/look-and-feel/org.parametral.desktop

echo "==> start icon (our logo, over Breeze's start-here-kde)"
install -Dm644 "$SRC/branding/icons/parametral-start.svg" \
  /usr/share/icons/hicolor/scalable/apps/parametral-start.svg
while IFS= read -r f; do
  [ -f "$f.orig" ] || cp "$f" "$f.orig"
  cp "$SRC/branding/icons/parametral-start.svg" "$f"
done < <(find /usr/share/icons/breeze -name 'start-here-kde*.svg' 2>/dev/null)


echo "==> Konsole (markalı profil + renk şeması)"
install -d /usr/share/konsole
install -m644 "$SRC/branding/kde/konsole/Parametral.colorscheme" /usr/share/konsole/
install -m644 "$SRC/branding/kde/konsole/Parametral.profile" /usr/share/konsole/

echo "==> 'Parametral görünümüne dön' (users may change everything, this is the way back)"
install -Dm755 "$SRC/branding/kde/parametral-reset-look.sh" /usr/local/bin/parametral-reset-look
install -d /usr/share/applications
cat > /usr/share/applications/parametral-reset-look.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Parametral görünümüne dön
Comment=Renkleri, simgeleri, imleci ve duvar kağıdını Parametral varsayılanına döndür
Exec=/usr/local/bin/parametral-reset-look
Icon=parametral-start
Terminal=false
Categories=Settings;
EOF

echo "==> first-login hook (launcher icon + wallpaper per account)"
install -Dm755 "$SRC/branding/kde/parametral-first-login.sh" \
  /usr/local/bin/parametral-first-login
install -d /etc/xdg/autostart
cat > /etc/xdg/autostart/parametral-first-login.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Parametral first login
Exec=/usr/local/bin/parametral-first-login
OnlyShowIn=KDE;
NoDisplay=true
X-KDE-autostart-after=panel
EOF

echo "==> per-user defaults (applied to every human account that exists)"
for home in /home/*; do
  [ -d "$home" ] || continue
  user="$(basename "$home")"
  [ "$user" = "lost+found" ] && continue
  id "$user" >/dev/null 2>&1 || continue

  cfg="$home/.config"
  install -d -o "$user" -g "$user" -m 0700 "$cfg"

  # palette: append the [Colors:*] groups (KConfig lets the last section win)
  touch "$cfg/kdeglobals"
  if ! grep -q '^ColorScheme=Parametral' "$cfg/kdeglobals"; then
    cat "$SRC/branding/kde/kdeglobals-snippet.ini" >> "$cfg/kdeglobals"
  fi

  # Dolphin: compact, readable, follows the system palette
  cat > "$cfg/dolphinrc" <<'EOF'
[DetailsMode]
PreviewSize=32

[General]
Version=203
ViewPropsTimestamp=2026,11,19,20,0,0

[MainWindow]
MenuBar=Disabled

[KDE]
SingleClickOpens=false

[CompactMode]
FontSize=12

[IconsMode]
PreviewSize=48
EOF

  chown -R "$user:$user" "$cfg"
  echo "    $user: palette + dolphin"
done

echo "==> done — the palette and wallpaper take effect at next login"
