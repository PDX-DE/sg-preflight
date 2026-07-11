pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

Item {
    id: root

    required property var page
    readonly property string rendererKind: "evidence"
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
                text: root.page.primaryText || "No evidence available"
                color: Theme.text
                font.pixelSize: 20
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: provenanceColumn.implicitHeight + 20
                radius: 8
                color: Theme.raised
                border.color: Theme.border

                ColumnLayout {
                    id: provenanceColumn
                    objectName: "payloadDetailRegion"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: 10
                    spacing: 3
                    Label {
                        text: "Provenance"
                        color: Theme.muted
                        font.pixelSize: 11
                    }
                    Label {
                        Layout.fillWidth: true
                        text: root.page.provenance && root.page.provenance.source ? root.page.provenance.source : "Local evidence"
                        color: Theme.text
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
            }
            Repeater {
                model: root.page.visibleItems || []
                delegate: Rectangle {
                    id: evidenceDelegate
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: evidenceItem.implicitHeight + 20
                    radius: 8
                    color: Theme.raised
                    border.color: Theme.border
                    ColumnLayout {
                        id: evidenceItem
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: 10
                        spacing: 4
                        Label {
                            Layout.fillWidth: true
                            text: evidenceDelegate.modelData.label || "Evidence"
                            color: Theme.text
                            font.weight: Font.DemiBold
                            wrapMode: Text.WordWrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: evidenceDelegate.modelData.value || evidenceDelegate.modelData.detail || "—"
                            color: Theme.muted
                            wrapMode: Text.WordWrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: evidenceDelegate.modelData.revision || evidenceDelegate.modelData.source || ""
                            color: Theme.muted
                            font.pixelSize: 11
                            visible: text.length > 0
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }
}
