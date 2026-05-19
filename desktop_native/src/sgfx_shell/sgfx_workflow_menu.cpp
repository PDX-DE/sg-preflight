#include "sgfx_shell/sgfx_menus.hpp"

namespace sg_preflight::sgfx_shell {

SgfxWorkflowMenu::SgfxWorkflowMenu()
    : SgfxMenuBase(
          SgfxScreenId::Workflow,
          "Workflow Picker",
          "Profile, brand, and workflow selectors mapped to SGFX read-only commands"
      ) {
    add_action(
        "Profile: G65",
        "Default local profile for the current operator proof path.",
        "desktop-state overview --profile-id G65 --json"
    );
    add_action(
        "BMW Git Readiness",
        "Read availability signals from the local BMW Git mirror without fetching or writing.",
        "bmw-git-readiness read --profile G65 --format json",
        "BMW 3DCar local mirror"
    );
    add_action(
        "QA Hero Readiness",
        "Read Quality-Hero subsystem presence counts for the selected profile.",
        "qa-hero-readiness read --profile G65 --format json",
        "Quality-Hero review process"
    );
    add_action(
        "Export Size",
        "Read the latest operator-local size analysis workbook.",
        "export-size-analysis read --profile G65 --workspace C:\\repositories\\trunk --latest --format json"
    );
}

}  // namespace sg_preflight::sgfx_shell
