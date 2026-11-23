# Parametral OS — ISO

Arch tabanlı canlı ISO. CI (GitHub Actions) her etikette (tag) ISO üretip **Releases**'e yükler.

```
kullanıcı : parametral     şifre: parametral
ön yükleme: UEFI + BIOS (syslinux / systemd-boot)
masaüstü  : XFCE · Materia-dark · Papirus-Dark · Inter + IBM Plex Mono
marka     : Ölçüm Plakası paleti (amber #E0A93B / zemin #0B0F14)
```

## Nasıl ISO alınır (tarayıcıdan, git gerekmez)

1. **Yeni repo aç:** github.com/new → isim `parametral-os-iso` → **Public** → Create.
2. **Dosyaları yükle:** repo sayfasında *Add file → Upload files*, bu klasörün **içeriğini** sürükle (`.github`, `iso`, `README.md`, `.gitattributes` dahil).
   - `.github` klasörü yüklenmediyse: *Add file → Create new file*, ad alanına `.github/workflows/iso.yml` yaz ve bu repodaki dosyanın içeriğini yapıştır.
3. **Çalıştır:** *Actions* sekmesi → solda `iso` → *Run workflow*. ~20-30 dakika sürer.
4. **İndir:** bitince *Actions → çalışma → Artifacts → parametral-iso* (zip içinde .iso) **veya** *Releases* sayfasından doğrudan ISO.

> Etiketle release: `git tag v0.1.0 && git push --tags` ya da *Releases → Draft a new release → tag `v0.1.0` → Publish*. Etiket push edilince ISO otomatik olarak release'e eklenir.

## Repoyu sonradan public yapmak

Settings → General → en alta in → **Danger Zone** → *Change repository visibility* → **Change to public** → repo adını yazıp onayla.

## GitHub Desktop ile (önerilen, tek tık)

1. GitHub Desktop kur, tarayıcıyla giriş yap (token gerekmez).
2. *File → Add local repository* → bu klasörü seç.
3. Sağ üstte **Publish repository** → **Keep this code private** işaretini **kaldır** → Publish.

## Yerelde üretmek (Linux/Arch)

```bash
sudo pacman -S archiso
cp -r /usr/share/archiso/configs/releng/{syslinux,efiboot,grub,pacman.conf} iso/
chmod +x iso/profiledef.sh iso/airootfs/root/customize_airootfs.sh
sudo mkarchiso -v -w /tmp/work -o out ./iso
```

## Test ederken

- VirtualBox/VMware: yeni VM → ISO'yu tak → 2 GB RAM, 2 vCPU, EFI veya BIOS.
- Canlı sistemde ağ: `nmtui`. Terminal: `Ctrl+Alt+T`.
- Masaüstü gelmezse: `Ctrl+Alt+F2` → `parametral` / `parametral` → `systemctl status lightdm`.

## Kapsam

Bu ISO **canlı test** içindir: masaüstü + marka + ağ. Kurulum yapmaz (calamares henüz yok).
