#!/usr/bin/env bash
# ISO kapanmadan önce çalışır: kullanıcı, servisler, marka.
set -euo pipefail

# --- canlı kullanıcı
useradd -m -g users -G wheel,audio,video,optical,storage,input -s /bin/bash parametral
echo 'parametral:parametral' | chpasswd
echo 'root:parametral' | chpasswd
echo 'parametral ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/10-parametral
chmod 440 /etc/sudoers.d/10-parametral

# --- servisler
systemctl enable NetworkManager.service
systemctl enable lightdm.service
systemctl enable bluetooth.service || true

# --- dil
sed -i 's/^#en_US.UTF-8/en_US.UTF-8/; s/^#tr_TR.UTF-8/tr_TR.UTF-8/' /etc/locale.gen
locale-gen

# --- marka dosyaları
install -d -m 755 /usr/share/backgrounds
[ -f /usr/share/backgrounds/parametral.png ] || true

# --- XFCE varsayılanları (yeni kullanıcı için skel zaten kopyalandı)
install -d -m 755 /etc/xdg/xfce4/xfconf/xfce-perchannel-xml
printf '%s\n' \
'<?xml version="1.0" encoding="UTF-8"?>' \
'<channel name="xsettings" version="1.0">' \
'  <property name="Net" type="empty">' \
'    <property name="ThemeName" type="string" value="Materia-dark"/>' \
'    <property name="IconThemeName" type="string" value="Papirus-Dark"/>' \
'  </property>' \
'</channel>' > /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml

# --- varsayılan uygulamalar
cat > /etc/xdg/xfce4/helpers.rc <<'EOF'
TerminalEmulator=xfce4-terminal
WebBrowser=firefox
FileManager=thunar
EOF

fc-cache -f >/dev/null 2>&1 || true

# --- karşılama notu
cat > /etc/motd <<'EOF'

  PARAMETRAL OS  ·  live
  ─────────────────────────────────────────────
  kullanıcı : parametral   şifre: parametral
  root      : parametral
  ağ        : nmcli device wifi list   /  nmtui
  kurulum   : henüz yok — bu ISO test içindir

EOF

echo "[customize] bitti"
