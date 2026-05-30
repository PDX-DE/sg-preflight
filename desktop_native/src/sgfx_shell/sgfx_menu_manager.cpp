#include "sgfx_shell/sgfx_menu_manager.hpp"

#include <stdexcept>
#include <utility>

namespace sg_preflight::sgfx_shell {

void SgfxMenuManager::add_menu(std::unique_ptr<SgfxMenuBase> menu) {
    if (!menu) {
        return;
    }
    menus_.push_back(std::move(menu));
}

void SgfxMenuManager::activate(SgfxScreenId screen_id) {
    for (size_t index = 0; index < menus_.size(); ++index) {
        if (menus_[index]->screen_id() == screen_id) {
            active_index_ = index;
            menus_[index]->reset_selection();
            return;
        }
    }
}

void SgfxMenuManager::activate_next() {
    if (menus_.empty()) {
        return;
    }
    active_index_ = (active_index_ + 1U) % menus_.size();
    menus_[active_index_]->reset_selection();
}

void SgfxMenuManager::activate_previous() {
    if (menus_.empty()) {
        return;
    }
    active_index_ = (active_index_ == 0U) ? (menus_.size() - 1U) : (active_index_ - 1U);
    menus_[active_index_]->reset_selection();
}

SgfxMenuBase& SgfxMenuManager::active_menu() {
    if (menus_.empty()) {
        throw std::runtime_error("SGFX shell has no active menu.");
    }
    return *menus_[active_index_];
}

const SgfxMenuBase& SgfxMenuManager::active_menu() const {
    if (menus_.empty()) {
        throw std::runtime_error("SGFX shell has no active menu.");
    }
    return *menus_[active_index_];
}

void SgfxMenuManager::move_selection(int delta) {
    if (!menus_.empty()) {
        menus_[active_index_]->move_selection(delta);
    }
}

const SgfxMenuAction* SgfxMenuManager::selected_action() const {
    return menus_.empty() ? nullptr : menus_[active_index_]->selected_action();
}

size_t SgfxMenuManager::menu_count() const {
    return menus_.size();
}

}  // namespace sg_preflight::sgfx_shell
