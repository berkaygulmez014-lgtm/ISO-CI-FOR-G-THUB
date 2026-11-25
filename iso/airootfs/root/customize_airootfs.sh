#!/usr/bin/env bash
# ISO kapanmadan önce çalışır.
#
# KURAL: marka elle kopyalanmaz. Arkadaşın parametral-os reposunun TAMAMI ISO içine
# /opt/parametral-src olarak gömülür ve onun kendi kurulum betikleri burada çalıştırılır
# (install/74-desktop.sh → desktop/kde.sh + desktop/hyprland.sh → 75-desktop.sh + 76-xdg-defaults.sh).
# Böylece ISO'daki görünüm, o repodaki kurulumun birebir aynısı olur.
set -euo pipefail

SRC=/opt/parametral-src
export SRC
export PARAMETRAL_DESKTOP=both          # arkadaşın "both" modu: iki oturum, birincil Parametral
export PARAMETRAL_APPEARANCE=dark
export PARAMETRAL_USER=parametral

# ---------------------------------------------------------------- 1. plymouth (açılış)
# install/65-branding.sh'in aynı komutları; tek fark /mnt yerine canlı kök.
echo "==> plymouth (install/65-branding.sh ile aynı kaynaklar)"
install -d /usr/share/plymouth/themes/parametral
cp -r "$SRC/branding/plymouth/parametral/." /usr/share/plymouth/themes/parametral/
plymouth-set-default-theme parametral || echo "UYARI: plymouth-set-default-theme basarisiz"
# initramfs'i burada üretiyoruz: mkinitcpio-archiso paket listesinde olduğu için artık
# archiso hook'lari chroot'ta VAR; splash bu sayede initramfs'e giriyor.
# KANIT: mkinitcpio ciktisinda "Running build hook: [archiso]" gorunmeli. Initramfs dosyasinin
# icini sonradan grep'lemek guvenilir DEGIL — mkinitcpio 42 dosyanin basina sikistirilmamis
# kucuk bir cpio koyuyor, govde zstd; zstd -dc dosya ortasindaki frame'i acamaz (v0.1.13-17
# bu yuzden gereksiz yere dustu).
if ! mkinitcpio -P 2>&1 | tee /tmp/mkinitcpio.log; then
  echo "HATA: mkinitcpio basarisiz" >&2; exit 1
fi
grep -q "Running build hook: \[archiso\]" /tmp/mkinitcpio.log || { echo "HATA: archiso hook calismadi — bu ISO acilmaz" >&2; exit 1; }
grep -q "Initcpio image generation successful" /tmp/mkinitcpio.log || { echo "HATA: initramfs uretilmedi" >&2; exit 1; }

# ---------------------------------------------------------------- 2. SDDM (giriş ekranı)
echo "==> sddm teması (install/65-branding.sh ile aynı)"
install -d /usr/share/sddm/themes/parametral
cp -r "$SRC/branding/sddm/parametral/." /usr/share/sddm/themes/parametral/
# SDDM 0.21 Qt6: metadata.desktop yoksa veya QtVersion=6 değilse greeter Qt5 ile açılmaya
# çalışıyor, Qt5 kurulu olmadığı için GİRİŞ EKRANI HİÇ GELMİYOR (siyah ekran). v0.1.11'de
# metadata.desktop yoktu — VM'de görülen siyah ekranın sebebi bu.
[ -f /usr/share/sddm/themes/parametral/metadata.desktop ] || { echo "HATA: sddm metadata.desktop yok" >&2; exit 1; }
grep -q '^QtVersion=6' /usr/share/sddm/themes/parametral/metadata.desktop || { echo "HATA: metadata QtVersion=6 degil" >&2; exit 1; }
grep -q '^MainScript=Main.qml' /usr/share/sddm/themes/parametral/metadata.desktop || { echo "HATA: metadata MainScript yok" >&2; exit 1; }
# Oturum secici (Hyprland / KDE Plasma / Parametral X11 kartlari) temanin icinde olmali.
grep -q 'chosenSession' /usr/share/sddm/themes/parametral/Main.qml || { echo "HATA: tema oturum secici yok" >&2; exit 1; }
# Tekrarlanan oturum girdileri tek karta indirilmeli (v0.1.21): 7 kart -> 3 kart.
grep -q 'sessionCards' /usr/share/sddm/themes/parametral/Main.qml || { echo "HATA: tema oturum tekilleştirmesi yok" >&2; exit 1; }

