#include "sgfx_shell/sgfx_shell_app.hpp"

#include "sgfx_shell/sgfx_menus.hpp"

#include <shellapi.h>

#include <algorithm>
#include <array>
#include <cstdio>
#include <cwctype>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace sg_preflight::sgfx_shell {

namespace {

#ifndef SG_NATIVE_SHELL_VERSION
#define SG_NATIVE_SHELL_VERSION "dev"
#endif

constexpr const wchar_t* kWindowClassName = L"SGFXProjectQualityHeroShell";
constexpr const wchar_t* kWindowTitle = L"SGFX: Project Quality-Hero";

std::filesystem::path CurrentDirectory() {
    std::array<wchar_t, MAX_PATH> buffer{};
    const DWORD length = GetCurrentDirectoryW(static_cast<DWORD>(buffer.size()), buffer.data());
    if (length == 0U || length >= buffer.size()) {
        return std::filesystem::current_path();
    }
    return std::filesystem::path(buffer.data());
}

std::wstring Quote(const std::wstring& value) {
    return L"\"" + value + L"\"";
}

std::wstring ToWideLocal(const std::string& text) {
    return sg_preflight::native_shell::ToWide(text);
}

void DrawTextLine(HDC dc, int x, int y, const std::wstring& text, COLORREF color) {
    SetTextColor(dc, color);
    SetBkMode(dc, TRANSPARENT);
    TextOutW(dc, x, y, text.c_str(), static_cast<int>(text.size()));
}

std::filesystem::path ResolveWorkspaceRoot(const std::filesystem::path& bundle_root) {
    const std::filesystem::path bundled_workspace = bundle_root / "workspace";
    if (std::filesystem::exists(bundled_workspace / "sg_preflight")) {
        return bundled_workspace;
    }
    return bundle_root;
}

std::wstring ResolvePythonExecutable(const std::filesystem::path& bundle_root) {
    const std::array<std::filesystem::path, 3> candidates = {
        bundle_root / "python" / "python.exe",
        bundle_root / "python" / "Scripts" / "python.exe",
        bundle_root / "workspace" / ".venv" / "Scripts" / "python.exe",
    };
    for (const auto& candidate : candidates) {
        if (std::filesystem::exists(candidate)) {
            return candidate.wstring();
        }
    }
    return L"python";
}

SgfxUiMode ParseModeValue(std::wstring value) {
    std::transform(value.begin(), value.end(), value.begin(), [](wchar_t ch) {
        return static_cast<wchar_t>(std::towlower(ch));
    });
    if (value == L"grafiks" || value == L"sgfx" || value == L"branded") {
        return SgfxUiMode::Branded;
    }
    if (value == L"work") {
        return SgfxUiMode::Clean;
    }
    return SgfxUiMode::Clean;
}

std::wstring ModeLabel(SgfxUiMode mode) {
    return mode == SgfxUiMode::Clean ? L"Clean mode" : L"Grafiks mode";
}

std::wstring ModeValue(SgfxUiMode mode) {
    return mode == SgfxUiMode::Clean ? L"clean" : L"grafiks";
}

std::wstring ReadIniValue(const std::filesystem::path& path, const wchar_t* key, const wchar_t* fallback) {
    std::array<wchar_t, 128> buffer{};
    GetPrivateProfileStringW(L"sg_preflight_native_shell", key, fallback, buffer.data(), static_cast<DWORD>(buffer.size()), path.wstring().c_str());
    return buffer.data();
}

std::wstring CycleValue(std::wstring current, std::initializer_list<const wchar_t*> values) {
    std::vector<std::wstring> items(values.begin(), values.end());
    const auto found = std::find(items.begin(), items.end(), current);
    if (found == items.end()) {
        return items.front();
    }
    auto next = found + 1;
    if (next == items.end()) {
        return items.front();
    }
    return *next;
}

void ReplaceAll(std::wstring& text, const std::wstring& needle, const std::wstring& replacement) {
    size_t offset = 0;
    while ((offset = text.find(needle, offset)) != std::wstring::npos) {
        text.replace(offset, needle.size(), replacement);
        offset += replacement.size();
    }
}

std::string SurfaceFromCommand(const std::string& command) {
    const size_t first_space = command.find(' ');
    if (first_space == std::string::npos) {
        return command.empty() ? "native-shell" : command;
    }
    const size_t second_space = command.find(' ', first_space + 1U);
    return command.substr(0, second_space == std::string::npos ? second_space : second_space);
}

}  // namespace

