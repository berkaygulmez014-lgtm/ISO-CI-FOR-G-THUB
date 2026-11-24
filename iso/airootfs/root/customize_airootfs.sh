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
mkinitcpio -P || echo "UYARI: mkinitcpio basarisiz"

# ---------------------------------------------------------------- 2. SDDM (giriş ekranı)
echo "==> sddm teması (install/65-branding.sh ile aynı)"
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
sed -i 's/^CheckSpace/#CheckSpace/' /etc/pacman.conf
echo "==> install/74-desktop.sh (PARAMETRAL_DESKTOP=both, primary=parametral)"
bash "$SRC/install/74-desktop.sh"

echo "==> install/45-apps.sh (tarayıcı, konsole, dolphin, gwenview, okular, ark, spectacle)"
bash "$SRC/install/45-apps.sh" || echo "UYARI: 45-apps.sh basarisiz — temel uygulamalar eksik olabilir"

# ---------------------------------------------------------------- 6. ev dizini sahipliği
chown -R parametral:parametral /home/parametral 2>/dev/null || true

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
  kurulum   : henüz yok — bu ISO test içindir

EOF

echo "[customize] bitti"
