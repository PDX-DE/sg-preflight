pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import SGFX 1.0

FocusScope {
    id: root

    required property var gates
    required property string selectedGateId
    required property bool reducedMotion
    signal gateSelected(string gateId)
    signal focusChecksRequested
    readonly property var gateIds: {
        const ids = [];
        for (let index = 0; index < gates.length; ++index)
            ids.push(gates[index].id);
        return ids;
    }
    readonly property bool allAccessibleNamesPresent: {
        for (let index = 0; index < gates.length; ++index) {
            if (!gates[index].label || !gates[index].state)
                return false;
        }
        return true;
    }

    function move(delta) {
        const current = Math.max(0, gateIds.indexOf(selectedGateId));
        const next = Math.max(0, Math.min(gateIds.length - 1, current + delta));
        if (gateIds.length > 0)
            gateSelected(gateIds[next]);
    }

    objectName: "qaPipelineSpine"
    implicitHeight: 108
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: "QA gates, " + String(gates.length) + " stages"
    Keys.onReturnPressed: gateSelected(selectedGateId)
    Keys.onEnterPressed: gateSelected(selectedGateId)
    Keys.onSpacePressed: gateSelected(selectedGateId)
    Keys.onLeftPressed: move(-1)
    Keys.onRightPressed: move(1)
    Keys.onTabPressed: event => {
        root.focusChecksRequested();
        event.accepted = true;
    }

    ListView {
        id: gateList

        anchors.fill: parent
        orientation: ListView.Horizontal
        spacing: Theme.space2
        clip: true
        model: root.gates
        boundsBehavior: Flickable.StopAtBounds
        highlightMoveDuration: Theme.duration(Theme.focusDuration, root.reducedMotion)

        delegate: FocusScope {
            id: gateItem

            required property int index
            required property var modelData
            readonly property bool selected: gateItem.modelData.id === root.selectedGateId

            objectName: "qaGate" + gateItem.index
            width: Math.max(104, (gateList.width - Theme.space2 * 6) / 7)
            height: gateList.height
            activeFocusOnTab: false
            Accessible.role: Accessible.Button
            Accessible.name: gateItem.modelData.label + ", " + StatusPresentation.label(gateItem.modelData.state)
            Keys.onReturnPressed: root.gateSelected(gateItem.modelData.id)
            Keys.onEnterPressed: root.gateSelected(gateItem.modelData.id)
            Keys.onSpacePressed: root.gateSelected(gateItem.modelData.id)
            Keys.onLeftPressed: root.move(-1)
            Keys.onRightPressed: root.move(1)
            scale: gateItem.selected && root.activeFocus ? 1.02 : 1

            Behavior on scale {
                NumberAnimation {
                    duration: Theme.duration(Theme.focusDuration, root.reducedMotion)
                }
            }

            Rectangle {
                anchors.fill: parent
                radius: gateItem.selected ? 16 : 9
                color: gateItem.selected ? Theme.raised : Theme.canvas
                border.color: gateItem.selected || gateItem.activeFocus ? Theme.accent : Theme.border
                border.width: gateItem.selected || gateItem.activeFocus ? 2 : 1

                Behavior on radius {
                    NumberAnimation {
                        duration: Theme.duration(Theme.focusDuration, root.reducedMotion)
                    }
                }
            }

            Column {
                anchors.fill: parent
                anchors.margins: Theme.space2
                spacing: Theme.space1

                Label {
                    width: parent.width
                    text: String(gateItem.index + 1).padStart(2, "0")
                    color: gateItem.selected ? Theme.accent : Theme.muted
                    font.family: Theme.operationalFont
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }
                Label {
                    width: parent.width
                    text: gateItem.modelData.label
                    color: Theme.text
                    font.family: Theme.operationalFont
                    font.pixelSize: 12
                    font.weight: gateItem.selected ? Font.DemiBold : Font.Normal
                    elide: Text.ElideRight
                }
                Label {
                    width: parent.width
                    text: StatusPresentation.label(gateItem.modelData.state)
                    color: gateItem.selected ? StatusPresentation.color(gateItem.modelData.state) : Theme.muted
                    font.family: Theme.operationalFont
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
            }

            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                onClicked: {
                    root.forceActiveFocus();
                    root.gateSelected(gateItem.modelData.id);
                }
            }
        }
    }
}
