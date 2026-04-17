#include "backend_bridge.hpp"

#include <d3d11.h>
#include <shellapi.h>
#include <windows.h>

#include <algorithm>
#include <array>
#include <cfloat>
#include <cmath>
#include <cstring>
#include <cwctype>
#include <filesystem>
#include <optional>
#include <string>
#include <system_error>
#include <vector>

#include "imgui.h"
#include "backends/imgui_impl_dx11.h"
#include "backends/imgui_impl_win32.h"

extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(HWND, UINT, WPARAM, LPARAM);

using sg_preflight::native_shell::ActionItem;
using sg_preflight::native_shell::ActionSnapshot;
using sg_preflight::native_shell::BackendConfig;
using sg_preflight::native_shell::BlockerItem;
using sg_preflight::native_shell::CopyItem;
using sg_preflight::native_shell::EvidenceItem;
using sg_preflight::native_shell::ManualCard;
using sg_preflight::native_shell::ProfileItem;
using sg_preflight::native_shell::RecentActionItem;
using sg_preflight::native_shell::RecentRunItem;
using sg_preflight::native_shell::RunSnapshot;

namespace {

ID3D11Device* g_device = nullptr;
ID3D11DeviceContext* g_device_context = nullptr;
IDXGISwapChain* g_swap_chain = nullptr;
ID3D11RenderTargetView* g_render_target = nullptr;
ImFont* g_title_font = nullptr;
ImFont* g_body_font = nullptr;
ImFont* g_small_font = nullptr;
double g_shell_appear_time = -1.0;
ImVec2 g_tab_highlight_min{};
ImVec2 g_tab_highlight_max{};
bool g_tab_highlight_ready = false;

struct ShellState {
    BackendConfig backend;
    std::vector<ProfileItem> profiles;
    std::vector<ActionItem> actions;
    std::vector<BlockerItem> blockers;
    std::vector<ManualCard> manual_cards;
    std::vector<RecentActionItem> recent_actions;
    std::vector<RecentRunItem> recent_runs;
    std::optional<ActionSnapshot> snapshot;
    std::optional<RunSnapshot> run_snapshot;
    int selected_profile_index = 0;
    int selected_evidence_index = 0;
    int selected_artifact_index = 0;
    std::string selected_action_id;
    std::string current_run_id;
    std::string current_result_run_id;
    std::string status_line = "Ready for the next SG QA action.";
    std::string last_error;
    double next_poll_at = 0.0;
};

struct ArtifactChoice {
    std::string section;
    std::string label;
    std::string path;
};

enum class UiCue {
    Cursor,
    Confirm,
    Error,
    Window,
};

constexpr float kPanelGrid = 9.0f;
constexpr float kPanelHeaderHeight = 34.0f;
constexpr float kRailFooterReserve = 62.0f;

float Saturate(float value) {
    return std::clamp(value, 0.0f, 1.0f);
}

float EaseOutCubic(float value) {
    const float clamped = Saturate(value);
    const float inverse = 1.0f - clamped;
    return 1.0f - (inverse * inverse * inverse);
}

float SmoothStep(float value) {
    const float clamped = Saturate(value);
    return clamped * clamped * (3.0f - 2.0f * clamped);
}

float LerpFloat(float lhs, float rhs, float alpha) {
    return lhs + (rhs - lhs) * alpha;
}

ImVec2 LerpVec2(ImVec2 lhs, ImVec2 rhs, float alpha) {
    return ImVec2(LerpFloat(lhs.x, rhs.x, alpha), LerpFloat(lhs.y, rhs.y, alpha));
}

float ExpApproach(float current, float target, float rate) {
    const float alpha = 1.0f - std::exp(-rate * ImGui::GetIO().DeltaTime);
    return LerpFloat(current, target, alpha);
}

ImVec2 ExpApproach(ImVec2 current, ImVec2 target, float rate) {
    const float alpha = 1.0f - std::exp(-rate * ImGui::GetIO().DeltaTime);
    return LerpVec2(current, target, alpha);
}

float ShellMotion(double offset_frames, double duration_frames) {
    if (g_shell_appear_time < 0.0) {
        return 1.0f;
    }
    const double frame = (ImGui::GetTime() - g_shell_appear_time) * 60.0;
    if (duration_frames <= 0.0) {
        return frame >= offset_frames ? 1.0f : 0.0f;
    }
    return SmoothStep(static_cast<float>((frame - offset_frames) / duration_frames));
}

ImU32 ApplyAlpha(ImU32 color, float alpha_scale) {
    ImVec4 rgba = ImGui::ColorConvertU32ToFloat4(color);
    rgba.w *= Saturate(alpha_scale);
    return ImGui::ColorConvertFloat4ToU32(rgba);
}

bool PathExists(const std::filesystem::path& path) {
    std::error_code error;
    return std::filesystem::exists(path, error);
}

std::optional<std::filesystem::path> DiscoverRepoRoot(std::filesystem::path start) {
    std::error_code error;
    if (start.empty()) {
        return std::nullopt;
    }
    if (PathExists(start) && std::filesystem::is_regular_file(start, error)) {
        start = start.parent_path();
    }
    for (std::filesystem::path current = start; !current.empty(); current = current.parent_path()) {
        if (
            PathExists(current / "pyproject.toml")
            && PathExists(current / "sg_preflight")
            && PathExists(current / "desktop_native")
        ) {
            return current;
        }
        if (current == current.root_path()) {
            break;
        }
    }
    return std::nullopt;
}

std::filesystem::path GetExecutableDirectory() {
    std::wstring buffer(MAX_PATH, L'\0');
    DWORD copied = 0;
    while (true) {
        copied = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
        if (copied == 0) {
            return std::filesystem::current_path();
        }
        if (copied < buffer.size() - 1) {
            break;
        }
        buffer.resize(buffer.size() * 2);
    }
    buffer.resize(copied);
    return std::filesystem::path(buffer).parent_path();
}

std::filesystem::path ResolveWorkspaceRoot() {
    if (const auto from_executable = DiscoverRepoRoot(GetExecutableDirectory())) {
        return *from_executable;
    }
    if (const auto from_cwd = DiscoverRepoRoot(std::filesystem::current_path())) {
        return *from_cwd;
    }
    return std::filesystem::current_path();
}

std::wstring ResolvePythonExecutable(const std::filesystem::path& workspace_root) {
    const std::array<std::filesystem::path, 2> candidates = {
        workspace_root / ".venv" / "Scripts" / "python.exe",
        workspace_root / "venv" / "Scripts" / "python.exe",
    };
    for (const auto& candidate : candidates) {
        if (PathExists(candidate)) {
            return candidate.wstring();
        }
    }
    return L"python";
}

void PlayCue(UiCue cue) {
    static double last_cursor = 0.0;
    static double last_confirm = 0.0;
    static double last_error = 0.0;
    static double last_window = 0.0;

    const double now = ImGui::GetTime();
    double* last_time = &last_cursor;
    UINT beep = MB_OK;
    switch (cue) {
    case UiCue::Cursor:
        last_time = &last_cursor;
        beep = MB_OK;
        break;
    case UiCue::Confirm:
        last_time = &last_confirm;
        beep = MB_ICONASTERISK;
        break;
    case UiCue::Error:
        last_time = &last_error;
        beep = MB_ICONHAND;
        break;
    case UiCue::Window:
        last_time = &last_window;
        beep = MB_ICONQUESTION;
        break;
    }
    if ((now - *last_time) < 0.08) {
        return;
    }
    *last_time = now;
    MessageBeep(beep);
}

void CreateRenderTarget() {
    ID3D11Texture2D* back_buffer = nullptr;
    g_swap_chain->GetBuffer(0, IID_PPV_ARGS(&back_buffer));
    if (back_buffer != nullptr) {
        g_device->CreateRenderTargetView(back_buffer, nullptr, &g_render_target);
        back_buffer->Release();
    }
}

void CleanupRenderTarget() {
    if (g_render_target != nullptr) {
        g_render_target->Release();
        g_render_target = nullptr;
    }
}

bool CreateDeviceD3D(HWND window_handle) {
    DXGI_SWAP_CHAIN_DESC swap_chain_desc{};
    swap_chain_desc.BufferCount = 2;
    swap_chain_desc.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    swap_chain_desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    swap_chain_desc.OutputWindow = window_handle;
    swap_chain_desc.SampleDesc.Count = 1;
    swap_chain_desc.Windowed = TRUE;
    swap_chain_desc.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;

    constexpr D3D_FEATURE_LEVEL feature_levels[] = {
        D3D_FEATURE_LEVEL_11_0,
        D3D_FEATURE_LEVEL_10_0,
    };
    D3D_FEATURE_LEVEL feature_level{};

    const HRESULT result = D3D11CreateDeviceAndSwapChain(
        nullptr,
        D3D_DRIVER_TYPE_HARDWARE,
        nullptr,
        0,
        feature_levels,
        static_cast<UINT>(sizeof(feature_levels) / sizeof(feature_levels[0])),
        D3D11_SDK_VERSION,
        &swap_chain_desc,
        &g_swap_chain,
        &g_device,
        &feature_level,
        &g_device_context
    );
    if (FAILED(result)) {
        return false;
    }

    CreateRenderTarget();
    return true;
}

void CleanupDeviceD3D() {
    CleanupRenderTarget();
    if (g_swap_chain != nullptr) {
        g_swap_chain->Release();
        g_swap_chain = nullptr;
    }
    if (g_device_context != nullptr) {
        g_device_context->Release();
        g_device_context = nullptr;
    }
    if (g_device != nullptr) {
        g_device->Release();
        g_device = nullptr;
    }
}

LRESULT WINAPI WndProc(HWND window_handle, UINT message, WPARAM w_param, LPARAM l_param) {
    if (ImGui_ImplWin32_WndProcHandler(window_handle, message, w_param, l_param)) {
        return TRUE;
    }

    switch (message) {
    case WM_SIZE:
        if (g_device != nullptr && w_param != SIZE_MINIMIZED) {
            CleanupRenderTarget();
            g_swap_chain->ResizeBuffers(0, static_cast<UINT>(LOWORD(l_param)), static_cast<UINT>(HIWORD(l_param)), DXGI_FORMAT_UNKNOWN, 0);
            CreateRenderTarget();
        }
        return 0;
    case WM_SYSCOMMAND:
        if ((w_param & 0xfff0) == SC_KEYMENU) {
            return 0;
        }
        break;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    default:
        break;
    }

    return DefWindowProcW(window_handle, message, w_param, l_param);
}

bool StartsWithInsensitive(const std::wstring& lhs, const std::wstring& rhs) {
    if (lhs.size() < rhs.size()) {
        return false;
    }
    for (size_t index = 0; index < rhs.size(); ++index) {
        if (towlower(lhs[index]) != towlower(rhs[index])) {
            return false;
        }
    }
    return true;
}

BackendConfig ParseArguments() {
    BackendConfig config;
    std::filesystem::path workspace_root = ResolveWorkspaceRoot();
    config.workspace_root = workspace_root.wstring();
    config.python_executable = ResolvePythonExecutable(workspace_root);
    bool workspace_override = false;
    bool python_override = false;

    for (int index = 1; index < __argc; ++index) {
        const std::wstring_view arg = __wargv[index];
        if ((arg == L"--workspace-root" || arg == L"--workspace") && index + 1 < __argc) {
            config.workspace_root = __wargv[++index];
            workspace_override = true;
            continue;
        }
        if (arg == L"--python" && index + 1 < __argc) {
            config.python_executable = __wargv[++index];
            python_override = true;
            continue;
        }
        if (StartsWithInsensitive(std::wstring(arg), L"--workspace-root=")) {
            config.workspace_root = std::wstring(arg.substr(17));
            workspace_override = true;
            continue;
        }
        if (StartsWithInsensitive(std::wstring(arg), L"--python=")) {
            config.python_executable = std::wstring(arg.substr(9));
            python_override = true;
            continue;
        }
    }

    if (workspace_override && !python_override) {
        config.python_executable = ResolvePythonExecutable(std::filesystem::path(config.workspace_root));
    }
    if (config.python_executable.empty()) {
        config.python_executable = L"python";
    }
    return config;
}

std::string CurrentProfileId(const ShellState& state) {
    if (state.profiles.empty()) {
        return {};
    }
    const int clamped_index = std::clamp(state.selected_profile_index, 0, static_cast<int>(state.profiles.size()) - 1);
    return state.profiles[static_cast<size_t>(clamped_index)].profile_id;
}

std::string CurrentActionId(const ShellState& state) {
    return state.selected_action_id.empty() ? std::string("daily_live_matrix") : state.selected_action_id;
}

const ActionItem* FindSelectedAction(const ShellState& state) {
    for (const ActionItem& action : state.actions) {
        if (action.action_id == state.selected_action_id) {
            return &action;
        }
    }
    return nullptr;
}

std::string ShortActionLabel(const std::string& action_id) {
    if (action_id == "daily_live_matrix") {
        return "DAILY";
    }
    if (action_id.find("qa_stack__") == 0) {
        return "STACK";
    }
    if (action_id.find("repo_checker_") == 0) {
        return "REPO";
    }
    if (action_id.find("scene_check__") == 0) {
        return "SCENE";
    }
    if (action_id.find("unused_resources__") == 0) {
        return "UNUSED";
    }
    if (action_id.find("delivery_checklist__") == 0) {
        return "DELIVERY";
    }
    return "ACTION";
}

void ClampSelections(ShellState& state) {
    const size_t top_paths = state.snapshot.has_value() ? state.snapshot->top_paths.size() : 0U;
    size_t artifacts = 0U;
    if (state.snapshot.has_value()) {
        artifacts += state.snapshot->artifacts.size();
    }
    if (state.run_snapshot.has_value()) {
        artifacts += state.run_snapshot->artifacts.size();
        artifacts += state.run_snapshot->source_files.size();
    }
    state.selected_evidence_index = top_paths == 0
        ? 0
        : std::clamp(state.selected_evidence_index, 0, static_cast<int>(top_paths) - 1);
    state.selected_artifact_index = artifacts == 0
        ? 0
        : std::clamp(state.selected_artifact_index, 0, static_cast<int>(artifacts) - 1);
}

std::vector<ArtifactChoice> CombinedArtifacts(const ShellState& state) {
    std::vector<ArtifactChoice> items;
    if (state.snapshot.has_value()) {
        for (const auto& artifact : state.snapshot->artifacts) {
            items.push_back({"Action files", artifact.label, artifact.path});
        }
    }
    if (state.run_snapshot.has_value()) {
        for (const auto& artifact : state.run_snapshot->artifacts) {
            items.push_back({"Run outputs", artifact.label, artifact.path});
        }
        for (const auto& source : state.run_snapshot->source_files) {
            items.push_back({"Source-of-truth files", source.label, source.path});
        }
    }
    return items;
}

std::vector<CopyItem> CombinedCopyItems(const ShellState& state) {
    std::vector<CopyItem> items;
    std::vector<std::string> seen_keys;
    const auto append_items = [&](const std::vector<CopyItem>& source) {
        for (const CopyItem& item : source) {
            if (item.text.empty()) {
                continue;
            }
            const bool duplicate = std::find(seen_keys.begin(), seen_keys.end(), item.key) != seen_keys.end();
            if (duplicate) {
                continue;
            }
            seen_keys.push_back(item.key);
            items.push_back(item);
        }
    };
    if (state.snapshot.has_value()) {
        append_items(state.snapshot->copy_items);
    }
    if (state.run_snapshot.has_value()) {
        append_items(state.run_snapshot->copy_items);
    }
    return items;
}

void RefreshSnapshot(ShellState& state) {
    if (state.current_run_id.empty()) {
        state.snapshot.reset();
        return;
    }
    try {
        state.snapshot = sg_preflight::native_shell::LoadSnapshot(state.backend, state.current_run_id);
        if (state.snapshot.has_value() && !state.snapshot->linked_run_id.empty()) {
            state.current_result_run_id = state.snapshot->linked_run_id;
        }
        ClampSelections(state);
        state.last_error.clear();
    } catch (const std::exception& error) {
        state.last_error = error.what();
        PlayCue(UiCue::Error);
    }
}

void RefreshRunSnapshot(ShellState& state) {
    if (state.current_result_run_id.empty()) {
        state.run_snapshot.reset();
        ClampSelections(state);
        return;
    }
    try {
        state.run_snapshot = sg_preflight::native_shell::LoadRunSnapshot(state.backend, state.current_result_run_id);
        ClampSelections(state);
        state.last_error.clear();
    } catch (const std::exception& error) {
        state.last_error = error.what();
        PlayCue(UiCue::Error);
    }
}

void RefreshRecentActions(ShellState& state) {
    try {
        const std::string profile_id = CurrentActionId(state) == "daily_live_matrix" ? std::string{} : CurrentProfileId(state);
        state.recent_actions = sg_preflight::native_shell::LoadRecentActions(state.backend, profile_id, 18);
        state.last_error.clear();
    } catch (const std::exception& error) {
        state.last_error = error.what();
        PlayCue(UiCue::Error);
    }
}

void RefreshRecentRuns(ShellState& state) {
    try {
        state.recent_runs = sg_preflight::native_shell::LoadRecentRuns(state.backend, CurrentProfileId(state), 18);
        state.last_error.clear();
    } catch (const std::exception& error) {
        state.last_error = error.what();
        PlayCue(UiCue::Error);
    }
}

void RefreshResultPanels(ShellState& state) {
    RefreshRecentActions(state);
    RefreshRecentRuns(state);

    if (state.snapshot.has_value() && !state.snapshot->linked_run_id.empty()) {
        state.current_result_run_id = state.snapshot->linked_run_id;
        RefreshRunSnapshot(state);
        return;
    }

    if (!state.current_result_run_id.empty()) {
        RefreshRunSnapshot(state);
        if (
            state.run_snapshot.has_value()
            && state.run_snapshot->profile_id == CurrentProfileId(state)
        ) {
            return;
        }
    }

    if (!state.recent_runs.empty()) {
        state.current_result_run_id = state.recent_runs.front().run_id;
        RefreshRunSnapshot(state);
        return;
    }

    state.current_result_run_id.clear();
    state.run_snapshot.reset();
    ClampSelections(state);
}

void RefreshProfilePanels(ShellState& state) {
    const std::string profile_id = CurrentProfileId(state);
    if (profile_id.empty()) {
        state.actions.clear();
        state.blockers.clear();
        state.manual_cards.clear();
        state.recent_actions.clear();
        state.recent_runs.clear();
        state.run_snapshot.reset();
        return;
    }

    try {
        state.actions = sg_preflight::native_shell::LoadActions(state.backend, profile_id);
        state.blockers = sg_preflight::native_shell::LoadBlockers(state.backend, profile_id);
        state.manual_cards = sg_preflight::native_shell::LoadManualCards(state.backend, profile_id);
        if (state.selected_action_id.empty() || (state.selected_action_id != "daily_live_matrix" && FindSelectedAction(state) == nullptr)) {
            state.selected_action_id = state.actions.empty() ? "daily_live_matrix" : state.actions.front().action_id;
        }
        state.last_error.clear();
    } catch (const std::exception& error) {
        state.last_error = error.what();
        PlayCue(UiCue::Error);
    }
    RefreshResultPanels(state);
}

void RefreshProfiles(ShellState& state) {
    try {
        const std::string current_profile = CurrentProfileId(state);
        state.profiles = sg_preflight::native_shell::LoadProfiles(state.backend);
        if (state.profiles.empty()) {
            state.selected_profile_index = 0;
            state.actions.clear();
            state.blockers.clear();
            state.manual_cards.clear();
            state.recent_actions.clear();
            state.recent_runs.clear();
            state.snapshot.reset();
            state.run_snapshot.reset();
            return;
        }
        const auto match = std::find_if(
            state.profiles.begin(),
            state.profiles.end(),
            [&](const ProfileItem& item) { return item.profile_id == current_profile; }
        );
        state.selected_profile_index = match == state.profiles.end()
            ? 0
            : static_cast<int>(std::distance(state.profiles.begin(), match));
        if (state.selected_action_id.empty()) {
            state.selected_action_id = state.profiles[static_cast<size_t>(state.selected_profile_index)].recommended_action_id;
        }
        RefreshProfilePanels(state);
        state.last_error.clear();
    } catch (const std::exception& error) {
        state.last_error = error.what();
        PlayCue(UiCue::Error);
    }
}

void SelectProfileById(ShellState& state, const std::string& profile_id) {
    const auto match = std::find_if(
        state.profiles.begin(),
        state.profiles.end(),
        [&](const ProfileItem& item) { return item.profile_id == profile_id; }
    );
    if (match == state.profiles.end()) {
        return;
    }
    state.selected_profile_index = static_cast<int>(std::distance(state.profiles.begin(), match));
    state.selected_action_id = match->recommended_action_id;
    RefreshProfilePanels(state);
}

void StartAction(ShellState& state, const std::string& action_id) {
    try {
        state.current_run_id = sg_preflight::native_shell::LaunchAction(state.backend, action_id);
        state.status_line = "Queued " + action_id + " locally.";
        state.last_error.clear();
        RefreshResultPanels(state);
        RefreshSnapshot(state);
        RefreshRunSnapshot(state);
        state.next_poll_at = ImGui::GetTime() + 0.25;
    } catch (const std::exception& error) {
        state.last_error = error.what();
        PlayCue(UiCue::Error);
    }
}

bool OpenPath(const std::wstring& path) {
    if (path.empty()) {
        return false;
    }
    const HINSTANCE result = ShellExecuteW(nullptr, L"open", path.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
    return reinterpret_cast<INT_PTR>(result) > 32;
}

bool RevealPath(const std::wstring& path) {
    if (path.empty()) {
        return false;
    }
    const std::wstring arguments = L"/select,\"" + path + L"\"";
    const HINSTANCE result = ShellExecuteW(nullptr, L"open", L"explorer.exe", arguments.c_str(), nullptr, SW_SHOWNORMAL);
    return reinterpret_cast<INT_PTR>(result) > 32;
}

bool CopyText(const std::wstring& text) {
    if (!OpenClipboard(nullptr)) {
        return false;
    }
    EmptyClipboard();
    const SIZE_T bytes = (text.size() + 1) * sizeof(wchar_t);
    HGLOBAL handle = GlobalAlloc(GMEM_MOVEABLE, bytes);
    if (handle == nullptr) {
        CloseClipboard();
        return false;
    }
    void* locked = GlobalLock(handle);
    memcpy(locked, text.c_str(), bytes);
    GlobalUnlock(handle);
    SetClipboardData(CF_UNICODETEXT, handle);
    CloseClipboard();
    return true;
}

std::wstring SelectedEvidencePath(const ShellState& state) {
    if (!state.snapshot.has_value() || state.snapshot->top_paths.empty()) {
        return {};
    }
    const EvidenceItem& item = state.snapshot->top_paths[static_cast<size_t>(state.selected_evidence_index)];
    return sg_preflight::native_shell::ToWide(item.path);
}

std::wstring SelectedArtifactPath(const ShellState& state) {
    const std::vector<ArtifactChoice> artifacts = CombinedArtifacts(state);
    if (artifacts.empty()) {
        return {};
    }
    const int clamped_index = std::clamp(state.selected_artifact_index, 0, static_cast<int>(artifacts.size()) - 1);
    return sg_preflight::native_shell::ToWide(artifacts[static_cast<size_t>(clamped_index)].path);
}

std::string Ellipsize(const std::string& text, size_t limit = 180U) {
    if (text.size() <= limit) {
        return text;
    }
    return text.substr(0, limit > 3U ? limit - 3U : limit) + "...";
}

ImFont* TryLoadFont(ImGuiIO& io, const std::filesystem::path& path, float size) {
    if (!PathExists(path)) {
        return nullptr;
    }
    return io.Fonts->AddFontFromFileTTF(path.string().c_str(), size);
}

void LoadShellFonts(ImGuiIO& io) {
    g_title_font = TryLoadFont(io, R"(C:\Windows\Fonts\bahnschrift.ttf)", 30.0f);
    g_body_font = TryLoadFont(io, R"(C:\Windows\Fonts\consola.ttf)", 18.0f);
    g_small_font = TryLoadFont(io, R"(C:\Windows\Fonts\consola.ttf)", 15.0f);

    if (g_body_font == nullptr) {
        g_body_font = io.Fonts->AddFontDefault();
    }
    if (g_small_font == nullptr) {
        g_small_font = g_body_font;
    }
    if (g_title_font == nullptr) {
        g_title_font = g_body_font;
    }
    io.FontDefault = g_body_font;
}

void ApplyStyle() {
    ImGuiStyle& style = ImGui::GetStyle();
    style.WindowPadding = ImVec2(0.0f, 0.0f);
    style.WindowRounding = 0.0f;
    style.ChildRounding = 0.0f;
    style.FrameRounding = 0.0f;
    style.PopupRounding = 0.0f;
    style.GrabRounding = 0.0f;
    style.ScrollbarRounding = 0.0f;
    style.FramePadding = ImVec2(10.0f, 7.0f);
    style.ItemSpacing = ImVec2(10.0f, 10.0f);
    style.WindowBorderSize = 0.0f;
    style.ChildBorderSize = 0.0f;
    style.TabBorderSize = 0.0f;
    style.ScrollbarSize = 12.0f;

    ImVec4* colors = style.Colors;
    colors[ImGuiCol_WindowBg] = ImVec4(0.04f, 0.06f, 0.07f, 1.00f);
    colors[ImGuiCol_ChildBg] = ImVec4(0.00f, 0.00f, 0.00f, 0.00f);
    colors[ImGuiCol_PopupBg] = ImVec4(0.07f, 0.09f, 0.10f, 1.00f);
    colors[ImGuiCol_Border] = ImVec4(0.10f, 0.35f, 0.30f, 0.00f);
    colors[ImGuiCol_BorderShadow] = ImVec4(0.00f, 0.00f, 0.00f, 0.00f);
    colors[ImGuiCol_FrameBg] = ImVec4(0.08f, 0.12f, 0.13f, 0.90f);
    colors[ImGuiCol_FrameBgHovered] = ImVec4(0.11f, 0.17f, 0.18f, 0.95f);
    colors[ImGuiCol_FrameBgActive] = ImVec4(0.13f, 0.22f, 0.22f, 1.00f);
    colors[ImGuiCol_TitleBg] = ImVec4(0.04f, 0.06f, 0.07f, 1.00f);
    colors[ImGuiCol_TitleBgActive] = ImVec4(0.04f, 0.06f, 0.07f, 1.00f);
    colors[ImGuiCol_Button] = ImVec4(0.09f, 0.22f, 0.17f, 0.00f);
    colors[ImGuiCol_ButtonHovered] = ImVec4(0.11f, 0.29f, 0.21f, 0.00f);
    colors[ImGuiCol_ButtonActive] = ImVec4(0.14f, 0.35f, 0.25f, 0.00f);
    colors[ImGuiCol_Header] = ImVec4(0.08f, 0.16f, 0.16f, 1.00f);
    colors[ImGuiCol_HeaderHovered] = ImVec4(0.12f, 0.23f, 0.22f, 1.00f);
    colors[ImGuiCol_HeaderActive] = ImVec4(0.15f, 0.28f, 0.26f, 1.00f);
    colors[ImGuiCol_Tab] = ImVec4(0.08f, 0.11f, 0.12f, 0.00f);
    colors[ImGuiCol_TabHovered] = ImVec4(0.19f, 0.21f, 0.11f, 1.00f);
    colors[ImGuiCol_TabActive] = ImVec4(0.20f, 0.16f, 0.06f, 1.00f);
    colors[ImGuiCol_Text] = ImVec4(0.86f, 0.92f, 0.88f, 1.00f);
    colors[ImGuiCol_TextDisabled] = ImVec4(0.55f, 0.62f, 0.58f, 1.00f);
    colors[ImGuiCol_PlotHistogram] = ImVec4(0.22f, 0.78f, 0.55f, 1.00f);
    colors[ImGuiCol_ScrollbarBg] = ImVec4(0.04f, 0.06f, 0.07f, 1.00f);
    colors[ImGuiCol_ScrollbarGrab] = ImVec4(0.18f, 0.24f, 0.24f, 1.00f);
    colors[ImGuiCol_ScrollbarGrabHovered] = ImVec4(0.24f, 0.32f, 0.31f, 1.00f);
    colors[ImGuiCol_ScrollbarGrabActive] = ImVec4(0.28f, 0.39f, 0.37f, 1.00f);
    colors[ImGuiCol_CheckMark] = ImVec4(0.25f, 0.83f, 0.58f, 1.00f);
    colors[ImGuiCol_Separator] = ImVec4(0.11f, 0.29f, 0.24f, 0.95f);
}

void DrawBackdropChrome(const ShellState& state) {
    ImDrawList* draw_list = ImGui::GetBackgroundDrawList();
    const ImVec2 display_size = ImGui::GetIO().DisplaySize;
    const float time = static_cast<float>(ImGui::GetTime());
    const float shift = std::fmod(time * 18.0f, 10.0f);

    draw_list->AddRectFilled(
        ImVec2(0.0f, 0.0f),
        display_size,
        IM_COL32(10, 17, 19, 255)
    );

    for (float y = -shift; y < display_size.y; y += 10.0f) {
        draw_list->AddLine(
            ImVec2(0.0f, y),
            ImVec2(display_size.x, y),
            IM_COL32(35, 120, 96, 20),
            1.0f
        );
    }

    const float top_height = 92.0f;
    const float bottom_height = 54.0f;
    draw_list->AddRectFilledMultiColor(
        ImVec2(0.0f, 0.0f),
        ImVec2(display_size.x, top_height),
        IM_COL32(3, 7, 8, 255),
        IM_COL32(3, 7, 8, 255),
        IM_COL32(3, 7, 8, 0),
        IM_COL32(3, 7, 8, 0)
    );
    draw_list->AddRectFilledMultiColor(
        ImVec2(0.0f, display_size.y - bottom_height),
        display_size,
        IM_COL32(3, 7, 8, 0),
        IM_COL32(3, 7, 8, 0),
        IM_COL32(3, 7, 8, 255),
        IM_COL32(3, 7, 8, 255)
    );

    const float bar_motion = ShellMotion(0.0, 16.0);
    draw_list->AddRectFilledMultiColor(
        ImVec2(0.0f, 26.0f),
        ImVec2(display_size.x, 88.0f),
        ApplyAlpha(IM_COL32(14, 35, 28, 255), bar_motion),
        ApplyAlpha(IM_COL32(14, 35, 28, 255), bar_motion),
        ApplyAlpha(IM_COL32(14, 35, 28, 120), bar_motion),
        ApplyAlpha(IM_COL32(14, 35, 28, 120), bar_motion)
    );
    draw_list->AddRectFilledMultiColor(
        ImVec2(0.0f, display_size.y - 52.0f),
        ImVec2(display_size.x, display_size.y - 18.0f),
        ApplyAlpha(IM_COL32(14, 35, 28, 120), bar_motion),
        ApplyAlpha(IM_COL32(14, 35, 28, 120), bar_motion),
        ApplyAlpha(IM_COL32(14, 35, 28, 255), bar_motion),
        ApplyAlpha(IM_COL32(14, 35, 28, 255), bar_motion)
    );
    draw_list->AddLine(
        ImVec2(0.0f, 88.0f),
        ImVec2(display_size.x, 88.0f),
        ApplyAlpha(IM_COL32(115, 178, 104, 255), bar_motion),
        2.0f
    );
    draw_list->AddLine(
        ImVec2(0.0f, display_size.y - 52.0f),
        ImVec2(display_size.x, display_size.y - 52.0f),
        ApplyAlpha(IM_COL32(115, 178, 104, 255), bar_motion),
        2.0f
    );

    const ImVec2 title_pos(26.0f, 30.0f);
    const float title_alpha = ShellMotion(4.0, 28.0);
    const float subtitle_alpha = ShellMotion(10.0, 20.0);
    const float square_motion = ShellMotion(14.0, 30.0);
    const float square_phase = std::fmod(std::max(0.0f, time * 3.0f), 4.0f);
    const float square_x = title_pos.x + 190.0f + (square_phase * 20.0f * square_motion);
    const float square_scale = 1.0f + 0.18f * std::sin(time * 4.0f);
    const ImVec2 square_min(square_x, title_pos.y + 6.0f);
    const ImVec2 square_max(square_x + 18.0f * square_scale, title_pos.y + 24.0f);

    if (g_title_font != nullptr) {
        draw_list->AddText(
            g_title_font,
            g_title_font->LegacySize,
            ImVec2(title_pos.x + 2.0f, title_pos.y + 2.0f),
            ApplyAlpha(IM_COL32(0, 0, 0, 200), title_alpha),
            "SG PREFLIGHT"
        );
        draw_list->AddText(
            g_title_font,
            g_title_font->LegacySize,
            title_pos,
            ApplyAlpha(IM_COL32(255, 188, 0, 255), title_alpha),
            "SG PREFLIGHT"
        );
    }
    if (g_small_font != nullptr) {
        draw_list->AddText(
            g_small_font,
            g_small_font->LegacySize,
            ImVec2(title_pos.x, title_pos.y + 34.0f),
            ApplyAlpha(IM_COL32(112, 239, 175, 255), subtitle_alpha),
            "NATIVE OPERATOR SHELL"
        );
        const std::string workspace = "workspace: " + sg_preflight::native_shell::ToUtf8(state.backend.workspace_root);
        draw_list->AddText(
            g_small_font,
            g_small_font->LegacySize,
            ImVec2(title_pos.x + 270.0f, title_pos.y + 34.0f),
            ApplyAlpha(IM_COL32(183, 205, 189, 210), subtitle_alpha),
            workspace.c_str()
        );
    }

    draw_list->AddRectFilled(square_min, square_max, ApplyAlpha(IM_COL32(201, 167, 82, 215), square_motion), 3.0f);
    draw_list->AddRect(square_min, square_max, ApplyAlpha(IM_COL32(255, 196, 104, 255), square_motion), 3.0f, 0, 1.5f);
}

bool BeginDecoratedPanel(const char* id, const char* title, ImVec2 size, bool static_overlay = false) {
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(14.0f, 14.0f));
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImVec4(0.0f, 0.0f, 0.0f, 0.0f));
    const bool open = ImGui::BeginChild(id, size, false, ImGuiWindowFlags_NoScrollWithMouse);

