#!/usr/bin/env bash
# 30-bootstrap.sh — base system into /mnt: both kernels, btrfs, nix, network.
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
mountpoint -q /mnt || { echo "/mnt is not mounted — run 20-disk.sh first" >&2; exit 1; }

source /mnt/etc/parametral/snapshot.env 2>/dev/null || true

echo "==> pacstrap (main kernel + backup kernel + nix; no desktop yet)"
# The desktop is a choice, not a bootstrap fact: install/74-desktop.sh adds KDE or Hyprland
# after the users exist. Installing Plasma here would make "Hyprland only" a lie (and would
# leave the SDDM session list full of an edition the user did not pick).
pacstrap /mnt \
  base base-devel linux linux-lts linux-firmware \
  btrfs-progs dosfstools e2fsprogs cryptsetup sudo efibootmgr \
  networkmanager openssh vim git less nix \
  python mesa \
  pipewire pipewire-pulse pipewire-alsa wireplumber \
  bluez bluez-utils \
  noto-fonts noto-fonts-emoji

# pacstrap can finish without a resolver inside the target; the desktop step installs packages
# from the chroot and would then fail with "could not resolve host".
[ -f /mnt/etc/resolv.conf ] || cp /etc/resolv.conf /mnt/etc/resolv.conf

echo "==> fstab"
genfstab -U /mnt >> /mnt/etc/fstab
# the snapshot tree must not be auto-snapshotted itself, and /var keeps logs out of @
grep -q 'subvol=/@snapshots' /mnt/etc/fstab || \
  echo "UUID=$(findmnt -no UUID /mnt/.snapshots) /.snapshots btrfs rw,noatime,compress=zstd:3,subvol=@snapshots 0 0" >> /mnt/etc/fstab

if [ "${PARAMETRAL_LUKS:-0}" = "1" ]; then
  echo "cryptroot UUID=${PARAMETRAL_LUKS_UUID} none luks,discard" > /mnt/etc/crypttab
fi

echo "==> hostname / locale / timezone"
echo parametral > /mnt/etc/hostname
sed -i 's/^#en_US.UTF-8/en_US.UTF-8/; s/^#tr_TR.UTF-8/tr_TR.UTF-8/' /mnt/etc/locale.gen
arch-chroot /mnt locale-gen
# the product is Turkish: every date in the bar, lock screen and apps reads LC_TIME
echo "LANG=tr_TR.UTF-8" > /mnt/etc/locale.conf
ln -sf /usr/share/zoneinfo/Europe/Istanbul /mnt/etc/localtime
arch-chroot /mnt hwclock --systohc

echo "==> initramfs for BOTH kernels"
HOOKS_BASE="base udev autodetect microcode modconf kms keyboard keymap consolefont block"
if [ "${PARAMETRAL_LUKS:-0}" = "1" ]; then
  HOOKS="$HOOKS_BASE encrypt filesystems fsck"
else
  HOOKS="$HOOKS_BASE filesystems fsck"
fi
sed -i "s/^HOOKS=.*/HOOKS=($HOOKS)/" /mnt/etc/mkinitcpio.conf
arch-chroot /mnt mkinitcpio -P

echo "==> network"
arch-chroot /mnt systemctl enable NetworkManager

echo "==> nix: signed cache only, sandboxed builds, no daemon for the AI user"
mkdir -p /mnt/etc/nix
cat > /mnt/etc/nix/nix.conf <<'EOF'
experimental-features = nix-command flakes
sandbox = true
require-sigs = true
trusted-users = root parametral
allowed-users = @users
EOF
arch-chroot /mnt systemctl enable nix-daemon

echo "bootstrap done: $(arch-chroot /mnt pacman -Q linux linux-lts | tr '\n' ' ')"
