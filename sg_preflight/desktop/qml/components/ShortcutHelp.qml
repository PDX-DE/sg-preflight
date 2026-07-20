pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

FocusScope {
    id: root

    required property bool open
    required property var shortcuts
    signal closeRequested

    visible: open
    focus: open
    z: 105
    Accessible.role: Accessible.Dialog
    Accessible.name: "Keyboard shortcuts"

    onOpenChanged: {
        if (open)
            Qt.callLater(closeControl.forceActiveFocus);
    }

    Rectangle {
        anchors.fill: parent
        color: "#b0000000"
    }

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
                id: closeControl

                objectName: "helpCloseControl"
                text: "Close help"
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.Button
                Accessible.name: text
                KeyNavigation.tab: closeControl
                KeyNavigation.backtab: closeControl
                onClicked: root.closeRequested()
            }
        }
    }
}
