// GENERATED FILE — do not edit. Source: branding/tokens.json, generator: scripts/gen_theme.py
.pragma library


// ---- dark (default) -------------------------------------------------------
var bg = "#0B0F14"
var surface = "#12171E"
var card = "#1A2029"
var cardHover = "#222B36"
var text = "#E9E4D8"
var muted = "#9AA4B2"
var faint = "#7C8592"
var line = "#2A323C"
var amber = "#E0A93B"
var amberInk = "#1A150A"
var primaryText = "#E0A93B"
var onPrimary = "#1A150A"
var danger = "#D66056"
var dangerInk = "#1A0B09"
var ok = "#7EAE68"
var okInk = "#0B0F14"
var edgeAlpha = 0.22
var hairlineAlpha = 0.14
var selectionTint = 0.07

// ---- light ----------------------------------------------------------------
var lightBg = "#EFE7D9"
var lightSurface = "#F4EFE6"
var lightCard = "#EAE2D5"
var lightCardHover = "#EFE2C8"
var lightText = "#1E2228"
var lightMuted = "#5C5852"
var lightFaint = "#625D55"
var lightLine = "#CFC3AD"
var lightPrimary = "#B8862B"
var lightPrimaryText = "#8A5F14"
var lightOnPrimary = "#1A150A"
var lightDanger = "#A2564A"
var lightDangerInk = "#FFFFFF"
var lightOk = "#4F7A3F"
var lightOkInk = "#FFFFFF"
var lightEdgeAlpha = 0.28
var lightHairlineAlpha = 0.18
var lightSelectionTint = 0.1

// ---- metrics --------------------------------------------------------------
var radiusTick = 1
var radiusRow = 8
var radiusPanel = 12
var radiusPill = 999
var gap = 8
var pad = 16
var barHeight = 40
var barTopGap = 6
var barSideGap = 8
var barSideGapWide = 12
var barPad = 10
var clusterGap = 6
var icon = 16
var panelWidth = 420
var panelWidthWide = 480
var panelPad = 16
var panelRow = 40
var panelHeader = 32
var launcherWidth = 520
var launcherInput = 48
var launcherRow = 36
var launcherMaxHeight = 480
var launcherGap = 8
var shadowY = 8
var shadowBlur = 24
var shadowAlpha = 0.08
var motionHover = 120
var motionPanel = 180
var motionEase = [0.2, 0, 0, 1]
var fontDisplay = 26
var fontTitle = 17
var fontBody = 13
var fontMeta = 11
var lineDisplay = 32
var lineTitle = 24
var lineBody = 20
var lineMeta = 16

// ---- type -----------------------------------------------------------------
var familyBody = "Inter"
var familyMono = "IBM Plex Mono"

// derived: the translucent strokes the shell uses everywhere
var edge = "rgba(224, 169, 59, " + edgeAlpha + ")"
var hairline = "rgba(154, 164, 178, " + hairlineAlpha + ")"
var selection = "rgba(224, 169, 59, " + selectionTint + ")"
var lightEdge = "rgba(184, 134, 43, " + lightEdgeAlpha + ")"
var lightHairline = "rgba(92, 88, 82, " + lightHairlineAlpha + ")"
var lightSelection = "rgba(184, 134, 43, " + lightSelectionTint + ")"

// compatibility aliases — shell.qml migrates to the explicit names in T6.
// Do not add new uses; the design spec calls the tokens radiusPanel / radiusRow /
// barSideGap / panelRow.
var radius = radiusPanel
var radiusSmall = radiusRow
var barMargin = barSideGap
var rowHeight = panelRow