    ImDrawList* draw_list = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetWindowPos();
    const ImVec2 max = ImVec2(min.x + ImGui::GetWindowSize().x, min.y + ImGui::GetWindowSize().y);
    const float alpha = ShellMotion(0.0, 22.0);
    const float grid = kPanelGrid;

    draw_list->AddRectFilled(min, max, ApplyAlpha(IM_COL32(7, 13, 15, 238), alpha));
    if (static_overlay) {
        const float noise = std::fmod(static_cast<float>(ImGui::GetTime()) * 52.0f, 28.0f);
        for (float x = min.x - noise; x < max.x; x += 46.0f) {
            draw_list->AddLine(
                ImVec2(x, min.y + kPanelHeaderHeight + 20.0f),
                ImVec2(x + 24.0f, max.y - 16.0f),
                ApplyAlpha(IM_COL32(22, 58, 48, 36), alpha),
                1.0f
            );
        }
    }

    draw_list->AddRect(min, max, ApplyAlpha(IM_COL32(16, 70, 60, 255), alpha));
    draw_list->AddRect(
        ImVec2(min.x + grid, min.y + grid),
        ImVec2(max.x - grid, max.y - grid),
        ApplyAlpha(IM_COL32(9, 42, 36, 255), alpha)
    );
    draw_list->AddLine(
        ImVec2(min.x + grid, min.y + kPanelHeaderHeight),
        ImVec2(max.x - grid, min.y + kPanelHeaderHeight),
        ApplyAlpha(IM_COL32(99, 162, 113, 255), alpha),
        1.0f
    );
    draw_list->AddRectFilled(
        ImVec2(min.x + grid, min.y + grid),
        ImVec2(min.x + 134.0f, min.y + kPanelHeaderHeight - 2.0f),
        ApplyAlpha(IM_COL32(20, 26, 18, 255), alpha)
    );

