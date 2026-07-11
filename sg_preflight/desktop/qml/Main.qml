pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0
import "components" as Components

ApplicationWindow {
    id: window

    required property var surfaceModel
    required property var shellModel
    required property var desktopController
    readonly property var navigationGroupTitles: shellModel.groupOrder
    readonly property var homeTileIds: {
        const ids = [];
        for (let index = 0; index < shellModel.homeTiles.length; ++index)
            ids.push(shellModel.homeTiles[index].routeId);
        return ids;
    }
    readonly property bool moreGroupVisible: shellModel.hasMore
    readonly property real referenceScale: Math.min(width / 1280, height / 720)
    readonly property real referenceOffsetX: (width - 1280 * referenceScale) / 2
    readonly property real referenceOffsetY: (height - 720 * referenceScale) / 2
    readonly property real firstHomeTileWidth: homePage.firstTileWidth
    readonly property real firstHomeTileHeight: homePage.firstTileHeight
    readonly property bool homeTileLayoutValid: homePage.tileLayoutValid
    readonly property int reducedMotionDuration: Theme.duration(Theme.motionEmphasis, true)
    readonly property int reducedMotionTravel: Theme.travel(16, true)
    readonly property int reducedMotionStagger: Theme.stagger(5, true)
    readonly property string activeNavigationRouteId: navigationSidebar.currentRouteId
    readonly property bool profileSelectorFocused: profileSelector.activeFocus
    readonly property string selectedProfileValue: profileSelector.currentValue || ""
    property bool reducedMotion: false
    property bool jumpOpen: false
    property bool helpOpen: false
    property bool diagnosticsOpen: false
    property bool sidebarOpen: true
    property bool exitGuidanceVisible: false

    function handleShortcut(key: string) {
        if (key === "F1") {
            helpOpen = true;
        } else if (key === "F2") {
            profileSelector.forceActiveFocus();
        } else if (key === "F5") {
            desktopController.refresh();
        } else if (key === "F12") {
            diagnosticsOpen = true;
        } else if (key === "/") {
            jumpOpen = true;
        } else if (key === "Esc") {
            if (jumpOpen)
                jumpOpen = false;
            else if (helpOpen)
                helpOpen = false;
            else if (diagnosticsOpen)
                diagnosticsOpen = false;
            else if (sidebarOpen)
                sidebarOpen = false;
            else
                exitGuidanceVisible = true;
        }
    }

    function updateHomeTileMetrics() {
        homePage.updateTileMetrics();
    }

    objectName: "sgfxQtQuickWindow"
    width: 1280
    height: 720
    minimumWidth: 1024
    minimumHeight: 640
    visible: true
    title: "SGFX QA Preflight"
    color: Theme.canvas

    Component.onCompleted: desktopController.initialize()

    Shortcut {
        sequence: "F1"
        onActivated: window.handleShortcut("F1")
    }
    Shortcut {
        sequence: "F2"
        onActivated: window.handleShortcut("F2")
    }
    Shortcut {
        sequence: "F5"
        onActivated: window.handleShortcut("F5")
    }
    Shortcut {
        sequence: "F12"
        onActivated: window.handleShortcut("F12")
    }
    Shortcut {
        sequence: "/"
        onActivated: window.handleShortcut("/")
    }
    Shortcut {
        sequence: "Esc"
        onActivated: window.handleShortcut("Esc")
    }

    Item {
        id: referenceSurface
        x: window.referenceOffsetX
        y: window.referenceOffsetY
        width: 1280
        height: 720
        scale: window.referenceScale
        transformOrigin: Item.TopLeft

        RowLayout {
            anchors.fill: parent
            spacing: 0

            Components.NavigationSidebar {
                id: navigationSidebar
                objectName: "navigationSidebar"
                Layout.preferredWidth: window.sidebarOpen ? 292 : 0
                Layout.fillHeight: true
                shellModel: window.shellModel
                currentRouteId: window.desktopController.currentRouteId
                currentProfileId: window.desktopController.currentProfileId
                reducedMotion: window.reducedMotion
                visible: window.sidebarOpen
                onNavigateRequested: routeId => window.desktopController.navigate(routeId)
                onJumpRequested: window.handleShortcut("/")
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.canvas

                ColumnLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 36
                    anchors.rightMargin: 36
                    anchors.topMargin: 28
                    anchors.bottomMargin: 24
                    spacing: 18

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 18

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 5

                            Label {
                                Layout.fillWidth: true
                                text: window.desktopController.pageTitle
                                color: Theme.text
                                font.pixelSize: 28
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }
                            Label {
                                Layout.fillWidth: true
                                text: window.desktopController.pageSubtitle
                                color: Theme.muted
                                font.pixelSize: 14
                                wrapMode: Text.WordWrap
                            }
                        }

                        ComboBox {
                            id: profileSelector

                            function syncProfileIndex() {
                                const selected = window.desktopController.currentProfileId;
                                for (let index = 0; index < count; ++index) {
                                    if (valueAt(index) === selected) {
                                        currentIndex = index;
                                        return;
                                    }
                                }
                                currentIndex = -1;
                            }

                            objectName: "profileSelector"
                            Layout.minimumWidth: 230
                            Layout.preferredHeight: 50
                            model: window.desktopController.profileOptions
                            textRole: "label"
                            valueRole: "id"
                            enabled: count > 0
                            focusPolicy: Qt.StrongFocus
                            Accessible.role: Accessible.ComboBox
                            Accessible.name: "Selected car profile"
                            onActivated: window.desktopController.selectProfile(currentValue)
                            onCountChanged: Qt.callLater(syncProfileIndex)

                            Component.onCompleted: Qt.callLater(syncProfileIndex)

                            Connections {
                                target: window.desktopController

                                function onCurrentProfileChanged() {
                                    Qt.callLater(profileSelector.syncProfileIndex);
                                }

                                function onProfileOptionsChanged() {
                                    Qt.callLater(profileSelector.syncProfileIndex);
                                }
                            }
                        }
                    }

                    Rectangle {
                        id: contentFrame
                        objectName: "pageFrame"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 14
                        color: Theme.panel
                        border.color: Theme.border
                        border.width: 1

                        Components.HomePage {
                            id: homePage
                            anchors.fill: parent
                            visible: window.desktopController.currentRouteId === "home"
                            homeTiles: window.shellModel.homeTiles
                            homeTileCount: window.shellModel.homeTileCount
                            payload: window.desktopController.currentPayload
                            pageState: window.desktopController.pageState
                            reducedMotion: window.reducedMotion
                            onNavigateRequested: routeId => window.desktopController.navigate(routeId)
                        }

                        Components.PageFrame {
                            id: pageContentHost
                            objectName: "pageContentHost"
                            anchors.fill: parent
                            anchors.margins: 24
                            visible: window.desktopController.currentRouteId !== "home"
                            pageState: window.desktopController.pageState
                            page: window.desktopController.currentPayload
                            errorCode: window.desktopController.errorCode
                            errorSummary: window.desktopController.errorSummary
                            reducedMotion: window.reducedMotion
                            desktopController: window.desktopController
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true

                        Components.StatusBadge {
                            objectName: "shellStatus"
                            status: window.desktopController.pageState === "error" ? "error" : window.desktopController.currentPayload.status || window.desktopController.pageState
                        }
                        Label {
                            Layout.fillWidth: true
                            text: "Read-only · Evidence only · Review stays manual"
                            color: Theme.muted
                            font.pixelSize: 11
                        }
                        Label {
                            text: "/ Jump · F1 Help · F12 Diagnostics · Esc Back"
                            color: Theme.muted
                            font.pixelSize: 11
                        }
                    }
                }
            }
        }
    }

    Components.JumpPalette {
        id: jumpPalette
        anchors.fill: parent
        open: window.jumpOpen
        routes: window.shellModel.routes
        onCloseRequested: window.jumpOpen = false
        onNavigateRequested: routeId => {
            window.jumpOpen = false;
            window.desktopController.navigate(routeId);
        }
    }
    Components.ShortcutHelp {
        anchors.fill: parent
        open: window.helpOpen
        shortcuts: window.shellModel.shortcuts
        onCloseRequested: window.helpOpen = false
    }
    Rectangle {
        anchors.fill: parent
        visible: window.diagnosticsOpen
        color: "#b0000000"
        z: 100

        Rectangle {
            anchors.centerIn: parent
            width: 520
            height: 300
            radius: 14
            color: Theme.raised
            border.color: Theme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 28
                spacing: 12
                Label {
                    text: "Local diagnostics"
                    color: Theme.text
                    font.pixelSize: 22
                }
                Label {
                    text: "Route: " + window.desktopController.currentRouteId
                    color: Theme.text
                }
                Label {
                    text: "Profile: " + window.desktopController.currentProfileId
                    color: Theme.text
                }
                Label {
                    text: "Operation: " + window.desktopController.currentOperation
                    color: Theme.text
                }
                Label {
                    text: "Error: " + (window.desktopController.errorCode || "none")
                    color: Theme.text
                }
                Label {
                    text: "No paths, credentials, commands, or network details are shown."
                    color: Theme.muted
                }
                Item {
                    Layout.fillHeight: true
                }
                Button {
                    text: "Close diagnostics"
                    focusPolicy: Qt.StrongFocus
                    Accessible.role: Accessible.Button
                    Accessible.name: text
                    onClicked: window.diagnosticsOpen = false
                }
            }
        }
    }
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        visible: window.exitGuidanceVisible
        z: 120
        width: exitLabel.implicitWidth + 32
        height: 48
        radius: 12
        color: Theme.raised
        border.color: Theme.border

        Label {
            id: exitLabel
            anchors.centerIn: parent
            text: "Use the window close button to exit SGFX."
            color: Theme.text
        }
    }
}
