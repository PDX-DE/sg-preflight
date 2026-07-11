import QtQuick
import QtQuick.Controls
import SGFX 1.0

Rectangle {
    id: root

    required property string status
    readonly property string statusText: {
        const value = status.toLowerCase();
        if (["error", "failed", "bad", "unavailable"].includes(value))
            return "Needs attention";
        if (["warning", "warn", "incomplete"].includes(value))
            return "Review needed";
        if (["available", "ready", "ok", "passed"].includes(value))
            return "Available";
        if (value === "loading")
            return "Loading";
        return "Not run";
    }
    readonly property color statusColor: {
        const value = status.toLowerCase();
        if (["error", "failed", "bad", "unavailable"].includes(value))
            return Theme.statusBad;
        if (["warning", "warn", "incomplete"].includes(value))
            return Theme.statusWarn;
        if (["available", "ready", "ok", "passed"].includes(value))
            return Theme.statusGood;
        return Theme.statusNeutral;
    }

    implicitWidth: badgeLabel.implicitWidth + 20
    implicitHeight: 30
    radius: 15
    color: Qt.alpha(statusColor, 0.16)
    border.color: statusColor
    Accessible.role: Accessible.StaticText
    Accessible.name: "Status: " + statusText

    Label {
        id: badgeLabel
        anchors.centerIn: parent
        text: root.statusText
        color: root.statusColor
        font.pixelSize: 11
        font.weight: Font.DemiBold
    }
}
