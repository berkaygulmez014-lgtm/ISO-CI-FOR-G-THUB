#!/usr/bin/env bash
# 79-hypr — legacy entry point for the Hyprland edition.
#
# The edition moved to install/desktop/hyprland.sh so the installer, the manual path and the
# docs all run the same code. This wrapper stays for older notes and scripts that call 79-hypr.
set -Eeuo pipefail

exec bash "$(cd "$(dirname "$0")" && pwd)/desktop/hyprland.sh" "$@"
