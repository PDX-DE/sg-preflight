pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0
import "../renderers" as Renderers

Item {
    id: root

    required property string pageState
    required property var page
    required property string errorCode
    required property string errorSummary
    required property bool reducedMotion
    property var desktopController: null
    readonly property string rendererKind: root.page && root.page.rendererKind ? root.page.rendererKind : ""
    readonly property Item homeActionItem: homeControl
    readonly property bool capabilityBusy: root.desktopController !== null && (root.desktopController.capabilityState === "queued" || root.desktopController.capabilityState === "running")
    readonly property string actionReadinessState: root.page && root.page.actionReadinessState ? root.page.actionReadinessState : ""
    readonly property bool actionReadinessLoading: root.actionReadinessState === "loading"
    readonly property bool rendererOwnsPrimaryAction: {
        if (!root.page)
            return false;
        if (root.page.surfaceId === "manual-review" || root.page.surfaceId === "operator-handoff")
            return true;
        const actions = root.page.actions || [];
        for (let index = 0; index < actions.length; ++index) {
            if (actions[index].capabilityId === "diagnostic.run" && actions[index].enabled)
                return true;
        }
        return false;
    }
    readonly property Item primaryActionItem: root.rendererOwnsPrimaryAction && rendererLoader.item ? rendererLoader.item.primaryActionItem : refreshControl

    RowLayout {
        id: orientationBar

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 40
        spacing: 10

        Button {
            id: homeControl

            objectName: "pageHomeControl"
            text: "Home"
            enabled: root.desktopController !== null
            focusPolicy: Qt.StrongFocus
            Accessible.role: Accessible.Button
            Accessible.name: "Return to QA overview"
            onClicked: root.desktopController.navigate("home")
        }
        Label {
            id: breadcrumbText

            objectName: "pageBreadcrumbText"
            Layout.fillWidth: true
            text: "QA overview / " + (root.desktopController !== null ? root.desktopController.pageTitle : "")
            color: Theme.muted
            font.pixelSize: 12
            elide: Text.ElideRight
            Accessible.role: Accessible.StaticText
            Accessible.name: text
        }
        Label {
            id: profileBadge

            objectName: "pageProfileBadge"
            text: "Selected car: " + (root.desktopController !== null && root.desktopController.currentProfileId.length > 0 ? root.desktopController.currentProfileId : "Not selected")
            color: Theme.text
            font.pixelSize: 12
            font.weight: Font.DemiBold
            leftPadding: 10
            rightPadding: 10
            topPadding: 6
            bottomPadding: 6
            Accessible.role: Accessible.StaticText
            Accessible.name: text

            background: Rectangle {
                radius: 8
                color: Theme.raised
                border.color: Theme.border
            }
        }
    }

    Component {
        id: overviewComponent
        Renderers.OverviewRenderer {
            page: root.page
        }
    }
    Component {
        id: matrixComponent
        Renderers.MatrixRenderer {
            page: root.page
        }
    }
    Component {
        id: evidenceComponent
        Renderers.EvidenceRenderer {
            page: root.page
        }
    }
    Component {
        id: workflowComponent
        Renderers.WorkflowRenderer {
            page: root.page
            controller: root.desktopController
        }
    }
    Component {
        id: reviewComponent
        Renderers.ReviewRenderer {
            page: root.page
            controller: root.desktopController
        }
    }
    Component {
        id: aboutComponent
        Renderers.AboutRenderer {
            page: root.page
        }
    }

    ActionFeedback {
        id: actionFeedback

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: orientationBar.bottom
        anchors.topMargin: 10
        controller: root.desktopController
        reducedMotion: root.reducedMotion
    }

    Loader {
        id: rendererLoader
        objectName: "readyRenderer"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: actionFeedback.visible ? actionFeedback.bottom : orientationBar.bottom
        anchors.bottom: parent.bottom
        anchors.topMargin: 10
        anchors.bottomMargin: pageActionBar.visible ? 58 : 0
        active: root.pageState === "ready"
        sourceComponent: {
            switch (root.rendererKind) {
            case "overview":
                return overviewComponent;
            case "matrix":
                return matrixComponent;
            case "evidence":
                return evidenceComponent;
            case "workflow":
                return workflowComponent;
            case "review":
                return reviewComponent;
            case "about":
                return aboutComponent;
            default:
                return undefined;
            }
        }
    }

    RowLayout {
        id: pageActionBar

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        visible: Boolean(root.pageState === "ready" && root.page)
        spacing: 8

        BusyIndicator {
            id: actionReadinessProgress

            objectName: "actionReadinessProgress"
            visible: root.actionReadinessLoading
            running: visible
            Layout.preferredWidth: 24
            Layout.preferredHeight: 24
            Accessible.role: Accessible.Indicator
            Accessible.name: "Checking local actions"
        }
        Label {
            id: actionReadinessMessage

            objectName: "actionReadinessMessage"
            Layout.fillWidth: true
            text: {
                if (root.actionReadinessState === "loading")
                    return root.page.actionReadinessMessage || "Checking local actions…";
                if (root.actionReadinessState === "unavailable")
                    return root.page.actionReadinessMessage || "Local actions are unavailable.";
                return root.page && root.page.artifacts && root.page.artifacts.length > 0 ? "Local page actions and evidence" : "Local page actions";
            }
            color: Theme.muted
            font.pixelSize: 11
            elide: Text.ElideRight
            Accessible.role: Accessible.StaticText
            Accessible.name: text
        }
        Button {
            id: refreshControl

            objectName: "pageRefreshControl"
            property bool primaryAction: !root.rendererOwnsPrimaryAction && !root.actionReadinessLoading
            text: "Refresh local evidence"
            highlighted: primaryAction
            enabled: root.desktopController !== null && !root.capabilityBusy
            Layout.preferredHeight: primaryAction ? 44 : 36
            font.weight: primaryAction ? Font.DemiBold : Font.Normal
            Accessible.name: text
            onClicked: root.desktopController.refresh()
        }
        Repeater {
            model: root.page.artifacts || []
            delegate: Button {
                id: artifactDelegate
                required property var modelData
                objectName: "artifactRevealControl"
                property bool primaryAction: false
                text: artifactDelegate.modelData.label || "Reveal artifact"
                highlighted: false
                enabled: root.desktopController !== null && !root.capabilityBusy
                Accessible.name: text
                onClicked: root.desktopController.revealArtifact(artifactDelegate.modelData.artifactId)
            }
        }
    }

    Label {
        anchors.centerIn: parent
        visible: root.pageState === "idle"
        text: "Choose a local evidence page."
        color: Theme.muted
        font.pixelSize: 14
    }
    BusyIndicator {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: -22
        running: visible
        visible: root.pageState === "loading"
    }
    Label {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: 28
        visible: root.pageState === "loading"
        text: "Loading local evidence…"
        color: Theme.muted
        font.pixelSize: 14
    }
    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 620)
        visible: root.pageState === "error"
        spacing: 10

        Label {
            Layout.fillWidth: true
            text: "Evidence unavailable"
            color: Theme.statusBad
            font.pixelSize: 18
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
        }
        Label {
            Layout.fillWidth: true
            text: root.errorSummary || "The local page evidence could not be loaded."
            color: Theme.muted
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
        }
    }
    Label {
        anchors.centerIn: parent
        visible: root.pageState === "ready" && rendererLoader.sourceComponent === undefined
        text: "This local evidence renderer is unavailable."
        color: Theme.statusBad
        wrapMode: Text.WordWrap
    }
}