    if (g_small_font != nullptr) {
        draw_list->AddText(
            g_small_font,
            g_small_font->LegacySize,
            ImVec2(min.x + 12.0f, min.y + 8.0f),
            ApplyAlpha(IM_COL32(255, 188, 0, 255), alpha),
            title
        );
    }

    const float line_y = min.y + kPanelHeaderHeight + 6.0f;
    draw_list->AddLine(
        ImVec2(min.x + 12.0f, line_y),
        ImVec2(max.x - 14.0f, line_y),
        ApplyAlpha(IM_COL32(18, 72, 62, 120), alpha),
        1.0f
    );

    ImGui::SetCursorPos(ImVec2(16.0f, kPanelHeaderHeight + 12.0f));
    return open;
}

void EndDecoratedPanel() {
    ImGui::EndChild();
    ImGui::PopStyleColor();
    ImGui::PopStyleVar();
}

bool DrawPanelButton(const char* id, const std::string& label, ImVec2 size, bool accent = false, bool enabled = true) {
    if (!enabled) {
        ImGui::BeginDisabled();
    }
    const bool pressed = ImGui::InvisibleButton(id, size);
    const bool hovered = ImGui::IsItemHovered();
    if (!enabled) {
        ImGui::EndDisabled();
    }

    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();
    const ImU32 bg = accent
        ? (hovered ? IM_COL32(34, 112, 76, 230) : IM_COL32(22, 79, 56, 230))
        : (hovered ? IM_COL32(18, 42, 44, 230) : IM_COL32(12, 26, 29, 230));
    const ImU32 border = accent ? IM_COL32(122, 255, 168, 210) : IM_COL32(67, 128, 113, 190);
    const ImU32 text = enabled ? IM_COL32(236, 246, 239, 255) : IM_COL32(114, 134, 127, 255);

    draw->AddRectFilled(min, max, bg, 4.0f);
    draw->AddRect(min, max, border, 4.0f, 0, 1.2f);
    draw->AddLine(ImVec2(min.x + 8.0f, max.y - 5.0f), ImVec2(max.x - 8.0f, max.y - 5.0f), border, 2.0f);

    if (g_small_font != nullptr) {
        const ImVec2 text_size = g_small_font->CalcTextSizeA(g_small_font->LegacySize, FLT_MAX, 0.0f, label.c_str());
        const ImVec2 text_pos(
            min.x + ((max.x - min.x) - text_size.x) * 0.5f,
            min.y + ((max.y - min.y) - text_size.y) * 0.5f
        );
        draw->AddText(g_small_font, g_small_font->LegacySize, text_pos, text, label.c_str());
    }

    if (pressed && enabled) {
        PlayCue(accent ? UiCue::Confirm : UiCue::Cursor);
    }
    return pressed && enabled;
}

