#pragma once

#include <string>

namespace sg_preflight::sgfx_shell {

class SgfxMenuControlsDisplay {
public:
    std::wstring controls_line() const;
    std::wstring help_text() const;
};

}  // namespace sg_preflight::sgfx_shell
