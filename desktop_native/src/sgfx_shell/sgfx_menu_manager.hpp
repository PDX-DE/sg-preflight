#pragma once

#include "sgfx_shell/sgfx_menu_base.hpp"

#include <memory>
#include <vector>

namespace sg_preflight::sgfx_shell {

class SgfxMenuManager {
public:
    void add_menu(std::unique_ptr<SgfxMenuBase> menu);
    void activate(SgfxScreenId screen_id);
    void activate_next();
    void activate_previous();
    SgfxMenuBase& active_menu();
    const SgfxMenuBase& active_menu() const;
    void move_selection(int delta);
    const SgfxMenuAction* selected_action() const;
    size_t menu_count() const;

private:
    std::vector<std::unique_ptr<SgfxMenuBase>> menus_;
    size_t active_index_ = 0U;
};

}  // namespace sg_preflight::sgfx_shell
