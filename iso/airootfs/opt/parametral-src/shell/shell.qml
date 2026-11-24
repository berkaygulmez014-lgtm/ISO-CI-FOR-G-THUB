// Parametral Shell — the bar.
//
// Quickshell (QML) on Hyprland. Everything is a file the AI can rewrite, and the whole surface
// is one design language: islands floating over the wallpaper, graphite body, amber edge.
//
// Colours and metrics come from Theme.js, which scripts/gen_theme.py generates from
// branding/tokens.json. Never paste a hex value in here.
//
// Left to right: launcher · workspaces · [space] · status · clock · power. The clock is not the
// brightest thing on the bar: the active workspace is, because that is what the hand is on.
//
// Geometry note: the panel uses PanelWindow.margins (not manual anchors) — anchoring the
// content to the window edge pushed the islands below the screen edge on a small panel.

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Services.SystemTray
import Quickshell.Services.UPower
import Quickshell.Networking
import "Theme.js" as Theme

ShellRoot {
    id: root

    readonly property int wsCount: 5
    property string volumeText: "—"
    property int volumePercent: -1

    Process {
        id: volumeProc
        command: ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]
        running: false
        stdout: StdioCollector {
            onStreamFinished: {
                const match = this.text.match(/Volume:\s*([0-9.]+)/)
                if (this.text.includes("MUTED")) {
                    root.volumeText = "sessiz"
                    root.volumePercent = 0
                } else if (match) {
                    const pct = Math.round(parseFloat(match[1]) * 100)
                    root.volumeText = pct + "%"
                    root.volumePercent = pct
                } else {
                    root.volumeText = "—"
                    root.volumePercent = -1
                }
            }
        }
    }

    Timer {
        interval: 3000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: volumeProc.running = true
    }

    component Island: Rectangle {
        radius: Theme.radius
        color: Theme.surface
        border.color: Theme.edge
        border.width: 1
    }

    // A workspace pill: hover and active must be visibly different — hover is a lift of the
    // body colour with an amber edge, active is the only amber fill on this part of the screen.
    component WsPill: Rectangle {
        id: pill
        property int number: 0
        property bool active: false
        property bool occupied: false

        width: 30
        height: 30
        radius: 9
        color: active ? Theme.amber
             : hover.containsMouse ? Theme.cardHover
             : "transparent"
        border.width: (!active && hover.containsMouse) ? 1 : 0
        border.color: Theme.edge

        Behavior on color { ColorAnimation { duration: 110 } }

        Text {
            anchors.centerIn: parent
            text: pill.number
            color: pill.active ? Theme.amberInk : (pill.occupied ? Theme.text : Theme.faint)
            font.pixelSize: 12
            font.bold: pill.active
        }

        MouseArea {
            id: hover
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: Hyprland.dispatch("workspace " + pill.number)
        }
    }

    PanelWindow {
        id: bar
        anchors.bottom: true
        anchors.left: true
        anchors.right: true

        implicitHeight: Theme.barHeight
        color: "transparent"
        exclusiveZone: 0

        margins {
            left: Theme.barMargin
            right: Theme.barMargin
            bottom: 8
        }

        RowLayout {
            anchors.fill: parent
            spacing: Theme.gap

            // ---- launcher -------------------------------------------------
            Island {
                Layout.preferredWidth: 46
                Layout.fillHeight: true
                color: launcherArea.containsMouse ? Theme.cardHover : Theme.surface

                Canvas {
                    anchors.centerIn: parent
                    width: 26
                    height: 26
                    onPaint: {
                        const ctx = getContext("2d")
                        ctx.reset()
                        const c = width / 2, r = width * 0.42
                        ctx.strokeStyle = Theme.amber
                        ctx.lineWidth = 1.6
                        ctx.beginPath()
                        for (let i = 0; i < 12; i++) {
                            const a = (Math.PI * 2 * i) / 12 - Math.PI / 2
                            ctx.moveTo(c + Math.cos(a) * r * 0.78, c + Math.sin(a) * r * 0.78)
                            ctx.lineTo(c + Math.cos(a) * r, c + Math.sin(a) * r)
                        }
                        ctx.stroke()
                        ctx.beginPath()
                        ctx.arc(c, c, r * 0.62, 0, Math.PI * 2)
                        ctx.stroke()
                        ctx.fillStyle = Theme.amber
                        ctx.beginPath()
                        ctx.arc(c, c, 2.2, 0, Math.PI * 2)
                        ctx.fill()
                    }
                }

                MouseArea {
                    id: launcherArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: Quickshell.execDetached(["/usr/local/bin/parametral-launcher"])
                }
            }

            // ---- workspaces -----------------------------------------------
            Island {
                Layout.preferredWidth: wsRow.implicitWidth + 20
                Layout.fillHeight: true

                Row {
                    id: wsRow
                    anchors.centerIn: parent
                    spacing: 4

                    Repeater {
                        model: root.wsCount

                        WsPill {
                            required property int index
                            number: index + 1
                            readonly property var ws: Hyprland.workspaces.values.find(w => w.id === (index + 1))
                            active: Hyprland.focusedWorkspace?.id === (index + 1)
                            occupied: ws !== undefined
                        }
                    }
                }
            }

            Item { Layout.fillWidth: true }

            // ---- tray ------------------------------------------------------
            Island {
                visible: SystemTray.items.values.length > 0
                Layout.preferredWidth: Math.max(52, trayRow.implicitWidth + 22)
                Layout.fillHeight: true

                Row {
                    id: trayRow
                    anchors.centerIn: parent
                    spacing: 10

                    Repeater {
                        model: SystemTray.items

                        Image {
                            required property var modelData
                            width: 17
                            height: 17
                            source: modelData.icon
                            fillMode: Image.PreserveAspectFit
                            opacity: modelData.status === 1 ? 1.0 : 0.45
                        }
                    }
                }
            }

            // ---- status: speaker glyph + %, battery glyph + %, connectivity dot ----
            Island {
                Layout.preferredWidth: statusRow.implicitWidth + 24
                Layout.fillHeight: true

                Row {
                    id: statusRow
                    anchors.centerIn: parent
                    spacing: 8

                    Item {
                        width: 15
                        height: 15
                        anchors.verticalCenter: parent.verticalCenter

                        Canvas {
                            anchors.fill: parent
                            onPaint: {
                                const ctx = getContext("2d")
                                ctx.reset()
                                ctx.strokeStyle = root.volumePercent === 0 ? Theme.faint : Theme.muted
                                ctx.fillStyle = ctx.strokeStyle
                                ctx.lineWidth = 1.3
                                ctx.beginPath()
                                ctx.moveTo(1.5, 5.5)
                                ctx.lineTo(4.5, 5.5)
                                ctx.lineTo(8, 2.5)
                                ctx.lineTo(8, 12.5)
                                ctx.lineTo(4.5, 9.5)
                                ctx.lineTo(1.5, 9.5)
                                ctx.closePath()
                                ctx.fill()
                                if (root.volumePercent > 0) {
                                    ctx.beginPath()
                                    ctx.arc(8.5, 7.5, 4, -0.9, 0.9)
                                    ctx.stroke()
                                } else {
                                    ctx.beginPath()
                                    ctx.moveTo(10, 5)
                                    ctx.lineTo(14, 10)
                                    ctx.moveTo(14, 5)
                                    ctx.lineTo(10, 10)
                                    ctx.stroke()
                                }
                            }
                        }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.volumeText
                        color: Theme.muted
                        font.pixelSize: Theme.fontMeta
                        font.family: "monospace"
                    }

                    Item {
                        width: 22
                        height: 15
                        anchors.verticalCenter: parent.verticalCenter
                        visible: UPower.displayDevice?.ready ?? false

                        readonly property real level: UPower.displayDevice?.percentage ?? 0

                        Canvas {
                            anchors.fill: parent
                            onPaint: {
                                const ctx = getContext("2d")
                                ctx.reset()
                                const lvl = parent.level
                                const low = lvl < 0.15
                                ctx.strokeStyle = low ? Theme.danger : Theme.muted
                                ctx.lineWidth = 1.2
                                ctx.beginPath()
                                ctx.rect(0.7, 1.5, 17, 12)
                                ctx.stroke()
                                ctx.fillStyle = low ? Theme.danger : Theme.muted
                                ctx.fillRect(2.2, 3, Math.max(1, 13 * lvl), 9)
                                ctx.fillRect(18.6, 5.5, 2, 4)
                            }
                        }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: UPower.displayDevice?.ready ?? false
                        text: Math.round((UPower.displayDevice?.percentage ?? 0) * 100) + "%"
                        color: (UPower.displayDevice?.percentage ?? 1) < 0.15 ? Theme.danger : Theme.muted
                        font.pixelSize: Theme.fontMeta
                        font.family: "monospace"
                    }

                    // connectivity: a dot, no word — "net" said nothing a dot says
                    Rectangle {
                        width: 6
                        height: 6
                        radius: 3
                        anchors.verticalCenter: parent.verticalCenter
                        color: Networking.connectivity === NetworkConnectivity.Full ? Theme.ok
                             : (Networking.connectivity === NetworkConnectivity.Limited
                                || Networking.connectivity === NetworkConnectivity.Portal) ? Theme.amber
                             : Networking.connectivity === NetworkConnectivity.None ? Theme.danger
                             : Theme.faint
                    }
                }
            }

            // ---- clock: deliberately quieter than the amber workspace ---------
            Island {
                Layout.preferredWidth: clockColumn.implicitWidth + 30
                Layout.fillHeight: true
                color: "transparent"
                border.width: 0

                Column {
                    id: clockColumn
                    anchors.centerIn: parent
                    spacing: -1

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: Qt.formatDateTime(clock.date, "HH:mm")
                        color: Theme.text
                        font.pixelSize: 14
                        font.weight: Font.Medium
                        opacity: 0.92
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        // "20 Kasım Cuma": full month, capitalised, same string as the lock screen
                        text: clock.date.toLocaleString(Qt.locale("tr_TR"), "d MMMM dddd")
                        color: Theme.faint
                        font.pixelSize: 10
                    }

                    SystemClock {
                        id: clock
                        precision: SystemClock.Minutes
                    }
                }
            }

            // ---- power -----------------------------------------------------
            Island {
                Layout.preferredWidth: 46
                Layout.fillHeight: true
                color: powerArea.containsMouse ? Theme.cardHover : Theme.surface

                Text {
                    anchors.centerIn: parent
                    text: "⏻"
                    color: powerArea.containsMouse ? Theme.amber : Theme.muted
                    font.pixelSize: 15
                }

                MouseArea {
                    id: powerArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: powerMenu.visible = !powerMenu.visible
                }
            }
        }
    }

    // IPC so a Hyprland keybind can open the menu without a second implementation of it
    IpcHandler {
        target: "powermenu"
        function toggle(): void { powerMenu.visible = !powerMenu.visible }
        function close(): void { powerMenu.visible = false }
        // dev hooks: run fixed commands INSIDE the session (the bar has the session env, a root
        // shell does not). Fixed paths, no arguments — not a general command runner.
        function diag(): void { Quickshell.execDetached(["/usr/bin/pkdiag"]) }
        function agent(): void { Quickshell.execDetached(["qs", "-p", "/usr/share/parametral/shell/polkit.qml"]) }
    }

    // ---- power menu -------------------------------------------------------
    PanelWindow {
        id: powerMenu
        visible: false
        anchors.bottom: true
        anchors.right: true
        margins { right: Theme.barMargin; bottom: 74 }
        implicitWidth: 190
        implicitHeight: 196
        color: "transparent"
        exclusiveZone: -1
        exclusionMode: ExclusionMode.Ignore

        Rectangle {
            anchors.fill: parent
            radius: Theme.radius
            color: Theme.surface
            border.color: Theme.edge
            border.width: 1

            Column {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 4

                Repeater {
                    model: [
                        { label: "Kilitle",        cmd: ["hyprlock", "--config", "/etc/parametral/hypr/hyprlock.conf"] },
                        { label: "Oturumu kapat",  cmd: ["hyprctl", "dispatch", "exit"] },
                        { label: "Yeniden başlat", cmd: ["systemctl", "reboot"] },
                        { label: "Kapat",          cmd: ["systemctl", "poweroff"] }
                    ]

                    Rectangle {
                        required property var modelData
                        width: parent.width
                        height: 42
                        radius: 9
                        color: itemArea.containsMouse ? Theme.cardHover : "transparent"

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.leftMargin: 12
                            text: modelData.label
                            color: (modelData.label === "Kapat" && itemArea.containsMouse) ? Theme.danger : Theme.text
                            font.pixelSize: Theme.fontBody
                        }

                        MouseArea {
                            id: itemArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                powerMenu.visible = false
                                Quickshell.execDetached(modelData.cmd)
                            }
                        }
                    }
                }
            }
        }
    }
}
