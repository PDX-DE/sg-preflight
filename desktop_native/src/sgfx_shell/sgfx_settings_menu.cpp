#include "sgfx_shell/sgfx_menus.hpp"

namespace sg_preflight::sgfx_shell {

SgfxSettingsMenu::SgfxSettingsMenu()
    : SgfxMenuBase(
          SgfxScreenId::Settings,
          "Settings",
          "Workspace, output, Jira dry-run, templates, and theme controls"
      ) {
    add_action("Workspace", "Current workspace is resolved locally; no BMW source writes.", "list-profiles --format json");
    add_action("Output Format", "JSON and Markdown surfaces stay available for handoff review.", "daily-digest latest --format markdown");
    add_action("Jira Dry Run", "Jira posting stays opt-in and confirmation-gated.", "jira post --ticket IDCEVODEV-977874 --body \"Dry run smoke. Evidence is not approval.\" --format json");
    add_action("Templates", "List operator-local templates with command and last-run metadata.", "template list --workspace {workspace} --json");
    add_action("UI mode", "Switch between Clean mode and Grafiks mode; SGFX is accepted as a one-release alias.", "@toggle-mode");
    add_action("Font size", "Cycle small / medium / large and persist it to the shell INI.", "@font-size");
    add_action("High-DPI scaling", "Cycle auto / 1.0x / 1.25x / 1.5x / 2.0x and persist for next launch.", "@dpi-scale");
    add_action("Color contrast", "Cycle standard / high contrast for operator comfort.", "@contrast");
}

}  // namespace sg_preflight::sgfx_shell
