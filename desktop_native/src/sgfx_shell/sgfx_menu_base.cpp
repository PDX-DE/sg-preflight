#include "sgfx_shell/sgfx_menu_base.hpp"

#include <algorithm>
#include <utility>

namespace sg_preflight::sgfx_shell {

SgfxMenuBase::SgfxMenuBase(SgfxScreenId screen_id, std::string title, std::string subtitle)
    : screen_id_(screen_id), title_(std::move(title)), subtitle_(std::move(subtitle)) {}

SgfxScreenId SgfxMenuBase::screen_id() const {
    return screen_id_;
}

const std::string& SgfxMenuBase::title() const {
    return title_;
}

const std::string& SgfxMenuBase::subtitle() const {
    return subtitle_;
}

const std::vector<SgfxMenuAction>& SgfxMenuBase::actions() const {
    return actions_;
}

int SgfxMenuBase::selected_index() const {
    return selected_index_;
}

const SgfxMenuAction* SgfxMenuBase::selected_action() const {
    if (actions_.empty()) {
        return nullptr;
    }
    const int clamped = std::clamp(selected_index_, 0, static_cast<int>(actions_.size() - 1U));
    return &actions_[static_cast<size_t>(clamped)];
}

void SgfxMenuBase::add_action(
    std::string label,
    std::string detail,
    std::string command,
    std::string confluence_anchor
) {
    actions_.push_back(SgfxMenuAction{
        std::move(label),
        std::move(detail),
        std::move(command),
        std::move(confluence_anchor),
    });
}

void SgfxMenuBase::move_selection(int delta) {
    if (actions_.empty()) {
        selected_index_ = 0;
        return;
    }
    const int last = static_cast<int>(actions_.size() - 1U);
    selected_index_ = std::clamp(selected_index_ + delta, 0, last);
}

void SgfxMenuBase::reset_selection() {
    selected_index_ = 0;
}

}  // namespace sg_preflight::sgfx_shell
