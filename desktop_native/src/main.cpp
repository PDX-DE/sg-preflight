#include "backend_bridge.hpp"

#include <d3d11.h>
#include <shellapi.h>
#include <windows.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <cwctype>
#include <filesystem>
#include <optional>
#include <string>
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
    config.workspace_root = std::filesystem::current_path().wstring();

    for (int index = 1; index < __argc; ++index) {
        const std::wstring_view arg = __wargv[index];
        if ((arg == L"--workspace-root" || arg == L"--workspace") && index + 1 < __argc) {
            config.workspace_root = __wargv[++index];
            continue;
        }
        if (arg == L"--python" && index + 1 < __argc) {
            config.python_executable = __wargv[++index];
            continue;
        }
        if (StartsWithInsensitive(std::wstring(arg), L"--workspace-root=")) {
            config.workspace_root = std::wstring(arg.substr(17));
            continue;
        }
        if (StartsWithInsensitive(std::wstring(arg), L"--python=")) {
            config.python_executable = std::wstring(arg.substr(9));
            continue;
        }
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
    }
}

void RefreshRecentActions(ShellState& state) {
    try {
        const std::string profile_id = CurrentActionId(state) == "daily_live_matrix" ? std::string{} : CurrentProfileId(state);
        state.recent_actions = sg_preflight::native_shell::LoadRecentActions(state.backend, profile_id, 18);
        state.last_error.clear();
    } catch (const std::exception& error) {
        state.last_error = error.what();
    }
}

