pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import SGFX 1.0

FocusScope {
    id: root

    required property var payload
    required property string pageState
    required property string capabilityState
    required property string capabilityError
    required property string previewState
    required property string previewToken
    required property int previewFrameCount
    required property int previewFrameIndex
    required property string previewLabel
    required property bool reducedMotion
    signal profileRequested(string profileId)
    signal actionRequested(string capabilityId, var inputs)
    signal routeRequested(string routeId)
    signal gateSelected(string gateId)
    signal inspectionRequested
    signal previewFrameRequested(int frameIndex)
    property var snapshot: ({})
    property var gates: []
    property var selectedProfile: ({})
    property var latestLocalRun: ({})
    property var nextAction: ({})
    property string payloadSelectedGateId: "context"
    property string nextActionLabel: ""
    property string nextCapabilityId: ""
    property string nextActionId: ""
    property string nextRouteId: ""
    property string selectedGateOverride: ""
    readonly property string selectedGateId: {
        for (let index = 0; index < gates.length; ++index) {
            if (gates[index].id === selectedGateOverride)
                return selectedGateOverride;
        }
        return payloadSelectedGateId;
    }
    readonly property var selectedGate: {
        for (let index = 0; index < gates.length; ++index) {
            if (gates[index].id === selectedGateId)
                return gates[index];
        }
        return ({});
    }
    readonly property var pipelineGateIds: pipeline.gateIds
    readonly property string primaryActionLabel: nextActionLabel
    readonly property bool capabilityBusy: capabilityState === "queued" || capabilityState === "running"
    readonly property bool primaryActionEnabled: Boolean(selectedProfile && selectedProfile.id && nextCapabilityId && pageState === "ready" && !capabilityBusy)
    readonly property int visibleCheckRowCount: gateDetail.visibleCheckRowCount

    objectName: "qaControlCenterHome"

    function requestPrimaryAction() {
        if (!primaryActionEnabled)
            return;
        if (nextCapabilityId === "page.navigate" && nextRouteId) {
            routeRequested(nextRouteId);
            return;
        }
        actionRequested(nextCapabilityId, {
            "action_id": nextActionId,
            "profile_ids": [selectedProfile.id]
        });
    }

    function acceptPayload(candidatePayload) {
        const candidate = candidatePayload || {};
        if (Number(candidate.schemaVersion || 0) !== 1) {
            root.snapshot = {};
            root.gates = [];
            root.selectedProfile = {};
            root.latestLocalRun = {};
            root.nextAction = {};
            root.payloadSelectedGateId = "context";
            root.nextActionLabel = "";
            root.nextCapabilityId = "";
            root.nextActionId = "";
            root.nextRouteId = "";
            root.selectedGateOverride = "";
            return;
        }
        root.snapshot = candidate;
        root.gates = candidate.gates || [];
        root.selectedProfile = candidate.selectedProfile || {};
        root.latestLocalRun = candidate.latestLocalRun || {};
        root.nextAction = candidate.nextAction || {};
        root.payloadSelectedGateId = candidate.selectedGateId || "context";
        root.nextActionLabel = root.nextAction.label || "";
        root.nextCapabilityId = root.nextAction.capabilityId || "";
        root.nextActionId = root.nextAction.actionId || "";
        root.nextRouteId = root.nextAction.routeId || "";
        root.selectedGateOverride = "";
    }

    function restoreFocus() {
        pipeline.forceActiveFocus();
    }

    onPayloadChanged: acceptPayload(root.payload)

    Component.onCompleted: acceptPayload(root.payload)

    ScrollView {
        anchors.fill: parent
        anchors.margins: Theme.space3
        clip: true

        ColumnLayout {
            width: Math.max(760, root.width - Theme.space4 * 2)
            spacing: Theme.space3

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space3

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Label {
                        Layout.fillWidth: true
                        text: "QA CONTROL CENTER"
                        color: Theme.accent
                        font.family: Theme.operationalFont
                        font.pixelSize: 10
                        font.weight: Font.Bold
                        font.letterSpacing: 1.8
                    }
                    Label {
                        Layout.fillWidth: true
                        text: root.snapshot.scopeLabel || "3D Car QA"
                        color: Theme.text
                        font.family: Theme.displayFont
                        font.pixelSize: 25
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "One selected scope. One local check. Clear evidence for the next handoff."
                        color: Theme.muted
                        font.family: Theme.operationalFont
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                }

                Button {
                    id: primaryAction

                    objectName: "qaPrimaryAction"
                    Layout.preferredWidth: 276
                    Layout.preferredHeight: 48
                    text: root.primaryActionLabel || "Choose profile"
                    enabled: root.primaryActionEnabled
                    focusPolicy: Qt.StrongFocus
                    Accessible.role: Accessible.Button
                    Accessible.name: text
                    onClicked: root.requestPrimaryAction()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 266
                spacing: Theme.space3

                QaContextPreview {
                    Layout.preferredWidth: 318
                    Layout.fillHeight: true
                    selectedProfile: root.selectedProfile
                    latestLocalRun: root.latestLocalRun
                    previewState: root.previewState
                    previewToken: root.previewToken
                    previewFrameCount: root.previewFrameCount
                    previewFrameIndex: root.previewFrameIndex
                    previewLabel: root.previewLabel
                    reducedMotion: root.reducedMotion
                    onInspectionRequested: root.inspectionRequested()
                    onPreviewFrameRequested: frameIndex => root.previewFrameRequested(frameIndex)
                }

                QaGateDetail {
                    id: gateDetail

                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    gate: root.selectedGate
                    reducedMotion: root.reducedMotion
                    onRouteRequested: routeId => root.routeRequested(routeId)
                }
            }

            QaPipelineSpine {
                id: pipeline

                Layout.fillWidth: true
                Layout.preferredHeight: 108
                gates: root.gates
                selectedGateId: root.selectedGateId
                reducedMotion: root.reducedMotion
                onGateSelected: gateId => {
                    root.selectedGateOverride = gateId;
                    root.gateSelected(gateId);
                }
            }

            Label {
                Layout.fillWidth: true
                visible: root.capabilityError.length > 0
                text: root.capabilityError
                color: Theme.statusBad
                font.family: Theme.operationalFont
                font.pixelSize: 11
                elide: Text.ElideRight
            }

            SequentialAnimation {
                running: root.pageState !== "idle"
                NumberAnimation {
                    target: pipeline
                    property: "opacity"
                    from: 0
                    to: 1
                    duration: Theme.duration(Theme.panelDuration, root.reducedMotion)
                }
            }
        }
    }
}
