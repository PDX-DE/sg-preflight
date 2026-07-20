import QtQuick
import QtQuick.Controls
import SGFX 1.0

Rectangle {
    id: root

    required property string status
    readonly property string statusText: StatusPresentation.label(status)
    readonly property string statusTone: StatusPresentation.tone(status)
    readonly property color statusColor: StatusPresentation.color(status)

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