# KDE panel/başlat menüsü onarımı: plasmashell çökerse/panel hiç kurulmazsa
# oturum açılışında paneli kurar (bkz. /usr/local/bin/parametral-kde-fix).
[ -f /usr/share/parametral/kde-layout.js ] || { echo "HATA: kde-layout.js yok" >&2; exit 1; }
grep -q 'org.kde.plasma.kickoff' /usr/share/parametral/kde-layout.js || { echo "HATA: KDE panelinde başlat menüsü yok" >&2; exit 1; }
grep -q 'writeConfig("icon", "parametral-start")' /usr/share/parametral/kde-layout.js || { echo "HATA: başlat menüsü logo ayari yok" >&2; exit 1; }
grep -q '24-tick dial' "$SRC/branding/icons/parametral-start.svg" || { echo "HATA: parametral-start logosu degismedi" >&2; exit 1; }
chmod 0755 /usr/local/bin/parametral-kde-fix
chmod 0644 /usr/share/parametral/kde-layout.js /etc/xdg/autostart/parametral-kde-fix.desktop

# Panel teması: v0.1.22'ye kadar SVG repoda vardı ama hiç kurulmuyordu — panel
# Breeze yarı saydam kalıyordu. Kendi opak Parametral panelimizi kuruyoruz.
install -d /usr/share/plasma/desktoptheme/Parametral/widgets
cp -r "$SRC/branding/plasma-theme/Parametral/." /usr/share/plasma/desktoptheme/Parametral/
grep -q 'fill-opacity="1"' /usr/share/plasma/desktoptheme/Parametral/widgets/panel-background.svg || { echo "HATA: panel opak degil" >&2; exit 1; }
cat > /etc/xdg/plasmarc <<'EOF'
[Theme]
name=Parametral
EOF
# Masaüstü taslağı (AI işlevi YOK — sadece görsel imza, sonraki sürümlerde tamolanacak)
[ -f /etc/skel/Desktop/parametral-ai-os.desktop ] || { echo "HATA: masaustu taslagi yok" >&2; exit 1; }
chmod 0755 /etc/skel/Desktop/*.desktop
install -d /etc/sddm.conf.d
cat > /etc/sddm.conf.d/10-parametral.conf <<'EOF'
[Theme]
Current=parametral

[General]
# Greeter'ı X11'de tut: Wayland greeter'ı VM'lerde (VirtualBox/VMSVGA) siyah ekran veriyor.
DisplayServer=x11
Numlock=on
HaltCommand=/usr/bin/systemctl poweroff
RebootCommand=/usr/bin/systemctl reboot
EOF

# ---------------------------------------------------------------- 3. dil
sed -i 's/^#en_US.UTF-8/en_US.UTF-8/; s/^#tr_TR.UTF-8/tr_TR.UTF-8/' /etc/locale.gen
grep -q '^tr_TR.UTF-8 UTF-8' /etc/locale.gen || echo 'tr_TR.UTF-8 UTF-8' >> /etc/locale.gen
locale-gen

# ---------------------------------------------------------------- 4. canlı kullanıcı
# ÖNEMLİ: 75-desktop.sh ve hyprland.sh /home/* üzerinde döner. Kullanıcı onlardan önce
# oluşturulmazsa marka hiçbir eve yazılmaz.
# ÖNEMLİ 2: birincil grup kullanıcıyla aynı adı taşımalı (install -g "$user") — bu yüzden
# -g users DEĞİL, useradd'in kendi grubunu kurmasına izin veriyoruz.
echo "==> canlı kullanıcı"
useradd -m -G wheel,audio,video,optical,storage,input -s /bin/bash parametral
echo 'parametral:parametral' | chpasswd
echo 'root:parametral' | chpasswd
echo 'parametral ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/10-parametral
chmod 440 /etc/sudoers.d/10-parametral

systemctl enable NetworkManager.service
systemctl enable bluetooth.service || true

# ---------------------------------------------------------------- 5. ARKADAŞIN KURULUM BETİKLERİ
# pacman chroot içinde statvfs yapamadığı için "not enough free disk space" diyip duruyor
# (45 MiB'lik kurulumu bile reddetti). Bu kontrolü kapatıyoruz; diskte 113 GB boş.
# Ayrıca chroot'ta /etc/pacman.d/gnupg yazılamadığı için "keyring is not writable" çıkıyor;
# kurulumlar boyunca imza kontrolünü kapatıp sonra dosyayı geri koyuyoruz.
cp -a /etc/pacman.conf /etc/pacman.conf.iso-bak
sed -i 's/^CheckSpace/#CheckSpace/; s/^SigLevel.*/SigLevel = Never/' /etc/pacman.conf
echo "==> install/74-desktop.sh (PARAMETRAL_DESKTOP=both, primary=parametral)"
bash "$SRC/install/74-desktop.sh"

