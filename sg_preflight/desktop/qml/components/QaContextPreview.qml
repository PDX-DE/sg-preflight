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
    readonly property bool scrubberRevealed: root.previewReady && root.previewFrameCount > 1 && (cardHover.hovered || previewScrubber.activeFocus || previewScrubber.hovered)
    readonly property bool allAccessibleNamesPresent: inspectionAction.Accessible.name.length > 0 && (!previewScrubber.visible || previewScrubber.Accessible.name.length > 0)
    property bool playbackComplete: false

    objectName: "qaContextPreview"
    activeFocusOnTab: false

    function requestFrame(candidate: int) {
        if (!root.previewReady)
            return;
        const bounded = Math.max(0, Math.min(root.previewFrameCount - 1, candidate));
        root.previewFrameRequested(bounded);
    }

    function focusFirstAction() {
        if (previewScrubber.visible)
            previewScrubber.forceActiveFocus();
        else
            inspectionAction.forceActiveFocus();
    }

    onPreviewTokenChanged: playbackComplete = false
    onPreviewFrameCountChanged: playbackComplete = false

    Rectangle {
        anchors.fill: parent
        radius: 14
        color: "#14191c"
        border.color: root.activeFocus ? Theme.accent : Theme.border
        border.width: root.activeFocus ? 2 : 1

        HoverHandler {
            id: cardHover
        }

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
            anchors.topMargin: 46
            anchors.bottomMargin: 62
            visible: root.previewReady

            Image {
                id: profilePreview

                objectName: "profilePreviewImage"
                anchors.fill: parent
                source: root.previewReady ? "image://sgfx-preview/" + root.previewToken + "/" + root.previewFrameIndex : ""
                fillMode: Image.PreserveAspectFit
                asynchronous: false
                cache: true
            }

            // The rendered frames carry an opaque black backdrop; feathering every edge into the
            // card colour makes the turntable float instead of sitting in a hard slab.
            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 26
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "#14191c" }
                    GradientStop { position: 1.0; color: "transparent" }
                }
            }
            Rectangle {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 26
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 1.0; color: "#14191c" }
                }
            }
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 20
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#14191c" }
                    GradientStop { position: 1.0; color: "transparent" }
                }
            }
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 20
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 1.0; color: "#14191c" }
                }
            }
        }

        Item {
            id: vehicleFigure

            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -4
            width: Math.min(parent.width * 0.72, 250)
            height: 92
            visible: !root.previewReady
            opacity: root.hasSelection ? 1 : 0.42

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 17
                width: parent.width
                height: 36
                radius: 18
                color: "#253238"
                border.color: root.hasSelection ? Theme.accent : Theme.border
            }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 43
                width: parent.width * 0.58
                height: 30
                radius: 15
                color: "#1d282d"
                border.color: root.hasSelection ? "#6edbc5" : Theme.border
            }
            Repeater {
                model: [-1, 1]

                delegate: Rectangle {
                    id: wheel

                    required property real modelData
                    x: wheel.modelData < 0 ? vehicleFigure.width * 0.14 : vehicleFigure.width * 0.70
                    y: vehicleFigure.height - 36
                    width: 34
                    height: 34
                    radius: 17
                    color: Theme.canvas
                    border.color: Theme.muted
                    border.width: 3
                }
            }
        }

        Timer {
            id: previewPlayback

            objectName: "previewPlayback"
            interval: Math.max(80, Math.round(2400 / Math.max(1, root.previewFrameCount - 1)))
            repeat: true
            running: root.playbackActive && root.previewReady && !root.reducedMotion && root.previewFrameCount > 1
            onTriggered: {
                // The cached revolution loops continuously; playbackComplete still marks that at
                // least one full revolution has been shown. Rendering stays a single bounded pass.
                if (root.previewFrameIndex >= root.previewFrameCount - 1) {
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
                        return root.scrubberRevealed ? root.previewLabel + " · " + String(root.previewFrameIndex + 1) + "/" + String(root.previewFrameCount) : root.previewLabel;
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
            Slider {
                id: previewScrubber

                objectName: "previewScrubber"
                Layout.fillWidth: true
                Layout.preferredHeight: root.scrubberRevealed ? implicitHeight : 6
                visible: root.previewReady && root.previewFrameCount > 1
                opacity: root.scrubberRevealed ? 1 : 0
                from: 0
                to: Math.max(0, root.previewFrameCount - 1)
                stepSize: 1
                value: root.previewFrameIndex
                focusPolicy: Qt.StrongFocus
                Accessible.name: "3D preview frame"
                Behavior on opacity {
                    NumberAnimation { duration: 120 }
                }
                Keys.onTabPressed: event => {
                    inspectionAction.forceActiveFocus();
                    event.accepted = true;
                }
                onMoved: root.requestFrame(Math.round(value))
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
    }
}
