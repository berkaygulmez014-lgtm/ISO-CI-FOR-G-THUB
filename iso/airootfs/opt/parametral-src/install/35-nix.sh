#!/usr/bin/env bash
# 35-nix.sh — Nix as *the* package manager: multi-user daemon, flakes, signatures.
#
# Nix is what makes an AI-managed system safe to experiment on: installs are additive,
# never touch /usr, and roll back by switching a profile generation. pacman still owns
# the base system; everything an application needs comes from Nix.
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
mountpoint -q /mnt || { echo "/mnt is not mounted — run 20-disk.sh first" >&2; exit 1; }

echo "==> store (Arch ships the binaries, but /nix must exist before the daemon can init)"
install -d -m 0755 /mnt/nix
if [ ! -d /mnt/nix/store ]; then
  arch-chroot /mnt nix-store --init
fi

echo "==> daemon configuration"
install -d -m 0755 /mnt/etc/nix
cat > /mnt/etc/nix/nix.conf <<'EOF'
# Parametral OS — Nix as the application package manager.
experimental-features = nix-command flakes
sandbox = true
require-sigs = true
# every local account may *use* the store; only root and the gateway user may *add* to it
allowed-users = *
trusted-users = root parametral
max-jobs = auto
cores = 0
EOF

echo "==> daemon service"
arch-chroot /mnt systemctl enable nix-daemon.service

echo "==> profile shim (login shells and the AI runtime both need it)"
cat > /mnt/etc/profile.d/nix.sh <<'EOF'
# shellcheck shell=sh
if [ -e "${HOME}/.nix-profile/etc/profile.d/nix.sh" ]; then
  . "${HOME}/.nix-profile/etc/profile.d/nix.sh"
fi
EOF
chmod 0644 /mnt/etc/profile.d/nix.sh

echo "==> first-party CLI"
install -Dm0755 "$(dirname "$0")/../bin/parametral-nix" /mnt/usr/local/bin/parametral-nix

echo "==> smoke test (cache-only, no build)"
if arch-chroot /mnt nix --version >/dev/null 2>&1; then
  echo "    nix $(arch-chroot /mnt nix --version 2>/dev/null | awk '{print $3}')"
else
  echo "WARN: nix did not report a version inside the target" >&2
fi
