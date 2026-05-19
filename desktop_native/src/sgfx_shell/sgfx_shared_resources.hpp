#pragma once

#include <filesystem>
#include <string>
#include <vector>

namespace sg_preflight::sgfx_shell {

struct SgfxResourceItem {
    std::wstring label;
    std::filesystem::path relative_path;
    bool available = false;
};

class SgfxSharedResources {
public:
    void load(const std::filesystem::path& workspace_root, const std::filesystem::path& bundle_root);
    const std::vector<SgfxResourceItem>& items() const;
    bool has_visual_chrome() const;
    bool has_sfx() const;
    const std::filesystem::path& root() const;

private:
    std::filesystem::path root_;
    std::vector<SgfxResourceItem> items_;
};

bool IsFontFileCandidate(const std::filesystem::path& path);
std::vector<std::filesystem::path> DiscoverFontCandidates(const std::filesystem::path& root);

}  // namespace sg_preflight::sgfx_shell
