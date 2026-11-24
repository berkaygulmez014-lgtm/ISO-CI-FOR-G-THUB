-- Look of the windows themselves: amber active border, graphite inactive edge, soft shadows.
-- The gaps match the bar's margin so windows do not sit flush against a floating bar.

hl.config({
    general = {
        gaps_in     = 6,
        gaps_out    = 14,
        border_size = 2,
        col = {
            active_border   = colour("amber"),
            inactive_border = colour("edge"),
        },
        layout        = "dwindle",
        allow_tearing = false,
    },

    decoration = {
        rounding       = 14,
        rounding_power = 2,
        active_opacity   = 1.0,
        inactive_opacity = 0.97,
        shadow = {
            enabled      = true,
            range        = 20,
            render_power = 3,
            color        = 0x66000000,
        },
        blur = {
            enabled  = true,
            size     = 6,
            passes   = 2,
            vibrancy = 0.08,
        },
    },

    animations = { enabled = true },

    dwindle = {
        -- 0.57 dropped `pseudotile`; only the keys the stub lists are accepted
        preserve_split = true,
        smart_split    = true,
    },

    misc = {
        force_default_wallpaper  = 0,
        disable_hyprland_logo    = true,
        disable_splash_rendering = true,
        focus_on_activate        = true,
    },
})

hl.curve("param", { type = "bezier", points = { {0.2, 0.9}, {0.2, 1} } })
hl.curve("soft",  { type = "bezier", points = { {0.35, 1.2}, {0.3, 1} } })

hl.animation({ leaf = "global",     enabled = true, speed = 8, bezier = "param" })
hl.animation({ leaf = "windows",    enabled = true, speed = 5, bezier = "param" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 4, bezier = "param", style = "popin 92%" })
hl.animation({ leaf = "border",     enabled = true, speed = 8, bezier = "param" })
hl.animation({ leaf = "fade",       enabled = true, speed = 6, bezier = "param" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 5, bezier = "soft"  })
