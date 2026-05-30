#pragma once

#include "sgfx_shell/sgfx_menu_base.hpp"

#include <filesystem>
#include <string>
#include <vector>

namespace sg_preflight::sgfx_shell {

struct SgfxDiagnosticRow {
    std::wstring label;
    std::wstring result;
    std::wstring detail;
};

class SgfxDiagnosticOverlay {
public:
    void refresh(const std::filesystem::path& workspace_root);
    const std::vector<SgfxDiagnosticRow>& rows() const;
    bool visible() const;
    void set_visible(bool visible);
    void toggle();

private:
    bool visible_ = false;
    std::vector<SgfxDiagnosticRow> rows_;
};

}  // namespace sg_preflight::sgfx_shell
