pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

Item {
    id: root

    objectName: "pageActionFeedback"
    property var controller: null
    property bool reducedMotion: false
    readonly property bool busy: root.controller !== null && (root.controller.capabilityState === "queued" || root.controller.capabilityState === "running")
    readonly property bool errorVisible: !root.busy && root.controller !== null && root.controller.capabilityError.length > 0
    readonly property bool resultVisible: !root.busy && !root.errorVisible && root.controller !== null && (root.controller.lastActionStatus.length > 0 || root.controller.capabilityState !== "idle")
    readonly property string selectedCar: root.controller !== null && root.controller.currentProfileId.length > 0 ? root.controller.currentProfileId : "Not selected"

    visible: root.busy || root.errorVisible || root.resultVisible
    implicitHeight: visible ? feedbackColumn.implicitHeight : 0
    Accessible.role: Accessible.StaticText
    Accessible.name: {
        if (root.busy)
            return runningActionText.text;
        if (root.errorVisible)
            return capabilityLifecycleText.text;
        return resultTitle.text;
    }

    ColumnLayout {
        id: feedbackColumn

        anchors.fill: parent
        spacing: 0

        Rectangle {
            objectName: "pageActionBusyBanner"
            Layout.fillWidth: true
            implicitHeight: busyContent.implicitHeight + 20
            visible: root.busy
            radius: 8
            color: Theme.raised
            border.color: Theme.accent

            RowLayout {
                id: busyContent

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: 10
                spacing: 10

                BusyIndicator {
                    running: root.busy && !root.reducedMotion
                    visible: !root.reducedMotion
                    Layout.preferredWidth: 28
                    Layout.preferredHeight: 28
                }
                Label {
                    id: runningActionText

                    objectName: "runningActionText"
                    Layout.fillWidth: true
                    text: {
                        const label = root.controller !== null && root.controller.activeActionLabel.length > 0 ? root.controller.activeActionLabel : "Local action";
                        return label + " for " + root.selectedCar + "…";
                    }
                    color: Theme.text
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }
                Button {
                    objectName: "cancelDiagnosticControl"
                    text: "Cancel queued diagnostic"
                    visible: root.controller !== null && root.controller.diagnosticCanCancel
                    enabled: visible
                    Accessible.name: text
                    onClicked: root.controller.cancelDiagnostic()
                }
            }
        }

        Rectangle {
            objectName: "pageActionErrorCard"
            Layout.fillWidth: true
            implicitHeight: capabilityLifecycleText.implicitHeight + 20
            visible: root.errorVisible
            radius: 8
            color: Theme.raised
            border.color: Theme.statusBad

            Label {
                id: capabilityLifecycleText

                objectName: "capabilityLifecycleText"
                anchors.fill: parent
                anchors.margins: 10
                text: root.controller !== null ? root.controller.capabilityError : ""
                color: Theme.statusBad
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }
        }

        Rectangle {
            id: actionResultPanel

            objectName: "actionResultPanel"
            readonly property color semanticColor: {
                if (root.controller !== null && root.controller.capabilityState === "completed")
                    return Theme.statusGood;
                if (root.controller !== null && root.controller.capabilityState === "failed")
                    return Theme.statusBad;
                return Theme.muted;
            }
            Layout.fillWidth: true
            implicitHeight: resultColumn.implicitHeight + 20
            visible: root.resultVisible
            radius: 8
            color: Theme.raised
            border.color: semanticColor

            ColumnLayout {
                id: resultColumn

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: 10
                spacing: 4

                Label {
                    id: resultTitle

                    objectName: "pageActionFeedbackTitle"
                    Layout.fillWidth: true
                    text: {
                        if (root.controller === null)
                            return "";
                        const result = root.controller.lastActionResult;
                        const label = result.label || root.controller.activeActionLabel || "Local action";
                        const status = result.status || root.controller.capabilityState;
                        return label + " — " + status;
                    }
                    color: actionResultPanel.semanticColor
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }
                Repeater {
                    model: root.controller !== null && root.controller.lastActionResult.lines ? root.controller.lastActionResult.lines : []
                    delegate: Label {
                        id: resultLineDelegate

                        required property var modelData
                        Layout.fillWidth: true
                        text: "• " + resultLineDelegate.modelData
                        color: Theme.text
                        wrapMode: Text.WordWrap
                    }
                }
                Repeater {
                    model: root.controller !== null && root.controller.lastActionResult.findings ? root.controller.lastActionResult.findings : []
                    delegate: ColumnLayout {
                        id: findingDelegate

                        required property var modelData
                        objectName: "actionFindingRow"
                        Layout.fillWidth: true
                        spacing: 1

                        Label {
                            Layout.fillWidth: true
                            text: findingDelegate.modelData.message
                            color: findingDelegate.modelData.severity === "error" ? Theme.statusBad : findingDelegate.modelData.severity === "warning" ? Theme.statusWarn : Theme.muted
                            font.weight: Font.DemiBold
                            wrapMode: Text.WordWrap
                        }
                        Label {
                            Layout.fillWidth: true
                            text: {
                                const parts = [];
                                if (findingDelegate.modelData.location)
                                    parts.push(findingDelegate.modelData.location);
                                if (findingDelegate.modelData.expected !== "" && findingDelegate.modelData.actual !== "")
                                    parts.push("expected " + findingDelegate.modelData.expected + ", exported " + findingDelegate.modelData.actual);
                                return parts.join("  ·  ");
                            }
                            visible: text.length > 0
                            color: Theme.muted
                            font.pixelSize: 11
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: root.controller !== null && root.controller.lastActionResult.outputRoot ? "Evidence: " + root.controller.lastActionResult.outputRoot : ""
                    visible: text.length > 0
                    color: Theme.muted
                    font.pixelSize: 11
                    wrapMode: Text.WrapAnywhere
                }
            }
        }
    }
}
