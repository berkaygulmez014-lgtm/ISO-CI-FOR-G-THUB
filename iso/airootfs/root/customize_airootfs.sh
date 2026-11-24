#!/usr/bin/env bash
# ISO kapanmadan önce çalışır: marka (plymouth + SDDM + Plasma), kullanıcı, servisler.
# Marka kaynağı: parametral-os reposunun branding/ + assets/ ağacı (ISO içine
# /opt/parametral-branding olarak kopyalandı). Sıra, arkadaşın install/65-branding.sh
# ve install/75-desktop.sh dosyalarındaki sırayla aynı tutuldu.
set -euo pipefail
SRC=/opt/parametral-branding

# ---------------------------------------------------------------- plymouth (açılış)
echo "==> plymouth teması"
install -d /usr/share/plymouth/themes/parametral
cp -r "$SRC/branding/plymouth/parametral/." /usr/share/plymouth/themes/parametral/
plymouth-set-default-theme parametral || echo "UYARI: plymouth-set-default-theme basarisiz"
mkinitcpio -P || echo "UYARI: mkinitcpio basarisiz — splash initramfs'e girmedi"

# ---------------------------------------------------------------- SDDM (giriş ekranı)
echo "==> SDDM teması"
install -d /usr/share/sddm/themes/parametral
cp -r "$SRC/branding/sddm/parametral/." /usr/share/sddm/themes/parametral/
install -d /etc/sddm.conf.d
cat > /etc/sddm.conf.d/10-parametral.conf <<'EOF'
[Theme]
Current=parametral

[General]
Numlock=on
HaltCommand=/usr/bin/systemctl poweroff
RebootCommand=/usr/bin/systemctl reboot
EOF

# ---------------------------------------------------------------- duvar kağıtları
echo "==> duvar kağıtları"
install -d /usr/share/wallpapers/Parametral/contents/images
for size in 2560x1440 2560x1440-light 1920x1080 1920x1080-light 1280x800 1280x800-light; do
  install -m 0644 "$SRC/branding/wallpapers/$size.png" \
    "/usr/share/wallpapers/Parametral/contents/images/$size.png"
done
cat > /usr/share/wallpapers/Parametral/metadata.json <<'EOF'
{"KPlugin": {"Id": "Parametral", "Name": "Parametral"}, "X-KDE-PluginInfo-Name": "Parametral"}
EOF
if [ -f "$SRC/branding/hypr/parametral-wallpaper" ]; then
  install -Dm 0755 "$SRC/branding/hypr/parametral-wallpaper" /usr/local/bin/parametral-wallpaper
fi

# ---------------------------------------------------------------- renk şeması
echo "==> renk şeması"
install -d /usr/share/color-schemes
install -m 0644 "$SRC/branding/kde/Parametral.colors" /usr/share/color-schemes/Parametral.colors
install -m 0644 "$SRC/branding/kde/ParametralLight.colors" /usr/share/color-schemes/ParametralLight.colors

# ---------------------------------------------------------------- imleç
echo "==> imleç teması"
if [ -d "$SRC/branding/cursors/Parametral" ]; then
  rm -rf /usr/share/icons/Parametral
  cp -r "$SRC/branding/cursors/Parametral" /usr/share/icons/Parametral
fi

