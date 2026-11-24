-- Keys. The shell is Noctalia, so the panel binds are its IPC rather than our own QML.

local ipc = "noctalia msg "

hl.bind(mod .. " + Return", hl.dsp.exec_cmd("konsole"))
hl.bind(mod .. " + E",      hl.dsp.exec_cmd("dolphin"))
hl.bind(mod .. " + Q",      hl.dsp.window.close())
hl.bind(mod .. " + M",      hl.dsp.exit())

-- shell panels
hl.bind(mod .. " + Space", hl.dsp.exec_cmd(ipc .. "panel-toggle launcher"))
hl.bind(mod .. " + S",     hl.dsp.exec_cmd(ipc .. "panel-toggle control-center"))
hl.bind(mod .. " + comma", hl.dsp.exec_cmd(ipc .. "settings-toggle"))
hl.bind(mod .. " + L",     hl.dsp.exec_cmd(ipc .. "session lock"))
hl.bind("ALT + Tab",       hl.dsp.exec_cmd(ipc .. "window-switcher hold"))
hl.bind("ALT + SHIFT + Tab", hl.dsp.exec_cmd(ipc .. "window-switcher hold reverse"))

-- media and brightness: Noctalia owns the OSD
hl.bind("XF86AudioRaiseVolume",  hl.dsp.exec_cmd(ipc .. "volume-up"))
hl.bind("XF86AudioLowerVolume",  hl.dsp.exec_cmd(ipc .. "volume-down"))
hl.bind("XF86AudioMute",         hl.dsp.exec_cmd(ipc .. "volume-mute"))
hl.bind("XF86MonBrightnessUp",   hl.dsp.exec_cmd(ipc .. "brightness-up"))
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd(ipc .. "brightness-down"))

-- focus and workspaces
hl.bind(mod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mod .. " + down",  hl.dsp.focus({ direction = "down" }))

for i = 1, 5 do
    hl.bind(mod .. " + " .. i,         hl.dsp.focus({ workspace = i }))
    hl.bind(mod .. " + SHIFT + " .. i, hl.dsp.window.move({ workspace = i }))
end

-- TEMPORARY debug binds (removed before commit): exercise the session from the keyboard, since
-- `hyprctl dispatch exec` is broken in this Lua build and a root shell is not in the session.
hl.bind("SUPER + SHIFT + P", hl.dsp.exec_cmd("/usr/bin/pkdiag"))
hl.bind("SUPER + SHIFT + N", hl.dsp.exec_cmd("notify-send 'Parametral' 'Bildirim testi'"))
