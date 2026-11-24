// Parametral dock layout.
//
// Shipped inside the look-and-feel package, so a fresh account (or "Apply" in System
// Settings → Global Theme) gets this instead of Plasma's default bar: a tall bottom dock
// with the gauge launcher, icon-only tasks, tray and clock.
//
// What this build actually honours, measured on Plasma 6.5 (Arch, 2026-11):
//   panel.height            yes (≈64 px)
//   panel.hiding            yes ("autohide": hidden until the pointer hits the edge)
//   panel.floating          accepted by the API and written to the config, but NOT rendered —
//                           the panel stays edge-to-edge. Do not rely on it for an island look.
//   panel.minimum/maxLength accepted, also not rendered while the panel fills the screen
//   panel.alignment         accepted, no visible effect on a full-width panel
// The two "island" lines are kept because they are harmless here and correct on builds that
// do render floating panels.

var panel = new Panel
var panelScreen = panel.screen

panel.location = "bottom"
panel.hiding = "autohide"

// 3 gridUnits ≈ 56 px at 96 dpi: tall enough for 32 px icons, still a bar and not a slab.
panel.height = 2 * Math.ceil(gridUnit * 3 / 2)

// floating + centred is what makes it read as a dock rather than a window frame edge
panel.floating = true
panel.alignment = "center"

// On ultrawide screens an unconstrained dock runs the whole width and looks like a taskbar
// again, so cap it at 16:9 like the stock template does with 21:9.
var geo = screenGeometry(panelScreen)
var maximumWidth = Math.ceil(geo.height * (16 / 9))
if (geo.formFactor === "horizontal" && geo.width > maximumWidth) {
    panel.minimumLength = maximumWidth
    panel.maximumLength = maximumWidth
}

panel.addWidget("org.kde.plasma.kickoff")
panel.addWidget("org.kde.plasma.icontasks")
panel.addWidget("org.kde.plasma.marginsseparator")
panel.addWidget("org.kde.plasma.systemtray")
panel.addWidget("org.kde.plasma.digitalclock")

// Wallpaper: ours, through the image plugin.
var desktopsArray = desktopsForActivity(currentActivity());
for (var j = 0; j < desktopsArray.length; j++) {
    desktopsArray[j].wallpaperPlugin = 'org.kde.image';
    desktopsArray[j].currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    desktopsArray[j].writeConfig("Image", "/usr/share/wallpapers/Parametral/contents/images/2560x1440.png");
}
