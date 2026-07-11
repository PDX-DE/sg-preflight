pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    objectName: "sgfxQtQuickWindow"
    required property var surfaceModel
    required property var desktopController
    width: 1280
    height: 720
    minimumWidth: 1024
    minimumHeight: 640
    visible: true
    title: "SGFX QA Preflight"
    color: "#111416"

    readonly property color canvasColor: "#111416"
    readonly property color panelColor: "#191e21"
    readonly property color raisedColor: "#22292d"
    readonly property color borderColor: "#344047"
    readonly property color accentColor: "#4ec9b0"
    readonly property color textColor: "#eef3f1"
    readonly property color mutedColor: "#a6b0b5"
    readonly property int motionFast: 120
    readonly property int motionNormal: 180

    Component.onCompleted: desktopController.initialize()

    Shortcut {
        sequence: "F5"
        onActivated: window.desktopController.refresh()
    }

    Shortcut {
        sequence: "Esc"
        onActivated: window.close()
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 292
            color: window.panelColor
            border.color: window.borderColor
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 14

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3

                    Label {
                        text: "SGFX QA Preflight"
                        color: window.textColor
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                    }

                    Label {
                        text: "Local, read-only delivery evidence"
                        color: window.mutedColor
                        font.pixelSize: 12
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: window.borderColor
                }

                ListView {
                    id: navigation
                    objectName: "surfaceNavigation"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 2
                    clip: true
                    model: window.surfaceModel
                    section.property: "group"
                    section.criteria: ViewSection.FullString

                    section.delegate: Item {
                        required property string section
                        width: navigation.width
                        height: 30

                        Label {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 6
                            text: parent.section
                            color: window.mutedColor
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                        }
                    }

                    delegate: ItemDelegate {
                        id: navigationItem
                        required property string surfaceId
                        required property string title
                        required property string subtitle
                        required property string group
                        required property string rendererKind
                        required property bool operational
                        width: navigation.width
                        height: 42
                        enabled: !operational || window.desktopController.currentProfileId.length > 0
                        hoverEnabled: true
                        padding: 10
                        onClicked: window.desktopController.navigate(surfaceId)

                        contentItem: Label {
                            text: navigationItem.title
                            color: window.textColor
                            font.pixelSize: 13
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }

                        background: Rectangle {
                            radius: 8
                            color: navigationItem.surfaceId === window.desktopController.currentPageId
                                   ? Qt.alpha(window.accentColor, 0.18)
                                   : navigationItem.hovered
                                     ? window.raisedColor
                                     : "transparent"
                            border.color: navigationItem.surfaceId === window.desktopController.currentPageId
                                          ? Qt.alpha(window.accentColor, 0.65)
                                          : "transparent"

                            Behavior on color {
                                ColorAnimation { duration: window.motionFast }
                            }
                        }
                    }

                    ScrollBar.vertical: ScrollBar { }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: window.canvasColor

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 36
                anchors.rightMargin: 36
                anchors.topMargin: 30
                anchors.bottomMargin: 30
                spacing: 22

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 18

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Label {
                            text: window.desktopController.pageTitle
                            color: window.textColor
                            font.pixelSize: 28
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }

                        Label {
                            text: window.desktopController.pageSubtitle
                            color: window.mutedColor
                            font.pixelSize: 14
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }

                    Rectangle {
                        implicitWidth: profileLabel.implicitWidth + 24
                        implicitHeight: 34
                        radius: 17
                        color: window.raisedColor
                        border.color: window.borderColor

                        Label {
                            id: profileLabel
                            anchors.centerIn: parent
                            text: window.desktopController.currentProfileId.length > 0
                                  ? window.desktopController.currentProfileId
                                  : "Profile not selected"
                            color: window.textColor
                            font.pixelSize: 12
                        }
                    }
                }

                Rectangle {
                    id: contentFrame
                    objectName: "pageFrame"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 14
                    color: window.panelColor
                    border.color: window.borderColor
                    border.width: 1
                    state: window.desktopController.pageState

                    Item {
                        id: pageContentHost
                        objectName: "pageContentHost"
                        readonly property var payload: window.desktopController.currentPayload
                        anchors.fill: parent
                        anchors.margins: 24
                        opacity: 0
                    }

                    Column {
                        id: loadingLayer
                        anchors.centerIn: parent
                        spacing: 12
                        opacity: 0

                        BusyIndicator {
                            anchors.horizontalCenter: parent.horizontalCenter
                            running: loadingLayer.opacity > 0
                        }

                        Label {
                            text: "Loading local evidence…"
                            color: window.mutedColor
                            font.pixelSize: 13
                        }
                    }

                    Label {
                        id: errorLayer
                        anchors.centerIn: parent
                        width: Math.min(parent.width - 80, 560)
                        text: window.desktopController.errorSummary
                        color: "#f2b8b5"
                        font.pixelSize: 14
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        opacity: 0
                    }

                    states: [
                        State {
                            name: "idle"
                            PropertyChanges { pageContentHost.opacity: 1 }
                        },
                        State {
                            name: "loading"
                            PropertyChanges { loadingLayer.opacity: 1 }
                        },
                        State {
                            name: "ready"
                            PropertyChanges { pageContentHost.opacity: 1 }
                        },
                        State {
                            name: "error"
                            PropertyChanges { errorLayer.opacity: 1 }
                        }
                    ]

                    transitions: Transition {
                        NumberAnimation {
                            properties: "opacity"
                            duration: window.motionNormal
                            easing.type: Easing.OutCubic
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true

                    Label {
                        text: window.desktopController.pageState === "loading"
                              ? "Reading operator-local evidence"
                              : "Read-only · Evidence only · Review stays manual"
                        color: window.mutedColor
                        font.pixelSize: 11
                    }

                    Item { Layout.fillWidth: true }

                    Label {
                        text: "F5 Refresh · Esc Close"
                        color: window.mutedColor
                        font.pixelSize: 11
                    }
                }
            }
        }
    }
}