SgfxShellApp::SgfxShellApp(HINSTANCE instance) : instance_(instance) {
    config_.bundle_root = CurrentDirectory();
    config_.workspace_root = ResolveWorkspaceRoot(config_.bundle_root);
    config_.ini_path = config_.bundle_root / "imgui.ini";
    config_.python_executable = ResolvePythonExecutable(config_.bundle_root);
    load_preferences();
}

int SgfxShellApp::run(PWSTR command_line, int show_command) {
    parse_command_line(command_line);
    backend_.workspace_root = config_.workspace_root.wstring();
    backend_.python_executable = config_.python_executable;
    backend_.initial_profile_id = "G65";

    resources_.load(config_.workspace_root, config_.bundle_root);
    build_menus();
    if (config_.ui_mode == SgfxUiMode::Clean) {
        menu_manager_.activate(SgfxScreenId::CleanStatus);
    }

    sg_preflight::native_shell::AppendNativeTrace("shell_start mode=" + std::string(config_.ui_mode == SgfxUiMode::Clean ? "clean" : "grafiks"));
    sg_preflight::native_shell::AppendNativeTrace(resources_.has_visual_chrome() ? "resource_bundle=available" : "resource_bundle=missing");
    sg_preflight::native_shell::AppendNativeTrace(resources_.has_sfx() ? "sfx_bundle=available" : "sfx_bundle=missing");

    if (!create_window(show_command)) {
        return 1;
    }
    diagnostic_.refresh(config_.workspace_root);
    load_backend_state();
    InvalidateRect(window_, nullptr, TRUE);
    UpdateWindow(window_);

    MSG message{};
    while (GetMessageW(&message, nullptr, 0U, 0U) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    return static_cast<int>(message.wParam);
}

void SgfxShellApp::parse_command_line(PWSTR command_line) {
    (void)command_line;
    int argc = 0;
    PWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv == nullptr) {
        return;
    }
    for (int index = 1; index < argc; ++index) {
        const std::wstring arg = argv[index];
        if ((arg == L"--ui-mode" || arg == L"--display-mode") && index + 1 < argc) {
            config_.ui_mode = ParseModeValue(argv[++index]);
        } else if (arg == L"--width" && index + 1 < argc) {
            config_.width = std::max(640, _wtoi(argv[++index]));
        } else if (arg == L"--height" && index + 1 < argc) {
            config_.height = std::max(480, _wtoi(argv[++index]));
        } else if (arg == L"--fullscreen") {
            config_.windowed = false;
        } else if (arg == L"--windowed") {
            config_.windowed = true;
        } else if (arg == L"--mode" && index + 1 < argc) {
            ++index;
        }
    }
    LocalFree(argv);
}

bool SgfxShellApp::create_window(int show_command) {
    WNDCLASSEXW window_class{};
    window_class.cbSize = sizeof(window_class);
    window_class.style = CS_HREDRAW | CS_VREDRAW;
    window_class.lpfnWndProc = &SgfxShellApp::WindowProc;
    window_class.hInstance = instance_;
    window_class.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    window_class.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
    window_class.lpszClassName = kWindowClassName;
    if (RegisterClassExW(&window_class) == 0U) {
        return false;
    }

    const DWORD style = config_.windowed ? WS_OVERLAPPEDWINDOW : WS_POPUP;
    RECT rect{0, 0, config_.width, config_.height};
    AdjustWindowRect(&rect, style, FALSE);
    window_ = CreateWindowExW(
        0,
        kWindowClassName,
        kWindowTitle,
        style,
        CW_USEDEFAULT,
        CW_USEDEFAULT,
        rect.right - rect.left,
        rect.bottom - rect.top,
        nullptr,
        nullptr,
        instance_,
        this
    );
    if (window_ == nullptr) {
        return false;
    }
    ShowWindow(window_, config_.windowed ? show_command : SW_MAXIMIZE);
    UpdateWindow(window_);
    return true;
}

