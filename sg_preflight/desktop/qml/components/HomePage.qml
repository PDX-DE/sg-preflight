pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

Item {
    id: root

    required property var homeTiles
    required property int homeTileCount
    required property var payload
    required property string pageState
    required property bool reducedMotion
    signal navigateRequested(string routeId)
    property real firstTileWidth: 0
    property real firstTileHeight: 0
    property bool tileLayoutValid: false

    function updateTileMetrics() {
        firstTileWidth = tileRepeater.count > 0 ? tileRepeater.itemAt(0).width : 0;
        firstTileHeight = tileRepeater.count > 0 ? tileRepeater.itemAt(0).height : 0;
        for (let leftIndex = 0; leftIndex < tileRepeater.count; ++leftIndex) {
            const left = tileRepeater.itemAt(leftIndex);
            if (!left || left.width < 50 || left.height < 50) {
                tileLayoutValid = false;
                return;
            }
            for (let rightIndex = leftIndex + 1; rightIndex < tileRepeater.count; ++rightIndex) {
                const right = tileRepeater.itemAt(rightIndex);
                if (!right) {
                    tileLayoutValid = false;
                    return;
                }
                const overlaps = left.x < right.x + right.width && left.x + left.width > right.x && left.y < right.y + right.height && left.y + left.height > right.y;
                if (overlaps) {
                    tileLayoutValid = false;
                    return;
                }
            }
        }
        tileLayoutValid = tileRepeater.count === root.homeTileCount;
    }

    Timer {
        interval: 16
        repeat: true
        running: root.pageState !== "idle" && (root.firstTileWidth === 0 || !root.tileLayoutValid)
        onTriggered: root.updateTileMetrics()
    }

    ScrollView {
        anchors.fill: parent
        anchors.margins: 24
        clip: true

        ColumnLayout {
            width: Math.max(760, root.width - 64)
            spacing: 18

            Label {
                Layout.fillWidth: true
                text: root.payload.freshness_label || "Reading local activity…"
                color: Theme.muted
                font.pixelSize: 12
            }
            Label {
                Layout.fillWidth: true
                text: root.payload.summary || "Choose a local evidence surface to begin."
                color: Theme.text
                font.pixelSize: 15
                wrapMode: Text.WordWrap
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 3
                columnSpacing: 14
                rowSpacing: 14

                Repeater {
                    id: tileRepeater
                    objectName: "homeTileRepeater"
                    model: root.homeTileCount

                    delegate: FocusScope {
                        id: tile

                        required property int index
                        readonly property var tileData: root.homeTiles[index]
                        objectName: "homeTile" + index
                        implicitWidth: 250
                        implicitHeight: 118
                        activeFocusOnTab: true
                        Layout.fillWidth: true
                        Layout.minimumWidth: 210
                        Layout.minimumHeight: 118
                        Accessible.role: Accessible.Button
                        Accessible.name: "Open " + tileData.title
                        Keys.onReturnPressed: root.navigateRequested(tileData.routeId)
                        Keys.onEnterPressed: root.navigateRequested(tileData.routeId)
                        Keys.onSpacePressed: root.navigateRequested(tileData.routeId)

                        Rectangle {
                            anchors.fill: parent
                            radius: 12
                            color: tile.activeFocus || tileMouse.containsMouse ? Theme.raised : Theme.canvas
                            border.color: tile.activeFocus ? Theme.accent : Theme.border

                            Behavior on color {
                                ColorAnimation {
                                    duration: Theme.duration(Theme.motionShort, root.reducedMotion)
                                }
                            }
                        }
                        Label {
                            anchors.fill: parent
                            anchors.margins: 14
                            text: tile.tileData.title + "\n" + tile.tileData.subtitle
                            color: Theme.text
                            wrapMode: Text.WordWrap
                            verticalAlignment: Text.AlignVCenter
                        }
                        MouseArea {
                            id: tileMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: {
                                tile.forceActiveFocus();
                                root.navigateRequested(tile.tileData.routeId);
                            }
                        }
                        SequentialAnimation {
                            running: root.pageState !== "idle"
                            PauseAnimation {
                                duration: Theme.stagger(tile.index, root.reducedMotion)
                            }
                            NumberAnimation {
                                target: tile
                                property: "opacity"
                                from: 0
                                to: 1
                                duration: Theme.duration(Theme.motionShort, root.reducedMotion)
                            }
                        }
                    }
                }
            }
            Label {
                Layout.fillWidth: true
                text: root.payload.activity && root.payload.activity.length > 0 ? "Latest local activity" : root.payload.empty_message || "No local activity recorded yet."
                color: Theme.text
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }
            Repeater {
                model: root.payload.activity ? root.payload.activity.length : 0

                delegate: Rectangle {
                    id: activityRow

                    required property int index
                    readonly property var activityData: root.payload.activity[index]
                    Layout.fillWidth: true
                    Layout.minimumHeight: 58
                    radius: 8
                    color: Theme.canvas
                    border.color: Theme.border

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        Label {
                            text: activityRow.activityData.label
                            color: Theme.muted
                            Layout.preferredWidth: 180
                        }
                        Label {
                            text: activityRow.activityData.detail
                            color: Theme.text
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                        StatusBadge {
                            status: activityRow.activityData.status
                        }
                    }
                }
            }
        }
    }
}
