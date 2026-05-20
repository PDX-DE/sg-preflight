#include "sgfx_shell/sgfx_menu_controls_display.hpp"

namespace sg_preflight::sgfx_shell {

std::wstring SgfxMenuControlsDisplay::controls_line() const {
    return L"[Enter] Run/read  [Esc] Quit  [F1] Help  [F2] Previous surface  [F3] Clean/Grafiks  [F5] Refresh  [F12] Diagnostic";
}

std::wstring SgfxMenuControlsDisplay::help_text() const {
    return L"SGFX reads local evidence and status. Manual review remains required. Decision: not approval — evidence only.";
}

}  // namespace sg_preflight::sgfx_shell
