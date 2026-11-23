#!/usr/bin/env bash
# ISO'yu privileged archlinux konteynerinde üretir.
# Profil /tmp/p'ye kopyalanır: bind-mount izin sorunları ve releng kirliliği önlenir.
set -euo pipefail

docker run --rm --privileged -v "$PWD":/build -w /build archlinux:latest bash -c '
set -euo pipefail
pacman -Syu --noconfirm --needed archiso

REL=/usr/share/archiso/configs/releng
rm -rf /tmp/p /tmp/work
cp -a /build/iso /tmp/p

# önyükleme yapılandırmaları relengden
for d in syslinux efiboot grub; do
  if [ -d "$REL/$d" ]; then cp -a "$REL/$d" /tmp/p/; fi
done
if [ -f "$REL/pacman.conf" ]; then cp -a "$REL/pacman.conf" /tmp/p/; fi

# releng etc: ÇAKIŞMASIZ birleştir — repodaki dosyalarımız kazanır
if [ -d "$REL/airootfs/etc" ]; then
  mkdir -p /tmp/p/airootfs/etc
  cp -an "$REL/airootfs/etc/." /tmp/p/airootfs/etc/ 2>/dev/null || true
fi

echo "=== mkinitcpio drop-in ==="
cat /tmp/p/airootfs/etc/mkinitcpio.conf.d/archiso.conf
grep -q archiso /tmp/p/airootfs/etc/mkinitcpio.conf.d/archiso.conf || { echo "HATA: archiso hook yok"; exit 1; }

sed -i "s/Arch Linux install medium/PARAMETRAL OS/" /tmp/p/syslinux/*.cfg 2>/dev/null || true
sed -i "s/Arch Linux install medium/PARAMETRAL OS/" /tmp/p/efiboot/loader/entries/*.conf 2>/dev/null || true
chmod +x /tmp/p/profiledef.sh /tmp/p/airootfs/root/customize_airootfs.sh

mkdir -p /build/out
mkarchiso -v -w /tmp/work -o /build/out /tmp/p
ls -lh /build/out
'