bool DrawGuideButton(const char* id, const char* key, const char* label, bool enabled) {
    const ImVec2 start = ImGui::GetCursorScreenPos();
    const ImVec2 size(165.0f, 30.0f);
    if (!enabled) {
        ImGui::BeginDisabled();
    }
    const bool pressed = ImGui::InvisibleButton(id, size);
    const bool hovered = ImGui::IsItemHovered();
    if (!enabled) {
        ImGui::EndDisabled();
    }
    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();
    draw->AddRectFilled(min, max, hovered ? IM_COL32(24, 75, 55, 235) : IM_COL32(17, 50, 38, 235), 4.0f);
    draw->AddRect(min, max, IM_COL32(89, 175, 123, 180), 4.0f);
    draw->AddRectFilled(ImVec2(min.x + 6.0f, min.y + 5.0f), ImVec2(min.x + 30.0f, max.y - 5.0f), IM_COL32(21, 20, 18, 255), 3.0f);
    draw->AddRect(ImVec2(min.x + 6.0f, min.y + 5.0f), ImVec2(min.x + 30.0f, max.y - 5.0f), IM_COL32(255, 188, 0, 210), 3.0f);
    if (g_small_font != nullptr) {
        draw->AddText(g_small_font, g_small_font->LegacySize, ImVec2(min.x + 13.0f, min.y + 7.0f), IM_COL32(255, 188, 0, 255), key);
        draw->AddText(g_small_font, g_small_font->LegacySize, ImVec2(min.x + 40.0f, min.y + 7.0f), enabled ? IM_COL32(235, 244, 239, 255) : IM_COL32(122, 134, 127, 255), label);
    }
    ImGui::SetCursorScreenPos(ImVec2(start.x + size.x + 8.0f, start.y));
    if (pressed && enabled) {
        PlayCue(UiCue::Cursor);
    }
    return pressed && enabled;
}

