pragma Singleton

import QtQuick

QtObject {
    readonly property var labels: ({
            "active": "Active",
            "aligned": "Aligned",
            "available": "Available",
            "bad": "Failed",
            "blocked": "Blocked",
            "cancelled": "Cancelled",
            "canceled": "Cancelled",
            "clean": "Clean",
            "completed": "Completed",
            "delivered": "Delivered",
            "done": "Done",
            "empty": "No evidence",
            "error": "Error",
            "external": "External evidence",
            "failed": "Failed",
            "findings": "Findings",
            "found": "Found",
            "human_review": "Human review",
            "idle": "Not loaded",
            "incomplete": "Incomplete",
            "loading": "Loading",
            "missing": "Missing",
            "missing_candidate": "Candidate missing",
            "needs_review": "Review needed",
            "not_available": "Not available",
            "not_delivered_yet": "Not delivered yet",
            "not_found": "Not found",
            "not_recorded": "Not recorded",
            "not_run": "Not run",
            "not_started": "Not started",
            "ok": "OK",
            "passed": "Passed",
            "pending": "Pending",
            "queued": "Queued",
            "read_only": "Read only",
            "ready": "Ready",
            "recorded": "Evidence recorded",
            "review": "Review needed",
            "running": "Running",
            "skipped": "Skipped",
            "stale": "Stale",
            "success": "Succeeded",
            "succeeded": "Succeeded",
            "unavailable": "Unavailable",
            "unknown": "Unknown",
            "unreadable": "Unreadable",
            "warn": "Review needed",
            "warning": "Warning"
        })
    readonly property var badStates: ["bad", "blocked", "error", "failed", "missing", "missing_candidate", "not_available", "not_found", "unavailable", "unreadable", "violation"]
    readonly property var warnStates: ["attention", "dimension_mismatch", "drift", "findings", "human_review", "incomplete", "mismatch", "needs_review", "not_delivered_yet", "outlier", "partial", "pending", "review", "stale", "structural_likely_review", "warn", "warning"]
    readonly property var goodStates: ["aligned", "clean", "cosmetic_likely_pass", "delivered", "done", "ok", "passed", "success", "succeeded"]
    readonly property var activeStates: ["active", "completed", "loading", "queued", "running"]
    readonly property var evidenceStates: ["available", "found", "ready", "recorded"]
    readonly property var knownNeutralStates: ["cancelled", "canceled", "empty", "external", "idle", "not_recorded", "not_run", "not_started", "read_only", "skipped", "unknown"]

    function normalize(value) {
        return String(value || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 64);
    }

    function label(value) {
        const normalized = normalize(value);
        if (!normalized)
            return "Unknown";
        if (labels[normalized])
            return labels[normalized];
        const readable = normalized.replace(/_/g, " ");
        return readable.charAt(0).toUpperCase() + readable.slice(1);
    }

    function tone(value) {
        const normalized = normalize(value);
        if (badStates.includes(normalized))
            return "bad";
        if (warnStates.includes(normalized))
            return "warn";
        if (goodStates.includes(normalized))
            return "good";
        if (activeStates.includes(normalized))
            return "active";
        if (evidenceStates.includes(normalized))
            return "evidence";
        return "neutral";
    }

    function color(value) {
        const semanticTone = tone(value);
        if (semanticTone === "bad")
            return Theme.statusBad;
        if (semanticTone === "warn")
            return Theme.statusWarn;
        if (semanticTone === "good")
            return Theme.statusGood;
        if (semanticTone === "active")
            return Theme.statusActive;
        if (semanticTone === "evidence")
            return Theme.statusEvidence;
        return Theme.statusNeutral;
    }

    function aggregate(gates) {
        if (!gates || gates.length === 0)
            return "not_recorded";
        const states = [];
        for (let index = 0; index < gates.length; ++index)
            states.push(normalize(gates[index] && gates[index].state ? gates[index].state : "not_recorded"));
        const priority = ["failed", "error", "bad", "blocked", "unavailable", "not_available", "missing", "missing_candidate", "not_found", "unreadable", "violation", "findings", "running", "loading", "queued", "human_review", "needs_review", "review", "warning", "warn", "incomplete", "pending", "stale", "drift", "outlier", "partial", "mismatch", "dimension_mismatch", "structural_likely_review"];
        for (let priorityIndex = 0; priorityIndex < priority.length; ++priorityIndex) {
            if (states.includes(priority[priorityIndex]))
                return priority[priorityIndex];
        }
        for (let stateIndex = 0; stateIndex < states.length; ++stateIndex) {
            const state = states[stateIndex];
            if (!badStates.includes(state) && !warnStates.includes(state) && !goodStates.includes(state) && !activeStates.includes(state) && !evidenceStates.includes(state) && !knownNeutralStates.includes(state))
                return state;
        }
        const remainingPriority = ["not_recorded", "not_run", "not_started", "external", "available", "recorded", "ready", "passed", "ok", "success", "succeeded", "clean", "aligned", "done", "delivered", "completed"];
        for (let remainingIndex = 0; remainingIndex < remainingPriority.length; ++remainingIndex) {
            if (states.includes(remainingPriority[remainingIndex]))
                return remainingPriority[remainingIndex];
        }
        return states[0] || "unknown";
    }
}
