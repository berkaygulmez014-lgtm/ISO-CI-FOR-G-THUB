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

# ISO acilabilmesi icin initramfs icinde archiso hook sart. Yoksa ISO hic boot etmez:
# bu kontrol olmadan bozuk ISO yayinladik.
# DIKKAT: /tmp/work altinda IKI initramfs var — airootfs/boot/icindeki (pacstrapin standart
# linux paketinin urettigi, archiso hooku YOK) ve iso/arch/boot/icindeki (mkarchiso nun
# urettigi, ISOyu acan). Ilkini kontrol edersen yanlis negatif alirsin (v0.1.13 boyle dustu).
# Bu yuzden bulunan TUM initramfsleri dene: en az biri archiso hooku tasimali.
mapfile -t IRS < <(find /tmp/work -name 'initramfs-linux.img' 2>/dev/null)
[ "${#IRS[@]}" -gt 0 ] || { echo "HATA: initramfs bulunamadi" >&2; exit 1; }
echo "--- teshis: lsinitcpio=$(command -v lsinitcpio || echo YOK) ---"
ok=0
for IR in "${IRS[@]}"; do
  echo "--- $IR ($(stat -c %s "$IR") bayt) ---"
  lsinitcpio -l "$IR" 2>&1 | grep -iE "archiso|error|command not found" | head -5 || true
  if lsinitcpio -l "$IR" 2>/dev/null | grep -qi archiso; then
    echo "KONTROL OK: archiso hook var -> $IR"
    ok=1
    break
  fi
done
[ "$ok" = 1 ] || { echo "HATA: hicbir initramfs icinde archiso hook yok — bu ISO acilmaz (denenen: ${IRS[*]})" >&2; exit 1; }

# GitHub Release tek dosyada 2 GiB siniri koyuyor; ISO ~2,4 GB oldugu icin boluyoruz.
cd /build/out
iso="$(ls *.iso | head -1)"
echo "ISO: $iso  $(stat -c %s "$iso") bayt"
sha256sum "$iso" > "${iso}.sha256"
split -b 1900M -d -a 2 "$iso" "${iso}.part"
rm -f "$iso"
ls -lh
cat *.sha256
'