bool DrawSelectableCard(
    const char* id,
    const std::string& title,
    const std::string& subtitle,
    const std::string& detail,
    bool selected,
    float height = 74.0f
) {
    const ImVec2 size(ImGui::GetContentRegionAvail().x, height);
    const bool pressed = ImGui::InvisibleButton(id, size);
    const bool hovered = ImGui::IsItemHovered();
    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();

    const float pulse = 0.5f + 0.5f * std::sin(static_cast<float>(ImGui::GetTime()) * 5.0f);
    const ImU32 bg = selected
        ? ApplyAlpha(IM_COL32(19, 84, 60, 255), 0.88f)
        : hovered
            ? ApplyAlpha(IM_COL32(13, 32, 36, 255), 0.92f)
            : ApplyAlpha(IM_COL32(9, 18, 22, 255), 0.92f);
    const ImU32 border = selected
        ? ApplyAlpha(IM_COL32(118, 255, 165, 230), 0.85f + 0.15f * pulse)
        : hovered
            ? IM_COL32(73, 143, 124, 205)
            : IM_COL32(33, 84, 74, 180);

    draw->AddRectFilled(min, max, bg, 4.0f);
    draw->AddRect(min, max, border, 4.0f, 0, selected ? 1.8f : 1.1f);
    draw->AddRectFilled(ImVec2(min.x + 7.0f, min.y + 9.0f), ImVec2(min.x + 13.0f, max.y - 9.0f), selected ? IM_COL32(255, 188, 0, 255) : IM_COL32(45, 92, 80, 160), 3.0f);
    for (float y = min.y + 2.0f; y < max.y; y += 8.0f) {
        draw->AddLine(ImVec2(min.x + 16.0f, y), ImVec2(max.x - 8.0f, y), IM_COL32(36, 88, 72, selected ? 28 : 12), 1.0f);
    }

    const float text_x = min.x + 24.0f;
    if (g_body_font != nullptr) {
        draw->AddText(g_body_font, g_body_font->LegacySize, ImVec2(text_x, min.y + 8.0f), IM_COL32(240, 247, 243, 255), title.c_str());
    }
    if (!subtitle.empty() && g_small_font != nullptr) {
        draw->AddText(g_small_font, g_small_font->LegacySize, ImVec2(text_x, min.y + 31.0f), IM_COL32(255, 188, 0, 220), subtitle.c_str());
    }
    if (!detail.empty() && g_small_font != nullptr) {
        draw->AddText(g_small_font, g_small_font->LegacySize, ImVec2(text_x, min.y + 49.0f), IM_COL32(169, 190, 180, 220), Ellipsize(detail, 120U).c_str());
    }

    if (pressed) {
        PlayCue(UiCue::Cursor);
    }
    return pressed;
}

void DrawProgressMeter(float progress, const std::string& label) {
    const ImVec2 size(ImGui::GetContentRegionAvail().x, 22.0f);
    const ImVec2 start = ImGui::GetCursorScreenPos();
    ImGui::InvisibleButton("##progress-meter", size);
    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();
    const float width = (max.x - min.x) * Saturate(progress);
    draw->AddRectFilled(min, max, IM_COL32(8, 18, 20, 255), 3.0f);
    draw->AddRect(min, max, IM_COL32(52, 113, 97, 210), 3.0f);
    draw->AddRectFilledMultiColor(
        min,
        ImVec2(min.x + width, max.y),
        IM_COL32(45, 193, 128, 255),
        IM_COL32(157, 255, 93, 255),
        IM_COL32(45, 193, 128, 235),
        IM_COL32(157, 255, 93, 235)
    );
    for (float x = min.x; x < min.x + width; x += 12.0f) {
        draw->AddLine(ImVec2(x, min.y + 1.0f), ImVec2(x + 8.0f, max.y - 1.0f), IM_COL32(255, 255, 255, 25), 1.0f);
    }
    if (g_small_font != nullptr) {
        draw->AddText(g_small_font, g_small_font->LegacySize, ImVec2(min.x + 10.0f, min.y + 3.0f), IM_COL32(8, 13, 11, 240), label.c_str());
    }
    ImGui::SetCursorScreenPos(ImVec2(start.x, start.y + size.y + 6.0f));
}

void InlineSectionLabel(const char* text) {
    if (g_small_font != nullptr) {
        ImGui::PushFont(g_small_font);
    }
    ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", text);
    if (g_small_font != nullptr) {
        ImGui::PopFont();
    }
    ImGui::Separator();
}

void RenderProfilesPanel(ShellState& state) {
    if (state.profiles.empty()) {
        ImGui::TextDisabled("No ready live profiles were discovered.");
        return;
    }
    for (size_t index = 0; index < state.profiles.size(); ++index) {
        const ProfileItem& profile = state.profiles[index];
        const bool selected = static_cast<int>(index) == state.selected_profile_index;
        const std::string row_id = "profile-" + profile.profile_id;
        const std::string title = profile.profile_id + "  " + profile.label;
        const std::string subtitle = "Recommended action: " + ShortActionLabel(profile.recommended_action_id);
        if (DrawSelectableCard(row_id.c_str(), title, subtitle, profile.summary, selected, 82.0f)) {
            state.selected_profile_index = static_cast<int>(index);
            state.selected_action_id = profile.recommended_action_id;
            RefreshProfilePanels(state);
        }
    }
}

