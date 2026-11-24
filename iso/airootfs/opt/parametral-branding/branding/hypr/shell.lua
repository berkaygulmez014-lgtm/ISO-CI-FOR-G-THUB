-- What starts with the session.
--
-- The shell is Noctalia (MIT, noctalia.dev). Our own Quickshell surfaces in shell/ are kept in
-- the tree as experiments and are deliberately NOT started: two bars would fight for the same
-- exclusive zone, and Noctalia's polkit agent is the one that answers pkexec.

hl.on("hyprland.start", function()
    -- The wallpaper is ours and it carries the bar plate, so the file has to be the screen's own
    -- resolution (a 2560 file on a 1280 screen shrinks the plate with it). parametral-wallpaper
    -- picks the matching asset, writes current.png and then execs noctalia.
    hl.exec_cmd("/usr/local/bin/parametral-wallpaper")

    -- first-party app: the approval window the AI layer talks to
    hl.exec_cmd("/usr/local/bin/parametral-approvals")
end)
