// Parametral splash — the two seconds between the login screen and the desktop.
//
// Breeze's splash is a logo on black; that is the single most "any distro" moment in the
// whole boot. Ours: graphite ground, the gauge rising with a warm halo, wordmark, amber
// progress hairline. Kept intentionally light on animation so it also looks right on a
// software renderer (VirtualBox).

import QtQuick

Rectangle {
    id: root

    // Plasma drives these two
    property int stage: 0
    property bool ready: false

    color: "#0F141A"

    // Warm halo behind the mark. A gradient Rectangle drew a visible disc edge; the same
    // pre-blurred glow the login screen uses fades out properly.
    Image {
        id: halo
        anchors.centerIn: parent
        source: "images/logo-glow.png"
        fillMode: Image.PreserveAspectFit
        width: Math.min(parent.width, parent.height) * 0.85
        opacity: 0
        smooth: true
    }

    Image {
        id: logo
        anchors.centerIn: parent
        source: "images/logo-large.png"
        fillMode: Image.PreserveAspectFit
        width: Math.min(parent.width, parent.height) * 0.22
        opacity: 0
        scale: 0.94
        smooth: true
    }

    Column {
        id: wordmark
        anchors.top: logo.bottom
        anchors.topMargin: 26
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 4
        opacity: 0

        Text {
            text: "Parametral"
            color: "#E9E4D8"
            font.pixelSize: 30
            font.letterSpacing: 1.4
            font.weight: Font.DemiBold
            anchors.horizontalCenter: parent.horizontalCenter
        }

        Text {
            text: "OS"
            color: "#9AA4B2"
            font.pixelSize: 13
            font.letterSpacing: 6
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }

    // amber hairline that fills while the session comes up
    Rectangle {
        id: track
        anchors.top: wordmark.bottom
        anchors.topMargin: 34
        anchors.horizontalCenter: parent.horizontalCenter
        width: 180
        height: 3
        radius: 1.5
        color: Qt.rgba(0.878, 0.663, 0.231, 0.18)

        Rectangle {
            id: fill
            width: track.width * 0.0
            height: parent.height
            radius: 1.5
            color: "#E0A93B"
        }
    }

    ParallelAnimation {
        id: intro
        running: true

        NumberAnimation { target: halo;   property: "opacity"; from: 0; to: 1; duration: 700; easing.type: Easing.OutCubic }
        NumberAnimation { target: logo;   property: "opacity"; from: 0; to: 1; duration: 600; easing.type: Easing.OutCubic }
        NumberAnimation { target: logo;   property: "scale";   from: 0.94; to: 1; duration: 700; easing.type: Easing.OutBack }
        // `delay` does not exist on Animation in this Qt; a pause inside a sequence does the job
        SequentialAnimation {
            PauseAnimation { duration: 220 }
            NumberAnimation { target: wordmark; property: "opacity"; from: 0; to: 1; duration: 600; easing.type: Easing.OutCubic }
        }
        SequentialAnimation {
            PauseAnimation { duration: 250 }
            NumberAnimation { target: fill; property: "width"; from: 0; to: track.width; duration: 1600; easing.type: Easing.InOutQuad }
        }
    }

    // stage 5 means the desktop is ready: fade the whole splash out rather than popping
    onStageChanged: {
        if (stage >= 5) {
            fadeOut.running = true;
        }
    }

    NumberAnimation {
        id: fadeOut
        target: root
        property: "opacity"
        to: 0
        duration: 220
    }
}