void RefreshRecentRuns(ShellState& state) {
    try {
        state.recent_runs = sg_preflight::native_shell::LoadRecentRuns(state.backend, CurrentProfileId(state), 18);
        state.last_error.clear();
    } catch (const std::exception& error) {
        state.last_error = error.what();
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

void ApplyStyle() {
    ImGuiStyle& style = ImGui::GetStyle();
    style.WindowRounding = 4.0f;
    style.ChildRounding = 4.0f;
    style.FrameRounding = 3.0f;
    style.PopupRounding = 3.0f;
    style.GrabRounding = 3.0f;
    style.ScrollbarRounding = 3.0f;
    style.FramePadding = ImVec2(10.0f, 7.0f);
    style.ItemSpacing = ImVec2(9.0f, 8.0f);
    style.WindowBorderSize = 1.0f;
    style.ChildBorderSize = 1.0f;

    ImVec4* colors = style.Colors;
    colors[ImGuiCol_WindowBg] = ImVec4(0.04f, 0.06f, 0.07f, 1.00f);
    colors[ImGuiCol_ChildBg] = ImVec4(0.06f, 0.09f, 0.10f, 0.98f);
    colors[ImGuiCol_PopupBg] = ImVec4(0.07f, 0.09f, 0.10f, 1.00f);
    colors[ImGuiCol_Border] = ImVec4(0.10f, 0.35f, 0.30f, 0.80f);
    colors[ImGuiCol_BorderShadow] = ImVec4(0.00f, 0.00f, 0.00f, 0.00f);
    colors[ImGuiCol_FrameBg] = ImVec4(0.08f, 0.12f, 0.13f, 1.00f);
    colors[ImGuiCol_FrameBgHovered] = ImVec4(0.11f, 0.17f, 0.18f, 1.00f);
    colors[ImGuiCol_FrameBgActive] = ImVec4(0.13f, 0.22f, 0.22f, 1.00f);
    colors[ImGuiCol_TitleBg] = ImVec4(0.04f, 0.06f, 0.07f, 1.00f);
    colors[ImGuiCol_TitleBgActive] = ImVec4(0.04f, 0.06f, 0.07f, 1.00f);
    colors[ImGuiCol_Button] = ImVec4(0.09f, 0.22f, 0.17f, 1.00f);
    colors[ImGuiCol_ButtonHovered] = ImVec4(0.11f, 0.29f, 0.21f, 1.00f);
    colors[ImGuiCol_ButtonActive] = ImVec4(0.14f, 0.35f, 0.25f, 1.00f);
    colors[ImGuiCol_Header] = ImVec4(0.08f, 0.16f, 0.16f, 1.00f);
    colors[ImGuiCol_HeaderHovered] = ImVec4(0.12f, 0.23f, 0.22f, 1.00f);
    colors[ImGuiCol_HeaderActive] = ImVec4(0.15f, 0.28f, 0.26f, 1.00f);
    colors[ImGuiCol_Tab] = ImVec4(0.08f, 0.11f, 0.12f, 1.00f);
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

void DrawScanlines() {
    ImDrawList* draw_list = ImGui::GetBackgroundDrawList();
    const ImVec2 display_size = ImGui::GetIO().DisplaySize;
    const float time = static_cast<float>(ImGui::GetTime());
    const float shift = std::fmod(time * 12.0f, 12.0f);
    for (float y = -shift; y < display_size.y; y += 12.0f) {
        draw_list->AddLine(
            ImVec2(0.0f, y),
            ImVec2(display_size.x, y),
            IM_COL32(35, 120, 96, 26),
            1.0f
        );
    }
}

void SectionTitle(const char* text) {
    ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", text);
    ImGui::Separator();
}

void RenderProfilesPanel(ShellState& state) {
    SectionTitle("Profiles");
    if (state.profiles.empty()) {
        ImGui::TextDisabled("No ready live profiles were discovered.");
        return;
    }
    for (size_t index = 0; index < state.profiles.size(); ++index) {
        const ProfileItem& profile = state.profiles[index];
        const bool selected = static_cast<int>(index) == state.selected_profile_index;
        const std::string label = profile.profile_id + "###profile-" + profile.profile_id;
        if (ImGui::Selectable(label.c_str(), selected, ImGuiSelectableFlags_AllowDoubleClick)) {
            state.selected_profile_index = static_cast<int>(index);
            state.selected_action_id = profile.recommended_action_id;
            RefreshProfilePanels(state);
        }
        ImGui::SameLine();
        ImGui::TextDisabled("%s", profile.label.c_str());
        ImGui::Indent(12.0f);
        ImGui::TextWrapped("%s", profile.summary.c_str());
        ImGui::Unindent(12.0f);
        ImGui::Spacing();
    }
}

void RenderRecentActionsPanel(ShellState& state) {
    SectionTitle("Recent Actions");
    if (state.recent_actions.empty()) {
        ImGui::TextDisabled("No recent actions yet for this selection.");
        return;
    }
    for (const RecentActionItem& item : state.recent_actions) {
        const bool selected = state.current_run_id == item.run_id;
        const std::string label = item.title + "###recent-" + item.run_id;
        if (ImGui::Selectable(label.c_str(), selected)) {
            state.current_run_id = item.run_id;
            if (!item.profile_id.empty()) {
                SelectProfileById(state, item.profile_id);
            }
            RefreshSnapshot(state);
            RefreshRunSnapshot(state);
        }
        ImGui::Indent(12.0f);
        ImGui::TextDisabled("%s | %s", item.status.c_str(), item.created_at_utc.c_str());
        ImGui::TextWrapped("%s", item.summary.c_str());
        ImGui::Unindent(12.0f);
        ImGui::Spacing();
    }
}

void RenderRecentResultsPanel(ShellState& state) {
    SectionTitle("Recent Results");
    if (state.recent_runs.empty()) {
        ImGui::TextDisabled("No recent run records yet for this profile.");
        return;
    }
    for (const RecentRunItem& item : state.recent_runs) {
        const bool selected = state.current_result_run_id == item.run_id;
        const std::string label = item.profile_id + " - " + item.title + "###recent-run-" + item.run_id;
        if (ImGui::Selectable(label.c_str(), selected)) {
            state.current_result_run_id = item.run_id;
            RefreshRunSnapshot(state);
        }
        ImGui::Indent(12.0f);
        ImGui::TextDisabled("%s | %s", item.status.c_str(), item.created_at_utc.c_str());
        ImGui::TextWrapped("%s", item.summary.c_str());
        ImGui::Unindent(12.0f);
        ImGui::Spacing();
    }
}

void RenderActionTabs(ShellState& state) {
    SectionTitle("Action Tabs");
    if (ImGui::BeginTabBar("action-tabs")) {
        const bool daily_selected = state.selected_action_id == "daily_live_matrix";
        if (ImGui::BeginTabItem("DAILY")) {
            if (!daily_selected) {
                state.selected_action_id = "daily_live_matrix";
                RefreshResultPanels(state);
            }
            ImGui::TextWrapped("Run the recommended SG QA stack across all ready live profiles and aggregate one shared `Open first` surface.");
            ImGui::EndTabItem();
        }
        for (const ActionItem& action : state.actions) {
            const std::string tab_label = ShortActionLabel(action.action_id) + "###tab-" + action.action_id;
            if (ImGui::BeginTabItem(tab_label.c_str())) {
                if (state.selected_action_id != action.action_id) {
                    state.selected_action_id = action.action_id;
                    RefreshResultPanels(state);
                }
                ImGui::TextWrapped("%s", action.description.c_str());
                if (!action.command_preview.empty()) {
                    ImGui::Spacing();
                    ImGui::TextDisabled("%s", action.command_preview.c_str());
                }
                if (!action.ready && !action.blocker_message.empty()) {
                    ImGui::Spacing();
                    ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", action.blocker_message.c_str());
                }
                ImGui::EndTabItem();
            }
        }
        ImGui::EndTabBar();
    }
}

void RenderSummaryPanel(ShellState& state) {
    const std::string selected_action = CurrentActionId(state);
    const ActionItem* action = FindSelectedAction(state);

    ImGui::PushStyleColor(ImGuiCol_Button, ImVec4(0.12f, 0.36f, 0.23f, 1.0f));
    if (ImGui::Button("Run Selected Action", ImVec2(220.0f, 0.0f))) {
        if (selected_action == "daily_live_matrix" || (action != nullptr && action->ready)) {
            StartAction(state, selected_action);
        }
    }
    ImGui::PopStyleColor();
    ImGui::SameLine();
    ImGui::TextDisabled("%s", state.status_line.c_str());

    if (!state.last_error.empty()) {
        ImGui::Spacing();
        ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", state.last_error.c_str());
    }

    ImGui::Spacing();
    SectionTitle("Active Run / Result");
    if (!state.snapshot.has_value() && !state.run_snapshot.has_value()) {
        ImGui::TextDisabled("Select a recent action or run a new one to populate the active result panel.");
        return;
    }

    if (state.snapshot.has_value()) {
        const ActionSnapshot& snapshot = *state.snapshot;
        ImGui::Text("Action: %s", snapshot.title.c_str());
        ImGui::SameLine();
        ImGui::TextColored(ImVec4(0.40f, 0.88f, 0.64f, 1.0f), "[%s]", snapshot.status.c_str());
        ImGui::ProgressBar(static_cast<float>(snapshot.progress_percent) / 100.0f, ImVec2(-1.0f, 0.0f));
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
        SectionTitle("Action Summary");
        if (snapshot.summary_lines.empty()) {
            ImGui::TextDisabled("No summary lines yet.");
        } else {
            for (const std::string& line : snapshot.summary_lines) {
                ImGui::BulletText("%s", line.c_str());
            }
        }

        ImGui::Spacing();
        SectionTitle("Log Tail");
        ImGui::BeginChild("log-tail", ImVec2(0.0f, 160.0f), true);
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
        SectionTitle("Result Drilldown");
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
    SectionTitle("Open First");
    if (!state.snapshot.has_value() || state.snapshot->top_paths.empty()) {
        ImGui::TextDisabled("No file-backed checker evidence is available for the current action.");
        return;
    }

    for (size_t index = 0; index < state.snapshot->top_paths.size(); ++index) {
        const EvidenceItem& item = state.snapshot->top_paths[index];
        const bool selected = static_cast<int>(index) == state.selected_evidence_index;
        const std::string label = item.path + "###evidence-" + std::to_string(index);
        if (ImGui::Selectable(label.c_str(), selected)) {
            state.selected_evidence_index = static_cast<int>(index);
        }
        ImGui::Indent(12.0f);
        if (!item.checker.empty()) {
            ImGui::TextDisabled("%s", item.checker.c_str());
        }
        if (item.line >= 0) {
            ImGui::TextDisabled("line %d", item.line);
        }
        ImGui::TextWrapped("%s", item.message.c_str());
        ImGui::Unindent(12.0f);
        ImGui::Spacing();
    }
}

void RenderArtifactsPanel(ShellState& state) {
    SectionTitle("Artifacts / Reports");
    const std::vector<ArtifactChoice> artifacts = CombinedArtifacts(state);
    const std::vector<CopyItem> copy_items = CombinedCopyItems(state);
    if (!state.snapshot.has_value() && !state.run_snapshot.has_value()) {
        ImGui::TextDisabled("No action or run snapshot loaded.");
        return;
    }

    if (!artifacts.empty()) {
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
            const std::string label = artifact.label + "###artifact-" + std::to_string(index);
            if (ImGui::Selectable(label.c_str(), selected)) {
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
    if (ImGui::Button("Open Selected", ImVec2(180.0f, 0.0f))) {
        OpenPath(selected_artifact_path);
    }
    if (ImGui::Button("Reveal Selected", ImVec2(180.0f, 0.0f))) {
        RevealPath(selected_artifact_path);
    }
    if (state.run_snapshot.has_value() && ImGui::Button("Open HTML Report", ImVec2(180.0f, 0.0f))) {
        for (const auto& artifact : state.run_snapshot->artifacts) {
            if (artifact.label == "HTML report") {
                OpenPath(sg_preflight::native_shell::ToWide(artifact.path));
                break;
            }
        }
    }
    ImGui::Spacing();
    SectionTitle("Copy / Export");
    for (const CopyItem& item : copy_items) {
        if (ImGui::Button(item.label.c_str(), ImVec2(180.0f, 0.0f))) {
            if (CopyText(sg_preflight::native_shell::ToWide(item.text))) {
                state.status_line = "Copied " + item.label + ".";
            }
        }
    }
}

void RenderBlockersPanel(ShellState& state) {
    SectionTitle("Blocked / Manual Stages");
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

    SectionTitle("Manual Review Companion");
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
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImVec4(0.05f, 0.08f, 0.09f, 1.0f));
    if (ImGui::BeginChild("button-guide", ImVec2(0.0f, 48.0f), true)) {
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "BUTTON GUIDE");
        ImGui::SameLine();

        if (ImGui::Button("RUN") && !CurrentActionId(state).empty()) {
            StartAction(state, CurrentActionId(state));
        }
        ImGui::SameLine();
        if (ImGui::Button("OPEN FILE")) {
            const std::wstring evidence_path = SelectedEvidencePath(state);
            if (!evidence_path.empty()) {
                OpenPath(evidence_path);
            } else {
                OpenPath(SelectedArtifactPath(state));
            }
        }
        ImGui::SameLine();
        if (ImGui::Button("REVEAL")) {
            const std::wstring evidence_path = SelectedEvidencePath(state);
            if (!evidence_path.empty()) {
                RevealPath(evidence_path);
            } else {
                RevealPath(SelectedArtifactPath(state));
            }
        }
        ImGui::SameLine();
        if (ImGui::Button("RAW LOG") && state.snapshot.has_value()) {
            OpenPath(sg_preflight::native_shell::ToWide(state.snapshot->log_path));
        }
        ImGui::SameLine();
        if (ImGui::Button("REPORT")) {
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
        ImGui::SameLine();
        if (ImGui::Button("COPY JIRA")) {
            for (const CopyItem& item : CombinedCopyItems(state)) {
                if (item.key == "jira") {
                    if (CopyText(sg_preflight::native_shell::ToWide(item.text))) {
                        state.status_line = "Copied Jira note.";
                    }
                    break;
                }
            }
        }
    }
    ImGui::EndChild();
    ImGui::PopStyleColor();
}

void RenderShell(ShellState& state) {
    DrawScanlines();

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

    ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "SG PREFLIGHT");
    ImGui::SameLine();
    ImGui::TextColored(ImVec4(0.30f, 0.88f, 0.62f, 1.0f), "NATIVE OPERATOR SHELL");
    ImGui::SameLine();
    ImGui::TextDisabled("| workspace: %s", sg_preflight::native_shell::ToUtf8(state.backend.workspace_root).c_str());
    ImGui::Separator();

    if (ImGui::BeginTable("shell-layout", 3, ImGuiTableFlags_Resizable | ImGuiTableFlags_BordersInnerV)) {
        ImGui::TableSetupColumn("left", ImGuiTableColumnFlags_WidthStretch, 0.25f);
        ImGui::TableSetupColumn("center", ImGuiTableColumnFlags_WidthStretch, 0.45f);
        ImGui::TableSetupColumn("right", ImGuiTableColumnFlags_WidthStretch, 0.30f);

        ImGui::TableNextColumn();
        ImGui::BeginChild("left-rail", ImVec2(0.0f, -56.0f), false);
        RenderProfilesPanel(state);
        ImGui::Spacing();
        RenderRecentActionsPanel(state);
        ImGui::Spacing();
        RenderRecentResultsPanel(state);
        ImGui::EndChild();

        ImGui::TableNextColumn();
        ImGui::BeginChild("center-rail", ImVec2(0.0f, -56.0f), false);
        RenderActionTabs(state);
        ImGui::Spacing();
        RenderSummaryPanel(state);
        ImGui::EndChild();

        ImGui::TableNextColumn();
        ImGui::BeginChild("right-rail", ImVec2(0.0f, -56.0f), false);
        RenderEvidencePanel(state);
        ImGui::Spacing();
        RenderArtifactsPanel(state);
        ImGui::Spacing();
        RenderBlockersPanel(state);
        ImGui::EndChild();

        ImGui::EndTable();
    }

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
    io.ConfigFlags |= ImGuiConfigFlags_DockingEnable;
    io.ConfigWindowsMoveFromTitleBarOnly = true;
    ImGui::StyleColorsDark();
    ApplyStyle();

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
