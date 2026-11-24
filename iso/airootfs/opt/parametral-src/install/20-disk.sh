#!/usr/bin/env bash
# 20-disk.sh — partitions, LUKS, btrfs subvolumes, mounts.
#   usage: 20-disk.sh /dev/nvme0n1 [--yes] [--no-luks]
set -Eeuo pipefail
DISK="${1:-}"; shift || true
YES=0; LUKS=1
for arg in "$@"; do
  case "$arg" in
    --yes) YES=1 ;;
    --no-luks) LUKS=0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ -n "$DISK" ] || { echo "usage: $0 /dev/nvme0n1 [--yes]" >&2; exit 1; }
[ "$YES" = "1" ] || { echo "refusing without --yes (this erases $DISK)" >&2; exit 1; }

PART_ESP="${DISK}1"
PART_ROOT="${DISK}2"
ROOT_DEV="$PART_ROOT"
if [ "$LUKS" = "1" ]; then ROOT_DEV="/dev/mapper/cryptroot"; fi

echo "==> partitioning $DISK"
sgdisk --zap-all "$DISK"
sgdisk --new=1:0:+1G --typecode=1:ef00 --change-name=1:PARAMETRAL-ESP "$DISK"
sgdisk --new=2:0:0   --typecode=2:8309 --change-name=2:PARAMETRAL-ROOT "$DISK"
sgdisk --print "$DISK"
partprobe "$DISK" || true
udevadm settle

echo "==> wiping old signatures"
wipefs -a "$PART_ESP" "$PART_ROOT" 2>/dev/null || true

echo "==> formatting ESP"
mkfs.fat -F32 -n PARAMETRAL "$PART_ESP"

if [ "$LUKS" = "1" ]; then
  echo "==> LUKS2 on $PART_ROOT (you will type this passphrase at every boot)"
  cryptsetup luksFormat --type luks2 --pbkdf argon2id "$PART_ROOT"
  cryptsetup open "$PART_ROOT" cryptroot
fi

echo "==> btrfs"
mkfs.btrfs -f -L parametral "$ROOT_DEV"

mount_opts="compress=zstd:3,noatime,ssd,discard=async,space_cache=v2"
mount "$ROOT_DEV" /mnt
for sub in @ @home @var @snapshots; do
  echo "  subvolume $sub"
  btrfs subvolume create "/mnt/$sub"
done
umount /mnt

echo "==> mounting the tree"
mount -o "$mount_opts,subvol=@" "$ROOT_DEV" /mnt
mkdir -p /mnt/{home,var,.snapshots,boot,etc}
mount -o "$mount_opts,subvol=@home" "$ROOT_DEV" /mnt/home
mount -o "$mount_opts,subvol=@var" "$ROOT_DEV" /mnt/var
mount -o "$mount_opts,subvol=@snapshots" "$ROOT_DEV" /mnt/.snapshots
mount "$PART_ESP" /mnt/boot

# remember the facts the later steps need
mkdir -p /mnt/etc/parametral
{
  echo "PARAMETRAL_DEV=UUID=$(blkid -s UUID -o value "$ROOT_DEV")"
  echo "PARAMETRAL_LUKS=$LUKS"
  echo "PARAMETRAL_LUKS_UUID=$([ "$LUKS" = 1 ] && blkid -s UUID -o value "$PART_ROOT" || echo)"
} > /mnt/etc/parametral/snapshot.env

cat <<EOF

Layout ready:
  ESP        $PART_ESP  → /boot (fat32)
  root       $ROOT_DEV  → btrfs @, @home, @var, @snapshots
  LUKS       $([ "$LUKS" = 1 ] && echo yes || echo "no (development only)")
  snapshot env written to /etc/parametral/snapshot.env

Next: 30-bootstrap.sh
EOF
