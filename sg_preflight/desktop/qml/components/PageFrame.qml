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

    Loader {
        id: rendererLoader
        objectName: "readyRenderer"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: orientationBar.bottom
        anchors.bottom: parent.bottom
        anchors.topMargin: 10
        anchors.bottomMargin: artifactBar.visible ? 52 : 0
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
        id: artifactBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        visible: Boolean(root.pageState === "ready" && root.page && root.page.artifacts && root.page.artifacts.length > 0)
        spacing: 8

        Label {
            Layout.fillWidth: true
            text: "Local evidence artifacts"
            color: Theme.muted
            font.pixelSize: 11
        }
        Repeater {
            model: root.page.artifacts || []
            delegate: Button {
                id: artifactDelegate
                required property var modelData
                objectName: "artifactRevealControl"
                text: artifactDelegate.modelData.label || "Reveal artifact"
                enabled: root.desktopController !== null
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
