#include "sgfx_shell/sgfx_menus.hpp"

namespace sg_preflight::sgfx_shell {

SgfxCleanStatusMenu::SgfxCleanStatusMenu()
    : SgfxMenuBase(
          SgfxScreenId::CleanStatus,
          "Clean Status Board",
          "Compact evidence tabs with no chrome, no sound, and direct SGFX status rows"
      ) {
    add_action("Delivery", "delivery-checklist read - Manual review remains required.", "delivery-checklist read --profile G65 --workspace C:\\repositories\\trunk --format json");
    add_action("Screenshots", "screenshot-test-state read - suggested review order only.", "screenshot-test-state read --profile G65 --format json");
    add_action("Digest", "daily-digest latest - status summary, not a QA verdict.", "daily-digest latest --format markdown");
    add_action("BMW Git", "bmw-git-readiness read - local mirror checks only.", "bmw-git-readiness read --profile G65 --format json");
    add_action("QA Hero", "qa-hero-readiness read - subsystem presence, not approval.", "qa-hero-readiness read --profile G65 --format json");
    add_action("Export Size", "export-size-analysis read - workbook evidence only.", "export-size-analysis read --profile G65 --workspace C:\\repositories\\trunk --latest --format json");
    add_action("Manual Review", "Manual review remains required.", "desktop-state manual G65 --json");
    add_action("Status Board", "Decision: not approval - evidence only.", "review-board latest --json");
}

}  // namespace sg_preflight::sgfx_shell
