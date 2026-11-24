-- Monitor rule for whatever is plugged in.
--
-- scale is pinned to 1, not "auto": with no EDID size (every VM, and some docks) Hyprland's auto
-- picked 2 on a 1280x800 output, which doubles the UI and crops Noctalia's lock surface. Users on
-- a HiDPI panel change this one number (or set it per-output) — the bar scales with it.

hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })
