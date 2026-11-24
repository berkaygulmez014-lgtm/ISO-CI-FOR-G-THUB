-- Default palette for a session that was copied without the installer.
--
-- install/desktop/hyprland.sh rewrites this file with the appearance the user chose
-- (dark or light). The values are projections of branding/tokens.json, never a second
-- source of truth: change tokens.json and regenerate, or run the installer again.

return {
  appearance = "dark",
  palette = {
    graphite = "0b0f14ff",
    surface  = "12171eff",
    card     = "1a2029ff",
    amber    = "e0a93bff",
    edge     = "2a323cff",
    text     = "e9e4d8ff",
  },
  wallpaper = "/usr/share/wallpapers/Parametral/contents/images/2560x1440.png",
  gtk_theme = "adw-gtk3-dark",
  icon_theme = "Papirus-Dark",
}
