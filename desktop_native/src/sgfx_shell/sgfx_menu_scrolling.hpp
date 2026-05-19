#pragma once

namespace sg_preflight::sgfx_shell {

class SgfxMenuScrolling {
public:
    void ensure_visible(int selected_index, int visible_rows);
    int first_visible_row() const;

private:
    int first_visible_row_ = 0;
};

}  // namespace sg_preflight::sgfx_shell