void RenderRecentActionsPanel(ShellState& state) {
    if (state.recent_actions.empty()) {
        ImGui::TextDisabled("No recent actions yet for this selection.");
        return;
    }
    for (const RecentActionItem& item : state.recent_actions) {
        const bool selected = state.current_run_id == item.run_id;
        const std::string row_id = "recent-" + item.run_id;
        const std::string subtitle = item.status + " | " + item.created_at_utc;
        if (DrawSelectableCard(row_id.c_str(), item.title, subtitle, item.summary, selected, 76.0f)) {
            state.current_run_id = item.run_id;
            if (!item.profile_id.empty()) {
                SelectProfileById(state, item.profile_id);
            }
            RefreshSnapshot(state);
            RefreshRunSnapshot(state);
        }
    }
}

void RenderRecentResultsPanel(ShellState& state) {
    if (state.recent_runs.empty()) {
        ImGui::TextDisabled("No recent run records yet for this profile.");
        return;
    }
    for (const RecentRunItem& item : state.recent_runs) {
        const bool selected = state.current_result_run_id == item.run_id;
        const std::string row_id = "recent-run-" + item.run_id;
        const std::string title = item.profile_id + "  " + item.title;
        const std::string subtitle = item.status + " | " + item.created_at_utc;
        if (DrawSelectableCard(row_id.c_str(), title, subtitle, item.summary, selected, 76.0f)) {
            state.current_result_run_id = item.run_id;
            RefreshRunSnapshot(state);
        }
    }
}

void RenderActionTabs(ShellState& state) {
    struct TabItem {
        std::string action_id;
        std::string label;
        std::string description;
        std::string command_preview;
        std::string blocker_message;
        bool ready = true;
    };

    std::vector<TabItem> tabs;
    tabs.push_back(
        {
            "daily_live_matrix",
            "DAILY",
            "Run the recommended SG QA stack across all ready live profiles and aggregate one shared 'Open first' surface.",
            "python -m sg_preflight run-action daily_live_matrix",
            {},
            true,
        }
    );
    for (const ActionItem& action : state.actions) {
        tabs.push_back(
            {
                action.action_id,
                ShortActionLabel(action.action_id),
                action.description,
                action.command_preview,
                action.blocker_message,
                action.ready,
            }
        );
    }

    const float available_width = ImGui::GetContentRegionAvail().x;
    const float tab_width = std::max(92.0f, std::min(120.0f, (available_width - 8.0f * (static_cast<float>(tabs.size()) - 1.0f)) / std::max(1.0f, static_cast<float>(tabs.size()))));
    const float tab_height = 34.0f;
    struct TabRect {
        std::string action_id;
        ImVec2 min;
        ImVec2 max;
        bool selected = false;
        bool ready = false;
        std::string label;
    };
    std::vector<TabRect> rectangles;
    rectangles.reserve(tabs.size());

    const ImVec2 strip_origin = ImGui::GetCursorScreenPos();
    for (const TabItem& tab : tabs) {
        const bool selected = state.selected_action_id == tab.action_id;
        const std::string item_id = "tab-" + tab.action_id;
        ImGui::InvisibleButton(item_id.c_str(), ImVec2(tab_width, tab_height));
        const bool pressed = ImGui::IsItemClicked();
        rectangles.push_back({tab.action_id, ImGui::GetItemRectMin(), ImGui::GetItemRectMax(), selected, tab.ready, tab.label});
        if (pressed && state.selected_action_id != tab.action_id) {
            state.selected_action_id = tab.action_id;
            RefreshResultPanels(state);
            PlayCue(UiCue::Cursor);
        }
        if (&tab != &tabs.back()) {
            ImGui::SameLine(0.0f, 8.0f);
        }
    }

    ImDrawList* draw = ImGui::GetWindowDrawList();
    ImVec2 highlight_min{};
    ImVec2 highlight_max{};
    bool highlight_found = false;
    for (const TabRect& rectangle : rectangles) {
        if (rectangle.selected) {
            highlight_min = rectangle.min;
            highlight_max = rectangle.max;
            highlight_found = true;
            break;
        }
    }
    if (highlight_found) {
        if (!g_tab_highlight_ready) {
            g_tab_highlight_min = highlight_min;
            g_tab_highlight_max = highlight_max;
            g_tab_highlight_ready = true;
        } else {
            g_tab_highlight_min = ExpApproach(g_tab_highlight_min, highlight_min, 18.0f);
            g_tab_highlight_max = ExpApproach(g_tab_highlight_max, highlight_max, 18.0f);
        }
        draw->AddRectFilled(g_tab_highlight_min, g_tab_highlight_max, IM_COL32(22, 83, 56, 238), 5.0f);
        draw->AddRect(g_tab_highlight_min, g_tab_highlight_max, IM_COL32(140, 255, 168, 220), 5.0f, 0, 1.3f);
        draw->AddLine(
            ImVec2(g_tab_highlight_min.x + 8.0f, g_tab_highlight_max.y - 5.0f),
            ImVec2(g_tab_highlight_max.x - 8.0f, g_tab_highlight_max.y - 5.0f),
            IM_COL32(255, 188, 0, 255),
            2.0f
        );
    }

    for (const TabRect& rectangle : rectangles) {
        const bool hovered = ImGui::IsMouseHoveringRect(rectangle.min, rectangle.max);
        const ImU32 fill = rectangle.selected
            ? IM_COL32(0, 0, 0, 0)
            : hovered
                ? IM_COL32(18, 31, 34, 228)
                : IM_COL32(11, 21, 24, 228);
        draw->AddRectFilled(rectangle.min, rectangle.max, fill, 5.0f);
        draw->AddRect(rectangle.min, rectangle.max, rectangle.ready ? IM_COL32(47, 97, 86, 210) : IM_COL32(95, 73, 54, 210), 5.0f);
        draw->AddCircleFilled(ImVec2(rectangle.min.x + 13.0f, rectangle.min.y + 17.0f), 4.0f, rectangle.ready ? IM_COL32(128, 255, 0, 220) : IM_COL32(255, 188, 0, 220));
        if (g_small_font != nullptr) {
            draw->AddText(
                g_small_font,
                g_small_font->LegacySize,
                ImVec2(rectangle.min.x + 24.0f, rectangle.min.y + 9.0f),
                rectangle.selected ? IM_COL32(243, 247, 245, 255) : IM_COL32(188, 204, 198, 235),
                rectangle.label.c_str()
            );
        }
    }

    ImGui::SetCursorScreenPos(ImVec2(strip_origin.x, strip_origin.y + tab_height + 12.0f));

    const TabItem* selected_tab = nullptr;
    for (const TabItem& tab : tabs) {
        if (tab.action_id == state.selected_action_id) {
            selected_tab = &tab;
            break;
        }
    }
    if (selected_tab == nullptr && !tabs.empty()) {
        selected_tab = &tabs.front();
    }
    if (selected_tab == nullptr) {
        return;
    }

    InlineSectionLabel("Selected Mode");
    ImGui::TextWrapped("%s", selected_tab->description.c_str());
    if (!selected_tab->command_preview.empty()) {
        ImGui::Spacing();
        ImGui::TextDisabled("%s", selected_tab->command_preview.c_str());
    }
    if (!selected_tab->ready && !selected_tab->blocker_message.empty()) {
        ImGui::Spacing();
        ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", selected_tab->blocker_message.c_str());
    }
}

