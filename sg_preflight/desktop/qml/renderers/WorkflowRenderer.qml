pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

Item {
    id: root

    required property var page
    readonly property string rendererKind: "workflow"
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
        }
    }
}