echo "==> install/45-apps.sh (tarayıcı, konsole, dolphin, gwenview, okular, ark, spectacle)"
bash "$SRC/install/45-apps.sh" || echo "UYARI: 45-apps.sh basarisiz — temel uygulamalar eksik olabilir"

# ---------------------------------------------------------------- 5b. SDDM oturum varsayılanı
# 74-desktop.sh oturumu "parametral" yazıyor. VM'de Hyprland (aquamarine) siyah ekran
# verebildiği için VM tespit edilirse varsayılanı Plasma (X11) yap: greeter açılır açılmaz
# girilebilen bir oturum olsun. Gerçek donanımda davranış değişmez.
install -d /etc/sddm.conf.d /var/lib/sddm
cat > /usr/local/bin/parametral-vm-session <<'EOF'
#!/usr/bin/env bash
# Varsayılan SDDM oturumu: VM ise plasmax11 (X11), değilse dokunma.
set -u
vm=0
if [ -r /sys/class/dmi/id/product_name ] && grep -qiE 'virtualbox|vmware|qemu|kvm|innotek' /sys/class/dmi/id/product_name; then vm=1; fi
if [ -r /sys/class/dmi/id/sys_vendor ] && grep -qiE 'virtualbox|vmware|qemu|innotek' /sys/class/dmi/id/sys_vendor; then vm=1; fi
if command -v lspci >/dev/null 2>&1 && lspci 2>/dev/null | grep -qiE 'VMware SVGA|VirtualBox|QXL|virtio.*(VGA|GPU)|Bochs'; then vm=1; fi
[ "$vm" = 1 ] || exit 0
# Yazılım GL: hipervizörde donanım GL yok, Mesa'nın llvmpipe'ı kullanılsın
cat > /etc/environment <<ENV
LIBGL_ALWAYS_SOFTWARE=1
QT_QUICK_BACKEND=software
ENV
sess=""
for cand in parametral-x11 plasmax11 plasma; do
  if [ -f "/usr/share/xsessions/$cand.desktop" ] || [ -f "/usr/share/wayland-sessions/$cand.desktop" ]; then sess="$cand"; break; fi
done
[ -n "$sess" ] || exit 0
cat > /etc/sddm.conf.d/30-vm-session.conf <<CONF
[Autologin]
Session=$sess
CONF
# SDDM once state.conf [Last] Session'i kullanir; orada parametral (Hyprland) yaziyor.
# VM'de o oturum acilmadigi icin greeter giris sonrasi geri donuyordu — burayi da duzelt.
# Yalniz ILK acilista: kullanici greeter'daki masaustu kartlarindan Hyprland'i secip
# giris yaparsa SDDM secimi state.conf'a yazar; her acilista X11'e geri cevirmiyoruz.
if [ ! -f /var/lib/sddm/.vm-default-seeded ]; then
  if [ -f /var/lib/sddm/state.conf ]; then
    sed -i "s/^Session=.*/Session=$sess/" /var/lib/sddm/state.conf
  fi
  : > /var/lib/sddm/.vm-default-seeded