void RenderSummaryPanel(ShellState& state) {
    const std::string selected_action = CurrentActionId(state);
    const ActionItem* action = FindSelectedAction(state);
    const bool action_ready = selected_action == "daily_live_matrix" || (action != nullptr && action->ready);

    if (DrawPanelButton("run-selected-action", "RUN SELECTED ACTION", ImVec2(248.0f, 34.0f), true, action_ready)) {
        if (action_ready) {
            StartAction(state, selected_action);
            PlayCue(UiCue::Confirm);
        }
    }
    ImGui::SameLine();
    ImGui::TextDisabled("%s", state.status_line.c_str());

    if (!state.last_error.empty()) {
        ImGui::Spacing();
        ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", state.last_error.c_str());
    }

    ImGui::Spacing();
    InlineSectionLabel("Active Run / Result");
    if (!state.snapshot.has_value() && !state.run_snapshot.has_value()) {
        ImGui::TextDisabled("Select a recent action or run a new one to populate the active result panel.");
        return;
    }

    if (state.snapshot.has_value()) {
        const ActionSnapshot& snapshot = *state.snapshot;
        InlineSectionLabel("Current Action");
        ImGui::Text("Action: %s", snapshot.title.c_str());
        ImGui::SameLine();
        ImGui::TextColored(
            snapshot.status == "completed" ? ImVec4(0.40f, 0.88f, 0.64f, 1.0f) : ImVec4(0.95f, 0.68f, 0.19f, 1.0f),
            "[%s]",
            snapshot.status.c_str()
        );
        DrawProgressMeter(static_cast<float>(snapshot.progress_percent) / 100.0f, std::to_string(snapshot.progress_percent) + "%");
        if (!snapshot.progress_label.empty()) {
            ImGui::TextWrapped("%s", snapshot.progress_label.c_str());
        }
        if (!snapshot.progress_detail.empty()) {
            ImGui::TextDisabled("%s", snapshot.progress_detail.c_str());
        }
        if (!snapshot.current_command.empty()) {
            ImGui::Spacing();
            ImGui::TextDisabled("Command: %s", snapshot.current_command.c_str());
        }

        ImGui::Spacing();
        InlineSectionLabel("Action Summary");
        if (snapshot.summary_lines.empty()) {
            ImGui::TextDisabled("No summary lines yet.");
        } else {
            for (const std::string& line : snapshot.summary_lines) {
                ImGui::BulletText("%s", line.c_str());
            }
        }

        ImGui::Spacing();
        InlineSectionLabel("Signal Log");
        ImGui::BeginChild("log-tail", ImVec2(0.0f, 170.0f), true);
        if (snapshot.log_tail.empty()) {
            ImGui::TextDisabled("No action-log lines captured yet.");
        } else {
            ImGui::TextWrapped("%s", snapshot.log_tail.c_str());
        }
        ImGui::EndChild();
    }

    if (state.run_snapshot.has_value()) {
        const RunSnapshot& run_snapshot = *state.run_snapshot;
        ImGui::Spacing();
        InlineSectionLabel("Result Drilldown");
        ImGui::Text("Run: %s", run_snapshot.profile_label.c_str());
        ImGui::SameLine();
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "[%s]", run_snapshot.status.c_str());
        ImGui::TextDisabled("%s", run_snapshot.created_at_utc.c_str());
        for (const std::string& line : run_snapshot.summary_lines) {
            ImGui::BulletText("%s", line.c_str());
        }
        if (!run_snapshot.grouped_lines.empty()) {
            ImGui::Spacing();
            ImGui::TextColored(ImVec4(0.40f, 0.88f, 0.64f, 1.0f), "Grouped Findings");
            ImGui::BeginChild("grouped-findings", ImVec2(0.0f, 160.0f), true);
            for (const std::string& line : run_snapshot.grouped_lines) {
                ImGui::TextWrapped("%s", line.c_str());
            }
            ImGui::EndChild();
        }
        if (!run_snapshot.notes.empty()) {
            ImGui::Spacing();
            ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "Run Notes");
            for (const std::string& note : run_snapshot.notes) {
                ImGui::BulletText("%s", note.c_str());
            }
        }
    }
}

void RenderEvidencePanel(ShellState& state) {
    if (!state.snapshot.has_value() || state.snapshot->top_paths.empty()) {
        ImGui::TextDisabled("No file-backed checker evidence is available for the current action.");
        return;
    }

    for (size_t index = 0; index < state.snapshot->top_paths.size(); ++index) {
        const EvidenceItem& item = state.snapshot->top_paths[index];
        const bool selected = static_cast<int>(index) == state.selected_evidence_index;
        std::string subtitle = item.checker.empty() ? item.source_kind : item.checker;
        if (item.line >= 0) {
            subtitle += subtitle.empty() ? "" : " | ";
            subtitle += "line " + std::to_string(item.line);
        }
        const std::string row_id = "evidence-" + std::to_string(index);
        if (DrawSelectableCard(row_id.c_str(), item.path, subtitle, item.message, selected, 88.0f)) {
            state.selected_evidence_index = static_cast<int>(index);
        }
    }
}

void RenderArtifactsPanel(ShellState& state) {
    const std::vector<ArtifactChoice> artifacts = CombinedArtifacts(state);
    const std::vector<CopyItem> copy_items = CombinedCopyItems(state);
    if (!state.snapshot.has_value() && !state.run_snapshot.has_value()) {
        ImGui::TextDisabled("No action or run snapshot loaded.");
        return;
    }

    if (!artifacts.empty()) {
        InlineSectionLabel("Artifacts / Reports");
        std::string current_section;
        for (size_t index = 0; index < artifacts.size(); ++index) {
            const auto& artifact = artifacts[index];
            if (artifact.section != current_section) {
                current_section = artifact.section;
                if (index > 0) {
                    ImGui::Spacing();
                }
                ImGui::TextColored(ImVec4(0.40f, 0.88f, 0.64f, 1.0f), "%s", current_section.c_str());
            }
            const bool selected = static_cast<int>(index) == state.selected_artifact_index;
            const std::string row_id = "artifact-" + std::to_string(index);
            if (DrawSelectableCard(row_id.c_str(), artifact.label, artifact.section, artifact.path, selected, 68.0f)) {
                state.selected_artifact_index = static_cast<int>(index);
            }
        }
    } else {
        ImGui::TextDisabled("No generated artifacts were attached to this selection.");
    }

    ImGui::Spacing();
    const std::wstring selected_artifact_path = SelectedArtifactPath(state);
    if (!selected_artifact_path.empty()) {
        ImGui::TextWrapped("%s", sg_preflight::native_shell::ToUtf8(selected_artifact_path).c_str());
        ImGui::Spacing();
    }
    if (DrawPanelButton("open-selected-artifact", "OPEN SELECTED", ImVec2(180.0f, 30.0f), false, !selected_artifact_path.empty())) {
        OpenPath(selected_artifact_path);
    }
    ImGui::SameLine();
    if (DrawPanelButton("reveal-selected-artifact", "REVEAL SELECTED", ImVec2(180.0f, 30.0f), false, !selected_artifact_path.empty())) {
        RevealPath(selected_artifact_path);
    }
    if (DrawPanelButton("open-html-report", "OPEN HTML REPORT", ImVec2(180.0f, 30.0f), false, state.run_snapshot.has_value())) {
        for (const auto& artifact : state.run_snapshot->artifacts) {
            if (artifact.label == "HTML report") {
                OpenPath(sg_preflight::native_shell::ToWide(artifact.path));
                break;
            }
        }
    }
    ImGui::Spacing();
    InlineSectionLabel("Copy / Export");
    const float copy_button_width = std::max(180.0f, (ImGui::GetContentRegionAvail().x - 10.0f) * 0.5f);
    for (size_t index = 0; index < copy_items.size(); ++index) {
        const CopyItem& item = copy_items[index];
        const std::string button_id = "copy-item-" + item.key;
        if (DrawPanelButton(button_id.c_str(), item.label, ImVec2(copy_button_width, 30.0f), false, !item.text.empty())) {
            if (CopyText(sg_preflight::native_shell::ToWide(item.text))) {
                state.status_line = "Copied " + item.label + ".";
            }
        }
        if ((index % 2U) == 0U && index + 1U < copy_items.size()) {
            ImGui::SameLine();
        }
    }
}

void RenderBlockersPanel(ShellState& state) {
    InlineSectionLabel("Blocked / Manual Stages");
    for (const BlockerItem& item : state.blockers) {
        ImGui::Text("%s [%s]", item.label.c_str(), item.state.c_str());
        ImGui::Indent(12.0f);
        ImGui::TextWrapped("%s", item.summary.c_str());
        for (const std::string& blocker : item.blockers) {
            ImGui::BulletText("%s", blocker.c_str());
        }
        ImGui::Unindent(12.0f);
        ImGui::Spacing();
    }

    InlineSectionLabel("Manual Review Companion");
    for (const ManualCard& card : state.manual_cards) {
        ImGui::Text("%s [%s]", card.label.c_str(), card.state.c_str());
        ImGui::Indent(12.0f);
        ImGui::TextWrapped("%s", card.summary.c_str());
        ImGui::TextDisabled("%s", card.note.c_str());
        ImGui::Unindent(12.0f);
        ImGui::Spacing();
    }
}