void SgfxShellApp::build_menus() {
    menu_manager_.add_menu(std::make_unique<SgfxMainMenu>());
    menu_manager_.add_menu(std::make_unique<SgfxWorkflowMenu>());
    menu_manager_.add_menu(std::make_unique<SgfxEvidenceSummaryMenu>());
    menu_manager_.add_menu(std::make_unique<SgfxSettingsMenu>());
    menu_manager_.add_menu(std::make_unique<SgfxQuickActionsMenu>());
    menu_manager_.add_menu(std::make_unique<SgfxDigestMenu>());
    menu_manager_.add_menu(std::make_unique<SgfxCleanStatusMenu>());
}

void SgfxShellApp::load_backend_state() {
    try {
        overview_ = sg_preflight::native_shell::LoadOperatorOverview(backend_, "G65");
        status_line_ = L"Overview loaded from Python data layer.";
    } catch (const std::exception& exc) {
        overview_.reset();
        status_line_ = L"Overview unavailable: " + ToWideLocal(exc.what()).substr(0, 180);
        sg_preflight::native_shell::AppendNativeTrace("overview unavailable");
    }
}

void SgfxShellApp::load_preferences() {
    if (config_.ini_path.empty()) {
        return;
    }
    config_.ui_mode = ParseModeValue(ReadIniValue(config_.ini_path, L"display_mode", L"clean"));
    config_.font_size = ReadIniValue(config_.ini_path, L"font_size", L"medium");
    config_.dpi_scale = ReadIniValue(config_.ini_path, L"dpi_scale", L"auto");
    config_.contrast = ReadIniValue(config_.ini_path, L"contrast", L"standard");
}

void SgfxShellApp::save_preferences() {
    if (config_.ini_path.empty()) {
        return;
    }
    WritePrivateProfileStringW(L"sg_preflight_native_shell", L"display_mode", ModeValue(config_.ui_mode).c_str(), config_.ini_path.wstring().c_str());
    WritePrivateProfileStringW(L"sg_preflight_native_shell", L"font_size", config_.font_size.c_str(), config_.ini_path.wstring().c_str());
    WritePrivateProfileStringW(L"sg_preflight_native_shell", L"dpi_scale", config_.dpi_scale.c_str(), config_.ini_path.wstring().c_str());
    WritePrivateProfileStringW(L"sg_preflight_native_shell", L"contrast", config_.contrast.c_str(), config_.ini_path.wstring().c_str());
}

void SgfxShellApp::refresh() {
    load_backend_state();
    InvalidateRect(window_, nullptr, TRUE);
}

void SgfxShellApp::toggle_mode() {
    config_.ui_mode = config_.ui_mode == SgfxUiMode::Clean ? SgfxUiMode::Branded : SgfxUiMode::Clean;
    if (config_.ui_mode == SgfxUiMode::Clean) {
        menu_manager_.activate(SgfxScreenId::CleanStatus);
    } else {
        menu_manager_.activate(SgfxScreenId::Main);
    }
    status_line_ = ModeLabel(config_.ui_mode) + L" active.";
    save_preferences();
    record_activity(SgfxMenuAction{"Mode switch", "", "@toggle-mode", ""}, 0);
    sg_preflight::native_shell::AppendNativeTrace(config_.ui_mode == SgfxUiMode::Clean ? "display_mode=clean" : "display_mode=grafiks");
    InvalidateRect(window_, nullptr, TRUE);
}

