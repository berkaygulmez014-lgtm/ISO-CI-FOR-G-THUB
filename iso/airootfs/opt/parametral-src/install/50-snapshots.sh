#!/usr/bin/env bash
# 50-snapshots.sh — the rollback net: tool + pacman hooks + first snapshot.
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"

echo "==> installing parametral-snapshot"
install -Dm0755 "$REPO/src/tools/parametral-snapshot" /usr/local/bin/parametral-snapshot
mkdir -p /.snapshots
chmod 0755 /.snapshots

echo "==> pacman hooks (pre-transaction snapshot, post-transaction prune)"
install -Dm0644 "$REPO/install/pacman/90-parametral-snapshot.hook" \
  /etc/pacman.d/hooks/90-parametral-snapshot.hook
install -Dm0644 "$REPO/install/pacman/95-parametral-prune.hook" \
  /etc/pacman.d/hooks/95-parametral-prune.hook

echo "==> keeping /var out of snapshots (logs and caches churn too much)"
grep -q 'subvol=@var' /etc/fstab || echo "WARN: /var is not a separate subvolume; snapshots will grow fast"

echo "==> first snapshot"
parametral-snapshot create install-baseline || {
  echo "WARN: first snapshot failed — check btrfs and /.snapshots" >&2
  exit 1
}
parametral-snapshot list

echo "==> hook check (dry run of the exact command pacman will run)"
PARAMETRAL_DRY_RUN=1 parametral-snapshot create pacman-dryrun
echo "snapshot layer installed"
