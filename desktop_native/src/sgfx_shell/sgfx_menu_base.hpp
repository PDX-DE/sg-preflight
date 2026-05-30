#pragma once

#include <string>
#include <vector>

namespace sg_preflight::sgfx_shell {

enum class SgfxUiMode {
    Clean,
    Branded,
};

enum class SgfxScreenId {
    Main,
    Workflow,
    EvidenceSummary,
    Settings,
    QuickActions,
    Digest,
    CleanStatus,
};

struct SgfxMenuAction {
    std::string label;
    std::string detail;
    std::string command;
    std::string confluence_anchor;
};

class SgfxMenuBase {
public:
    SgfxMenuBase(SgfxScreenId screen_id, std::string title, std::string subtitle);
    virtual ~SgfxMenuBase() = default;

    SgfxScreenId screen_id() const;
    const std::string& title() const;
    const std::string& subtitle() const;
    const std::vector<SgfxMenuAction>& actions() const;
    int selected_index() const;
    const SgfxMenuAction* selected_action() const;

    void add_action(std::string label, std::string detail, std::string command, std::string confluence_anchor = {});
    void move_selection(int delta);
    void reset_selection();

private:
    SgfxScreenId screen_id_;
    std::string title_;
    std::string subtitle_;
    std::vector<SgfxMenuAction> actions_;
    int selected_index_ = 0;
};

}  // namespace sg_preflight::sgfx_shell
