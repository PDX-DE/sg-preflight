pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

Item {
    id: root

    required property var page
    readonly property string rendererKind: "review"
    readonly property int renderedItemCount: root.page.visibleItems ? root.page.visibleItems.length : 0
    readonly property string renderedStatus: root.page.status || ""

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
                    border.color: Theme.border
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
                    objectName: "reviewVerdictControl"
                    Layout.preferredWidth: 220
                    model: ["Operator verdict unavailable in evidence-only mode"]
                    enabled: false
                    Accessible.name: "Manual verdict is read-only in evidence-only mode"
                }
                TextArea {
                    objectName: "reviewNoteControl"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 72
                    text: "Notes become editable only through the audited capability boundary."
                    readOnly: true
                    wrapMode: TextEdit.Wrap
                    Accessible.name: "Manual review note is read-only"
                }
            }
        }
    }
}
