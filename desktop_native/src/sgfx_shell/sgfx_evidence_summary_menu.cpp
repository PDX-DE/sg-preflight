#include "sgfx_shell/sgfx_menus.hpp"

namespace sg_preflight::sgfx_shell {

SgfxEvidenceSummaryMenu::SgfxEvidenceSummaryMenu()
    : SgfxMenuBase(
          SgfxScreenId::EvidenceSummary,
          "Run Summary",
          "Evidence, blockers, and pending manual review without approval wording"
      ) {
    add_action(
        "Operator Overview",
        "Read the Python-owned overview cache for current profile, actions, blockers, and manual cards.",
        "desktop-state overview --profile-id G65 --json"
    );
    add_action(
        "Manual Review Companion",
        "Open manual review context. Manual review remains required.",
        "desktop-state manual G65 --json",
        "Quality-Hero review process"
    );
    add_action(
        "Screenshot Priority",
        "Surface suggested review order. It is not a verdict.",
        "screenshot-test-state read --profile G65 --format markdown",
        "Quality-Hero review process"
    );
}

}  // namespace sg_preflight::sgfx_shell
