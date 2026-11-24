-- Parametral OS — Hyprland session entry.
--
-- Hyprland 0.57 reads Lua. The session is split the way CachyOS splits its own: one concern per
-- file, so a setting has one obvious home and a btrfs snapshot of /etc/parametral/hypr is still a
-- complete undo. Nothing here starts a shell — shell.lua does, and it starts Noctalia.

local here = "/etc/parametral/hypr/"

for _, module in ipairs({
    "variables",
    "environment",
    "monitors",
    "inputs",
    "appearance",
    "binds",
    "windowrules",
    "workspaces",
    "shell",
}) do
    dofile(here .. module .. ".lua")
end