# ---------------------------------------------------------------- uygulama ikonları
echo "==> ikonlar"
if [ -d "$SRC/branding/icons/apps" ]; then
  for svg in "$SRC/branding/icons/apps"/*.svg; do
    [ -f "$svg" ] || continue
    name="$(basename "$svg")"
    while IFS= read -r target; do
      cp "$svg" "$target"
    done < <(find /usr/share/icons/breeze /usr/share/icons/breeze-dark -name "$name" 2>/dev/null)
  done
fi
install -Dm 0644 "$SRC/branding/icons/parametral-start.svg" \
  /usr/share/icons/hicolor/scalable/apps/parametral-start.svg
while IFS= read -r f; do
  cp "$SRC/branding/icons/parametral-start.svg" "$f"
done < <(find /usr/share/icons/breeze -name 'start-here-kde*.svg' 2>/dev/null)

# ---------------------------------------------------------------- KDE global tema
echo "==> KDE global tema"
install -d /usr/share/plasma/look-and-feel
rm -rf /usr/share/plasma/look-and-feel/org.parametral.desktop
cp -r "$SRC/branding/kde/look-and-feel/org.parametral.desktop" \
  /usr/share/plasma/look-and-feel/org.parametral.desktop

# ---------------------------------------------------------------- Konsole
echo "==> Konsole"
install -d /usr/share/konsole
install -m 0644 "$SRC/branding/kde/konsole/Parametral.colorscheme" /usr/share/konsole/
install -m 0644 "$SRC/branding/kde/konsole/Parametral.profile" /usr/share/konsole/

# ---------------------------------------------------------------- görünüme dön / ilk oturum
echo "==> yardımcı betikler"
install -Dm 0755 "$SRC/branding/kde/parametral-reset-look.sh" /usr/local/bin/parametral-reset-look
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

install -Dm 0755 "$SRC/branding/kde/parametral-first-login.sh" /usr/local/bin/parametral-first-login
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

# ---------------------------------------------------------------- skel (canlı kullanıcının evi)
echo "==> kullanıcı varsayılanları"
SKEL=/etc/skel/.config
install -d "$SKEL"

cat > "$SKEL/kdeglobals" <<'EOF'
[General]
ColorScheme=Parametral
LookAndFeelPackage=org.parametral.desktop

[KDE]
widgetStyle=Breeze
SingleClick=false
EOF
if [ -f "$SRC/branding/kde/kdeglobals-snippet.ini" ]; then
  cat "$SRC/branding/kde/kdeglobals-snippet.ini" >> "$SKEL/kdeglobals"
fi

printf '[Theme]\nname=breeze-dark\n' > "$SKEL/plasmarc"
printf '[KSplash]\nTheme=org.parametral.desktop\n' > "$SKEL/ksplashrc"
printf '[Daemon]\nAutolock=false\nAutolockTimeout=0\n' > "$SKEL/kscreenlockerrc"
printf '[Desktop Entry]\nDefaultProfile=Parametral.profile\n' > "$SKEL/konsolerc"
cat > "$SKEL/dolphinrc" <<'EOF'
[DetailsMode]
PreviewSize=32

[MainWindow]
MenuBar=Disabled

[KDE]
SingleClickOpens=false

[CompactMode]
FontSize=12

[IconsMode]
PreviewSize=48
EOF
install -d "$SKEL/gtk-3.0"
cat > "$SKEL/gtk-3.0/settings.ini" <<'EOF'
[Settings]
gtk-theme-name=Breeze-Dark
gtk-icon-theme-name=breeze-dark
gtk-cursor-theme-name=breeze_cursors
gtk-font-name=Inter 10.5
gtk-application-prefer-dark-theme=1
EOF

# ---------------------------------------------------------------- canlı kullanıcı
echo "==> canlı kullanıcı"
useradd -m -g users -G wheel,audio,video,optical,storage,input -s /bin/bash parametral
echo 'parametral:parametral' | chpasswd
echo 'root:parametral' | chpasswd
echo 'parametral ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/10-parametral
chmod 440 /etc/sudoers.d/10-parametral

# ---------------------------------------------------------------- servisler
echo "==> servisler"
systemctl enable NetworkManager.service
systemctl enable sddm.service
systemctl disable lightdm.service 2>/dev/null || true
systemctl enable bluetooth.service || true

# ---------------------------------------------------------------- dil
sed -i 's/^#en_US.UTF-8/en_US.UTF-8/; s/^#tr_TR.UTF-8/tr_TR.UTF-8/' /etc/locale.gen
locale-gen

# ---------------------------------------------------------------- logolar
install -d /usr/share/backgrounds /usr/share/pixmaps
if [ -f "$SRC/assets/parametral-mark-512.png" ]; then
  install -m 0644 "$SRC/assets/parametral-mark-512.png" /usr/share/pixmaps/parametral-logo.png
fi
install -m 0644 "$SRC/branding/wallpapers/1920x1080.png" /usr/share/backgrounds/parametral.png

fc-cache -f >/dev/null 2>&1 || true

# ---------------------------------------------------------------- karşılama notu
cat > /etc/motd <<'EOF'

  PARAMETRAL OS  ·  live
  ─────────────────────────────────────────────
  masaüstü  : KDE Plasma (Parametral görünümü) · SDDM girişi
  kullanıcı : parametral   şifre: parametral
  root      : parametral
  ağ        : nmcli device wifi list   /  nmtui
  kurulum   : henüz yok — bu ISO test içindir

EOF

echo "[customize] bitti"
