// Parametral launcher — search + keyboard, our own surface.
//
// Opens on the launcher button or SUPER+Space. Lists desktop entries with their icons, filters
// as you type, Enter launches the selected one, Escape closes.
//
// Selection is a 3 px amber bar plus a 7% tint, not a filled amber row: a full amber block made
// the list look like a set of buttons. Rows are a fixed height in a clipped ListView — letting a
// ColumnLayout size itself from delegates made the card grow past the bottom of the screen.

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "Theme.js" as Theme

ShellRoot {
    id: root

    readonly property int rowHeight: Theme.rowHeight
    readonly property int maxRows: 8

    property string query: ""
    property int selected: 0
    property var entries: []

    Process {
        id: lister
        command: ["sh", "-c",
            "for f in /usr/share/applications/*.desktop /home/*/.local/share/applications/*.desktop; do " +
            "[ -f \"$f\" ] || continue; " +
            "n=$(sed -n 's/^Name=//p' \"$f\" | head -1); " +
            "e=$(sed -n 's/^Exec=//p' \"$f\" | head -1); " +
            "i=$(sed -n 's/^Icon=//p' \"$f\" | head -1); " +
            "h=$(sed -n 's/^NoDisplay=true//p' \"$f\" | head -1); " +
            "[ -z \"$n\" ] && continue; [ -n \"$h\" ] && continue; " +
            "printf '%s\\t%s\\t%s\\n' \"$n\" \"$e\" \"$i\"; done | sort -u"]
        running: true
        stdout: SplitParser {
            onRead: line => {
                const parts = line.split("\t")
                if (parts.length < 2) return
                // `entries.push()` mutates in place and QML never re-evaluates `filtered`;
                // reassigning the array is what actually notifies the bindings.
                const next = root.entries.slice()
                next.push({ name: parts[0], exec: parts[1], icon: parts[2] || "" })
                root.entries = next
            }
        }
    }

    // Icon resolution stays defensive: a missing icon theme must not blank the row.
    function iconFor(name) {
        if (!name) return ""
        try {
            if (name.charAt(0) === "/") return "file://" + name
            const resolved = Quickshell.iconPath(name, true)
            return resolved ? "file://" + resolved : ""
        } catch (e) {
            return ""
        }
    }

    readonly property var filtered: {
        const q = query.toLowerCase().trim()
        const seen = new Set()
        const out = []
        for (const e of entries) {
            const key = e.name.toLowerCase()
            if (seen.has(key)) continue          // same app in /usr/share and ~/.local/share
            if (q !== "" && !key.includes(q)) continue
            seen.add(key)
            out.push(e)
            if (out.length === maxRows) break
        }
        return out
    }

    function launch(entry) {
        if (!entry) return
        const cmd = entry.exec.replace(/%[a-zA-Z]/g, "").trim()
        Quickshell.execDetached(["sh", "-c", cmd])
        Qt.quit()
    }

    PanelWindow {
        id: window
        anchors { top: true; bottom: true; left: true; right: true }
        color: "transparent"
        exclusiveZone: 0
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
        onVisibleChanged: if (visible) input.forceActiveFocus()

        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0.02, 0.03, 0.04, 0.55)

            MouseArea {
                anchors.fill: parent
                onClicked: Qt.quit()
            }
        }

        Rectangle {
            id: card
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.round(parent.height * 0.18)
            width: Math.min(640, parent.width - 80)
            height: column.implicitHeight + 24
            radius: 18
            color: Theme.bg
            border.color: Theme.edge
            border.width: 1

            Column {
                id: column
                width: card.width - 24
                x: 12
                y: 12
                spacing: 8

                // ---- search field -------------------------------------
                Rectangle {
                    width: parent.width
                    height: 48
                    radius: Theme.radiusSmall
                    color: Theme.surface

                    Item {
                        id: mark
                        width: 24
                        height: 24
                        anchors.left: parent.left
                        anchors.leftMargin: 14
                        anchors.verticalCenter: parent.verticalCenter

                        Canvas {
                            anchors.fill: parent
                            onPaint: {
                                const ctx = getContext("2d")
                                ctx.reset()
                                const c = width / 2, r = width * 0.42
                                ctx.strokeStyle = Theme.amber
                                ctx.lineWidth = 1.5
                                ctx.beginPath()
                                for (let i = 0; i < 12; i++) {
                                    const a = (Math.PI * 2 * i) / 12 - Math.PI / 2
                                    ctx.moveTo(c + Math.cos(a) * r * 0.78, c + Math.sin(a) * r * 0.78)
                                    ctx.lineTo(c + Math.cos(a) * r, c + Math.sin(a) * r)
                                }
                                ctx.stroke()
                                ctx.beginPath()
                                ctx.arc(c, c, r * 0.6, 0, Math.PI * 2)
                                ctx.stroke()
                            }
                        }
                    }

                    TextInput {
                        id: input
                        anchors.left: mark.right
                        anchors.leftMargin: 12
                        anchors.right: parent.right
                        anchors.rightMargin: 14
                        anchors.verticalCenter: parent.verticalCenter
                        color: Theme.text
                        font.pixelSize: 17
                        focus: true
                        selectByMouse: true
                        onTextChanged: {
                            root.query = text
                            root.selected = 0
                        }
                        Keys.onDownPressed: root.selected = Math.min(root.selected + 1, root.filtered.length - 1)
                        Keys.onUpPressed: root.selected = Math.max(root.selected - 1, 0)
                        Keys.onReturnPressed: root.launch(root.filtered[root.selected])
                        Keys.onEscapePressed: Qt.quit()

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: input.text === ""
                            text: "Uygulama ara…"
                            color: Theme.faint
                            font.pixelSize: 17
                        }
                    }
                }

                // ---- empty state --------------------------------------
                Item {
                    visible: root.filtered.length === 0
                    width: parent.width
                    height: 96

                    Column {
                        anchors.centerIn: parent
                        spacing: 6

                        Canvas {
                            width: 28
                            height: 28
                            anchors.horizontalCenter: parent.horizontalCenter
                            opacity: 0.5
                            onPaint: {
                                const ctx = getContext("2d")
                                ctx.reset()
                                const c = width / 2, r = width * 0.42
                                ctx.strokeStyle = Theme.muted
                                ctx.lineWidth = 1.4
                                ctx.beginPath()
                                for (let i = 0; i < 12; i++) {
                                    const a = (Math.PI * 2 * i) / 12 - Math.PI / 2
                                    ctx.moveTo(c + Math.cos(a) * r * 0.78, c + Math.sin(a) * r * 0.78)
                                    ctx.lineTo(c + Math.cos(a) * r, c + Math.sin(a) * r)
                                }
                                ctx.stroke()
                                ctx.beginPath()
                                ctx.arc(c, c, r * 0.6, 0, Math.PI * 2)
                                ctx.stroke()
                            }
                        }

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: root.entries.length === 0 ? "Uygulama listesi yüklenemedi" : "Eşleşme yok"
                            color: Theme.muted
                            font.pixelSize: Theme.fontBody
                        }
                    }
                }

                // ---- results ------------------------------------------
                Item {
                    visible: root.filtered.length > 0
                    width: parent.width
                    height: Math.min(root.filtered.length * root.rowHeight, root.maxRows * root.rowHeight)

                    ListView {
                        id: list
                        anchors.fill: parent
                        clip: true
                        model: root.filtered
                        currentIndex: root.selected
                        interactive: false

                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            width: list.width
                            height: root.rowHeight
                            radius: Theme.radiusSmall
                            color: index === root.selected ? Theme.selection
                                 : rowArea.containsMouse ? Theme.surface : "transparent"

                            // the 3 px amber bar is the selection; the tint only supports it
                            Rectangle {
                                width: 3
                                height: 20
                                radius: 1.5
                                anchors.left: parent.left
                                anchors.leftMargin: 2
                                anchors.verticalCenter: parent.verticalCenter
                                color: Theme.amber
                                visible: index === root.selected
                            }

                            Image {
                                id: rowIcon
                                source: root.iconFor(modelData.icon)
                                width: 18
                                height: 18
                                anchors.left: parent.left
                                anchors.leftMargin: 16
                                anchors.verticalCenter: parent.verticalCenter
                                fillMode: Image.PreserveAspectFit
                                visible: source.toString() !== ""
                            }

                            // fallback mark when the entry has no resolvable icon
                            Canvas {
                                width: 10
                                height: 10
                                anchors.left: parent.left
                                anchors.leftMargin: 20
                                anchors.verticalCenter: parent.verticalCenter
                                visible: !rowIcon.visible
                                onPaint: {
                                    const ctx = getContext("2d")
                                    ctx.reset()
                                    ctx.strokeStyle = index === root.selected ? Theme.amber : Theme.faint
                                    ctx.lineWidth = 1.3
                                    ctx.beginPath()
                                    ctx.arc(5, 5, 3.6, 0, Math.PI * 2)
                                    ctx.stroke()
                                }
                            }

                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 44
                                anchors.right: parent.right
                                anchors.rightMargin: 12
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.name
                                color: index === root.selected ? Theme.text : Theme.muted
                                font.pixelSize: 14
                                elide: Text.ElideRight
                            }

                            MouseArea {
                                id: rowArea
                                anchors.fill: parent
                                hoverEnabled: true
                                onEntered: root.selected = index
                                onClicked: root.launch(modelData)
                            }
                        }
                    }

                    // scroll indicator: thin, only when there is more than the card shows
                    Rectangle {
                        width: 2
                        radius: 1
                        color: Theme.amber
                        opacity: 0.55
                        visible: root.entries.length > root.maxRows
                        x: list.width - 2
                        height: Math.max(18, list.height * (list.height / Math.max(list.height, list.contentHeight)))
                        y: list.height > list.contentHeight
                           ? 0
                           : (list.height - height) * (list.contentY / Math.max(1, list.contentHeight - list.height))
                    }
                }

                // ---- footer: keys are mono chips, labels are quiet ----------
                Row {
                    width: parent.width
                    spacing: 12
                    topPadding: 2
                    layoutDirection: Qt.LeftToRight
                    anchors.horizontalCenter: parent.horizontalCenter

                    Repeater {
                        model: [
                            { key: "↵", label: "aç" },
                            { key: "↑↓", label: "seç" },
                            { key: "esc", label: "kapat" }
                        ]

                        Row {
                            required property var modelData
                            spacing: 5

                            Rectangle {
                                width: keyText.implicitWidth + 10
                                height: 18
                                radius: 5
                                color: Theme.surface
                                border.color: Theme.hairline
                                border.width: 1

                                Text {
                                    id: keyText
                                    anchors.centerIn: parent
                                    text: modelData.key
                                    color: Theme.muted
                                    font.pixelSize: 10
                                    font.family: "monospace"
                                }
                            }

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.label
                                color: Theme.faint
                                font.pixelSize: 10
                            }
                        }
                    }
                }
            }
        }
    }
}
