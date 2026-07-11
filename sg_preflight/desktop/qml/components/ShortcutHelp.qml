pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

Rectangle {
    id: root

    required property bool open
    required property var shortcuts
    signal closeRequested

    visible: open
    color: "#b0000000"
    z: 105

    Rectangle {
        anchors.centerIn: parent
        width: 520
        height: 430
        radius: 14
        color: Theme.raised
        border.color: Theme.border

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 26
            spacing: 12

            Label {
                text: "Keyboard shortcuts"
                color: Theme.text
                font.pixelSize: 22
            }
            Repeater {
                model: root.shortcuts

                delegate: RowLayout {
                    id: shortcutRow

                    required property var modelData
                    Layout.fillWidth: true
                    Layout.minimumHeight: 44
                    Label {
                        text: shortcutRow.modelData.key
                        color: Theme.accent
                        Layout.preferredWidth: 70
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: shortcutRow.modelData.label
                        color: Theme.text
                        Layout.fillWidth: true
                    }
                }
            }
            Item {
                Layout.fillHeight: true
            }
            Button {
                text: "Close help"
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.Button
                Accessible.name: text
                onClicked: root.closeRequested()
            }
        }
    }
}
