pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

Item {
    id: root

    required property var page
    property var controller: null
    readonly property string rendererKind: "review"
    readonly property int renderedItemCount: root.page.visibleItems ? root.page.visibleItems.length : 0
    readonly property string renderedStatus: root.page.status || ""
    property int selectedStepIndex: 0
    readonly property bool capabilityBusy: root.controller !== null && (root.controller.capabilityState === "queued" || root.controller.capabilityState === "running")
    readonly property Item primaryActionItem: recordReviewControl
    readonly property bool canRecord: {
        const actions = root.page.actions || [];
        for (let index = 0; index < actions.length; ++index) {
            if (actions[index].capabilityId === "manual_review.record" && actions[index].enabled)
                return root.controller !== null && !root.capabilityBusy;
        }
        return false;
    }
    readonly property string currentStepId: root.page.visibleItems && root.selectedStepIndex >= 0 && root.selectedStepIndex < root.page.visibleItems.length ? root.page.visibleItems[root.selectedStepIndex].itemId : ""

    onPageChanged: root.selectedStepIndex = 0

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
                text: root.page.primaryText || "No manual-review evidence available"
                color: Theme.text
                font.pixelSize: 20
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }
            Label {
                Layout.fillWidth: true
                text: root.page.ownershipNote || "The operator owns every review verdict."
                color: Theme.muted
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
                delegate: Rectangle {
                    id: reviewDelegate
                    required property int index
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: reviewItem.implicitHeight + 20
                    radius: 8
                    color: Theme.raised
                    border.color: root.canRecord && root.selectedStepIndex === reviewDelegate.index ? Theme.accent : Theme.border
                    TapHandler {
                        enabled: root.canRecord
                        onTapped: root.selectedStepIndex = reviewDelegate.index
                    }
                    ColumnLayout {
                        id: reviewItem
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: 10
                        spacing: 4
                        Label {
                            Layout.fillWidth: true
                            text: (reviewDelegate.index + 1) + ". " + (reviewDelegate.modelData.label || "Review step")
                            color: Theme.text
                            font.weight: Font.DemiBold
                            wrapMode: Text.WordWrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: reviewDelegate.modelData.value || reviewDelegate.modelData.detail || "Pending operator review"
                            color: Theme.muted
                            wrapMode: Text.WordWrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: reviewDelegate.modelData.status || root.renderedStatus
                            color: Theme.muted
                            font.pixelSize: 11
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                ComboBox {
                    id: verdictControl
                    objectName: "reviewVerdictControl"
                    Layout.preferredWidth: 220
                    model: ["passed", "failed", "skipped", "incomplete"]
                    enabled: root.canRecord
                    Accessible.name: root.canRecord ? "Manual review verdict" : "Manual verdict is read-only in evidence-only mode"
                }
                TextArea {
                    id: noteControl
                    objectName: "reviewNoteControl"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 72
                    placeholderText: "Bounded operator note"
                    readOnly: !root.canRecord
                    wrapMode: TextEdit.Wrap
                    Accessible.name: root.canRecord ? "Manual review note" : "Manual review note is read-only"
                }
                Button {
                    id: recordReviewControl

                    objectName: "recordManualReviewControl"
                    property bool primaryAction: true
                    text: "Record verdict"
                    enabled: root.canRecord && root.currentStepId.length > 0
                    highlighted: primaryAction
                    Layout.preferredHeight: 44
                    font.weight: Font.DemiBold
                    Accessible.name: text
                    onClicked: root.controller.recordManualReview(root.currentStepId, verdictControl.currentText, noteControl.text)
                }
            }
        }
    }
}