fi
echo "parametral: VM algilandi, varsayilan oturum $sess (secim greeter'da degistirilebilir)"
EOF
chmod 0755 /usr/local/bin/parametral-vm-session
cat > /etc/systemd/system/parametral-vm-session.service <<'EOF'
[Unit]
Description=Parametral: VM icin varsayilan SDDM oturumu (Plasma X11)
Before=sddm.service
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/parametral-vm-session

[Install]
WantedBy=multi-user.target
EOF
systemctl enable parametral-vm-session.service

# SDDM son kullanıcı/oturum: greeter kullanıcı alanını "parametral" ile doldursun
cat > /var/lib/sddm/state.conf <<'EOF'
[Last]
Session=parametral
User=parametral
EOF
chown sddm:sddm /var/lib/sddm/state.conf 2>/dev/null || true
chmod 0640 /var/lib/sddm/state.conf

# ---------------------------------------------------------------- 5c. X11 yedek oturum (VM)
# Plasma 6.8 X11 oturumunu kaldırdı; Hyprland ve Plasma Wayland hipervizörde (VirtualBox
# VMSVGA, 3D kapalı) DRM/KMS yüzünden açılmıyor ve SDDM'ye geri düşüyor. XFCE tabanlı bu
# oturum X11 ile her VM'de açılır; palet ve duvar kağıdı aynı Parametral markası.
cat > /usr/share/xsessions/parametral-x11.desktop <<'EOF'
[Desktop Entry]
Name=Parametral X11
Comment=XFCE tabanli X11 oturumu — Wayland acilmazsa bunu secin
Exec=startxfce4
TryExec=startxfce4
Type=Application
DesktopNames=XFCE
EOF
chmod 0644 /usr/share/xsessions/parametral-x11.desktop
install -d /etc/xdg/xfce4/xfconf/xfce-perchannel-xml
cat > /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="backdrop" type="empty">
    <property name="screen0" type="empty">
      <property name="monitorVirtual-1" type="empty">
        <property name="workspace0" type="empty">
          <property name="last-image" type="string" value="/usr/share/backgrounds/parametral.png"/>
          <property name="image-style" type="int" value="5"/>
        </property>
      </property>
    </property>
  </property>
</channel>
EOF
cat > /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xsettings" version="1.0">
  <property name="Net" type="empty">
    <property name="ThemeName" type="string" value="Adwaita-dark"/>
    <property name="IconThemeName" type="string" value="Papirus-Dark"/>
  </property>
</channel>
EOF
# VM'de (X11) yazılım GL: /etc/environment yalnız VM algılanınca yazılır (parametral-vm-session);
# gerçek donanımda yazılım GL'e düşürmek istemiyoruz.
install -d /usr/share/xsessions

# ---------------------------------------------------------------- 6. ev dizini sahipliği
mkdir -p /home/parametral/Desktop
cp -f /etc/skel/Desktop/. /home/parametral/Desktop/ 2>/dev/null || true
chown -R parametral:parametral /home/parametral 2>/dev/null || true

# pacman.conf'u geri koy (canlı sistemde imza kontrolü ve disk kontrolü normal çalışsın)
if [ -f /etc/pacman.conf.iso-bak ]; then
  mv -f /etc/pacman.conf.iso-bak /etc/pacman.conf
fi

# pacman önbelleği squashfs'e girmesin (kurulum sırasında indirilen ~150 MB)
pacman -Scc --noconfirm >/dev/null 2>&1 || true
rm -rf /var/cache/pacman/pkg/* 2>/dev/null || true

fc-cache -f >/dev/null 2>&1 || true

# ---------------------------------------------------------------- 7. karşılama notu
cat > /etc/motd <<'EOF'

  PARAMETRAL OS  ·  live
  ─────────────────────────────────────────────
  oturumlar : Parametral (Hyprland + Noctalia) · Plasma (KDE)
  kullanıcı : parametral   şifre: parametral
  root      : parametral
  ağ        : nmcli device wifi list   /  nmtui
  oturum    : parametral-desktop default parametral|plasma
  VM notu   : sanal makinede varsayılan oturum "Parametral X11" (XFCE) seçilir;
              Wayland oturumları (Parametral/Plasma) VM'de açılmayabilir
  kurulum   : henüz yok — bu ISO test içindir

EOF

echo "[customize] bitti"
