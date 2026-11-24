-- Window and layer rules.

-- Noctalia's settings window opens as a floating card, not a tiled pane
hl.window_rule({
    match = { class = "dev.noctalia.Noctalia" },
    float = true,
    size = "monitor_w*0.5625 monitor_h*0.85",
})

-- Noctalia animates its own surfaces; Hyprland's layer animations run on top of them and tear
-- panels that reopen while still closing.
hl.layer_rule({
    name = "noctalia-no-anim",
    match = { namespace = "^noctalia-(bar-.+|notification|dock|panel|attached-panel|osd|window-switcher)$" },
    no_anim = true,
})

hl.layer_rule({
    name = "noctalia-blur",
    match = { namespace = "^noctalia-(bar-.+|notification|dock|panel|attached-panel|osd|window-switcher)$" },
    ignore_alpha = 0.5,
    blur = true,
    blur_popups = true,
})

-- If ecosystem.enforce_permissions is ever turned on, these two rules are required:
--   hl.permission("^/usr/bin/noctalia$", "screencopy", "allow")
--   hl.permission("^hl-virtual-keyboard-noctalia$", "keyboard", "allow")
-- They are not applied here because the permission system is off by default.
