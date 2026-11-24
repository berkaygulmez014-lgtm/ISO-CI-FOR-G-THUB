// Parametral polkit agent — the dialog that asks a human for permission.
//
// Without this, `pkexec` in the Hyprland session has nobody to ask. KDE ships its own agent;
// this session needs ours.
//
// It MUST start as a child of the graphical session (the `hyprland.start` handler in
// parametral.lua). Launched from a systemd user unit or a root shell it has no XDG_SESSION_ID,
// registers for the wrong subject, and pkexec answers "No authentication agent found".
// Verified in the VM: pkcheck --allow-user-interaction returns rc=0 with the right password.
//
// Flow handling: polkit hands out a *new* flow after a failed attempt. The flow is therefore
// assigned in onFlowChanged (not bound), and the window follows the flow rather than isActive —
// binding to `isActive` left the window open with no request, and missing the retry flow left
// pkcheck waiting until it timed out.

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Services.Polkit
import "Theme.js" as Theme

ShellRoot {
    id: root

    PolkitAgent {
        id: agent
        path: "/org/parametral/PolkitAgent"
    }

    property var flow: null
    property string password: ""
    property string feedback: ""

    // diagnostics: "is the agent registered, and does it have a request?"
    IpcHandler {
        target: "polkitstatus"
        function report(): string {
            return "registered=" + agent.isRegistered
                 + " active=" + agent.isActive
                 + " flow=" + (root.flow ? "yes" : "no")
        }
    }

    function submitNow(): void {
        if (!root.flow) { root.feedback = "istek yok"; return }
        if (root.password === "") { root.feedback = "şifre boş"; return }
        root.feedback = "denetleniyor…"
        root.flow.submit(root.password)
    }

    Connections {
        target: agent
        function onFlowChanged() {
            root.flow = agent.flow
            root.password = ""
            root.feedback = ""
            input.text = ""
            if (root.flow) input.forceActiveFocus()
        }
    }

    PanelWindow {
        id: window
        visible: root.flow !== null
        anchors { top: true; bottom: true; left: true; right: true }
        color: "transparent"
        exclusiveZone: 0
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

        // key handling inside a layer-shell focused TextInput proved unreliable: window-level
        // shortcuts are the path that actually fires every time
        Shortcut { sequence: "Return"; onActivated: root.submitNow() }
        Shortcut { sequence: "Enter"; onActivated: root.submitNow() }
        Shortcut { sequence: "Escape"; onActivated: if (root.flow) root.flow.cancelAuthenticationRequest() }

        onVisibleChanged: if (visible) input.forceActiveFocus()

        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0.02, 0.03, 0.04, 0.62)
        }

        Rectangle {
            id: card
            anchors.centerIn: parent
            width: 420
            height: column.implicitHeight + 30
            radius: 16
            color: Theme.bg
            border.color: Theme.edge
            border.width: 1

            Column {
                id: column
                x: 15
                y: 15
                width: card.width - 30
                spacing: 10

                Row {
                    spacing: 10

                    Item {
                        width: 30
                        height: 30
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

                    Column {
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                            text: "Yetki isteği"
                            color: Theme.text
                            font.pixelSize: 15
                            font.bold: true
                        }
                        Text {
                            text: "Parametral OS · polkit"
                            color: Theme.faint
                            font.pixelSize: 10
                        }
                    }
                }

                Text {
                    width: parent.width
                    text: root.flow ? root.flow.message : ""
                    color: Theme.muted
                    font.pixelSize: Theme.fontBody
                    wrapMode: Text.WordWrap
                }

                // polkit's own failure text ("Sorry, that didn't work") arrives on the retry flow
                Text {
                    width: parent.width
                    visible: root.flow !== null && root.flow.supplementaryMessage !== ""
                    text: root.flow ? root.flow.supplementaryMessage : ""
                    color: root.flow && root.flow.supplementaryIsError ? Theme.danger : Theme.muted
                    font.pixelSize: Theme.fontMeta
                    wrapMode: Text.WordWrap
                }

                Rectangle {
                    width: parent.width
                    height: 42
                    radius: Theme.radiusSmall
                    color: Theme.card
                    border.color: input.activeFocus ? Theme.edge : Theme.hairline
                    border.width: 1

                    TextInput {
                        id: input
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        verticalAlignment: TextInput.AlignVCenter
                        color: Theme.text
                        font.pixelSize: 14
                        echoMode: TextInput.Password
                        focus: true
                        selectByMouse: true
                        onTextChanged: root.password = text
                        onAccepted: root.submitNow()

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: input.text === ""
                            text: "şifre"
                            color: Theme.faint
                            font.pixelSize: 14
                        }
                    }
                }

                Text {
                    width: parent.width
                    visible: root.feedback !== ""
                    text: root.feedback
                    color: Theme.faint
                    font.pixelSize: 10
                }

                Row {
                    width: parent.width
                    spacing: 8
                    layoutDirection: Qt.RightToLeft

                    Rectangle {
                        width: 96
                        height: 34
                        radius: 9
                        color: okArea.containsMouse ? Theme.cardHover : Theme.amber

                        Text {
                            anchors.centerIn: parent
                            text: "Onayla"
                            color: Theme.amberInk
                            font.pixelSize: Theme.fontBody
                            font.bold: true
                        }

                        MouseArea {
                            id: okArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.submitNow()
                        }
                    }

                    Rectangle {
                        width: 96
                        height: 34
                        radius: 9
                        color: cancelArea.containsMouse ? Theme.card : "transparent"
                        border.color: Theme.hairline
                        border.width: 1

                        Text {
                            anchors.centerIn: parent
                            text: "İptal"
                            color: Theme.muted
                            font.pixelSize: Theme.fontBody
                        }

                        MouseArea {
                            id: cancelArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: if (root.flow) root.flow.cancelAuthenticationRequest()
                        }
                    }
                }
            }
        }
    }
}
