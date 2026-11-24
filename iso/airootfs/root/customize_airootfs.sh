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
sess=""
for cand in plasmax11 plasma; do
  if [ -f "/usr/share/xsessions/$cand.desktop" ] || [ -f "/usr/share/wayland-sessions/$cand.desktop" ]; then sess="$cand"; break; fi
done
[ -n "$sess" ] || exit 0
cat > /etc/sddm.conf.d/30-vm-session.conf <<CONF
[Autologin]
Session=$sess
CONF
echo "parametral: VM algilandi, varsayilan oturum $sess"
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

# ---------------------------------------------------------------- 6. ev dizini sahipliği
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
  VM notu   : sanal makinede varsayılan oturum Plasma (X11) seçilir;
              Hyprland istiyorsan SDDM'de "Parametral"i seç
  kurulum   : henüz yok — bu ISO test içindir

EOF

echo "[customize] bitti"
