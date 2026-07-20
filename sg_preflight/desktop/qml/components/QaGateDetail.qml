pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

FocusScope {
    id: root

    required property var gate
    required property bool reducedMotion
    signal routeRequested(string routeId)
    signal focusContextRequested
    readonly property var checks: gate && gate.checks ? gate.checks : []
    readonly property int visibleCheckRowCount: Math.min(4, checks.length)
    readonly property bool allAccessibleNamesPresent: {
        for (let index = 0; index < visibleCheckRowCount; ++index) {
            if (!checks[index].label || !checks[index].state)
                return false;
        }
        return true;
    }

    function focusFirstCheck() {
        for (let index = 0; index < checkRows.count; ++index) {
            const row = checkRows.itemAt(index);
            if (row.routing) {
                row.forceActiveFocus();
                return true;
            }
        }
        return false;
    }

    function focusNextCheck(index: int) {
        for (let next = index + 1; next < checkRows.count; ++next) {
            const row = checkRows.itemAt(next);
            if (row.routing) {
                row.forceActiveFocus();
                return;
            }
        }
        root.focusContextRequested();
    }

    objectName: "qaGateDetail"
    activeFocusOnTab: false

    Rectangle {
        anchors.fill: parent
        radius: 14
        color: Theme.canvas
        border.color: Theme.border
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space3
        spacing: Theme.space2

        RowLayout {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Label {
                    Layout.fillWidth: true
                    text: root.gate && root.gate.label ? root.gate.label : "Local QA state unavailable"
                    color: Theme.text
                    font.family: Theme.displayFont
                    font.pixelSize: 22
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Label {
                    Layout.fillWidth: true
                    text: root.gate && root.gate.ownerLabel ? "Owner · " + root.gate.ownerLabel : "Owner not recorded"
                    color: Theme.muted
                    font.family: Theme.operationalFont
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }

            StatusBadge {
                status: root.gate && root.gate.state ? root.gate.state : "not_recorded"
            }
        }

        Label {
            Layout.fillWidth: true
            text: root.gate && root.gate.summary ? root.gate.summary : "No local evidence is recorded for this gate."
            color: Theme.muted
            font.family: Theme.operationalFont
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }

        Repeater {
            id: checkRows

            model: root.visibleCheckRowCount

            delegate: FocusScope {
                id: checkRow

                required property int index
                readonly property var checkData: root.checks[checkRow.index]
                readonly property bool routing: Boolean(checkData.routeId)

                objectName: "qaCheckRow" + checkRow.index
                Layout.fillWidth: true
                Layout.minimumHeight: 48
                activeFocusOnTab: checkRow.routing
                Accessible.role: checkRow.routing ? Accessible.Button : Accessible.StaticText
                Accessible.name: checkRow.checkData.label + ", " + StatusPresentation.label(checkRow.checkData.state)
                Keys.onReturnPressed: {
                    if (checkRow.checkData.routeId)
                        root.routeRequested(checkRow.checkData.routeId);
                }
                Keys.onEnterPressed: {
                    if (checkRow.checkData.routeId)
                        root.routeRequested(checkRow.checkData.routeId);
                }
                Keys.onSpacePressed: {
                    if (checkRow.checkData.routeId)
                        root.routeRequested(checkRow.checkData.routeId);
                }
                Keys.onTabPressed: event => {
                    root.focusNextCheck(checkRow.index);
                    event.accepted = true;
                }

                Rectangle {
                    anchors.fill: parent
                    radius: 8
                    color: checkRow.activeFocus ? Theme.raised : Theme.panel
                    border.color: checkRow.activeFocus ? Theme.accent : Theme.border
                    border.width: checkRow.activeFocus ? 2 : 1
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.space2
                    anchors.rightMargin: Theme.space2
                    spacing: Theme.space2

                    Label {
                        Layout.preferredWidth: 128
                        text: checkRow.checkData.label
                        color: Theme.text
                        font.family: Theme.operationalFont
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Label {
                        Layout.fillWidth: true
                        text: checkRow.checkData.summary
                        color: Theme.muted
                        font.family: Theme.operationalFont
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                    Label {
                        text: StatusPresentation.label(checkRow.checkData.state)
                        color: StatusPresentation.color(checkRow.checkData.state)
                        font.family: Theme.operationalFont
                        font.pixelSize: 10
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: checkRow.routing
                    onClicked: {
                        checkRow.forceActiveFocus();
                        root.routeRequested(checkRow.checkData.routeId);
                    }
                }
            }
        }

        Item {
            Layout.fillHeight: true
        }
    }
}
