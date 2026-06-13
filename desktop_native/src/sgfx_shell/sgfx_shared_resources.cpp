#include "sgfx_shell/sgfx_shared_resources.hpp"

#include <algorithm>
#include <cwctype>

namespace sg_preflight::sgfx_shell {

namespace {

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
    (void)workspace_root;
    root_ = bundle_root / "resources";
    items_.clear();
}

const std::vector<SgfxResourceItem>& SgfxSharedResources::items() const {
    return items_;
}

bool SgfxSharedResources::has_visual_chrome() const {
    return false;
}

bool SgfxSharedResources::has_sfx() const {
    return false;
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