void SgfxShellApp::execute_selected_action() {
    const SgfxMenuAction* action = menu_manager_.selected_action();
    if (action == nullptr) {
        return;
    }
    if (action->label == "Quit SGFX") {
        PostQuitMessage(0);
        return;
    }
    if (handle_internal_action(action->command)) {
        if (action->command != "@toggle-mode") {
            record_activity(*action, 0);
        }
        InvalidateRect(window_, nullptr, TRUE);
        return;
    }
    if (action->command.empty()) {
        status_line_ = ToWideLocal(action->label + ": local UI setting, no backend command.");
        command_output_.clear();
        InvalidateRect(window_, nullptr, TRUE);
        return;
    }
    status_line_ = ToWideLocal("Running read-only command: python -B -m sg_preflight " + action->command);
    command_output_ = run_python_command(action->command);
    record_activity(*action, last_command_exit_code_);
    InvalidateRect(window_, nullptr, TRUE);
}

bool SgfxShellApp::handle_internal_action(const std::string& command) {
    if (command == "@toggle-mode") {
        toggle_mode();
        return true;
    }
    if (command == "@font-size") {
        config_.font_size = CycleValue(config_.font_size, {L"small", L"medium", L"large"});
        save_preferences();
        status_line_ = L"Font size set to " + config_.font_size + L".";
        return true;
    }
    if (command == "@dpi-scale") {
        config_.dpi_scale = CycleValue(config_.dpi_scale, {L"auto", L"1.0x", L"1.25x", L"1.5x", L"2.0x"});
        save_preferences();
        status_line_ = L"High-DPI scaling set to " + config_.dpi_scale + L".";
        return true;
    }
    if (command == "@contrast") {
        config_.contrast = config_.contrast == L"high" ? L"standard" : L"high";
        save_preferences();
        status_line_ = L"Color contrast set to " + config_.contrast + L".";
        return true;
    }
    return false;
}

std::wstring SgfxShellApp::run_python_command(const std::string& command) {
    std::wstring expanded_command = ToWideLocal(command);
    ReplaceAll(expanded_command, L"{workspace}", Quote(config_.workspace_root.wstring()));
    const std::wstring full_command =
        Quote(config_.python_executable) + L" -B -m sg_preflight " + expanded_command;
    FILE* pipe = _wpopen(full_command.c_str(), L"rt");
    if (pipe == nullptr) {
        last_command_exit_code_ = 1;
        return L"Could not launch Python command.";
    }
    std::wstring output;
    wchar_t buffer[512]{};
    while (fgetws(buffer, static_cast<int>(std::size(buffer)), pipe) != nullptr) {
        output += buffer;
        if (output.size() > 2400U) {
            output += L"\n[truncated]";
            break;
        }
    }
    const int code = _pclose(pipe);
    last_command_exit_code_ = code;
    status_line_ = L"Command exited with code " + std::to_wstring(code);
    return output.empty() ? L"No output captured." : output;
}

void SgfxShellApp::record_activity(const SgfxMenuAction& action, int exit_code) {
    const std::wstring outcome = exit_code == 0 ? L"ok" : L"error";
    const std::wstring verb = action.command == "@toggle-mode" ? L"switched-mode" : L"read";
    const std::wstring surface = action.command.empty() ? ToWideLocal(action.label) : ToWideLocal(SurfaceFromCommand(action.command));
    const std::wstring command =
        Quote(config_.python_executable)
        + L" -B -m sg_preflight activity-log append --workspace "
        + Quote(config_.workspace_root.wstring())
        + L" --verb " + verb
        + L" --surface " + Quote(surface)
        + L" --profile G65 --outcome " + outcome
        + L" --note " + Quote(L"native shell");
    FILE* pipe = _wpopen(command.c_str(), L"rt");
    if (pipe != nullptr) {
        (void)_pclose(pipe);
    }
}

