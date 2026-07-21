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
    required property var desktopController
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
    signal focusNavigationRequested
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
    readonly property string selectedCarLabel: selectedProfile && selectedProfile.label ? selectedProfile.label : "Choose a car profile"
    readonly property bool capabilityBusy: capabilityState === "queued" || capabilityState === "running"
    readonly property bool primaryActionEnabled: Boolean(selectedProfile && selectedProfile.id && nextCapabilityId && pageState === "ready" && !capabilityBusy)
    readonly property bool primaryActionVisible: primaryAction.visible
    readonly property int visibleCheckRowCount: gateDetail.visibleCheckRowCount
    readonly property bool allAccessibleNamesPresent: primaryAction.Accessible.name.length > 0 && findingsLink.Accessible.name.length > 0 && manualReviewLink.Accessible.name.length > 0 && evidenceLink.Accessible.name.length > 0 && historyLink.Accessible.name.length > 0 && pipeline.allAccessibleNamesPresent && gateDetail.allAccessibleNamesPresent && contextPreview.allAccessibleNamesPresent
    property alias primaryActionItem: primaryAction

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

    function focusPrimaryAction() {
        primaryAction.forceActiveFocus();
    }

    function countLabel(value, singular) {
        const count = Number(value || 0);
        return count + " " + singular + (count === 1 ? "" : "s");
    }

    function latestOutcomeLabel() {
        if (!latestLocalRun || !latestLocalRun.state)
            return "Latest run · No local run recorded";
        const counts = [countLabel(latestLocalRun.errors, "error"), countLabel(latestLocalRun.warnings, "warning"), countLabel(latestLocalRun.info, "info item")];
        return "Latest run · " + StatusPresentation.label(latestLocalRun.state) + " · " + counts.join(", ");
    }

    function findingPreviewText(finding) {
        if (!finding)
            return "";
        const parts = [finding.message || "Finding details unavailable"];
        if (finding.location)
            parts.push(finding.location);
        if (finding.expected && finding.actual)
            parts.push("expected " + finding.expected + ", exported " + finding.actual);
        return parts.join(" · ");
    }

    function findingPreviewLines() {
        const findings = latestLocalRun && latestLocalRun.findings ? latestLocalRun.findings : [];
        const lines = [];
        for (let index = 0; index < Math.min(3, findings.length); ++index)
            lines.push("• " + findingPreviewText(findings[index]));
        return lines.join("\n");
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
                        text: "SELECTED CAR · " + (root.snapshot.scopeLabel || "3D Car QA")
                        color: Theme.accent
                        font.family: Theme.operationalFont
                        font.pixelSize: 10
                        font.weight: Font.Bold
                        font.letterSpacing: 1.8
                    }
                    Label {
                        id: selectedCarTitle

                        objectName: "homeSelectedCarTitle"
                        Layout.fillWidth: true
                        text: root.selectedCarLabel
                        color: Theme.text
                        font.family: Theme.displayFont
                        font.pixelSize: 30
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Accessible.role: Accessible.StaticText
                        Accessible.name: "Selected car: " + text
                    }
                    Label {
                        id: latestOutcome

                        objectName: "homeLatestOutcome"
                        Layout.fillWidth: true
                        text: root.latestOutcomeLabel()
                        color: root.latestLocalRun && root.latestLocalRun.state ? StatusPresentation.color(root.latestLocalRun.state) : Theme.muted
                        font.family: Theme.operationalFont
                        font.pixelSize: 11
                        elide: Text.ElideRight
                        Accessible.role: Accessible.StaticText
                        Accessible.name: text
                    }
                }

                Button {
                    id: primaryAction

                    objectName: "qaPrimaryAction"
                    Layout.preferredWidth: 300
                    Layout.preferredHeight: 58
                    text: root.primaryActionLabel || "Choose profile"
                    enabled: root.primaryActionEnabled
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                    focusPolicy: Qt.StrongFocus
                    Accessible.role: Accessible.Button
                    Accessible.name: text
                    KeyNavigation.tab: findingsLink
                    Keys.onTabPressed: event => {
                        findingsLink.forceActiveFocus();
                        event.accepted = true;
                    }
                    onClicked: root.requestPrimaryAction()
                }
            }

            ColumnLayout {
                objectName: "homeFindingsPreview"
                Layout.fillWidth: true
                spacing: Theme.space1
                visible: Boolean(root.latestLocalRun && root.latestLocalRun.findings && root.latestLocalRun.findings.length > 0)

                Label {
                    Layout.fillWidth: true
                    text: "LATEST FINDINGS"
                    color: Theme.muted
                    font.family: Theme.operationalFont
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.2
                }
                Label {
                    objectName: "homeFindingPreview"
                    Layout.fillWidth: true
                    text: root.findingPreviewLines()
                    color: Theme.text
                    font.family: Theme.operationalFont
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    Accessible.role: Accessible.StaticText
                    Accessible.name: text
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space2

                Label {
                    text: "Open"
                    color: Theme.muted
                    font.family: Theme.operationalFont
                    font.pixelSize: 11
                }
                Button {
                    id: findingsLink

                    objectName: "homeFindingsLink"
                    Layout.preferredHeight: 36
                    text: "Latest findings"
                    flat: true
                    enabled: Boolean(root.selectedProfile && root.selectedProfile.id)
                    focusPolicy: Qt.StrongFocus
                    Accessible.role: Accessible.Button
                    Accessible.name: "Open latest findings for " + root.selectedCarLabel
                    KeyNavigation.backtab: primaryAction
                    KeyNavigation.tab: manualReviewLink
                    onClicked: root.routeRequested("full-qa-pass")
                }
                Button {
                    id: manualReviewLink

                    objectName: "homeManualReviewLink"
                    Layout.preferredHeight: 36
                    text: "Manual Review"
                    flat: true
                    enabled: Boolean(root.selectedProfile && root.selectedProfile.id)
                    focusPolicy: Qt.StrongFocus
                    Accessible.role: Accessible.Button
                    Accessible.name: "Open Manual Review for " + root.selectedCarLabel
                    KeyNavigation.backtab: findingsLink
                    KeyNavigation.tab: evidenceLink
                    onClicked: root.routeRequested("manual-review")
                }
                Button {
                    id: evidenceLink

                    objectName: "homeEvidenceLink"
                    Layout.preferredHeight: 36
                    text: "Evidence"
                    flat: true
                    enabled: Boolean(root.selectedProfile && root.selectedProfile.id)
                    focusPolicy: Qt.StrongFocus
                    Accessible.role: Accessible.Button
                    Accessible.name: "Open delivery evidence for " + root.selectedCarLabel
                    KeyNavigation.backtab: manualReviewLink
                    KeyNavigation.tab: historyLink
                    onClicked: root.routeRequested("delivery-checklist")
                }
                Button {
                    id: historyLink

                    objectName: "homeHistoryLink"
                    Layout.preferredHeight: 36
                    text: "History"
                    flat: true
                    enabled: Boolean(root.selectedProfile && root.selectedProfile.id)
                    focusPolicy: Qt.StrongFocus
                    Accessible.role: Accessible.Button
                    Accessible.name: "Open run history for " + root.selectedCarLabel
                    KeyNavigation.backtab: evidenceLink
                    KeyNavigation.tab: pipeline
                    Keys.onTabPressed: event => {
                        pipeline.forceActiveFocus();
                        event.accepted = true;
                    }
                    onClicked: root.routeRequested("batch-full-qa-pass")
                }
                Item {
                    Layout.fillWidth: true
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 336
                spacing: Theme.space3

                QaContextPreview {
                    id: contextPreview

                    Layout.preferredWidth: 470
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
                    onFocusNavigationRequested: root.focusNavigationRequested()
                }

                QaGateDetail {
                    id: gateDetail

                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    gate: root.selectedGate
                    reducedMotion: root.reducedMotion
                    onRouteRequested: routeId => root.routeRequested(routeId)
                    onFocusContextRequested: contextPreview.focusFirstAction()
                }
            }

            QaPipelineSpine {
                id: pipeline

                Layout.fillWidth: true
                Layout.preferredHeight: 108
                gates: root.gates
                selectedGateId: root.selectedGateId
                reducedMotion: root.reducedMotion
                KeyNavigation.backtab: historyLink
                onFocusChecksRequested: {
                    if (!gateDetail.focusFirstCheck())
                        contextPreview.focusFirstAction();
                }
                onGateSelected: gateId => {
                    root.selectedGateOverride = gateId;
                    root.gateSelected(gateId);
                }
            }

            ActionFeedback {
                Layout.fillWidth: true
                controller: root.desktopController
                reducedMotion: root.reducedMotion
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
