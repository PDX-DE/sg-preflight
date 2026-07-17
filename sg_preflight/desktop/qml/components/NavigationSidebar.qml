pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

Rectangle {
    id: root

    required property var shellModel
    required property string currentRouteId
    required property string currentProfileId
    required property bool reducedMotion
    signal navigateRequested(string routeId)
    signal jumpRequested
    readonly property bool allAccessibleNamesPresent: jumpButton.Accessible.name.length > 0

    function focusFirst() {
        jumpButton.forceActiveFocus();
    }

    color: Theme.panel
    border.color: Theme.border
    border.width: 1

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Image {
                Layout.preferredWidth: 34
                Layout.preferredHeight: 34
                source: "../assets/logo_sgfx.png"
                sourceSize.width: 68
                sourceSize.height: 68
                fillMode: Image.PreserveAspectFit
                smooth: true
            }
            Label {
                Layout.fillWidth: true
                text: "Seriengrafik: Project Quality-Hero"
                color: Theme.text
                font.pixelSize: 18
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
        }
        Label {
            Layout.fillWidth: true
            text: "Local, read-only delivery evidence"
            color: Theme.muted
            font.pixelSize: 12
        }
        Button {
            id: jumpButton

            objectName: "navigationJumpAction"
            Layout.fillWidth: true
            Layout.minimumHeight: 50
            text: "Jump to page  /"
            focusPolicy: Qt.StrongFocus
            Accessible.role: Accessible.Button
            Accessible.name: "Jump to page"
            onClicked: root.jumpRequested()
        }
        ListView {
            id: navigation
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: root.shellModel
            clip: true
            spacing: 2
            section.property: "group"
            section.criteria: ViewSection.FullString

            section.delegate: Item {
                required property string section
                width: navigation.width
                height: section.length > 0 ? 32 : 0
                visible: section.length > 0

                Label {
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 6
                    text: parent.section
                    color: Theme.muted
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                }
            }
            delegate: ItemDelegate {
                id: navigationItem

                required property string routeId
                required property string title
                required property string subtitle
                required property string group
                required property string rendererKind
                required property bool operational
                width: navigation.width
                height: 50
                text: title
                enabled: routeId === "home" || !operational || root.currentProfileId.length > 0
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.Button
                Accessible.name: "Open " + title
                onClicked: root.navigateRequested(routeId)

                background: Rectangle {
                    radius: 8
                    color: navigationItem.routeId === root.currentRouteId ? Qt.alpha(Theme.accent, 0.18) : navigationItem.hovered ? Theme.raised : "transparent"
                    border.color: navigationItem.routeId === root.currentRouteId ? Qt.alpha(Theme.accent, 0.65) : "transparent"

                    Behavior on color {
                        ColorAnimation {
                            duration: Theme.duration(Theme.motionFeedback, root.reducedMotion)
                        }
                    }
                }
                contentItem: Label {
                    text: navigationItem.title
                    color: Theme.text
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
            }
            ScrollBar.vertical: ScrollBar {}
        }
    }
}
