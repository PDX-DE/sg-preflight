#pragma once

#include "sgfx_shell/sgfx_menu_base.hpp"

#include <windows.h>

namespace sg_preflight::sgfx_shell {

class SgfxMenuBackground {
public:
    void draw(HDC dc, const RECT& bounds, SgfxUiMode mode) const;
};

}  // namespace sg_preflight::sgfx_shell
