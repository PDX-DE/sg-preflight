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
    readonly property bool canRecordHandoff: {
        const actions = root.page.actions || [];
        for (let index = 0; index < actions.length; ++index) {
            if (actions[index].capabilityId === "operator_handoff.record" && actions[index].enabled)
                return root.controller !== null && !root.capabilityBusy;
        }
        return false;
    }

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
            RowLayout {
                Layout.fillWidth: true
                visible: root.capabilityBusy
                spacing: 10

                BusyIndicator {
                    running: root.capabilityBusy
                    Layout.preferredWidth: 28
                    Layout.preferredHeight: 28
                }
                Label {
                    objectName: "runningActionText"
                    Layout.fillWidth: true
                    text: root.controller !== null && root.controller.activeActionLabel.length > 0 ? "Running: " + root.controller.activeActionLabel + "…" : "Running…"
                    color: Theme.text
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }
                Button {
                    objectName: "cancelDiagnosticControl"
                    text: "Cancel queued diagnostic"
                    visible: root.controller !== null && root.controller.diagnosticCanCancel
                    enabled: visible
                    Accessible.name: text
                    onClicked: root.controller.cancelDiagnostic()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: root.controller !== null && (root.controller.capabilityState !== "idle" || root.controller.capabilityError.length > 0) && !root.capabilityBusy && !actionResultPanel.visible
                spacing: 10

                Label {
                    objectName: "capabilityLifecycleText"
                    Layout.fillWidth: true
                    text: root.controller.capabilityError || ("Action state: " + root.controller.capabilityState)
                    color: root.controller.capabilityError.length > 0 ? Theme.statusBad : Theme.muted
                    wrapMode: Text.WordWrap
                }
            }
            Rectangle {
                id: actionResultPanel
                objectName: "actionResultPanel"
                Layout.fillWidth: true
                visible: root.controller !== null && !root.capabilityBusy && root.controller.lastActionStatus.length > 0
                implicitHeight: actionResultColumn.implicitHeight + 20
                radius: 8
                color: Theme.raised
                border.color: root.controller !== null && root.controller.lastActionStatus === "completed" ? Theme.statusGood : Theme.statusBad

                ColumnLayout {
                    id: actionResultColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: 10
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: root.controller !== null && root.controller.lastActionResult.label ? root.controller.lastActionResult.label + " — " + root.controller.lastActionResult.status : ""
                        color: root.controller !== null && root.controller.lastActionStatus === "completed" ? Theme.statusGood : Theme.statusBad
                        font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                    }
                    Repeater {
                        model: root.controller !== null && root.controller.lastActionResult.lines ? root.controller.lastActionResult.lines : []
                        delegate: Label {
                            id: resultLineDelegate
                            required property var modelData
                            Layout.fillWidth: true
                            text: "• " + resultLineDelegate.modelData
                            color: Theme.text
                            wrapMode: Text.WordWrap
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: root.controller !== null && root.controller.lastActionResult.outputRoot ? "Evidence: " + root.controller.lastActionResult.outputRoot : ""
                        visible: text.length > 0
                        color: Theme.muted
                        font.pixelSize: 11
                        wrapMode: Text.WrapAnywhere
                    }
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
            Repeater {
                model: root.page.actions || []
                delegate: Button {
                    id: diagnosticDelegate
                    required property var modelData
                    objectName: "diagnosticActionControl"
                    Layout.fillWidth: true
                    visible: diagnosticDelegate.modelData.capabilityId === "diagnostic.run"
                    enabled: visible && diagnosticDelegate.modelData.enabled && root.controller !== null && !root.capabilityBusy
                    text: diagnosticDelegate.modelData.label || "Run audited diagnostic"
                    Accessible.name: text
                    onClicked: root.controller.runDiagnostic(diagnosticDelegate.modelData.actionId, [root.controller.currentProfileId])
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                visible: root.canRecordHandoff
                spacing: 8

                TextField {
                    id: stoppingPointControl
                    objectName: "handoffStoppingPointControl"
                    Layout.fillWidth: true
                    placeholderText: "Stopping point"
                    maximumLength: 1000
                }
                TextField {
                    id: nextStepControl
                    objectName: "handoffNextStepControl"
                    Layout.fillWidth: true
                    placeholderText: "Next local step"
                    maximumLength: 1000
                }
                TextArea {
                    id: handoffNoteControl
                    objectName: "handoffNoteControl"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 72
                    placeholderText: "Bounded operator note"
                    wrapMode: TextEdit.Wrap
                }
                Button {
                    objectName: "recordOperatorHandoffControl"
                    text: "Record handoff"
                    enabled: root.canRecordHandoff && stoppingPointControl.text.trim().length > 0
                    Accessible.name: text
                    onClicked: root.controller.recordOperatorHandoff(stoppingPointControl.text, nextStepControl.text, handoffNoteControl.text)
                }
            }
        }
    }
}
