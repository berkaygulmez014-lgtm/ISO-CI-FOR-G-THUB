# Panel theme (work in progress — NOT wired into the installer)

Goal: draw the dock as a rounded, translucent island instead of a full-width strip, by giving
`widgets/panel-background.svg` transparent padding and 9-slice margins.

State of the attempt: Plasma 6.5 does not pick up the margins from this SVG and tiles the
whole 64x64 canvas across the panel (visible as a repeated rounded-rect grid). Two variants
were tried; the second removed `hint-tile-center`, which did not change the result. The
theme is therefore left out of `install/75-desktop.sh` so nobody ships a broken panel.

What is missing: the exact hint conventions this Plasma build expects (the stock
`default/widgets/panel-background.svgz` uses margins at 4 px plus separate `mask-*`
elements for the shadow). Reproducing that file's structure, rather than a fresh minimal one,
is the way forward.

Until then the dock is: 64 px, centred content, amber icons, autohide — and the supported way
to get a floating island is Plasma's own per-panel "Floating" toggle in Panel Settings.
