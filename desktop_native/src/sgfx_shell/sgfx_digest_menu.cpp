#include "sgfx_shell/sgfx_menus.hpp"

namespace sg_preflight::sgfx_shell {

SgfxDigestMenu::SgfxDigestMenu()
    : SgfxMenuBase(
          SgfxScreenId::Digest,
          "Digest / Readiness / Activity",
          "Daily digest, readiness and local activity context"
      ) {
    add_action(
        "Daily Digest",
        "Latest evidence/status summary for the operator daily loop.",
        "daily-digest latest --format markdown",
        "SG daily process"
    );
    add_action("BMW Git Readiness", "Read-only mirror availability for the selected profile.", "bmw-git-readiness read --profile G65 --format json");
    add_action("QA Hero Readiness", "Read subsystem presence without claiming approval.", "qa-hero-readiness read --profile G65 --format json");
    add_action("Activity Log", "Read today's operator-local action history; never posted anywhere.", "activity-log read --workspace {workspace} --profile G65 --since today --format json");
}

}  // namespace sg_preflight::sgfx_shell
