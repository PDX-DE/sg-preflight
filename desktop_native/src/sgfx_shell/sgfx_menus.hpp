#pragma once

#include "sgfx_shell/sgfx_menu_base.hpp"

namespace sg_preflight::sgfx_shell {

class SgfxMainMenu final : public SgfxMenuBase {
public:
    SgfxMainMenu();
};

class SgfxWorkflowMenu final : public SgfxMenuBase {
public:
    SgfxWorkflowMenu();
};

class SgfxEvidenceSummaryMenu final : public SgfxMenuBase {
public:
    SgfxEvidenceSummaryMenu();
};

class SgfxSettingsMenu final : public SgfxMenuBase {
public:
    SgfxSettingsMenu();
};

class SgfxQuickActionsMenu final : public SgfxMenuBase {
public:
    SgfxQuickActionsMenu();
};

class SgfxDigestMenu final : public SgfxMenuBase {
public:
    SgfxDigestMenu();
};

class SgfxCleanStatusMenu final : public SgfxMenuBase {
public:
    SgfxCleanStatusMenu();
};

}  // namespace sg_preflight::sgfx_shell
