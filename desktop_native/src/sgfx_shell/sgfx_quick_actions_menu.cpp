#include "sgfx_shell/sgfx_menus.hpp"

namespace sg_preflight::sgfx_shell {

SgfxQuickActionsMenu::SgfxQuickActionsMenu()
    : SgfxMenuBase(
          SgfxScreenId::QuickActions,
          "Quick Actions",
          "Refresh, open status, and return paths. No manual-review completion action exists."
      ) {
    add_action("Refresh Data", "Refresh the current read-only overview.", "desktop-state overview --profile-id G65 --json");
    add_action("Open Digest", "Read latest digest in Markdown for operator scan.", "daily-digest latest --format markdown");
    add_action("Open Review Board", "Read latest review board package when one exists.", "review-board latest --json");
    add_action("Quit SGFX", "Close the local shell. No repository or Jira action is performed.", "");
}

}  // namespace sg_preflight::sgfx_shell
