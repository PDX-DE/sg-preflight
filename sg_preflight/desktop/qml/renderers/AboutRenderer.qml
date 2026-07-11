pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

Item {
    id: root

    required property var page
    readonly property string rendererKind: "about"
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
                text: root.page.primaryText || "SGFX local QA preflight"
                color: Theme.text
                font.pixelSize: 20
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }
            Label {
                Layout.fillWidth: true
                text: "Local-only · Evidence-first · No telemetry"
                color: Theme.muted
                font.pixelSize: 12
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
                    id: aboutDelegate
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: aboutItem.implicitHeight + 20
                    radius: 8
                    color: Theme.raised
                    border.color: Theme.border
                    ColumnLayout {
                        id: aboutItem
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: 10
                        spacing: 4
                        Label {
                            Layout.fillWidth: true
                            text: aboutDelegate.modelData.label || "About"
                            color: Theme.text
                            font.weight: Font.DemiBold
                            wrapMode: Text.WordWrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: aboutDelegate.modelData.value || aboutDelegate.modelData.detail || "—"
                            color: Theme.muted
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }
}
