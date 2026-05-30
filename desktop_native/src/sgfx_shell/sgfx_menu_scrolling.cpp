#include "sgfx_shell/sgfx_menu_scrolling.hpp"

#include <algorithm>

namespace sg_preflight::sgfx_shell {

void SgfxMenuScrolling::ensure_visible(int selected_index, int visible_rows) {
    if (visible_rows <= 0) {
        first_visible_row_ = 0;
        return;
    }
    if (selected_index < first_visible_row_) {
        first_visible_row_ = selected_index;
    } else if (selected_index >= first_visible_row_ + visible_rows) {
        first_visible_row_ = selected_index - visible_rows + 1;
    }
    first_visible_row_ = std::max(0, first_visible_row_);
}

int SgfxMenuScrolling::first_visible_row() const {
    return first_visible_row_;
}

}  // namespace sg_preflight::sgfx_shell
