#!/usr/bin/env bash
# 76-xdg-defaults — make Parametral the default look for every account on the image.
#
# Per-user KDE config (~/.config/kdeglobals) overrides these, which is what we want: a user
# who changes the theme keeps their choice, and a fresh account gets ours. Written to
# /etc/xdg because KConfig reads it as the fallback layer.
#
# Desktop and appearance come from the installer:
#   PARAMETRAL_DESKTOP=kde|hyprland|both (default kde)
#   PARAMETRAL_APPEARANCE=dark|light     (default dark)
set -eu

[ "${1:-}" = "--help" ] && {
  echo "usage: [PARAMETRAL_DESKTOP=kde|hyprland|both] [PARAMETRAL_APPEARANCE=dark|light] 76-xdg-defaults.sh"
  exit 0
}

DESKTOP="${PARAMETRAL_DESKTOP:-kde}"
case "${PARAMETRAL_APPEARANCE:-dark}" in
  light) SCHEME=ParametralLight; PLASMA_STYLE=breeze ;;
  dark)  SCHEME=Parametral;      PLASMA_STYLE=breeze-dark ;;
  *)     echo "PARAMETRAL_APPEARANCE must be dark or light" >&2; exit 2 ;;
esac

# KDE uses its own Breeze icons; the Hyprland edition ships Papirus because it reads better on
# a dark Wayland surface and Breeze's monochrome symbolic set is tuned for Plasma's own widgets.
# `both` follows the primary session (Hyprland), which is the one the installer preselects.
case "$DESKTOP:${PARAMETRAL_APPEARANCE:-dark}" in
  hyprland:light|both:light)
    ICON_THEME=Papirus;     GTK_THEME=adw-gtk3;      CURSOR_THEME=Parametral ;;
  hyprland:dark|both:dark)
    ICON_THEME=Papirus-Dark; GTK_THEME=adw-gtk3-dark; CURSOR_THEME=Parametral ;;
  *:light)
    ICON_THEME=breeze;      GTK_THEME=Breeze;        CURSOR_THEME=breeze ;;
  *)
    ICON_THEME=breeze-dark; GTK_THEME=Breeze-Dark;   CURSOR_THEME=breeze ;;
esac

echo "==> /etc/xdg defaults (görünüm: $SCHEME)"

install -d /etc/xdg /etc/gtk-3.0 /etc/gtk-4.0

cat > /etc/xdg/kdeglobals <<EOF
[General]
ColorScheme=$SCHEME
font=Noto Sans,10,-1,5,50,0,0,0,0,0
fixed=Noto Sans Mono,10,-1,5,50,0,0,0,0,0
menuFont=Noto Sans,10,-1,5,50,0,0,0,0,0
toolBarFont=Noto Sans,10,-1,5,50,0,0,0,0,0
smallestReadableFont=Noto Sans,8,-1,5,50,0,0,0,0,0

[KDE]
LookAndFeelPackage=org.parametral.desktop
widgetStyle=Breeze
SingleClick=false

[Icons]
Theme=$ICON_THEME

[Mouse]
cursorSize=24
EOF

cat > /etc/xdg/kcminputrc <<'EOF'
[Mouse]
cursorSize=24
EOF

cat > /etc/xdg/plasmarc <<EOF
[Theme]
name=$PLASMA_STYLE
EOF

cat > /etc/xdg/konsolerc <<'EOF'
[Desktop Entry]
DefaultProfile=Parametral.profile
EOF

# Splash: our boot screen (look-and-feel package carries contents/splash)
cat > /etc/xdg/ksplashrc <<'EOF'
[KSplash]
Theme=org.parametral.desktop
Engine=none
EOF

# Lock screen: the greeter renders "wallpaper" from this image path. Set here so every
# account gets our background without touching Breeze's lockscreen QML.
cat > /etc/xdg/kscreenlockerrc <<'EOF'
[Daemon]
Autolock=false

[Greeter][Wallpaper][org.kde.image][General]
Image=/usr/share/wallpapers/Parametral/contents/images/2560x1440.png
EOF

for ini in /etc/gtk-3.0/settings.ini /etc/gtk-4.0/settings.ini; do
  cat > "$ini" <<EOF
[Settings]
gtk-theme-name=$GTK_THEME
gtk-icon-theme-name=$ICON_THEME
gtk-cursor-theme-name=$CURSOR_THEME
gtk-cursor-theme-size=24
gtk-font-name=Noto Sans 10
gtk-application-prefer-dark-theme=$([ "${PARAMETRAL_APPEARANCE:-dark}" = dark ] && echo 1 || echo 0)
EOF
done

# Default pointer: the Parametral cursor in the Hyprland edition, stock Breeze in KDE.
install -d /usr/share/icons/default
printf '[Icon Theme]\nInherits=%s\n' "$CURSOR_THEME" > /usr/share/icons/default/index.theme

echo "==> done"
