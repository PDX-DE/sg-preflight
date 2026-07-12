pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

FocusScope {
    id: root

    required property var selectedProfile
    required property var latestLocalRun
    required property bool reducedMotion
    signal inspectionRequested
    readonly property bool hasSelection: Boolean(selectedProfile && selectedProfile.id)

    objectName: "qaContextPreview"
    activeFocusOnTab: root.hasSelection

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
        }

        Item {
            id: vehicleFigure

            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -4
            width: Math.min(parent.width * 0.72, 250)
            height: 92
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

            SequentialAnimation on y {
                running: root.hasSelection && !root.reducedMotion
                loops: Animation.Infinite
                NumberAnimation {
                    from: -2
                    to: 2
                    duration: 1200
                    easing.type: Easing.InOutSine
                }
                NumberAnimation {
                    from: 2
                    to: -2
                    duration: 1200
                    easing.type: Easing.InOutSine
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
                text: root.latestLocalRun && root.latestLocalRun.state ? "Local evidence · " + String(root.latestLocalRun.state).replace(/_/g, " ") : "Local evidence · not run"
                color: Theme.muted
                font.family: Theme.operationalFont
                font.pixelSize: 10
                elide: Text.ElideRight
            }
            Button {
                Layout.fillWidth: true
                text: "Open 3D inspection"
                enabled: root.hasSelection
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.Button
                Accessible.name: text
                onClicked: root.inspectionRequested()
            }
        }
    }
}
