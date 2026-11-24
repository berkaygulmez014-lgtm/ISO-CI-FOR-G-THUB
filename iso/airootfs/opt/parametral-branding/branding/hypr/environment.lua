-- Environment handed to every application in the session.

hl.env("XCURSOR_THEME", "Parametral")
hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_THEME", "Parametral")
hl.env("HYPRCURSOR_SIZE", "24")

-- Qt apps follow the same look instead of falling back to Breeze defaults
hl.env("QT_QPA_PLATFORM", "wayland;xcb")
hl.env("QT_QPA_PLATFORMTHEME", "qt6ct")

-- GTK apps follow the installer's appearance answer. `theme` is defined by variables.lua,
-- which parametral.lua loads first.
hl.env("GTK_THEME", theme.gtk_theme)
hl.env("ICON_THEME", theme.icon_theme)

-- Turkish session locale: the bar's date, the lock screen and the apps all read this. Without
-- it Noctalia falls back to English strings and "20 Kasım Cuma" becomes "20 November Friday".
hl.env("LANG", "tr_TR.UTF-8")
hl.env("LC_TIME", "tr_TR.UTF-8")
