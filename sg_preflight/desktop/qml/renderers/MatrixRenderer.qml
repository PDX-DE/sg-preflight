pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

Item {
    id: root

    required property var page
    readonly property string rendererKind: "matrix"
    readonly property int renderedItemCount: root.page.visibleItems ? root.page.visibleItems.length : 0
    readonly property string renderedStatus: root.page.status || ""

    ScrollView {
        id: scroll
        anchors.fill: parent
        clip: true
        contentWidth: Math.max(availableWidth, 760)

        ColumnLayout {
            width: Math.max(scroll.availableWidth, 760)
            spacing: 10

            Label {
                objectName: "primaryPayloadText"
                Layout.fillWidth: true
                text: root.page.primaryText || "No matrix rows available"
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
                    text: root.page.provenance && root.page.provenance.source ? root.page.provenance.source : ""
                    color: Theme.muted
                    visible: text.length > 0
                }
                Label {
                    text: root.page.provenance && root.page.provenance.revision ? root.page.provenance.revision : ""
                    color: Theme.muted
                    visible: text.length > 0
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: ["Evidence", "Expected", "Actual", "Diff", "Status"]
                    delegate: Label {
                        required property string modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: modelData === "Evidence" ? 220 : 120
                        text: modelData
                        color: Theme.muted
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                }
            }
            Repeater {
                model: root.page.visibleItems || []
                delegate: Rectangle {
                    id: matrixDelegate
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 54
                    radius: 7
                    color: Theme.raised
                    border.color: Theme.border

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 8
                        Label {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 220
                            text: matrixDelegate.modelData.label || matrixDelegate.modelData.value || "Evidence"
                            color: Theme.text
                            elide: Text.ElideRight
                        }
                        Label {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 120
                            text: matrixDelegate.modelData.expected || "—"
                            color: Theme.muted
                            elide: Text.ElideMiddle
                        }
                        Label {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 120
                            text: matrixDelegate.modelData.actual || matrixDelegate.modelData.value || "—"
                            color: Theme.muted
                            elide: Text.ElideMiddle
                        }
                        Label {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 120
                            text: matrixDelegate.modelData.diff || "—"
                            color: Theme.muted
                            elide: Text.ElideMiddle
                        }
                        Label {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 120
                            text: matrixDelegate.modelData.status || root.renderedStatus
                            color: Theme.text
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }
}
