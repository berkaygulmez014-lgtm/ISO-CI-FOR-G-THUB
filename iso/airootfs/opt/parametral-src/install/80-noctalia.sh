#!/usr/bin/env bash
# 80-noctalia — legacy entry point for the Hyprland + Noctalia session.
#
# Noctalia is part of install/desktop/hyprland.sh now: there is one session entry, one set of
# Lua modules and one place that applies the installer's dark/light answer. This wrapper exists
# so older notes that call 80-noctalia.sh still do the right thing instead of half-installing a
# second shell.
set -Eeuo pipefail

exec bash "$(cd "$(dirname "$0")" && pwd)/desktop/hyprland.sh" "$@"
