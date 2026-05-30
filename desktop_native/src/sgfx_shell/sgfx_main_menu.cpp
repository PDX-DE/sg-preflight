#include "sgfx_shell/sgfx_menus.hpp"

namespace sg_preflight::sgfx_shell {

SgfxMainMenu::SgfxMainMenu()
    : SgfxMenuBase(
          SgfxScreenId::Main,
          "SGFX: Project Quality-Hero",
          "Operator hub - read-only evidence surfaces and manual-review support"
      ) {
    add_action(
        "Delivery Checklist",
        "Read operator-local delivery workbook evidence. Manual review remains required.",
        "delivery-checklist read --profile G65 --workspace C:\\repositories\\trunk --format json",
        "Quality-Hero review process"
    );
    add_action(
        "Screenshot State",
        "Surface screenshot baseline / actual / diff counts and suggested review order.",
        "screenshot-test-state read --profile G65 --format json",
        "Quality-Hero review process"
    );
    add_action(
        "Workflow Picker",
        "Pick a read-only SGFX workflow and profile before opening the evidence surface.",
        "desktop-state actions G65 --json",
        "SG checker process"
    );
    add_action(
        "Daily Digest",
        "Open the latest status and evidence summary. Decision: not approval — evidence only.",
        "daily-digest latest --format markdown",
        "SG daily process"
    );
    add_action(
        "Templates",
        "List operator-local saved command configurations.",
        "template list --workspace {workspace} --json",
        "SG refinement workflow"
    );
    add_action(
        "Review Board",
        "Open latest review package when one exists; no package is a documented local-alpha state.",
        "review-board latest --json",
        "Quality-Hero review process"
    );
}

}  // namespace sg_preflight::sgfx_shell
