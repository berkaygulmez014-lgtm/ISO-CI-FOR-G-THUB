// Parametral SDDM theme v2 — soft cream, watermark, and a complete login.
//
// Rules this file obeys (learned the hard way):
//  * no fixed root width/height: SDDM sizes the root to the screen, and every size is
//    derived from `u`, so 1024x768 and 4K both lay out correctly
//  * no QtQuick.Controls Button (contentItem is not assignable in the greeter) —
//    buttons are Rectangle + Text + MouseArea
//  * no graphical-effect imports: the halo is a PNG, the rest is plain QtQuick
//  * every optional feature (user chips, caps-lock hint) degrades quietly instead of
//    breaking the whole theme
//  * unversioned Qt6 imports: SDDM 0.21 runs sddm-greeter-qt6, and a versioned/py-qt5 import
//    aborts the greeter -> black screen with no cursor (seen in a VirtualBox run of 0.1.11)
import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    property real u: Math.min(width / 1920, height / 1080)
    property bool busy: false
    property string errorText: ""
    property int selectedUser: -1
    property int chosenSession: -1

    property bool dark: true

    // palettes — amber accent is shared, everything else flips with `dark`
    property color cBg:         dark ? "#0d0f12" : "#f7f2e8"
    property color cInk:        dark ? "#f2ede4" : "#1a1a1e"
    property color cSoft:       dark ? "#b9b1a4" : "#5c5852"
    property color cMuted:      dark ? "#8e877b" : "#8a8378"
    property color cMuted2:     dark ? "#7d766b" : "#a09788"
    property color cCard:       dark ? "#191d24" : "#fffefb"
    property color cCardBorder: dark ? "#343b45" : "#e4dbca"
    property color cField:      dark ? "#101317" : "#ffffff"
    property color cFieldBorder:dark ? "#2e343c" : "#e6ddcc"
    property color cChip:       dark ? "#20242a" : "#f1e8d8"
    property color cChipBorder: dark ? "#333a43" : "#e2d6bf"
    property color cBorder:     dark ? "#31373f" : "#cfc3ad"
    property color cHover:      dark ? "#242a31" : "#efe2c8"
    property color cError:      dark ? "#e08a7a" : "#a2564a"
    property color cBusy:       dark ? "#8a6a33" : "#d8b071"
    property color cDot:        dark ? "#f7e6c2" : "#5a4718"
    property color cOnAccent:   dark ? "#1a1509" : "#231c10"
    property string bgSource:   dark ? "background-dark.png" : "background.png"
    property string glowSource: dark ? "logo-glow-dark.png" : "logo-glow.png"

    color: root.cBg

    Image {
        anchors.fill: parent
        source: root.bgSource
        fillMode: Image.PreserveAspectCrop
    }

    // ── Turkish date without depending on the greeter's locale ───────────────
    function trDate(d) {
        var days = ["Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi"]
        var months = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
                      "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
        return days[d.getDay()] + ", " + d.getDate() + " " + months[d.getMonth()]
    }

    // ── clock / date, top-left ───────────────────────────────────────────────
    Column {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.leftMargin: 64 * root.u
        anchors.topMargin: 52 * root.u
        spacing: 0

        Text {
            id: clock
            text: Qt.formatTime(new Date(), "HH:mm")
            color: root.cInk
            font.family: "DejaVu Sans"
            font.weight: Font.ExtraLight
            font.pixelSize: 56 * root.u
        }
        Text {
            id: dateText
            text: root.trDate(new Date())
            color: root.cMuted
            font.family: "DejaVu Sans"
            font.weight: Font.Light
            font.pixelSize: 16 * root.u
        }
    }

    Timer {
        interval: 15000
        running: true
        repeat: true
        onTriggered: {
            clock.text = Qt.formatTime(new Date(), "HH:mm")
            dateText.text = root.trDate(new Date())
        }
    }

    // ── controls, bottom-right ───────────────────────────────────────────────
    // Text buttons, not glyphs: the greeter's font may not carry ⏻/⟳, and a missing
    // glyph is a box on the login screen.
    Row {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: 56 * root.u
        anchors.bottomMargin: 40 * root.u
        spacing: 22 * root.u

        Text {
            text: root.dark ? "Açık tema" : "Koyu tema"
            color: themePointer.containsMouse ? root.cInk : root.cSoft
            font.family: "DejaVu Sans"
            font.weight: Font.Light
            font.pixelSize: 15 * root.u

            MouseArea {
                id: themePointer
                anchors.fill: parent
                anchors.margins: -6 * root.u
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.dark = !root.dark
            }
        }

        Text {
            text: "Kapat"
            color: offPointer.containsMouse ? root.cInk : root.cSoft
            font.family: "DejaVu Sans"
            font.weight: Font.Light
            font.pixelSize: 15 * root.u

            MouseArea {
                id: offPointer
                anchors.fill: parent
                anchors.margins: -6 * root.u
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: sddm.powerOff()
            }
        }

        Text {
            text: "Yeniden"
            color: rebootPointer.containsMouse ? root.cInk : root.cSoft
            font.family: "DejaVu Sans"
            font.weight: Font.Light
            font.pixelSize: 15 * root.u

            MouseArea {
                id: rebootPointer
                anchors.fill: parent
                anchors.margins: -6 * root.u
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: sddm.reboot()
            }
        }
    }

    // ── footer, bottom-left ──────────────────────────────────────────────────
    Text {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.leftMargin: 64 * root.u
        anchors.bottomMargin: 42 * root.u
        text: "Parametral OS"
        color: root.cMuted
        font.family: "DejaVu Sans"
        font.weight: Font.Light
        font.pixelSize: 16 * root.u
    }

    // ── oturum listesini toplayan görünmez tekne ─────────────────────────────
    Item {
        id: sessionCollector
        visible: false
        Repeater {
            model: sessionModel
            delegate: Item {
                Component.onCompleted: root.noteSession(index, "" + model.name)
            }
        }
    }
    Timer { id: rebuildTimer; interval: 0; onTriggered: root.buildSessionCards() }

    // ── centre column ────────────────────────────────────────────────────────
    Column {
        id: centre
        anchors.centerIn: parent
        spacing: 16 * root.u
        opacity: 0

        NumberAnimation {
            id: entrance
            target: centre
            property: "opacity"
            from: 0
            to: 1
            duration: 420
            easing.type: Easing.OutCubic
        }

        Component.onCompleted: entrance.start()

        Item {
            width: 150 * root.u
            height: 150 * root.u
            anchors.horizontalCenter: parent.horizontalCenter

            Image {
                anchors.centerIn: parent
                source: root.glowSource
                width: parent.width * 1.55
                height: parent.height * 1.55
                fillMode: Image.PreserveAspectFit
                smooth: true
            }
            Image {
                anchors.fill: parent
                source: "logo-large.png"
                fillMode: Image.PreserveAspectFit
                smooth: true
            }
        }

        Text {
            text: "Parametral"
            anchors.horizontalCenter: parent.horizontalCenter
            color: root.cInk
            font.family: "DejaVu Sans"
            font.weight: Font.ExtraLight
            font.pixelSize: 52 * root.u
            font.letterSpacing: 1.2
        }

        // ── masaüstü seçimi: Hyprland / KDE Plasma / Parametral X11 ──────────
        // Greeter açılır açılmaz neye gireceğini gösterir; seçim SDDM tarafından
        // state.conf'a yazılır, sonraki açılışta hatırlanır.
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8 * root.u

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "MASAÜSTÜ SEÇ"
                color: root.cMuted
                font.family: "DejaVu Sans"
                font.weight: Font.Light
                font.pixelSize: 12 * root.u
                font.letterSpacing: 1.6
            }

            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 10 * root.u

                Repeater {
                    id: sessionRepeater
                    model: root.sessionCards

                    delegate: Rectangle {
                        id: sessionCard
                        property bool active: root.chosenSession === modelData.real
                        width: (520 * root.u - (sessionRepeater.count - 1) * 10 * root.u)
                               / Math.max(1, sessionRepeater.count)
                        height: 82 * root.u
                        radius: 14 * root.u
                        color: active ? "#e0a93b"
                             : (sessionPointer.containsMouse ? root.cHover : root.cCard)
                        border.color: active ? "#d09a2c" : root.cCardBorder
                        border.width: active ? 2 : 1

                        Column {
                            anchors.centerIn: parent
                            spacing: 4 * root.u
                            width: parent.width - 10 * root.u

                            // üst satır: oturum tipi (etiket kısa, kesilmesin)
                            Text {
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                text: ("" + modelData.label).toUpperCase()
                                color: sessionCard.active ? root.cOnAccent : root.cMuted
                                font.family: "DejaVu Sans"
                                font.weight: Font.DemiBold
                                font.pixelSize: 9 * root.u
                                font.letterSpacing: 1.3 * root.u
                            }
                            // asıl ad: kart genişliği 3 karta bölündüğü için tam sığar
                            Text {
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                text: modelData.name
                                color: sessionCard.active ? root.cOnAccent : root.cInk
                                font.family: "DejaVu Sans"
                                font.pixelSize: 15 * root.u
                            }
                            Text {
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                text: modelData.hint
                                color: sessionCard.active ? root.cOnAccent : root.cMuted
                                font.family: "DejaVu Sans"
                                font.weight: Font.Light
                                font.pixelSize: 10 * root.u
                            }
                        }

                        MouseArea {
                            id: sessionPointer
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.chosenSession = modelData.real
                        }
                    }
                }
            }
        }

        Rectangle {
            id: card
            width: 620 * root.u
            height: 400 * root.u
            radius: 26 * root.u
            color: root.cCard
            border.color: root.cCardBorder
            border.width: 1
            anchors.horizontalCenter: parent.horizontalCenter

            // gentle shake on a wrong password / empty user
            SequentialAnimation {
                id: shake
                NumberAnimation { target: card; property: "anchors.horizontalCenterOffset"; to: -10 * root.u; duration: 60 }
                NumberAnimation { target: card; property: "anchors.horizontalCenterOffset"; to: 10 * root.u; duration: 60 }
                NumberAnimation { target: card; property: "anchors.horizontalCenterOffset"; to: -6 * root.u; duration: 60 }
                NumberAnimation { target: card; property: "anchors.horizontalCenterOffset"; to: 0; duration: 60 }
            }

            Column {
                anchors.centerIn: parent
                spacing: 11 * root.u

                Text {
                    text: "Hoş geldiniz"
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: root.cSoft
                    font.family: "DejaVu Sans"
                    font.weight: Font.Light
                    font.pixelSize: 24 * root.u
                }

                // user chips — only when the greeter actually reports users
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8 * root.u
                    height: visible ? 44 * root.u : 0
                    visible: chipRepeater.count > 1

                    Repeater {
                        id: chipRepeater
                        model: userModel

                        delegate: Item {
                            width: 44 * root.u
                            height: 44 * root.u

                            Rectangle {
                                anchors.fill: parent
                                radius: width / 2
                                color: root.selectedUser === index ? "#e0a93b" : root.cChip
                                border.color: root.selectedUser === index ? "#d09a2c" : root.cChipBorder
                                border.width: 1

                                Text {
                                    anchors.centerIn: parent
                                    text: ("" + model.name).charAt(0).toUpperCase()
                                    color: root.selectedUser === index ? root.cOnAccent : root.cMuted
                                    font.pixelSize: 17 * root.u
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.selectedUser = index
                                        userEntry.text = model.name
                                        passwordEntry.forceActiveFocus()
                                    }
                                }
                            }
                        }
                    }
                }

                TextField {
                    id: userEntry
                    width: 520 * root.u
                    height: 52 * root.u
                    placeholderText: "kullanıcı"
                    text: userModel.lastUser.length > 0 ? userModel.lastUser : "parametral"
                    leftPadding: 22 * root.u
                    verticalAlignment: TextInput.AlignVCenter
                    font.pixelSize: 18 * root.u
                    color: root.cInk
                    selectByMouse: true
                    background: Rectangle {
                        radius: 13 * root.u
                        color: root.cField
                        border.color: userEntry.activeFocus ? "#e0a93b" : root.cFieldBorder
                        border.width: userEntry.activeFocus ? 2 : 1
                    }
                }

                // password field with show/hide
                Item {
                    width: 520 * root.u
                    height: 52 * root.u

                    TextField {
                        id: passwordEntry
                        anchors.fill: parent
                        rightPadding: 74 * root.u
                        placeholderText: "parola"
                        echoMode: TextInput.Password
                        leftPadding: 22 * root.u
                        verticalAlignment: TextInput.AlignVCenter
                        font.pixelSize: 18 * root.u
                        color: root.cInk
                        selectByMouse: true
                        onAccepted: root.doLogin()
                        background: Rectangle {
                            radius: 13 * root.u
                            color: root.cField
                            border.color: passwordEntry.activeFocus ? "#e0a93b" : root.cFieldBorder
                            border.width: passwordEntry.activeFocus ? 2 : 1
                        }
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 16 * root.u
                        anchors.verticalCenter: parent.verticalCenter
                        text: passwordEntry.echoMode === TextInput.Password ? "göster" : "gizle"
                        color: root.cMuted2
                        font.pixelSize: 13 * root.u

                        MouseArea {
                            anchors.fill: parent
                            anchors.margins: -10 * root.u
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                passwordEntry.echoMode =
                                    passwordEntry.echoMode === TextInput.Password
                                        ? TextInput.Normal : TextInput.Password
                                passwordEntry.forceActiveFocus()
                            }
                        }
                    }
                }

                // caps-lock hint — silent when the greeter has no keyboard object
                Text {
                    height: visible ? 15 * root.u : 0
                    visible: typeof keyboard !== "undefined" && keyboard.capsLock === true
                    text: "Caps Lock açık"
                    color: root.cError
                    font.pixelSize: 13 * root.u
                    anchors.horizontalCenter: parent.horizontalCenter
                }

                // login button
                Rectangle {
                    id: loginButton
                    width: 520 * root.u
                    height: 54 * root.u
                    radius: 13 * root.u
                    color: root.busy ? root.cBusy
                          : (buttonArea.pressed ? "#c9942f" : "#e0a93b")

                    Text {
                        anchors.centerIn: parent
                        visible: !root.busy
                        text: "Giriş yap"
                        color: root.cOnAccent
                        font.pixelSize: 18 * root.u
                    }

                    // three dots while the greeter authenticates
                    Row {
                        anchors.centerIn: parent
                        spacing: 7 * root.u
                        visible: root.busy

                        Repeater {
                            model: 3

                            delegate: Rectangle {
                                width: 7 * root.u
                                height: 7 * root.u
                                radius: width / 2
                                color: root.cDot
                                opacity: 0.35

                                SequentialAnimation on opacity {
                                    running: root.busy
                                    loops: Animation.Infinite
                                    PauseAnimation { duration: index * 140 }
                                    NumberAnimation { to: 0.25; duration: 260 }
                                    NumberAnimation { to: 1.0; duration: 260 }
                                }
                            }
                        }
                    }

                    MouseArea {
                        id: buttonArea
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        enabled: !root.busy
                        onClicked: root.doLogin()
                    }
                }

                Text {
                    height: visible ? 17 * root.u : 0
                    visible: root.errorText.length > 0
                    text: root.errorText
                    color: root.cError
                    font.pixelSize: 14 * root.u
                    anchors.horizontalCenter: parent.horizontalCenter
                }
            }
        }
    }

    // SDDM'in oturum listesi aynı masaüstünü birden çok kez veriyor
    // (hyprland + hyprland-uwsm, plasma + plasma-x11, xfce + parametral-x11 ...).
    // Kart olarak her masaüstü BİR kez çıksın diye isimler önce toplanıyor, sonra
    // gruplara indirgeniyor. Toplama işi görünmez bir Repeater'da yapılıyor:
    // rowCount() bazı SDDM sürümlerinde QML'den çağrılamıyor.
    property var sessionNames: []
    property var sessionCards: []

    function sessionGroup(raw) {
        var s = ("" + raw).toLowerCase()
        if (s === "parametral" || s.indexOf("hypr") >= 0) return "hypr"
        if (s.indexOf("plasma") >= 0 || s.indexOf("kde") >= 0) return "kde"
        if (s.indexOf("xfce") >= 0 || s.indexOf("x11") >= 0) return "x11"
        return "other:" + s
    }

    function sessionInfo(raw) {
        var g = sessionGroup(raw)
        if (g === "hypr") return { label: "Wayland", name: "Hyprland", hint: "Noctalia · birincil" }
        if (g === "kde")  return { label: "Wayland", name: "KDE Plasma", hint: "panel + başlat menüsü" }
        if (g === "x11")  return { label: "X11", name: "Parametral X11", hint: "VM'de garanti açılır" }
        return { label: "", name: "" + raw, hint: "" }
    }

    function noteSession(idx, raw) {
        if (idx < 0) return
        if (sessionNames[idx] === raw) return
        sessionNames[idx] = raw
        rebuildTimer.restart()
    }

    function buildSessionCards() {
        var order = { "hypr": 0, "kde": 1, "x11": 2 }
        var seen = {}
        var out = []
        for (var i = 0; i < sessionNames.length; ++i) {
            var raw = sessionNames[i]
            if (!raw) continue
            var g = sessionGroup(raw)
            if (seen[g]) continue
            seen[g] = true
            var info = sessionInfo(raw)
            out.push({ label: info.label, name: info.name, hint: info.hint,
                       group: g, real: i })
        }
        // sıra sabit: Hyprland, KDE, X11 — kartların yeri her açılışta aynı olsun
        out.sort(function (a, b) {
            var oa = order[a.group] === undefined ? 9 : order[a.group]
            var ob = order[b.group] === undefined ? 9 : order[b.group]
            return oa - ob
        })
        sessionCards = out
        if (out.length > 0 && chosenSession < 0) chosenSession = out[0].real
    }

    function doLogin() {
        if (userEntry.text.length === 0) {
            errorText = "Kullanıcı adı boş"
            shake.start()
            userEntry.forceActiveFocus()
            return
        }
        errorText = ""
        busy = true
        var idx = chosenSession >= 0 ? chosenSession : Math.max(0, sessionModel.lastIndex)
        sddm.login(userEntry.text, passwordEntry.text, idx)
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            busy = false
            passwordEntry.text = ""
            errorText = "Parola hatalı"
            shake.start()
            passwordEntry.forceActiveFocus()
        }
        function onLoginSucceeded() {
            busy = false
            errorText = ""
        }
    }

    Component.onCompleted: {
        // SDDM'in son kullanicisi/oturumu state.conf'tan gelir; secim yoksa onu kullan.
        if (chosenSession < 0) chosenSession = Math.max(0, sessionModel.lastIndex)
        if (userEntry.text.length > 0) passwordEntry.forceActiveFocus()
        else userEntry.forceActiveFocus()
    }
}
