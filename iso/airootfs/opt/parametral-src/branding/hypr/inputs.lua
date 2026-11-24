-- Keyboard layout is Turkish: this is a Turkish distribution, and the compose key behaviour of
-- tr is what the users expect. Add "us" as a second layout for guests.

hl.config({
    input = {
        kb_layout    = "tr,us",
        kb_options   = "grp:alt_shift_toggle",
        follow_mouse = 1,
        sensitivity  = 0,
        touchpad = {
            natural_scroll = false,
        },
    },
})
