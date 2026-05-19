#pragma once

#include "backend_bridge.hpp"
#include "sgfx_shell/sgfx_diagnostic_overlay.hpp"
#include "sgfx_shell/sgfx_menu_background.hpp"
#include "sgfx_shell/sgfx_menu_controls_display.hpp"
#include "sgfx_shell/sgfx_menu_manager.hpp"
#include "sgfx_shell/sgfx_menu_scrolling.hpp"
#include "sgfx_shell/sgfx_shared_resources.hpp"

#include <windows.h>

#include <filesystem>
#include <optional>
#include <string>

namespace sg_preflight::sgfx_shell {

struct SgfxShellConfig {
    std::filesystem::path bundle_root;
    std::filesystem::path workspace_root;
    std::filesystem::path ini_path;
    std::wstring python_executable = L"python";
    SgfxUiMode ui_mode = SgfxUiMode::Clean;
    std::wstring font_size = L"medium";
    std::wstring dpi_scale = L"auto";
    std::wstring contrast = L"standard";
    int width = 1280;
    int height = 720;
    bool windowed = true;
};

class SgfxShellApp {
public:
    explicit SgfxShellApp(HINSTANCE instance);
    int run(PWSTR command_line, int show_command);

private:
    static LRESULT CALLBACK WindowProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam);
    LRESULT handle_message(UINT message, WPARAM wparam, LPARAM lparam);

    void parse_command_line(PWSTR command_line);
    bool create_window(int show_command);
    void build_menus();
    void load_backend_state();
    void load_preferences();
    void save_preferences();
    void refresh();
    void toggle_mode();
    void execute_selected_action();
    bool handle_internal_action(const std::string& command);
    void draw(HDC dc);
    void draw_menu(HDC dc, const RECT& bounds);
    void draw_diagnostic_overlay(HDC dc, const RECT& bounds);
    std::wstring run_python_command(const std::string& command);
    void record_activity(const SgfxMenuAction& action, int exit_code);

    HINSTANCE instance_ = nullptr;
    HWND window_ = nullptr;
    SgfxShellConfig config_;
    sg_preflight::native_shell::BackendConfig backend_;
    SgfxMenuManager menu_manager_;
    SgfxSharedResources resources_;
    SgfxMenuBackground background_;
    SgfxMenuControlsDisplay controls_;
    SgfxMenuScrolling scrolling_;
    SgfxDiagnosticOverlay diagnostic_;
    std::optional<sg_preflight::native_shell::OperatorOverview> overview_;
    std::wstring status_line_ = L"Loading SGFX evidence surfaces.";
    std::wstring command_output_;
    int last_command_exit_code_ = 0;
    bool show_help_ = false;
};

int RunShell(HINSTANCE instance, PWSTR command_line, int show_command);

}  // namespace sg_preflight::sgfx_shell
