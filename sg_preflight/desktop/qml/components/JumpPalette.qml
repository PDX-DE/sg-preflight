pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

FocusScope {
    id: root

    required property bool open
    required property var routes
    signal closeRequested
    signal navigateRequested(string routeId)
    property string filterText: ""

    visible: open
    focus: open
    z: 110
    Accessible.role: Accessible.Dialog
    Accessible.name: "Jump to page"

    onOpenChanged: {
        if (open)
            Qt.callLater(filter.forceActiveFocus);
    }

    Rectangle {
        anchors.fill: parent
        color: "#b0000000"
    }

    function activateFirst() {
        for (let index = 0; index < routes.length; ++index) {
            const route = routes[index];
            if (!filterText || route.title.toLowerCase().includes(filterText) || route.routeId.toLowerCase().includes(filterText)) {
                root.navigateRequested(route.routeId);
                return;
            }
        }
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 100
        width: 640
        height: 460
        radius: 14
        color: Theme.raised
        border.color: Theme.border

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 12

            TextField {
                id: filter
                objectName: "jumpFilter"
                Layout.fillWidth: true
                Layout.minimumHeight: 50
                placeholderText: "Jump to page — type to filter, Enter opens the first match"
                focus: root.open
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.EditableText
                Accessible.name: "Filter pages"
                KeyNavigation.tab: closeControl
                KeyNavigation.backtab: closeControl
                onTextChanged: root.filterText = text.toLowerCase()
                Keys.onReturnPressed: root.activateFirst()
                Keys.onEnterPressed: root.activateFirst()
            }
            ListView {
                id: results
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: root.routes.length
                clip: true

                delegate: ItemDelegate {
                    required property int index
                    readonly property var routeData: root.routes[index]
                    width: results.width
                    height: visible ? 50 : 0
                    visible: !root.filterText || routeData.title.toLowerCase().includes(root.filterText) || routeData.routeId.toLowerCase().includes(root.filterText)
                    text: routeData.title
                    focusPolicy: Qt.NoFocus
                    Accessible.role: Accessible.Button
                    Accessible.name: "Jump to " + routeData.title
                    onClicked: root.navigateRequested(routeData.routeId)
                }
            }
            Button {
                id: closeControl

                objectName: "jumpCloseControl"
                text: "Close"
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.Button
                Accessible.name: "Close jump palette"
                KeyNavigation.tab: filter
                KeyNavigation.backtab: filter
                onClicked: root.closeRequested()
            }
        }
    }
}