LRESULT CALLBACK SgfxShellApp::WindowProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_NCCREATE) {
        const CREATESTRUCTW* create = reinterpret_cast<CREATESTRUCTW*>(lparam);
        auto* app = static_cast<SgfxShellApp*>(create->lpCreateParams);
        SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
        app->window_ = window;
    }
    auto* app = reinterpret_cast<SgfxShellApp*>(GetWindowLongPtrW(window, GWLP_USERDATA));
    if (app != nullptr) {
        return app->handle_message(message, wparam, lparam);
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

LRESULT SgfxShellApp::handle_message(UINT message, WPARAM wparam, LPARAM lparam) {
    switch (message) {
        case WM_KEYDOWN:
            switch (wparam) {
                case VK_UP:
                    menu_manager_.move_selection(-1);
                    InvalidateRect(window_, nullptr, TRUE);
                    return 0;
                case VK_DOWN:
                    menu_manager_.move_selection(1);
                    InvalidateRect(window_, nullptr, TRUE);
                    return 0;
                case VK_RETURN:
                    execute_selected_action();
                    return 0;
                case VK_ESCAPE:
                    PostQuitMessage(0);
                    return 0;
                case VK_F1:
                    show_help_ = !show_help_;
                    InvalidateRect(window_, nullptr, TRUE);
                    return 0;
                case VK_F2:
                    menu_manager_.activate_previous();
                    InvalidateRect(window_, nullptr, TRUE);
                    return 0;
                case VK_F3:
                    toggle_mode();
                    return 0;
                case VK_F5:
                    refresh();
                    return 0;
                case VK_F12:
                    diagnostic_.toggle();
                    diagnostic_.refresh(config_.workspace_root);
                    InvalidateRect(window_, nullptr, TRUE);
                    return 0;
                default:
                    break;
            }
            break;
        case WM_RBUTTONUP:
            menu_manager_.activate_next();
            InvalidateRect(window_, nullptr, TRUE);
            return 0;
        case WM_PAINT: {
            PAINTSTRUCT paint{};
            HDC dc = BeginPaint(window_, &paint);
            draw(dc);
            EndPaint(window_, &paint);
            return 0;
        }
        case WM_DESTROY:
            PostQuitMessage(0);
            return 0;
        default:
            break;
    }
    return DefWindowProcW(window_, message, wparam, lparam);
}

void SgfxShellApp::draw(HDC dc) {
    RECT bounds{};
    GetClientRect(window_, &bounds);
    background_.draw(dc, bounds, config_.ui_mode);
    draw_menu(dc, bounds);
    if (diagnostic_.visible()) {
        draw_diagnostic_overlay(dc, bounds);
    }
}

void SgfxShellApp::draw_menu(HDC dc, const RECT& bounds) {
    const int font_adjust = config_.font_size == L"large" ? 4 : (config_.font_size == L"small" ? -2 : 0);
    HFONT title_font = CreateFontW(34 + font_adjust, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    HFONT body_font = CreateFontW(20 + font_adjust, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    HFONT small_font = CreateFontW(16 + font_adjust, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");

    const auto& menu = menu_manager_.active_menu();
    SelectObject(dc, title_font);
    DrawTextLine(dc, 42, 30, ToWideLocal(menu.title()), RGB(238, 242, 246));

    SelectObject(dc, body_font);
    DrawTextLine(dc, 46, 76, ToWideLocal(menu.subtitle()), RGB(176, 188, 202));
    DrawTextLine(dc, bounds.right - 260, 38, ModeLabel(config_.ui_mode), RGB(128, 220, 198));

    const int row_start = 136;
    const int row_height = 58;
    const int visible_rows = std::max(1, static_cast<int>(bounds.bottom - 230) / row_height);
    scrolling_.ensure_visible(menu.selected_index(), visible_rows);
    const int first_row = scrolling_.first_visible_row();
    const auto& actions = menu.actions();

    SelectObject(dc, body_font);
    for (int row = 0; row < visible_rows; ++row) {
        const int action_index = first_row + row;
        if (action_index >= static_cast<int>(actions.size())) {
            break;
        }
        const SgfxMenuAction& action = actions[static_cast<size_t>(action_index)];
        RECT item_rect{42, row_start + row * row_height, bounds.right - 42, row_start + row * row_height + row_height - 8};
        const bool high_contrast = config_.contrast == L"high";
        HBRUSH brush = CreateSolidBrush(
            action_index == menu.selected_index()
                ? (high_contrast ? RGB(54, 66, 76) : (config_.ui_mode == SgfxUiMode::Clean ? RGB(37, 44, 49) : RGB(45, 61, 83)))
                : (high_contrast ? RGB(8, 12, 16) : (config_.ui_mode == SgfxUiMode::Clean ? RGB(25, 28, 31) : RGB(25, 32, 46)))
        );
        FillRect(dc, &item_rect, brush);
        DeleteObject(brush);
        DrawTextLine(dc, item_rect.left + 14, item_rect.top + 8, ToWideLocal(action.label), RGB(239, 243, 246));
        SelectObject(dc, small_font);
        DrawTextLine(dc, item_rect.left + 16, item_rect.top + 34, ToWideLocal(action.detail), RGB(162, 174, 186));
        SelectObject(dc, body_font);
    }

    SelectObject(dc, small_font);
    DrawTextLine(dc, 46, bounds.bottom - 44, controls_.controls_line(), RGB(172, 184, 196));
    DrawTextLine(dc, 46, bounds.bottom - 24, status_line_, RGB(128, 220, 198));

    if (overview_) {
        const std::wstring summary = L"Profiles ready: " + std::to_wstring(overview_->ready_profile_count)
            + L"  Actions ready: " + std::to_wstring(overview_->ready_action_count)
            + L"  Blockers: " + std::to_wstring(overview_->blocker_count)
            + L"  Manual cards: " + std::to_wstring(overview_->manual_card_count)
            + L"  Export-size analysis: " + ToWideLocal(overview_->export_size_analysis_status);
        DrawTextLine(dc, 46, 106, summary, RGB(204, 213, 222));
    } else {
        DrawTextLine(dc, 46, 106, L"Overview unavailable; shell remains usable for direct read-only commands.", RGB(224, 196, 128));
    }

    if (show_help_) {
        DrawTextLine(dc, 46, bounds.bottom - 84, controls_.help_text(), RGB(245, 220, 154));
    } else if (!command_output_.empty()) {
        std::wstring preview = command_output_.substr(0, 170);
        std::replace(preview.begin(), preview.end(), L'\n', L' ');
        DrawTextLine(dc, 46, bounds.bottom - 84, preview, RGB(207, 216, 226));
    }

    DeleteObject(title_font);
    DeleteObject(body_font);
    DeleteObject(small_font);
}

void SgfxShellApp::draw_diagnostic_overlay(HDC dc, const RECT& bounds) {
    RECT overlay{bounds.right - 520, 116, bounds.right - 42, bounds.bottom - 96};
    HBRUSH brush = CreateSolidBrush(RGB(14, 18, 22));
    FillRect(dc, &overlay, brush);
    DeleteObject(brush);
    FrameRect(dc, &overlay, static_cast<HBRUSH>(GetStockObject(WHITE_BRUSH)));

    HFONT font = CreateFontW(16, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    SelectObject(dc, font);
    DrawTextLine(dc, overlay.left + 14, overlay.top + 14, L"Diagnostic Mode - read-only environment health", RGB(239, 243, 246));

    int y = overlay.top + 44;
    for (const auto& row : diagnostic_.rows()) {
        DrawTextLine(dc, overlay.left + 14, y, row.label + L": " + row.result, RGB(128, 220, 198));
        y += 20;
        DrawTextLine(dc, overlay.left + 28, y, row.detail.substr(0, 58), RGB(165, 176, 188));
        y += 26;
        if (y > overlay.bottom - 36) {
            break;
        }
    }
    DrawTextLine(dc, overlay.left + 14, overlay.bottom - 28, L"All checks are local read-only lookups.", RGB(245, 220, 154));
    DeleteObject(font);
}

int RunShell(HINSTANCE instance, PWSTR command_line, int show_command) {
    try {
        SgfxShellApp app(instance);
        return app.run(command_line, show_command);
    } catch (const std::exception& exc) {
        MessageBoxW(nullptr, ToWideLocal(exc.what()).c_str(), L"SGFX shell startup failed", MB_ICONERROR | MB_OK);
        return 1;
    }
}

}  // namespace sg_preflight::sgfx_shell
