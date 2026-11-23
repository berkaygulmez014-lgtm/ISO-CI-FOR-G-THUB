#!/usr/bin/env bash
# Parametral OS — archiso profili
iso_name="parametral-os"
iso_label="PARAMETRAL_$(date +%Y%m)"
iso_publisher="Parametral OS"
iso_application="Parametral OS Live — Arch + Nix, AI'ın işletebildiği ama sahiplenemediği sistem"
iso_version="$(date +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
bootmodes=('bios.syslinux' 'uefi.systemd-boot')
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '12')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/etc/gshadow"]="0:0:400"
  ["/root"]="0:0:750"
  ["/root/customize_airootfs.sh"]="0:0:755"
)
