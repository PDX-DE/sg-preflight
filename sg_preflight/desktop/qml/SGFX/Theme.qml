pragma Singleton

import QtQuick

QtObject {
    readonly property color canvas: "#111416"
    readonly property color panel: "#191e21"
    readonly property color raised: "#22292d"
    readonly property color border: "#344047"
    readonly property color accent: "#4ec9b0"
    readonly property color text: "#eef3f1"
    readonly property color muted: "#a6b0b5"
    readonly property color statusBad: "#f14c4c"
    readonly property color statusWarn: "#cca700"
    readonly property color statusGood: "#89d185"
    readonly property color statusActive: "#6cb6ff"
    readonly property color statusEvidence: accent
    readonly property color statusNeutral: "#8b949e"
    readonly property string operationalFont: typeof sgfxProductFonts !== "undefined" && sgfxProductFonts.operational ? sgfxProductFonts.operational : "sans-serif"
    readonly property string displayFont: typeof sgfxProductFonts !== "undefined" && sgfxProductFonts.display ? sgfxProductFonts.display : operationalFont
    readonly property int space1: 6
    readonly property int space2: 10
    readonly property int space3: 16
    readonly property int space4: 24
    readonly property int focusDuration: 160
    readonly property int panelDuration: 280
    readonly property int routeDuration: 500
    readonly property int entranceLimit: 700
    readonly property int entranceStagger: 55
    readonly property int motionMicro: 83
    readonly property int motionFeedback: 120
    readonly property int motionShort: 250
    readonly property int motionStandard: 333
    readonly property int motionEmphasis: 450
    readonly property int motionStagger: 70

    function duration(value, reducedMotion) {
        return reducedMotion ? Math.min(value, 120) : value;
    }

    function travel(value, reducedMotion) {
        return reducedMotion ? Math.min(value, 8) : value;
    }

    function stagger(index, reducedMotion) {
        return reducedMotion ? 0 : index * motionStagger;
    }
}
