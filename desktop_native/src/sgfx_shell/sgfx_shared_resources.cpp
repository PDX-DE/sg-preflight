#include "sgfx_shell/sgfx_shared_resources.hpp"

#include <algorithm>
#include <array>
#include <cwctype>

namespace sg_preflight::sgfx_shell {

namespace {

std::filesystem::path PickResourceRoot(
    const std::filesystem::path& workspace_root,
    const std::filesystem::path& bundle_root
) {
    const std::array<std::filesystem::path, 3> candidates = {
        workspace_root / "desktop_native" / "assets",
        bundle_root / "resources",
        workspace_root / "resources",
    };
    for (const auto& candidate : candidates) {
        if (std::filesystem::exists(candidate / "images\\common\\raw\\general_window.png")) {
            return candidate;
        }
    }
    return candidates.front();
}

std::wstring Lower(std::wstring text) {
    std::transform(text.begin(), text.end(), text.begin(), [](wchar_t ch) {
        return static_cast<wchar_t>(std::towlower(ch));
    });
    return text;
}

}  // namespace

void SgfxSharedResources::load(
    const std::filesystem::path& workspace_root,
    const std::filesystem::path& bundle_root
) {
    root_ = PickResourceRoot(workspace_root, bundle_root);
    items_ = {
        {L"frame", "images\\common\\raw\\general_window.png"},
        {L"selection", "images\\common\\raw\\select.png"},
        {L"light", "images\\common\\raw\\light.png"},
        {L"settings panel", "images\\common\\raw\\options_static.png"},
        {L"settings panel flash", "images\\common\\raw\\options_static_flash.png"},
        {L"cursor sound", "sounds\\ui_cursor.wav"},
        {L"confirm sound", "sounds\\ui_confirm.wav"},
        {L"cancel sound", "sounds\\ui_cancel.wav"},
        {L"panel open sound", "sounds\\ui_panel_open.wav"},
        {L"panel close sound", "sounds\\ui_panel_close.wav"},
        {L"page sound", "sounds\\ui_page.wav"},
    };

    for (auto& item : items_) {
        item.available = std::filesystem::exists(root_ / item.relative_path);
    }
}

const std::vector<SgfxResourceItem>& SgfxSharedResources::items() const {
    return items_;
}

bool SgfxSharedResources::has_visual_chrome() const {
    int available = 0;
    for (const auto& item : items_) {
        if (item.relative_path.wstring().find(L"images\\") == 0U && item.available) {
            ++available;
        }
    }
    return available >= 3;
}

bool SgfxSharedResources::has_sfx() const {
    int available = 0;
    for (const auto& item : items_) {
        if (item.relative_path.wstring().find(L"sounds\\") == 0U && item.available) {
            ++available;
        }
    }
    return available >= 3;
}

const std::filesystem::path& SgfxSharedResources::root() const {
    return root_;
}

bool IsFontFileCandidate(const std::filesystem::path& path) {
    const std::wstring extension = Lower(path.extension().wstring());
    if (extension != L".otf" && extension != L".ttf") {
        return false;
    }
    const std::wstring filename = Lower(path.filename().wstring());
    return filename.find(L"archive") == std::wstring::npos;
}

std::vector<std::filesystem::path> DiscoverFontCandidates(const std::filesystem::path& root) {
    std::vector<std::filesystem::path> result;
    if (!std::filesystem::exists(root)) {
        return result;
    }
    for (const auto& entry : std::filesystem::directory_iterator(root)) {
        if (!entry.is_regular_file()) {
            continue;
        }
        if (!IsFontFileCandidate(entry.path())) {
            continue;
        }
        result.push_back(entry.path());
    }
    return result;
}

}  // namespace sg_preflight::sgfx_shell