void RenderButtonGuide(ShellState& state) {
    const std::vector<CopyItem> copy_items = CombinedCopyItems(state);
    const auto copy_by_key = [&](const std::string& key, const std::string& status) {
        for (const CopyItem& item : copy_items) {
            if (item.key == key && !item.text.empty()) {
                if (CopyText(sg_preflight::native_shell::ToWide(item.text))) {
                    state.status_line = status;
                }
                return true;
            }
        }
        return false;
    };

    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(12.0f, 10.0f));
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImVec4(0.0f, 0.0f, 0.0f, 0.0f));
    if (ImGui::BeginChild("button-guide", ImVec2(0.0f, 52.0f), false)) {
        ImDrawList* draw = ImGui::GetWindowDrawList();
        const ImVec2 min = ImGui::GetWindowPos();
        const ImVec2 max = ImVec2(min.x + ImGui::GetWindowSize().x, min.y + ImGui::GetWindowSize().y);
        draw->AddRectFilled(min, max, IM_COL32(8, 18, 20, 240), 4.0f);
        draw->AddRect(min, max, IM_COL32(18, 92, 74, 220), 4.0f);
        if (g_small_font != nullptr) {
            draw->AddText(g_small_font, g_small_font->LegacySize, ImVec2(min.x + 10.0f, min.y + 9.0f), IM_COL32(255, 188, 0, 255), "BUTTON GUIDE");
        }

        ImGui::SetCursorPos(ImVec2(118.0f, 10.0f));
        if (DrawGuideButton("guide-run", "A", "RUN", !CurrentActionId(state).empty())) {
            StartAction(state, CurrentActionId(state));
        }
        const std::wstring evidence_path = SelectedEvidencePath(state);
        const std::wstring artifact_path = SelectedArtifactPath(state);
        if (DrawGuideButton("guide-open", "X", "OPEN FILE", !evidence_path.empty() || !artifact_path.empty())) {
            if (!evidence_path.empty()) {
                OpenPath(evidence_path);
            } else {
                OpenPath(artifact_path);
            }
        }
        if (DrawGuideButton("guide-reveal", "Y", "REVEAL", !evidence_path.empty() || !artifact_path.empty())) {
            if (!evidence_path.empty()) {
                RevealPath(evidence_path);
            } else {
                RevealPath(artifact_path);
            }
        }
        if (DrawGuideButton("guide-log", "LB", "RAW LOG", state.snapshot.has_value())) {
            OpenPath(sg_preflight::native_shell::ToWide(state.snapshot->log_path));
        }
        const bool has_report = state.run_snapshot.has_value() || (state.snapshot.has_value() && !state.snapshot->latest_run_links.html_report.empty());
        if (DrawGuideButton("guide-report", "RB", "REPORT", has_report)) {
            if (state.run_snapshot.has_value()) {
                for (const auto& artifact : state.run_snapshot->artifacts) {
                    if (artifact.label == "HTML report") {
                        OpenPath(sg_preflight::native_shell::ToWide(artifact.path));
                        break;
                    }
                }
            } else if (state.snapshot.has_value()) {
                OpenPath(sg_preflight::native_shell::ToWide(state.snapshot->latest_run_links.html_report));
            }
        }
        if (DrawGuideButton("guide-jira", "J", "COPY JIRA", true)) {
            copy_by_key("jira", "Copied Jira note.");
        }
        if (DrawGuideButton("guide-hero", "Q", "COPY QA HERO", true)) {
            copy_by_key("qa_hero", "Copied QA Hero note.");
        }
        if (DrawGuideButton("guide-handoff", "H", "COPY HANDOFF", true)) {
            copy_by_key("handoff", "Copied handoff note.");
        }
    }
    ImGui::EndChild();
    ImGui::PopStyleColor();
    ImGui::PopStyleVar();
}

void RenderShell(ShellState& state) {
    DrawBackdropChrome(state);

    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(viewport->WorkPos);
    ImGui::SetNextWindowSize(viewport->WorkSize);
    ImGui::SetNextWindowViewport(viewport->ID);

    constexpr ImGuiWindowFlags flags =
        ImGuiWindowFlags_NoDecoration |
        ImGuiWindowFlags_NoMove |
        ImGuiWindowFlags_NoResize |
        ImGuiWindowFlags_NoSavedSettings;

    if (!ImGui::Begin("sg-preflight-native-shell", nullptr, flags)) {
        ImGui::End();
        return;
    }

    ImGui::SetCursorPos(ImVec2(14.0f, 102.0f));
    if (BeginDecoratedPanel("mode-select-panel", "MODE SELECT", ImVec2(0.0f, 132.0f))) {
        ImGui::TextDisabled("Recommended SG action tabs for the selected live slice.");
        RenderActionTabs(state);
    }
    EndDecoratedPanel();

    ImGui::SetCursorPosX(14.0f);
    const float rails_height = std::max(240.0f, ImGui::GetContentRegionAvail().y - kRailFooterReserve - 10.0f);
    if (ImGui::BeginTable("shell-layout", 3, ImGuiTableFlags_SizingStretchSame, ImVec2(0.0f, rails_height))) {
        ImGui::TableSetupColumn("left", ImGuiTableColumnFlags_WidthStretch, 0.25f);
        ImGui::TableSetupColumn("center", ImGuiTableColumnFlags_WidthStretch, 0.45f);
        ImGui::TableSetupColumn("right", ImGuiTableColumnFlags_WidthStretch, 0.30f);

        ImGui::TableNextColumn();
        if (BeginDecoratedPanel("profiles-panel", "PROFILES", ImVec2(0.0f, rails_height * 0.60f))) {
            RenderProfilesPanel(state);
        }
        EndDecoratedPanel();
        if (BeginDecoratedPanel("recent-actions-panel", "RECENT ACTIONS", ImVec2(0.0f, rails_height * 0.19f))) {
            RenderRecentActionsPanel(state);
        }
        EndDecoratedPanel();
        if (BeginDecoratedPanel("recent-runs-panel", "RECENT RESULTS", ImVec2(0.0f, 0.0f))) {
            RenderRecentResultsPanel(state);
        }
        EndDecoratedPanel();

        ImGui::TableNextColumn();
        if (BeginDecoratedPanel("active-result-panel", "ACTIVE RUN / RESULT", ImVec2(0.0f, 0.0f))) {
            RenderSummaryPanel(state);
        }
        EndDecoratedPanel();

        ImGui::TableNextColumn();
        if (BeginDecoratedPanel("evidence-panel", "OPEN FIRST", ImVec2(0.0f, rails_height * 0.43f), true)) {
            ImGui::TextDisabled("TV-static-framed evidence panel for the first files to inspect.");
            RenderEvidencePanel(state);
        }
        EndDecoratedPanel();
        if (BeginDecoratedPanel("artifacts-panel", "ARTIFACTS / REPORTS", ImVec2(0.0f, rails_height * 0.25f))) {
            RenderArtifactsPanel(state);
        }
        EndDecoratedPanel();
        if (BeginDecoratedPanel("blockers-panel", "BLOCKED / MANUAL STAGES", ImVec2(0.0f, 0.0f))) {
            RenderBlockersPanel(state);
        }
        EndDecoratedPanel();

        ImGui::EndTable();
    }

    ImGui::SetCursorPosX(14.0f);
    RenderButtonGuide(state);
    ImGui::End();
}

}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    BackendConfig backend = ParseArguments();

    WNDCLASSEXW window_class{};
    window_class.cbSize = sizeof(window_class);
    window_class.style = CS_CLASSDC;
    window_class.lpfnWndProc = WndProc;
    window_class.hInstance = instance;
    window_class.lpszClassName = L"SGPreflightNativeShell";
    RegisterClassExW(&window_class);

    HWND window_handle = CreateWindowW(
        window_class.lpszClassName,
        L"SG Preflight - Native Operator Shell",
        WS_OVERLAPPEDWINDOW,
        100,
        100,
        1660,
        960,
        nullptr,
        nullptr,
        instance,
        nullptr
    );

    if (window_handle == nullptr || !CreateDeviceD3D(window_handle)) {
        CleanupDeviceD3D();
        UnregisterClassW(window_class.lpszClassName, window_class.hInstance);
        return 1;
    }

    ShowWindow(window_handle, SW_SHOWDEFAULT);
    UpdateWindow(window_handle);

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    io.ConfigWindowsMoveFromTitleBarOnly = true;
    LoadShellFonts(io);
    ImGui::StyleColorsDark();
    ApplyStyle();
    g_shell_appear_time = ImGui::GetTime();
    PlayCue(UiCue::Window);

    ImGui_ImplWin32_Init(window_handle);
    ImGui_ImplDX11_Init(g_device, g_device_context);

    ShellState state;
    state.backend = backend;
    RefreshProfiles(state);
    if (!state.profiles.empty()) {
        state.selected_action_id = state.profiles[static_cast<size_t>(state.selected_profile_index)].recommended_action_id;
        RefreshProfilePanels(state);
        if (!state.recent_actions.empty()) {
            state.current_run_id = state.recent_actions.front().run_id;
            RefreshSnapshot(state);
        }
        if (!state.recent_runs.empty()) {
            state.current_result_run_id = state.recent_runs.front().run_id;
            RefreshRunSnapshot(state);
        }
    }

    bool done = false;
    while (!done) {
        MSG message;
        while (PeekMessageW(&message, nullptr, 0U, 0U, PM_REMOVE)) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
            if (message.message == WM_QUIT) {
                done = true;
            }
        }
        if (done) {
            break;
        }

        if (!state.current_run_id.empty() && ImGui::GetTime() >= state.next_poll_at) {
            RefreshSnapshot(state);
            RefreshRunSnapshot(state);
            RefreshResultPanels(state);
            state.next_poll_at = ImGui::GetTime() + (
                state.snapshot.has_value() && (state.snapshot->status == "queued" || state.snapshot->status == "running")
                    ? 0.75
                    : 3.0
            );
        }

        ImGui_ImplDX11_NewFrame();
        ImGui_ImplWin32_NewFrame();
        ImGui::NewFrame();

        RenderShell(state);

        ImGui::Render();
        const float clear_color[4] = {0.03f, 0.05f, 0.06f, 1.0f};
        g_device_context->OMSetRenderTargets(1, &g_render_target, nullptr);
        g_device_context->ClearRenderTargetView(g_render_target, clear_color);
        ImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());
        g_swap_chain->Present(1, 0);
    }

    ImGui_ImplDX11_Shutdown();
    ImGui_ImplWin32_Shutdown();
    ImGui::DestroyContext();

    CleanupDeviceD3D();
    DestroyWindow(window_handle);
    UnregisterClassW(window_class.lpszClassName, window_class.hInstance);
    return 0;
}
