pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

Item {
    id: root

    required property var page
    property var controller: null
    readonly property string rendererKind: "workflow"
    readonly property int renderedItemCount: root.page.visibleItems ? root.page.visibleItems.length : 0
    readonly property string renderedStatus: root.page.status || ""
    readonly property bool capabilityBusy: root.controller !== null && (root.controller.capabilityState === "queued" || root.controller.capabilityState === "running")
    readonly property var diagnosticActions: {
        const accepted = [];
        const actions = root.page.actions || [];
        for (let index = 0; index < actions.length; ++index) {
            if (actions[index].capabilityId === "diagnostic.run" && actions[index].enabled)
                accepted.push(actions[index]);
        }
        return accepted;
    }
    readonly property bool hasRecordHandoff: {
        const actions = root.page.actions || [];
        for (let index = 0; index < actions.length; ++index) {
            if (actions[index].capabilityId === "operator_handoff.record" && actions[index].enabled)
                return true;
        }
        return false;
    }
    readonly property bool canRecordHandoff: {
        return root.hasRecordHandoff && root.controller !== null && !root.capabilityBusy;
    }
    readonly property Item primaryActionItem: root.hasRecordHandoff ? recordHandoffControl : (primaryDiagnosticControl.visible ? primaryDiagnosticControl : null)

    ScrollView {
        id: scroll
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: scroll.availableWidth
            spacing: 12

            Label {
                objectName: "primaryPayloadText"
                Layout.fillWidth: true
                text: root.page.primaryText || "No workflow evidence available"
                color: Theme.text
                font.pixelSize: 20
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }
            ColumnLayout {
                objectName: "payloadDetailRegion"
                Layout.fillWidth: true
                spacing: 2
                Label {
                    Layout.fillWidth: true
                    text: root.page.provenance && root.page.provenance.source ? root.page.provenance.source : ""
                    color: Theme.muted
                    visible: text.length > 0
                    wrapMode: Text.WordWrap
                }
                Label {
                    Layout.fillWidth: true
                    text: root.page.provenance && root.page.provenance.revision ? root.page.provenance.revision : ""
                    color: Theme.muted
                    visible: text.length > 0
                    wrapMode: Text.WordWrap
                }
            }
            Repeater {
                model: root.page.visibleItems || []
                delegate: RowLayout {
                    id: workflowDelegate
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 12

                    Rectangle {
                        Layout.preferredWidth: 30
                        Layout.preferredHeight: 30
                        radius: 15
                        color: Theme.raised
                        border.color: Theme.border
                        Label {
                            anchors.centerIn: parent
                            text: workflowDelegate.index + 1
                            color: Theme.text
                            font.weight: Font.DemiBold
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: workflowItem.implicitHeight + 20
                        radius: 8
                        color: Theme.raised
                        border.color: Theme.border
                        ColumnLayout {
                            id: workflowItem
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.margins: 10
                            spacing: 4
                            Label {
                                Layout.fillWidth: true
                                text: workflowDelegate.modelData.label || "Workflow step"
                                color: Theme.text
                                font.weight: Font.DemiBold
                                wrapMode: Text.WordWrap
                            }
                            Label {
                                Layout.fillWidth: true
                                text: workflowDelegate.modelData.value || workflowDelegate.modelData.detail || "—"
                                color: Theme.muted
                                wrapMode: Text.WordWrap
                            }
                            Label {
                                Layout.fillWidth: true
                                text: workflowDelegate.modelData.status || root.renderedStatus
                                color: Theme.muted
                                font.pixelSize: 11
                            }
                        }
                    }
                }
            }
            Button {
                id: primaryDiagnosticControl

                objectName: "diagnosticActionControl"
                property bool primaryAction: visible
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                visible: root.diagnosticActions.length > 0
                enabled: visible && root.controller !== null && !root.capabilityBusy
                highlighted: primaryAction
                text: visible ? root.diagnosticActions[0].label || "Run audited diagnostic" : ""
                font.weight: Font.DemiBold
                Accessible.name: text
                onClicked: root.controller.runDiagnostic(root.diagnosticActions[0].actionId, [root.controller.currentProfileId])
            }
            Repeater {
                objectName: "secondaryDiagnosticRepeater"
                model: root.diagnosticActions.slice(1)
                delegate: Button {
                    id: diagnosticDelegate
                    required property var modelData
                    objectName: "diagnosticActionControl"
                    property bool primaryAction: false
                    Layout.fillWidth: true
                    enabled: root.controller !== null && !root.capabilityBusy
                    highlighted: false
                    text: diagnosticDelegate.modelData.label || "Run audited diagnostic"
                    Accessible.name: text
                    onClicked: root.controller.runDiagnostic(diagnosticDelegate.modelData.actionId, [root.controller.currentProfileId])
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.hasRecordHandoff
                spacing: 8

                TextField {
                    id: stoppingPointControl
                    objectName: "handoffStoppingPointControl"
                    Layout.fillWidth: true
                    placeholderText: "Stopping point"
                    maximumLength: 1000
                    enabled: root.canRecordHandoff
                    Accessible.name: "Handoff stopping point"
                }
                TextField {
                    id: nextStepControl
                    objectName: "handoffNextStepControl"
                    Layout.fillWidth: true
                    placeholderText: "Next local step"
                    maximumLength: 1000
                    enabled: root.canRecordHandoff
                    Accessible.name: "Handoff next local step"
                }
                TextArea {
                    id: handoffNoteControl
                    objectName: "handoffNoteControl"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 72
                    placeholderText: "Bounded operator note"
                    wrapMode: TextEdit.Wrap
                    enabled: root.canRecordHandoff
                    Accessible.name: "Handoff operator note"
                }
                Button {
                    id: recordHandoffControl

                    objectName: "recordOperatorHandoffControl"
                    property bool primaryAction: true
                    text: "Record handoff"
                    enabled: root.canRecordHandoff && stoppingPointControl.text.trim().length > 0
                    highlighted: primaryAction
                    Layout.preferredHeight: 44
                    font.weight: Font.DemiBold
                    Accessible.name: text
                    onClicked: root.controller.recordOperatorHandoff(stoppingPointControl.text, nextStepControl.text, handoffNoteControl.text)
                }
            }
        }
    }

    Connections {
        target: root.controller

        function onActionFeedbackChanged() {
            if (root.controller.lastActionStatus === "completed" && root.controller.lastActionResult.capabilityId === "operator_handoff.record") {
                stoppingPointControl.clear();
                nextStepControl.clear();
                handoffNoteControl.clear();
            }
        }
    }
}
