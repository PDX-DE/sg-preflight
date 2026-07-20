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
    property var grafiksHost: null
    readonly property var navigationGroupTitles: shellModel.groupOrder
    readonly property var pipelineGateIds: homePage.pipelineGateIds
    readonly property bool moreGroupVisible: shellModel.hasMore
    readonly property real referenceScale: Math.min(width / 1280, height / 720)
    readonly property real referenceOffsetX: (width - 1280 * referenceScale) / 2
    readonly property real referenceOffsetY: (height - 720 * referenceScale) / 2
    readonly property string primaryActionLabel: homePage.primaryActionLabel
    readonly property bool primaryActionEnabled: homePage.primaryActionEnabled
    readonly property string selectedGateId: homePage.selectedGateId
    readonly property int visibleCheckRowCount: homePage.visibleCheckRowCount
    readonly property int gateCount: homePage.pipelineGateIds.length
    readonly property int entranceDuration: Theme.entranceLimit
    readonly property int reducedMotionDuration: Theme.duration(Theme.motionEmphasis, true)
    readonly property int reducedMotionTravel: Theme.travel(16, true)
    readonly property int reducedMotionStagger: Theme.stagger(5, true)
    readonly property string activeNavigationRouteId: navigationSidebar.currentRouteId
    readonly property bool profileSelectorFocused: profileSelector.activeFocus
    readonly property bool profilePopoverOpen: profileSelector.popup.visible
    readonly property string selectedProfileValue: profileSelector.currentValue || ""
    readonly property var productFontFamilies: sgfxProductFonts
    readonly property bool primaryActionVisible: homePage.primaryActionVisible
    readonly property bool layoutWithinViewport: referenceSurface.x >= -0.5 && referenceSurface.y >= -0.5 && referenceSurface.x + referenceSurface.width * referenceSurface.scale <= width + 0.5 && referenceSurface.y + referenceSurface.height * referenceSurface.scale <= height + 0.5
    readonly property bool allAccessibleNamesPresent: profileSelector.Accessible.name.length > 0 && presentationViewControl.Accessible.name.length > 0 && grafiksLaunchControl.Accessible.name.length > 0 && homePage.allAccessibleNamesPresent && navigationSidebar.allAccessibleNamesPresent
    property bool reducedMotion: false
    property bool presentationView: false
    property bool jumpOpen: false
    property bool helpOpen: false
    property bool diagnosticsOpen: false
    property bool sidebarOpen: true
    property bool exitGuidanceVisible: false
    property bool shellInitializationStarted: false
    property var overlayReturnFocus: null

    function setPresentation(enabled: bool) {
        presentationView = enabled;
        sidebarOpen = !enabled;
        Qt.callLater(window.focusPagePrimary);
    }

    function focusProductStart() {
        profileSelector.forceActiveFocus();
    }

    function currentPagePrimaryAction() {
        if (desktopController.currentRouteId === "home")
            return homePage.primaryActionItem;
        return pageContentHost.item ? pageContentHost.item.primaryActionItem : null;
    }

    function focusPagePrimary() {
        const target = currentPagePrimaryAction();
        if (target && target.visible && target.enabled) {
            target.forceActiveFocus();
        } else if (presentationView) {
            exitPresentation.forceActiveFocus();
        } else {
            presentationViewControl.forceActiveFocus();
        }
    }

    function restoreOverlayFocus() {
        const target = overlayReturnFocus;
        overlayReturnFocus = null;
        Qt.callLater(() => {
            if (target && target.visible && target.enabled)
                target.forceActiveFocus();
            else
                presentationViewControl.forceActiveFocus();
        });
    }

    function openOverlay(kind: string) {
        if (!jumpOpen && !helpOpen && !diagnosticsOpen)
            overlayReturnFocus = window.activeFocusItem;
        jumpOpen = kind === "jump";
        helpOpen = kind === "help";
        diagnosticsOpen = kind === "diagnostics";
        exitGuidanceVisible = false;
    }

    function closeOverlay() {
        jumpOpen = false;
        helpOpen = false;
        diagnosticsOpen = false;
        restoreOverlayFocus();
    }

    function openProfilePopover() {
        profileSelector.popup.open();
    }

    function closeProfilePopover() {
        profileSelector.popup.close();
    }

    function handleShortcut(key: string) {
        if (key === "F1") {
            openOverlay("help");
        } else if (key === "F2") {
            profileSelector.forceActiveFocus();
        } else if (key === "F5") {
            desktopController.refresh();
        } else if (key === "F12") {
            openOverlay("diagnostics");
        } else if (key === "/") {
            openOverlay("jump");
        } else if (key === "Esc") {
            if (jumpOpen || helpOpen || diagnosticsOpen)
                closeOverlay();
            else if (presentationView)
                setPresentation(false);
            else if (desktopController.currentRouteId !== "home")
                desktopController.navigate("home");
            else
                exitGuidanceVisible = true;
        }
    }

    objectName: "sgfxQtQuickWindow"
    width: 1280
    height: 720
    minimumWidth: 1024
    minimumHeight: 640
    visible: true
    title: "Seriengrafik: Project Quality-Hero"
    color: Theme.canvas

    onFrameSwapped: {
        if (!shellInitializationStarted) {
            shellInitializationStarted = true;
            Qt.callLater(desktopController.initialize);
        }
    }

    onReducedMotionChanged: desktopController.setPreviewReducedMotion(reducedMotion)
    onDiagnosticsOpenChanged: {
        if (diagnosticsOpen)
            Qt.callLater(diagnosticsCloseControl.forceActiveFocus);
    }

    Component.onCompleted: {
        desktopController.setPreviewReducedMotion(reducedMotion);
        Qt.callLater(window.focusProductStart);
    }

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
                Layout.preferredWidth: window.sidebarOpen && !window.presentationView ? 292 : 0
                Layout.fillHeight: true
                shellModel: window.shellModel
                currentRouteId: window.desktopController.currentRouteId
                currentProfileId: window.desktopController.currentProfileId
                reducedMotion: window.reducedMotion
                visible: window.sidebarOpen && !window.presentationView
                onNavigateRequested: routeId => window.desktopController.navigate(routeId)
                onJumpRequested: window.handleShortcut("/")
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.canvas

                ColumnLayout {
                    anchors.fill: parent
                    anchors.leftMargin: window.presentationView ? 18 : 36
                    anchors.rightMargin: window.presentationView ? 18 : 36
                    anchors.topMargin: window.presentationView ? 18 : 28
                    anchors.bottomMargin: window.presentationView ? 18 : 24
                    spacing: window.presentationView ? 0 : 18

                    RowLayout {
                        id: headerChrome

                        objectName: "headerChrome"
                        Layout.fillWidth: true
                        visible: !window.presentationView
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
                            KeyNavigation.tab: presentationViewControl
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
                        Button {
                            id: presentationViewControl

                            objectName: "presentationViewControl"
                            Layout.preferredHeight: 50
                            text: "Presentation view"
                            focusPolicy: Qt.StrongFocus
                            Accessible.role: Accessible.Button
                            Accessible.name: text
                            KeyNavigation.tab: grafiksLaunchControl.enabled ? grafiksLaunchControl : window.currentPagePrimaryAction()
                            KeyNavigation.backtab: profileSelector
                            Keys.onTabPressed: event => {
                                if (grafiksLaunchControl.enabled)
                                    grafiksLaunchControl.forceActiveFocus();
                                else
                                    window.focusPagePrimary();
                                event.accepted = true;
                            }
                            onClicked: window.setPresentation(true)
                        }
                        Button {
                            id: grafiksLaunchControl

                            objectName: "grafiksLaunchControl"
                            Layout.preferredHeight: 50
                            text: {
                                if (window.grafiksHost === null)
                                    return "3D inspection unavailable";
                                if (window.grafiksHost.state === "validating")
                                    return "Checking 3D inspection…";
                                if (window.grafiksHost.state === "starting")
                                    return "Starting 3D inspection…";
                                if (window.grafiksHost.state === "running")
                                    return "3D inspection running";
                                return "Open 3D inspection";
                            }
                            enabled: window.grafiksHost !== null && window.grafiksHost.canLaunch && window.desktopController.currentProfileId.length > 0
                            focusPolicy: Qt.StrongFocus
                            Accessible.role: Accessible.Button
                            Accessible.name: text
                            KeyNavigation.tab: window.currentPagePrimaryAction()
                            KeyNavigation.backtab: presentationViewControl
                            Keys.onTabPressed: event => {
                                window.focusPagePrimary();
                                event.accepted = true;
                            }
                            onClicked: window.desktopController.invokeCapability("grafiks.launch", {
                                "profile_id": window.desktopController.currentProfileId
                            })
                        }
                    }

                    Rectangle {
                        id: contentFrame
                        objectName: "pageFrame"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: window.presentationView ? 20 : 14
                        color: Theme.panel
                        border.color: Theme.border
                        border.width: 1

                        Components.HomePage {
                            id: homePage
                            anchors.fill: parent
                            visible: window.desktopController.currentRouteId === "home"
                            payload: window.desktopController.currentPayload
                            pageState: window.desktopController.pageState
                            capabilityState: window.desktopController.capabilityState
                            desktopController: window.desktopController
                            previewState: window.desktopController.previewState
                            previewToken: window.desktopController.previewToken
                            previewFrameCount: window.desktopController.previewFrameCount
                            previewFrameIndex: window.desktopController.previewFrameIndex
                            previewLabel: window.desktopController.previewLabel
                            reducedMotion: window.reducedMotion
                            onProfileRequested: profileId => window.desktopController.selectProfile(profileId)
                            onActionRequested: (capabilityId, inputs) => window.desktopController.invokeCapability(capabilityId, inputs)
                            onRouteRequested: routeId => window.desktopController.navigate(routeId)
                            onInspectionRequested: window.desktopController.invokeCapability("grafiks.launch", {
                                "profile_id": window.desktopController.currentProfileId
                            })
                            onPreviewFrameRequested: frameIndex => window.desktopController.selectPreviewFrame(frameIndex)
                            onFocusNavigationRequested: navigationSidebar.focusFirst()
                        }

                        Loader {
                            id: pageContentHost
                            objectName: "pageContentHost"
                            anchors.fill: parent
                            anchors.margins: 24
                            active: window.desktopController.currentRouteId !== "home"
                            sourceComponent: Components.PageFrame {
                                anchors.fill: parent
                                pageState: window.desktopController.pageState
                                page: window.desktopController.currentPayload
                                errorCode: window.desktopController.errorCode
                                errorSummary: window.desktopController.errorSummary
                                reducedMotion: window.reducedMotion
                                desktopController: window.desktopController
                            }
                        }

                        Button {
                            id: exitPresentation

                            objectName: "exitPresentationControl"
                            anchors.bottom: parent.bottom
                            anchors.right: parent.right
                            anchors.margins: 14
                            z: 4
                            visible: window.presentationView
                            text: "Esc · Exit presentation"
                            focusPolicy: Qt.StrongFocus
                            Accessible.role: Accessible.Button
                            Accessible.name: text
                            onClicked: window.setPresentation(false)

                            background: Rectangle {
                                radius: 8
                                color: Theme.raised
                                border.color: exitPresentation.activeFocus ? Theme.accent : Theme.border
                                border.width: exitPresentation.activeFocus ? 2 : 1
                            }

                            contentItem: Label {
                                text: exitPresentation.text
                                color: Theme.muted
                                font.family: Theme.operationalFont
                                font.pixelSize: 11
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }

                    RowLayout {
                        id: footerChrome

                        objectName: "footerChrome"
                        Layout.fillWidth: true
                        visible: !window.presentationView

                        Components.StatusBadge {
                            objectName: "shellStatus"
                            status: window.desktopController.pageState === "error" ? "error" : window.desktopController.currentPayload.status || window.desktopController.pageState
                        }
                        Label {
                            Layout.fillWidth: true
                            text: window.grafiksHost !== null && window.grafiksHost.errorSummary ? window.grafiksHost.errorSummary : "Read-only · Evidence only · Review stays manual"
                            color: window.grafiksHost !== null && window.grafiksHost.errorSummary ? Theme.statusBad : Theme.muted
                            font.pixelSize: 11
                        }
                        Label {
                            visible: window.grafiksHost !== null && window.grafiksHost.state !== "idle"
                            text: "3D inspection: " + (window.grafiksHost !== null ? window.grafiksHost.state : "unavailable")
                            color: Theme.muted
                            font.pixelSize: 11
                        }
                        Label {
                            text: "/ Jump · F1 Help · F12 Diagnostics · Esc closes overlays or returns Home"
                            color: Theme.muted
                            font.pixelSize: 11
                        }
                    }
                }
            }
        }
    }

    Loader {
        anchors.fill: parent
        active: window.jumpOpen
        sourceComponent: Components.JumpPalette {
            anchors.fill: parent
            open: window.jumpOpen
            routes: window.shellModel.routes
            onCloseRequested: window.closeOverlay()
            onNavigateRequested: routeId => {
                window.closeOverlay();
                window.desktopController.navigate(routeId);
            }
        }
    }
    Loader {
        anchors.fill: parent
        active: window.helpOpen
        sourceComponent: Components.ShortcutHelp {
            anchors.fill: parent
            open: window.helpOpen
            shortcuts: window.shellModel.shortcuts
            onCloseRequested: window.closeOverlay()
        }
    }
    FocusScope {
        id: diagnosticsOverlay

        objectName: "diagnosticsOverlay"
        anchors.fill: parent
        visible: window.diagnosticsOpen
        focus: visible
        z: 100
        Accessible.role: Accessible.Dialog
        Accessible.name: "Local diagnostics"

        Rectangle {
            anchors.fill: parent
            color: "#b0000000"
        }

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
                    text: "3D inspection: " + (window.grafiksHost !== null ? window.grafiksHost.state : "unavailable")
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
                    id: diagnosticsCloseControl

                    objectName: "diagnosticsCloseControl"
                    text: "Close diagnostics"
                    focusPolicy: Qt.StrongFocus
                    Accessible.role: Accessible.Button
                    Accessible.name: text
                    KeyNavigation.tab: diagnosticsCloseControl
                    KeyNavigation.backtab: diagnosticsCloseControl
                    onClicked: window.closeOverlay()
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
