#!/usr/bin/env bash
# parametral-first-login — one-shot per-user setup for the desktop identity.
#
# Runs from /etc/xdg/autostart on the first KDE login and then leaves a marker. Kept as a
# script (not baked config) because the launcher applet only exists after Plasma has
# created its default panel for that account.
set -eu

marker="${XDG_CONFIG_HOME:-$HOME/.config}/parametral/.first-login-done"
[ -f "$marker" ] && exit 0
mkdir -p "$(dirname "$marker")"

cfg="${XDG_CONFIG_HOME:-$HOME/.config}"
applets="$cfg/plasma-org.kde.plasma.desktop-appletsrc"

# 1. launcher icon: find the kickoff applet and set its icon
if [ -f "$applets" ]; then
  cid="$(awk -F'[][]' '/^\[Containments\]\[[0-9]+\]\[Applets\]\[[0-9]+\]$/{split($0,a,"]["); split(a[3],b,"]"); id=b[1]} /^plugin=org\.kde\.plasma\.kickoff$/{print id}' "$applets" | head -1)"
  if [ -n "$cid" ]; then
    cont="$(awk -F'[][]' '/^\[Containments\]\[[0-9]+\]\[Applets\]\[[0-9]+\]$/{split($0,a,"]["); split(a[2],c,"]"); cid=c[1]} /^plugin=org\.kde\.plasma\.kickoff$/{print cid}' "$applets" | head -1)"
    kwriteconfig6 --file "$applets" \
      --group Containments --group "${cont:-2}" --group Applets --group "$cid" \
      --group Configuration --group General --key icon parametral-start 2>/dev/null || true
  fi
fi

# 2. wallpaper (the look-and-feel package sets the palette)
if command -v plasma-apply-wallpaperimage >/dev/null 2>&1; then
  plasma-apply-wallpaperimage /usr/share/wallpapers/Parametral/contents/images/2560x1440.png >/dev/null 2>&1 || true
fi

# 3. Konsole: our profile by default
if command -v konsole >/dev/null 2>&1; then
  kwriteconfig6 --file konsolerc --group Desktop\ Entry --key DefaultProfile Parametral.profile 2>/dev/null || true
fi

# 4. no screen locking on a fresh install: it interrupts the first session
kwriteconfig6 --file kscreenlockerrc --group Daemon --key Autolock false 2>/dev/null || true

date -u +%FT%TZ > "$marker"
