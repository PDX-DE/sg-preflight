pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import SGFX 1.0

FocusScope {
    id: root

    required property var selectedProfile
    required property var latestLocalRun
    required property string previewState
    required property string previewToken
    required property int previewFrameCount
    required property int previewFrameIndex
    required property string previewLabel
    required property bool reducedMotion
    signal inspectionRequested
    signal previewFrameRequested(int frameIndex)
    signal focusNavigationRequested
    readonly property bool hasSelection: Boolean(selectedProfile && selectedProfile.id)
    readonly property bool previewReady: previewState === "ready" && previewToken.length > 0 && previewFrameCount > 0
    readonly property bool playbackActive: root.visible && root.Window.window !== null && root.Window.window.active
    readonly property bool allAccessibleNamesPresent: inspectionAction.Accessible.name.length > 0
    readonly property var motionNames: ["Orbit", "Sway", "Drift"]
    property bool playbackComplete: false
    property int motionMode: 0
    property int sweepDirection: 1

    objectName: "qaContextPreview"
    activeFocusOnTab: false

    function requestFrame(candidate: int) {
        if (!root.previewReady)
            return;
        const bounded = Math.max(0, Math.min(root.previewFrameCount - 1, candidate));
        root.previewFrameRequested(bounded);
    }

    function focusFirstAction() {
        inspectionAction.forceActiveFocus();
    }

    onPreviewTokenChanged: {
        playbackComplete = false;
        sweepDirection = 1;
    }
    onPreviewFrameCountChanged: playbackComplete = false

    Rectangle {
        anchors.fill: parent
        radius: 14
        color: "#14191c"
        border.color: root.activeFocus ? Theme.accent : Theme.border
        border.width: root.activeFocus ? 2 : 1

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width * 0.82, 300)
            height: width * 0.48
            radius: width / 2
            color: "transparent"
            border.color: "#26363b"
            border.width: 1
            opacity: 0.75
            visible: !root.previewReady
        }

        Item {
            id: previewStage

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.margins: Theme.space3
            anchors.topMargin: 40
            anchors.bottomMargin: 48
            visible: root.previewReady

            // The frames carry real transparency; only a soft floor shadow grounds the car.
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: parent.height * 0.05
                width: parent.width * 0.5
                height: 10
                radius: 5
                color: "#000000"
                opacity: 0.45
            }

            Item {
                id: turntable

                anchors.fill: parent
                // Drift breathes with the turntable itself: the scale follows the played frame,
                // so all motion stays timer-driven and stops exactly when playback stops. The
                // baseline zoom fills the stage; frame borders are transparent, so nothing crops.
                scale: (root.previewReady && root.motionMode === 2 && !root.reducedMotion ? 1.0 + 0.05 * Math.sin((root.previewFrameIndex / Math.max(1, root.previewFrameCount)) * Math.PI * 2) : 1.0) * 1.22

                Behavior on scale {
                    NumberAnimation {
                        duration: 420
                        easing.type: Easing.InOutSine
                    }
                }

                Image {
                    id: profilePreview

                    objectName: "profilePreviewImage"
                    anchors.fill: parent
                    source: root.previewReady ? "image://sgfx-preview/" + root.previewToken + "/" + root.previewFrameIndex : ""
                    fillMode: Image.PreserveAspectFit
                    asynchronous: false
                    cache: true
                    smooth: true
                    mipmap: true
                }
            }
        }

        Timer {
            id: previewPlayback

            objectName: "previewPlayback"
            interval: Math.max(160, Math.round(9600 / Math.max(1, root.previewFrameCount - 1)))
            repeat: true
            running: root.playbackActive && root.previewReady && !root.reducedMotion && root.previewFrameCount > 1
            onTriggered: {
                // The cached revolution plays continuously as a cosmetic loop; rendering stays a
                // single bounded pass and playbackComplete marks the first full revolution.
                if (root.motionMode === 1) {
                    let next = root.previewFrameIndex + root.sweepDirection;
                    if (next >= root.previewFrameCount) {
                        root.sweepDirection = -1;
                        next = root.previewFrameCount - 2;
                        root.playbackComplete = true;
                    } else if (next < 0) {
                        root.sweepDirection = 1;
                        next = 1;
                    }
                    root.requestFrame(next);
                } else if (root.previewFrameIndex >= root.previewFrameCount - 1) {
                    root.playbackComplete = true;
                    root.requestFrame(0);
                } else {
                    root.requestFrame(root.previewFrameIndex + 1);
                }
            }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.space3

            Label {
                Layout.fillWidth: true
                text: "QA CONTEXT"
                color: Theme.accent
                font.family: Theme.operationalFont
                font.pixelSize: 10
                font.weight: Font.Bold
                font.letterSpacing: 1.6
            }
            Label {
                Layout.fillWidth: true
                text: root.hasSelection ? root.selectedProfile.label : "No profile selected"
                color: Theme.text
                font.family: Theme.displayFont
                font.pixelSize: 21
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            Item {
                Layout.fillHeight: true
            }
            Label {
                Layout.fillWidth: true
                visible: root.previewReady || root.hasSelection
                text: {
                    if (root.previewReady)
                        return root.reducedMotion ? root.previewLabel : "Motion: " + root.motionNames[root.motionMode] + " · click the car to change";
                    if (!root.hasSelection)
                        return "";
                    if (root.previewState === "loading")
                        return "Preparing the 3D preview…";
                    return "No exported 3D scene found for this car - showing the placeholder.";
                }
                color: root.previewReady ? Theme.accent : Theme.muted
                font.family: Theme.operationalFont
                font.pixelSize: 10
                elide: Text.ElideRight
            }
            Label {
                Layout.fillWidth: true
                text: root.latestLocalRun && root.latestLocalRun.state ? "Local evidence · " + String(root.latestLocalRun.state).replace(/_/g, " ") : "Local evidence · not run"
                color: Theme.muted
                font.family: Theme.operationalFont
                font.pixelSize: 10
                elide: Text.ElideRight
            }
            Button {
                id: inspectionAction

                objectName: "qaInspectionAction"
                Layout.fillWidth: true
                text: "Open 3D inspection"
                enabled: root.hasSelection
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.Button
                Accessible.name: text
                Keys.onTabPressed: event => {
                    root.focusNavigationRequested();
                    event.accepted = true;
                }
                onClicked: root.inspectionRequested()
            }
        }

        Item {
            // Topmost interaction layer over the turntable: nothing in the layout can swallow
            // the tap, and the cursor advertises the gesture.
            x: previewStage.x
            y: previewStage.y
            width: previewStage.width
            height: previewStage.height
            visible: root.previewReady

            HoverHandler {
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                enabled: root.previewReady && !root.reducedMotion
                onTapped: {
                    root.motionMode = (root.motionMode + 1) % root.motionNames.length;
                    root.sweepDirection = 1;
                }
            }
        }
    }
}
