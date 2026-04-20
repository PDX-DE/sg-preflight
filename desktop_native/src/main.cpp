#include "backend_bridge.hpp"
#include "audio_player.hpp"
#include "localization.hpp"
#include "screenshot_capture.hpp"
#include "texture_loader.hpp"

#include <d3d12.h>
#include <commdlg.h>
#include <dxgi1_5.h>
#include <shellapi.h>
#include <windows.h>

#include <algorithm>
#include <array>
#include <cfloat>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cwctype>
#include <fstream>
#include <filesystem>
#include <mutex>
#include <optional>
#include <random>
#include <string>
#include <system_error>
#include <thread>
#include <unordered_map>
#include <vector>

#include "imgui.h"
#include "backends/imgui_impl_dx12.h"
#include "backends/imgui_impl_win32.h"

extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(HWND, UINT, WPARAM, LPARAM);

using sg_preflight::native_shell::ActionItem;
using sg_preflight::native_shell::ActionSnapshot;
using sg_preflight::native_shell::BackendConfig;
using sg_preflight::native_shell::BlockerItem;
using sg_preflight::native_shell::CopyItem;
using sg_preflight::native_shell::DdsTextureHandle;
using sg_preflight::native_shell::EvidenceItem;
using sg_preflight::native_shell::EnvironmentDoctorItem;
using sg_preflight::native_shell::ManualCard;
using sg_preflight::native_shell::ManualEvidenceItem;
using sg_preflight::native_shell::ProfileItem;
using sg_preflight::native_shell::RecentActionItem;
using sg_preflight::native_shell::RecentRunItem;
using sg_preflight::native_shell::RunSnapshot;
using sg_preflight::native_shell::ShellLanguage;
using sg_preflight::native_shell::UiText;

namespace {

#ifndef SG_NATIVE_SHELL_VERSION
#define SG_NATIVE_SHELL_VERSION "dev"
#endif

constexpr const char* kShellVersionLabel = SG_NATIVE_SHELL_VERSION;

constexpr UINT kFrameCount = 3U;
constexpr UINT kSrvHeapSize = 128U;

struct FrameContext {
    ID3D12CommandAllocator* allocator = nullptr;
    UINT64 fence_value = 0;
};

struct DescriptorHeapAllocator {
    ID3D12DescriptorHeap* heap = nullptr;
    D3D12_DESCRIPTOR_HEAP_TYPE heap_type = D3D12_DESCRIPTOR_HEAP_TYPE_NUM_TYPES;
    D3D12_CPU_DESCRIPTOR_HANDLE heap_start_cpu{};
    D3D12_GPU_DESCRIPTOR_HANDLE heap_start_gpu{};
    UINT heap_handle_increment = 0;
    std::vector<int> free_indices;

    void Create(ID3D12Device* device, ID3D12DescriptorHeap* descriptor_heap) {
        heap = descriptor_heap;
        const D3D12_DESCRIPTOR_HEAP_DESC desc = heap->GetDesc();
        heap_type = desc.Type;
        heap_start_cpu = heap->GetCPUDescriptorHandleForHeapStart();
        heap_start_gpu = heap->GetGPUDescriptorHandleForHeapStart();
        heap_handle_increment = device->GetDescriptorHandleIncrementSize(heap_type);
        free_indices.reserve(desc.NumDescriptors);
        for (int index = static_cast<int>(desc.NumDescriptors); index > 0; --index) {
            free_indices.push_back(index - 1);
        }
    }

    void Destroy() {
        heap = nullptr;
        heap_type = D3D12_DESCRIPTOR_HEAP_TYPE_NUM_TYPES;
        heap_start_cpu.ptr = 0;
        heap_start_gpu.ptr = 0;
        heap_handle_increment = 0;
        free_indices.clear();
    }

    void Alloc(D3D12_CPU_DESCRIPTOR_HANDLE* out_cpu_desc_handle, D3D12_GPU_DESCRIPTOR_HANDLE* out_gpu_desc_handle) {
        if (free_indices.empty()) {
            out_cpu_desc_handle->ptr = 0;
            out_gpu_desc_handle->ptr = 0;
            return;
        }
        const int index = free_indices.back();
        free_indices.pop_back();
        out_cpu_desc_handle->ptr = heap_start_cpu.ptr + (static_cast<SIZE_T>(index) * heap_handle_increment);
        out_gpu_desc_handle->ptr = heap_start_gpu.ptr + (static_cast<UINT64>(index) * heap_handle_increment);
    }

    void Free(D3D12_CPU_DESCRIPTOR_HANDLE cpu_desc_handle, D3D12_GPU_DESCRIPTOR_HANDLE gpu_desc_handle) {
        if (heap == nullptr || cpu_desc_handle.ptr == 0 || gpu_desc_handle.ptr == 0) {
            return;
        }
        const int cpu_index = static_cast<int>((cpu_desc_handle.ptr - heap_start_cpu.ptr) / heap_handle_increment);
        const int gpu_index = static_cast<int>((gpu_desc_handle.ptr - heap_start_gpu.ptr) / heap_handle_increment);
        if (cpu_index == gpu_index) {
            free_indices.push_back(cpu_index);
        }
    }
};

FrameContext g_frame_contexts[kFrameCount]{};
UINT g_frame_index = 0U;
ID3D12Device* g_device = nullptr;
IDXGISwapChain3* g_swap_chain = nullptr;
ID3D12DescriptorHeap* g_rtv_descriptor_heap = nullptr;
ID3D12DescriptorHeap* g_srv_descriptor_heap = nullptr;
DescriptorHeapAllocator g_srv_descriptor_allocator;
ID3D12CommandQueue* g_command_queue = nullptr;
ID3D12GraphicsCommandList* g_command_list = nullptr;
ID3D12CommandAllocator* g_upload_command_allocator = nullptr;
ID3D12GraphicsCommandList* g_upload_command_list = nullptr;
ID3D12Fence* g_fence = nullptr;
HANDLE g_fence_event = nullptr;
UINT64 g_fence_last_signaled_value = 0;
ID3D12Resource* g_main_render_targets[kFrameCount]{};
D3D12_CPU_DESCRIPTOR_HANDLE g_main_render_target_descriptors[kFrameCount]{};
ImFont* g_title_font = nullptr;
ImFont* g_body_font = nullptr;
ImFont* g_small_font = nullptr;
ImFont* g_readable_body_font = nullptr;
ImFont* g_readable_small_font = nullptr;
ImFont* g_mono_font = nullptr;
double g_shell_appear_time = -1.0;
double g_shell_disappear_time = -1.0;
ImVec2 g_tab_highlight_min{};
ImVec2 g_tab_highlight_max{};
bool g_tab_highlight_ready = false;
bool g_using_warp = false;
bool g_request_close_prompt = false;
ImGuiID g_last_hovered_control = 0;
float g_shell_text_visibility = 1.0f;

constexpr float kInstallerImageX = 161.5f;
constexpr float kInstallerImageY = 103.5f;
constexpr float kInstallerImageWidth = 512.0f;
constexpr float kInstallerImageHeight = 512.0f;
constexpr float kInstallerContainerX = 513.0f;
constexpr float kInstallerContainerY = 226.0f;
constexpr float kInstallerContainerWidth = 526.5f;
constexpr float kInstallerContainerHeight = 246.0f;
constexpr bool kRenderPlaceholderInstallerCharacters = false;
constexpr double kRunAutoPollDelaySeconds = 1.0;
constexpr double kRunInitialPollDelaySeconds = 0.35;
constexpr double kExitTransitionDurationFrames = 180.0;

struct ShellAssets {
    std::filesystem::path resource_root;
    DdsTextureHandle general_window;
    DdsTextureHandle select;
    DdsTextureHandle light;
    DdsTextureHandle controller_icons;
    DdsTextureHandle kbm_icons;
    DdsTextureHandle help_key_f1;
    DdsTextureHandle help_key_f2;
    DdsTextureHandle help_key_f3;
    DdsTextureHandle help_key_f4;
    DdsTextureHandle options_static;
    DdsTextureHandle options_static_flash;
    DdsTextureHandle installer_panel;
    DdsTextureHandle miles_electric_icon;
    DdsTextureHandle debug_icon;
    DdsTextureHandle arrow_circle;
    DdsTextureHandle pulse_install;
    DdsTextureHandle framework_icon;
    DdsTextureHandle game_icon;
    std::array<DdsTextureHandle, 8> install_images;
    bool attempted = false;
    bool loaded = false;
    std::string error;
};

ShellAssets g_shell_assets;

struct ShellAudio {
    std::filesystem::path cursor;
    std::filesystem::path confirm;
    std::filesystem::path cancel;
    std::filesystem::path window;
    std::filesystem::path page;
    std::filesystem::path window_close;
    std::filesystem::path music;
    std::filesystem::path music_default;
    std::filesystem::path music_easter_egg;
    bool attempted = false;
    bool available = false;
    bool sfx_enabled = true;
    bool music_enabled = false;
    bool music_playing = false;
    bool music_easter_egg_selected = false;
    std::string last_error;
};

ShellAudio g_shell_audio;

struct PendingManualEvidenceCapture {
    bool active = false;
    std::string run_id;
    std::wstring note;
    std::filesystem::path output_path;
};

struct ShellWindowOptions {
    bool fullscreen = true;
    int width = 0;
    int height = 0;
};

ShellWindowOptions g_window_options;
std::filesystem::path g_capture_dir;
std::filesystem::path g_capture_request_path;
std::filesystem::path g_shell_ini_override_path;
std::filesystem::path g_pending_capture_output_path;
std::string g_pending_capture_name;
PendingManualEvidenceCapture g_pending_manual_capture;

enum class ShellScreen {
    Language,
    Introduction,
    Select,
    Review,
    Run,
    Evidence,
    Files,
    Environment,
    Stages,
};

enum class ShellDisplayMode {
    Work,
    Cinematic,
};

ShellDisplayMode g_shell_display_mode = ShellDisplayMode::Cinematic;

struct ShellState {
    BackendConfig backend;
    ShellLanguage language = ShellLanguage::English;
    std::vector<ProfileItem> profiles;
    std::vector<ActionItem> actions;
    std::vector<BlockerItem> blockers;
    std::vector<ManualCard> manual_cards;
    std::vector<EnvironmentDoctorItem> environment_items;
    std::vector<RecentActionItem> recent_actions;
    std::vector<RecentRunItem> recent_runs;
    std::optional<ActionSnapshot> snapshot;
    std::optional<RunSnapshot> run_snapshot;
    int selected_profile_index = 0;
    int selected_evidence_index = 0;
    int selected_artifact_index = 0;
    int selected_environment_index = 0;
    std::string selected_action_id;
    std::string current_run_id;
    std::string current_result_run_id;
    std::string status_line = sg_preflight::native_shell::FormatReadyForNextActionStatus(ShellLanguage::English);
    std::string last_error;
    double next_poll_at = DBL_MAX;
    ShellScreen current_screen = ShellScreen::Introduction;
    ShellScreen previous_screen = ShellScreen::Introduction;
    int selected_language_index = 0;
    double screen_transition_started_at = -1.0;
    bool prompt_visible = false;
    bool prompt_confirmation = false;
    bool prompt_accepts_exit = false;
    bool prompt_accepts_leave_run = false;
    std::string prompt_title;
    std::string prompt_message;
    std::string prompt_accept_label = "YES";
    std::string prompt_cancel_label = "NO";
    bool prompt_closing = false;
    bool prompt_accept_pending = false;
    bool prompt_cancel_pending = false;
    double prompt_opened_at = -1.0;
    double prompt_closing_started_at = -1.0;
    int prompt_selected_index = 0;
    int prompt_previous_selected_index = 0;
    bool prompt_controls_visible = false;
    double prompt_controls_opened_at = -1.0;
    double prompt_selection_changed_at = -1.0;
    bool request_exit = false;
    bool initial_state_loading = true;
    bool profile_panel_loading = false;
    std::string profile_panel_loading_id;
    uint64_t profile_panel_load_token = 0;
    bool run_refresh_loading = false;
    uint64_t run_refresh_token = 0;
    bool exit_transition_active = false;
    double exit_transition_started_at = -1.0;
    std::array<char, 4096> manual_evidence_note{};
};

struct ProfilePanelLoadResult {
    uint64_t token = 0;
    std::string profile_id;
    std::vector<ActionItem> actions;
    std::vector<BlockerItem> blockers;
    std::vector<ManualCard> manual_cards;
    std::string error;
};

struct RunRefreshResult {
    uint64_t token = 0;
    std::string run_id;
    std::string requested_result_run_id;
    std::string current_result_run_id;
    std::string profile_id;
    std::string action_id;
    bool refresh_recent_lists = false;
    bool still_running = false;
    std::vector<RecentActionItem> recent_actions;
    std::vector<RecentRunItem> recent_runs;
    std::optional<ActionSnapshot> snapshot;
    std::optional<RunSnapshot> run_snapshot;
    std::string error;
};

ShellState* g_live_shell_state = nullptr;

struct ProfileSelectionCacheEntry {
    std::vector<ActionItem> actions;
    std::vector<BlockerItem> blockers;
    std::vector<ManualCard> manual_cards;
};

std::mutex g_profile_selection_cache_mutex;
std::unordered_map<std::string, ProfileSelectionCacheEntry> g_profile_selection_cache;

enum class GuideInputMode {
    Keyboard,
    Mouse,
};

GuideInputMode g_guide_input_mode = GuideInputMode::Keyboard;

struct InitialShellLoadResult {
    std::vector<ProfileItem> profiles;
    std::vector<ActionItem> actions;
    std::vector<BlockerItem> blockers;
    std::vector<ManualCard> manual_cards;
    std::vector<EnvironmentDoctorItem> environment_items;
    std::vector<RecentActionItem> recent_actions;
    std::vector<RecentRunItem> recent_runs;
    std::optional<ActionSnapshot> snapshot;
    std::optional<RunSnapshot> run_snapshot;
    int selected_profile_index = 0;
    std::string selected_action_id;
    std::string current_run_id;
    std::string current_result_run_id;
    std::string error;
};

std::mutex g_initial_load_mutex;
std::optional<InitialShellLoadResult> g_initial_load_result;
std::jthread g_initial_load_thread;
bool g_initial_load_started = false;

std::mutex g_profile_panel_load_mutex;
std::optional<ProfilePanelLoadResult> g_profile_panel_load_result;
std::jthread g_profile_panel_load_thread;
uint64_t g_profile_panel_load_next_token = 0;

std::mutex g_run_refresh_mutex;
std::optional<RunRefreshResult> g_run_refresh_result;
std::jthread g_run_refresh_thread;
uint64_t g_run_refresh_next_token = 0;

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
    Page,
    WindowClose,
};

void PlayCue(UiCue cue);

const char* Tr(const ShellState& state, UiText text) {
    return sg_preflight::native_shell::Translate(text, state.language);
}

const char* RefreshShortLabel(ShellLanguage language) {
    switch (language) {
    case ShellLanguage::English: return "Refresh";
    case ShellLanguage::Spanish: return "REFRESCAR";
    case ShellLanguage::German: return "AKTUALISIEREN";
    case ShellLanguage::Romanian: return "Refresh";
    }
    return "Refresh";
}

const char* RefreshActiveRunLabel(ShellLanguage language) {
    switch (language) {
    case ShellLanguage::English: return "Refresh Active Run";
    case ShellLanguage::Spanish: return "REFRESCAR EJECUCION";
    case ShellLanguage::German: return "AKTIVEN LAUF AKTUALISIEREN";
    case ShellLanguage::Romanian: return "REFRESH RULARE";
    }
    return "Refresh Active Run";
}

const char* RunSelectedActionLabel(ShellLanguage language) {
    switch (language) {
    case ShellLanguage::English: return "Run Selected Check";
    case ShellLanguage::Spanish: return "EJECUTAR ACCION";
    case ShellLanguage::German: return "AKTION STARTEN";
    case ShellLanguage::Romanian: return "RULEAZA ACTIUNEA";
    }
    return "Run Selected Check";
}

void SetShellLanguage(ShellState& state, ShellLanguage language, bool announce = true) {
    state.language = language;
    state.selected_language_index = sg_preflight::native_shell::LanguageIndex(language);
    (void)announce;
}

void MoveLanguageSelection(ShellState& state, int delta_x, int delta_y) {
    const int columns = 2;
    const int rows = 2;
    int index = std::clamp(state.selected_language_index, 0, static_cast<int>(sg_preflight::native_shell::SupportedLanguages().size()) - 1);
    int column = index % columns;
    int row = index / columns;
    column = std::clamp(column + delta_x, 0, columns - 1);
    row = std::clamp(row + delta_y, 0, rows - 1);
    const int next_index = std::clamp(row * columns + column, 0, static_cast<int>(sg_preflight::native_shell::SupportedLanguages().size()) - 1);
    if (next_index == state.selected_language_index) {
        return;
    }
    state.selected_language_index = next_index;
    SetShellLanguage(state, sg_preflight::native_shell::LanguageFromIndex(next_index), false);
    PlayCue(UiCue::Cursor);
}

std::string CurrentActionId(const ShellState& state);
const ActionItem* FindSelectedAction(const ShellState& state);
ShellScreen PreviousScreen(const ShellState& state, ShellScreen screen);
void OpenPrompt(ShellState& state, const std::string& title, const std::string& message, bool confirmation = true, bool accepts_exit = false, bool accepts_leave_run = false);
void RequestBackAction(ShellState& state);
void RenderSummaryPanel(ShellState& state);
void RenderEvidencePanel(ShellState& state);
void RenderArtifactsPanel(ShellState& state);
void RenderBlockersPanel(ShellState& state);
void ClampSelections(ShellState& state);
void RefreshSnapshot(ShellState& state);
void RefreshRunSnapshot(ShellState& state);
void RefreshResultPanels(ShellState& state);
void RefreshProfilePanels(ShellState& state, bool refresh_results = true);
void RenderLocalStatePanel(ShellState& state, const char* id, const char* title, float height, const std::string& loading_copy);
void StartInitialShellLoad(ShellState& state);
void PollInitialShellLoad(ShellState& state);
void CancelInitialShellLoad();
void StartProfilePanelLoad(ShellState& state, const std::string& profile_id);
void PollProfilePanelLoad(ShellState& state);
void StartRunRefresh(ShellState& state, bool refresh_recent_lists = false);
void PollRunRefresh(ShellState& state);
void UpdateRunPollingDeadline(ShellState& state, double delay_seconds = -1.0);
void TraceUi(std::string message);
const char* ScreenLabel(ShellScreen screen);
bool EnvFlagEnabled(const wchar_t* name);
float ShellTextLifecycleMotion();
float ShellChromeLifecycleMotion();
float ShellHeaderTextLifecycleMotion();
float ShellExitTextVisibility(const ShellState& state);
std::string SanitiseTraceText(std::string text);
void DrawSelectionContainerChrome(ImDrawList* draw, const ImVec2& min, const ImVec2& max, float alpha, bool fade_top);
bool DrawPanelButton(const char* id, const std::string& label, ImVec2 size, bool accent, bool enabled);
void ClearManualEvidenceNote(ShellState& state);
void DrawPromptTextStyled(
    ImDrawList* draw,
    ImFont* font,
    float font_size,
    const ImVec2& position,
    ImU32 text_color,
    float alpha,
    const char* text,
    float wrap_width
);
float DrawLeftAlignedPromptParagraphStyled(
    ImDrawList* draw,
    ImFont* font,
    float font_size,
    float max_width,
    const ImVec2& min,
    float line_margin,
    ImU32 text_color,
    float alpha,
    const std::string& text
);

constexpr float kPanelGrid = 9.0f;
constexpr float kPanelHeaderHeight = 34.0f;
constexpr float kRailFooterReserve = 62.0f;
constexpr float kDesignWidth = 1280.0f;
constexpr float kDesignHeight = 720.0f;
constexpr double kContainerLineAnimationDuration = 8.0;
constexpr double kContainerOuterTime = kContainerLineAnimationDuration + 8.0;
constexpr double kContainerOuterDuration = 8.0;
constexpr double kContainerInnerTime = kContainerOuterTime + kContainerOuterDuration + 8.0;
constexpr double kContainerInnerDuration = 8.0;
constexpr double kContainerBackgroundTime = kContainerInnerTime + kContainerInnerDuration + 8.0;
constexpr double kContainerBackgroundDuration = 12.0;
constexpr double kContainerCategoryTime = (kContainerInnerTime + kContainerBackgroundTime) / 2.0;
constexpr double kContainerCategoryDuration = 12.0;
constexpr double kShellDisappearDurationFrames = kContainerInnerTime + kContainerInnerDuration;

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

float HermiteFloat(float lhs, float rhs, float alpha) {
    const float t = Saturate(alpha);
    const float t2 = t * t;
    const float t3 = t2 * t;
    return lhs + (rhs - lhs) * ((3.0f * t2) - (2.0f * t3));
}

ImVec2 HermiteVec2(ImVec2 lhs, ImVec2 rhs, float alpha) {
    return ImVec2(HermiteFloat(lhs.x, rhs.x, alpha), HermiteFloat(lhs.y, rhs.y, alpha));
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

double ComputeLinearMotionFrames(double offset_frames, double total_frames) {
    if (g_shell_appear_time < 0.0) {
        return 1.0;
    }

    const double appear_motion = std::clamp(
        (ImGui::GetTime() - g_shell_appear_time - offset_frames / 60.0) / total_frames * 60.0,
        0.0,
        1.0
    );

    if (g_shell_disappear_time < 0.0) {
        return appear_motion;
    }

    const double disappear_offset = std::max(0.0, kShellDisappearDurationFrames - offset_frames - total_frames);
    const double disappear_motion = std::clamp(
        (ImGui::GetTime() - g_shell_disappear_time - disappear_offset / 60.0) / total_frames * 60.0,
        0.0,
        1.0
    );
    return appear_motion * (1.0 - disappear_motion);
}

double ComputeLinearMotionFramesAsymmetric(
    double appear_offset_frames,
    double appear_total_frames,
    double disappear_offset_frames,
    double disappear_total_frames
) {
    if (g_shell_appear_time < 0.0) {
        return 1.0;
    }

    const double appear_motion = std::clamp(
        (ImGui::GetTime() - g_shell_appear_time - appear_offset_frames / 60.0) / appear_total_frames * 60.0,
        0.0,
        1.0
    );

    if (g_shell_disappear_time < 0.0) {
        return appear_motion;
    }

    const double disappear_motion = std::clamp(
        (ImGui::GetTime() - g_shell_disappear_time - disappear_offset_frames / 60.0) / disappear_total_frames * 60.0,
        0.0,
        1.0
    );
    return appear_motion * (1.0 - disappear_motion);
}

double ComputeMotionFrames(double offset_frames, double total_frames) {
    return std::sqrt(ComputeLinearMotionFrames(offset_frames, total_frames));
}

double ComputeMotionFramesAsymmetric(
    double appear_offset_frames,
    double appear_total_frames,
    double disappear_offset_frames,
    double disappear_total_frames
) {
    return std::sqrt(ComputeLinearMotionFramesAsymmetric(
        appear_offset_frames,
        appear_total_frames,
        disappear_offset_frames,
        disappear_total_frames
    ));
}

ImU32 ApplyAlpha(ImU32 color, float alpha_scale) {
    ImVec4 rgba = ImGui::ColorConvertU32ToFloat4(color);
    rgba.w *= Saturate(alpha_scale);
    return ImGui::ColorConvertFloat4ToU32(rgba);
}

float ShellScaleX() {
    const ImVec2 display = ImGui::GetIO().DisplaySize;
    return display.x / kDesignWidth;
}

float ShellScaleY() {
    const ImVec2 display = ImGui::GetIO().DisplaySize;
    return display.y / kDesignHeight;
}

float ShellScale() {
    return std::min(ShellScaleX(), ShellScaleY());
}

ImVec2 ShellOffset() {
    const ImVec2 display = ImGui::GetIO().DisplaySize;
    const float scaled_width = kDesignWidth * ShellScale();
    const float scaled_height = kDesignHeight * ShellScale();
    return ImVec2(
        std::max(0.0f, (display.x - scaled_width) * 0.5f),
        std::max(0.0f, (display.y - scaled_height) * 0.5f)
    );
}

float ShellUi(float value) {
    return value * ShellScale();
}

ImVec2 ShellPoint(float x, float y) {
    const ImVec2 offset = ShellOffset();
    return ImVec2(offset.x + x * ShellScale(), offset.y + y * ShellScale());
}

bool PathExists(const std::filesystem::path& path) {
    std::error_code error;
    return std::filesystem::exists(path, error);
}

std::filesystem::path ResolveShellIniPath() {
    if (!g_shell_ini_override_path.empty()) {
        return g_shell_ini_override_path;
    }
    const char* ini_filename = ImGui::GetIO().IniFilename;
    if (ini_filename == nullptr || *ini_filename == '\0') {
        return std::filesystem::current_path() / "imgui.ini";
    }

    const std::filesystem::path path = std::filesystem::path(ini_filename);
    if (path.is_absolute()) {
        return path;
    }
    return std::filesystem::current_path() / path;
}

void EnsureShellIniDefaults(const std::filesystem::path& ini_path) {
    std::error_code error;
    if (ini_path.has_parent_path()) {
        std::filesystem::create_directories(ini_path.parent_path(), error);
    }

    const auto ensure_value = [&](const wchar_t* key, const wchar_t* default_value) {
        wchar_t value_buffer[64] = {};
        GetPrivateProfileStringW(
            L"sg_preflight_native_shell",
            key,
            L"",
            value_buffer,
            static_cast<DWORD>(std::size(value_buffer)),
            ini_path.wstring().c_str()
        );
        if (value_buffer[0] == L'\0') {
            WritePrivateProfileStringW(
                L"sg_preflight_native_shell",
                key,
                default_value,
                ini_path.wstring().c_str()
            );
        }
    };

    ensure_value(L"display_mode", L"cinematic");
    ensure_value(L"music_enabled", L"1");
    ensure_value(L"sfx_enabled", L"1");
}

void BindShellIniFile(ImGuiIO& io, const std::filesystem::path& ini_path) {
    g_shell_ini_override_path = ini_path;
    EnsureShellIniDefaults(ini_path);
    io.IniFilename = nullptr;

    std::ifstream stream(ini_path, std::ios::binary);
    if (!stream) {
        return;
    }

    const std::string content((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    if (!content.empty()) {
        ImGui::LoadIniSettingsFromMemory(content.c_str(), content.size());
    }
}

void SaveShellIniFile() {
    const std::filesystem::path ini_path = ResolveShellIniPath();
    std::error_code error;
    if (ini_path.has_parent_path()) {
        std::filesystem::create_directories(ini_path.parent_path(), error);
    }

    size_t imgui_settings_size = 0U;
    const char* imgui_settings = ImGui::SaveIniSettingsToMemory(&imgui_settings_size);

    std::string content;
    if (imgui_settings != nullptr && imgui_settings_size > 0U) {
        content.assign(imgui_settings, imgui_settings_size);
    }
    if (!content.empty() && content.back() != '\n') {
        content += "\r\n";
    }
    if (!content.empty()) {
        content += "\r\n";
    }

    content += "[sg_preflight_native_shell]\r\n";
    content += std::string("display_mode=") + (g_shell_display_mode == ShellDisplayMode::Cinematic ? "cinematic" : "work") + "\r\n";
    content += std::string("music_enabled=") + (g_shell_audio.music_enabled ? "1" : "0") + "\r\n";
    content += std::string("sfx_enabled=") + (g_shell_audio.sfx_enabled ? "1" : "0") + "\r\n";

    std::ofstream stream(ini_path, std::ios::binary | std::ios::trunc);
    if (!stream) {
        return;
    }
    stream.write(content.data(), static_cast<std::streamsize>(content.size()));
}

void SaveMusicPreferenceToIni(bool enabled);
void SaveDisplayModePreferenceToIni(ShellDisplayMode mode);
bool LoadSfxPreferenceFromIni();
void SaveSfxPreferenceToIni(bool enabled);

bool IsWorkDisplayMode() {
    return g_shell_display_mode == ShellDisplayMode::Work;
}

bool IsDenseWorkScreen(ShellScreen screen) {
    switch (screen) {
    case ShellScreen::Run:
    case ShellScreen::Evidence:
    case ShellScreen::Files:
    case ShellScreen::Environment:
    case ShellScreen::Stages:
        return true;
    case ShellScreen::Language:
    case ShellScreen::Introduction:
    case ShellScreen::Select:
    case ShellScreen::Review:
    default:
        return false;
    }
}

ShellDisplayMode LoadDisplayModePreferenceFromIni() {
    const std::filesystem::path ini_path = ResolveShellIniPath();
    wchar_t value_buffer[32] = {};
    GetPrivateProfileStringW(
        L"sg_preflight_native_shell",
        L"display_mode",
        L"",
        value_buffer,
        static_cast<DWORD>(std::size(value_buffer)),
        ini_path.wstring().c_str()
    );
    std::wstring value(value_buffer);
    std::transform(
        value.begin(),
        value.end(),
        value.begin(),
        [](wchar_t character) { return static_cast<wchar_t>(towlower(character)); }
    );
    const ShellDisplayMode mode = ShellDisplayMode::Cinematic;
    if (value != L"cinematic") {
        SaveDisplayModePreferenceToIni(mode);
    }
    return mode;
}

void SaveDisplayModePreferenceToIni(ShellDisplayMode mode) {
    const std::filesystem::path ini_path = ResolveShellIniPath();
    WritePrivateProfileStringW(
        L"sg_preflight_native_shell",
        L"display_mode",
        mode == ShellDisplayMode::Cinematic ? L"cinematic" : L"work",
        ini_path.wstring().c_str()
    );
}

bool LoadMusicPreferenceFromIni() {
    const std::filesystem::path ini_path = ResolveShellIniPath();
    wchar_t value_buffer[16] = {};
    GetPrivateProfileStringW(
        L"sg_preflight_native_shell",
        L"music_enabled",
        L"",
        value_buffer,
        static_cast<DWORD>(std::size(value_buffer)),
        ini_path.wstring().c_str()
    );
    const bool enabled = GetPrivateProfileIntW(
        L"sg_preflight_native_shell",
        L"music_enabled",
        1,
        ini_path.wstring().c_str()
    ) != 0;
    if (value_buffer[0] == L'\0') {
        SaveMusicPreferenceToIni(enabled);
    }
    return enabled;
}

void SaveMusicPreferenceToIni(bool enabled) {
    const std::filesystem::path ini_path = ResolveShellIniPath();
    WritePrivateProfileStringW(
        L"sg_preflight_native_shell",
        L"music_enabled",
        enabled ? L"1" : L"0",
        ini_path.wstring().c_str()
    );
}

bool LoadSfxPreferenceFromIni() {
    const std::filesystem::path ini_path = ResolveShellIniPath();
    wchar_t value_buffer[16] = {};
    GetPrivateProfileStringW(
        L"sg_preflight_native_shell",
        L"sfx_enabled",
        L"",
        value_buffer,
        static_cast<DWORD>(std::size(value_buffer)),
        ini_path.wstring().c_str()
    );
    const bool enabled = GetPrivateProfileIntW(
        L"sg_preflight_native_shell",
        L"sfx_enabled",
        1,
        ini_path.wstring().c_str()
    ) != 0;
    if (value_buffer[0] == L'\0') {
        SaveSfxPreferenceToIni(enabled);
    }
    return enabled;
}

void SaveSfxPreferenceToIni(bool enabled) {
    const std::filesystem::path ini_path = ResolveShellIniPath();
    WritePrivateProfileStringW(
        L"sg_preflight_native_shell",
        L"sfx_enabled",
        enabled ? L"1" : L"0",
        ini_path.wstring().c_str()
    );
}

std::wstring Lowercase(const std::wstring& text) {
    std::wstring lowered = text;
    std::transform(
        lowered.begin(),
        lowered.end(),
        lowered.begin(),
        [](wchar_t character) { return static_cast<wchar_t>(towlower(character)); }
    );
    return lowered;
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

std::optional<std::filesystem::path> DiscoverBundleWorkspace(std::filesystem::path start) {
    std::error_code error;
    if (start.empty()) {
        return std::nullopt;
    }
    if (PathExists(start) && std::filesystem::is_regular_file(start, error)) {
        start = start.parent_path();
    }
    for (std::filesystem::path current = start; !current.empty(); current = current.parent_path()) {
        const std::filesystem::path workspace = current / "workspace";
        if (
            PathExists(workspace / "pyproject.toml")
            && PathExists(workspace / "sg_preflight")
        ) {
            return workspace;
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
    if (const auto from_bundle = DiscoverBundleWorkspace(GetExecutableDirectory())) {
        return *from_bundle;
    }
    if (const auto from_executable = DiscoverRepoRoot(GetExecutableDirectory())) {
        return *from_executable;
    }
    if (const auto from_bundle_cwd = DiscoverBundleWorkspace(std::filesystem::current_path())) {
        return *from_bundle_cwd;
    }
    if (const auto from_cwd = DiscoverRepoRoot(std::filesystem::current_path())) {
        return *from_cwd;
    }
    return std::filesystem::current_path();
}

std::wstring ResolvePythonExecutable(const std::filesystem::path& workspace_root) {
    const std::filesystem::path bundle_root = workspace_root.filename() == "workspace"
        ? workspace_root.parent_path()
        : workspace_root;
    const std::array<std::filesystem::path, 5> candidates = {
        bundle_root / "python" / "python.exe",
        bundle_root / "python" / "Scripts" / "python.exe",
        bundle_root / "runtime" / "python.exe",
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

bool IsResourceBundleRoot(const std::filesystem::path& root) {
    return PathExists(root / "images" / "common" / "general_window.dds")
        && PathExists(root / "images" / "common" / "select.dds")
        && PathExists(root / "images" / "common" / "light.dds")
        && PathExists(root / "images" / "options_menu" / "options_static.dds");
}

std::optional<std::filesystem::path> DiscoverResourceRoot(const std::filesystem::path& workspace_root) {
    const std::filesystem::path bundle_root = workspace_root.filename() == "workspace"
        ? workspace_root.parent_path()
        : workspace_root;
    const std::array<std::filesystem::path, 9> direct_candidates = {
        bundle_root / "resources",
        bundle_root / "UnleashedRecompResources-main" / "UnleashedRecompResources-main",
        bundle_root / "UnleashedRecompResources-main",
        bundle_root / "UnleashedRecompResources",
        workspace_root / "UnleashedRecompResources-main" / "UnleashedRecompResources-main",
        workspace_root / "UnleashedRecompResources-main",
        workspace_root / "UnleashedRecompResources",
        workspace_root / "UnleashedRecomp-1.0.3" / "UnleashedRecomp-1.0.3" / "UnleashedRecompResources",
        workspace_root / "UnleashedRecomp-1.0.3" / "UnleashedRecomp-1.0.3" / "UnleashedRecompResources-main",
    };
    for (const auto& candidate : direct_candidates) {
        if (IsResourceBundleRoot(candidate)) {
            return candidate;
        }
    }

    std::error_code error;
    for (const auto& entry : std::filesystem::directory_iterator(workspace_root, error)) {
        if (error || !entry.is_directory()) {
            continue;
        }
        const std::wstring lower_name = Lowercase(entry.path().filename().wstring());
        if (lower_name.find(L"unleashedrecompresources") == std::wstring::npos) {
            continue;
        }
        if (IsResourceBundleRoot(entry.path())) {
            return entry.path();
        }
        for (const auto& nested : std::filesystem::directory_iterator(entry.path(), error)) {
            if (error || !nested.is_directory()) {
                continue;
            }
            if (IsResourceBundleRoot(nested.path())) {
                return nested.path();
            }
        }
    }
    return std::nullopt;
}

std::optional<std::filesystem::path> ResolveDownloadsRoot() {
    const DWORD length = GetEnvironmentVariableW(L"USERPROFILE", nullptr, 0);
    if (length == 0) {
        return std::nullopt;
    }
    std::wstring buffer(length, L'\0');
    const DWORD copied = GetEnvironmentVariableW(L"USERPROFILE", buffer.data(), length);
    if (copied == 0 || copied >= length) {
        return std::nullopt;
    }
    buffer.resize(copied);
    const std::filesystem::path downloads = std::filesystem::path(buffer) / "Downloads";
    if (!PathExists(downloads)) {
        return std::nullopt;
    }
    return downloads;
}

std::optional<std::filesystem::path> ResolveDownloadedFont(
    const std::vector<std::filesystem::path>& relative_candidates,
    const std::vector<std::wstring>& filename_needles
) {
    const auto downloads_root = ResolveDownloadsRoot();
    if (!downloads_root.has_value()) {
        return std::nullopt;
    }

    for (const auto& relative : relative_candidates) {
        const std::filesystem::path candidate = *downloads_root / relative;
        if (PathExists(candidate)) {
            return candidate;
        }
    }

    std::error_code error;
    for (const auto& entry : std::filesystem::recursive_directory_iterator(*downloads_root, error)) {
        if (error || !entry.is_regular_file()) {
            continue;
        }
        const std::wstring lowered_name = Lowercase(entry.path().filename().wstring());
        for (const auto& needle : filename_needles) {
            if (lowered_name.find(Lowercase(needle)) != std::wstring::npos) {
                return entry.path();
            }
        }
    }
    return std::nullopt;
}

std::optional<std::filesystem::path> ResolveBundledFont(
    const std::filesystem::path& workspace_root,
    const std::vector<std::filesystem::path>& relative_candidates,
    const std::vector<std::wstring>& filename_needles
) {
    const std::filesystem::path bundle_root = workspace_root.filename() == "workspace"
        ? workspace_root.parent_path()
        : workspace_root;
    const std::filesystem::path fonts_root = bundle_root / "fonts";
    if (!PathExists(fonts_root)) {
        return std::nullopt;
    }

    for (const auto& relative : relative_candidates) {
        const std::filesystem::path candidate = fonts_root / relative;
        if (PathExists(candidate)) {
            return candidate;
        }
    }

    std::error_code error;
    for (const auto& entry : std::filesystem::recursive_directory_iterator(fonts_root, error)) {
        if (error || !entry.is_regular_file()) {
            continue;
        }
        const std::wstring lowered_name = Lowercase(entry.path().filename().wstring());
        for (const auto& needle : filename_needles) {
            if (lowered_name.find(Lowercase(needle)) != std::wstring::npos) {
                return entry.path();
            }
        }
    }
    return std::nullopt;
}

bool HasTexture(const DdsTextureHandle& texture) {
    return texture.resource != nullptr && texture.gpu_descriptor.ptr != 0;
}

ImTextureID ToTextureId(const DdsTextureHandle& texture) {
    return static_cast<ImTextureID>(texture.gpu_descriptor.ptr);
}

void DrawTexturedRect(
    ImDrawList* draw,
    const DdsTextureHandle& texture,
    ImVec2 min,
    ImVec2 max,
    ImU32 tint,
    ImVec2 uv0 = ImVec2(0.0f, 0.0f),
    ImVec2 uv1 = ImVec2(1.0f, 1.0f)
) {
    if (!HasTexture(texture)) {
        return;
    }
    draw->AddImage(ToTextureId(texture), min, max, uv0, uv1, tint);
}

void DrawTexturedRectRounded(
    ImDrawList* draw,
    const DdsTextureHandle& texture,
    ImVec2 min,
    ImVec2 max,
    ImU32 tint,
    float rounding,
    ImVec2 uv0 = ImVec2(0.0f, 0.0f),
    ImVec2 uv1 = ImVec2(1.0f, 1.0f)
) {
    if (!HasTexture(texture)) {
        return;
    }
    draw->AddImageRounded(ToTextureId(texture), min, max, uv0, uv1, tint, rounding);
}

void DrawRotatedTexture(
    ImDrawList* draw,
    const DdsTextureHandle& texture,
    ImVec2 center,
    ImVec2 size,
    float radians,
    ImU32 tint
) {
    if (!HasTexture(texture)) {
        return;
    }

    const float cos_theta = std::cos(radians);
    const float sin_theta = std::sin(radians);
    const ImVec2 half(size.x * 0.5f, size.y * 0.5f);
    const std::array<ImVec2, 4> corners = {{
        ImVec2(-half.x, -half.y),
        ImVec2(half.x, -half.y),
        ImVec2(half.x, half.y),
        ImVec2(-half.x, half.y),
    }};

    std::array<ImVec2, 4> points{};
    for (size_t index = 0; index < corners.size(); ++index) {
        const ImVec2 corner = corners[index];
        points[index] = ImVec2(
            center.x + (corner.x * cos_theta) - (corner.y * sin_theta),
            center.y + (corner.x * sin_theta) + (corner.y * cos_theta)
        );
    }

    draw->AddImageQuad(
        ToTextureId(texture),
        points[0],
        points[1],
        points[2],
        points[3],
        ImVec2(0.0f, 0.0f),
        ImVec2(1.0f, 0.0f),
        ImVec2(1.0f, 1.0f),
        ImVec2(0.0f, 1.0f),
        tint
    );
}

void DrawContainedTexture(
    ImDrawList* draw,
    const DdsTextureHandle& texture,
    ImVec2 min,
    ImVec2 max,
    ImU32 tint,
    float scale = 1.0f,
    ImVec2 center_offset = ImVec2(0.0f, 0.0f)
) {
    if (!HasTexture(texture) || texture.width == 0 || texture.height == 0) {
        return;
    }

    const float box_width = max.x - min.x;
    const float box_height = max.y - min.y;
    if (box_width <= 0.0f || box_height <= 0.0f) {
        return;
    }

    const float texture_width = static_cast<float>(texture.width);
    const float texture_height = static_cast<float>(texture.height);
    const float contain_scale = std::min(box_width / texture_width, box_height / texture_height) * scale;
    const ImVec2 draw_size(texture_width * contain_scale, texture_height * contain_scale);
    const ImVec2 center((min.x + max.x) * 0.5f + center_offset.x, (min.y + max.y) * 0.5f + center_offset.y);
    const ImVec2 draw_min(center.x - draw_size.x * 0.5f, center.y - draw_size.y * 0.5f);
    const ImVec2 draw_max(center.x + draw_size.x * 0.5f, center.y + draw_size.y * 0.5f);
    draw->AddImage(ToTextureId(texture), draw_min, draw_max, ImVec2(0.0f, 0.0f), ImVec2(1.0f, 1.0f), tint);
}

void ReleaseShellAssets() {
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.general_window);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.select);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.light);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.controller_icons);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.kbm_icons);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.help_key_f1);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.help_key_f2);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.help_key_f3);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.help_key_f4);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.options_static);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.options_static_flash);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.installer_panel);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.miles_electric_icon);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.debug_icon);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.arrow_circle);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.pulse_install);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.framework_icon);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.game_icon);
    for (auto& texture : g_shell_assets.install_images) {
        sg_preflight::native_shell::ReleaseTexture(texture);
    }
    g_shell_assets = {};
}

void AllocSrvDescriptor(void*, D3D12_CPU_DESCRIPTOR_HANDLE* out_cpu_desc_handle, D3D12_GPU_DESCRIPTOR_HANDLE* out_gpu_desc_handle) {
    g_srv_descriptor_allocator.Alloc(out_cpu_desc_handle, out_gpu_desc_handle);
}

void FreeSrvDescriptor(void*, D3D12_CPU_DESCRIPTOR_HANDLE cpu_desc_handle, D3D12_GPU_DESCRIPTOR_HANDLE gpu_desc_handle) {
    g_srv_descriptor_allocator.Free(cpu_desc_handle, gpu_desc_handle);
}

sg_preflight::native_shell::D3d12TextureUploadContext BuildTextureUploadContext() {
    sg_preflight::native_shell::D3d12TextureUploadContext context{};
    context.device = g_device;
    context.command_queue = g_command_queue;
    context.command_allocator = g_upload_command_allocator;
    context.command_list = g_upload_command_list;
    context.fence = g_fence;
    context.fence_event = g_fence_event;
    context.next_fence_value = &g_fence_last_signaled_value;
    context.descriptors.user_data = nullptr;
    context.descriptors.alloc = &AllocSrvDescriptor;
    context.descriptors.free = &FreeSrvDescriptor;
    return context;
}

void LoadShellAssets(const std::filesystem::path& workspace_root) {
    ReleaseShellAssets();
    g_shell_assets.attempted = true;
    const auto resource_root = DiscoverResourceRoot(workspace_root);
    if (!resource_root.has_value()) {
        g_shell_assets.error = "UI asset bundle was not found locally.";
        return;
    }

    g_shell_assets.resource_root = *resource_root;
    std::string error;
    const auto upload_context = BuildTextureUploadContext();
    auto load_required_texture = [&](const std::filesystem::path& relative, DdsTextureHandle& target) {
        if (!sg_preflight::native_shell::LoadDdsTexture(upload_context, *resource_root / relative, target, &error)) {
            g_shell_assets.error = error;
            return false;
        }
        return true;
    };
    auto load_optional_texture = [&](const std::filesystem::path& relative, DdsTextureHandle& target) {
        std::string optional_error;
        sg_preflight::native_shell::LoadDdsTexture(upload_context, *resource_root / relative, target, &optional_error);
    };
    auto load_optional_workspace_texture = [&](const std::filesystem::path& relative, DdsTextureHandle& target, uint8_t alpha_trim_threshold = 0, uint32_t fit_square_canvas_size = 0) {
        std::string optional_error;
        const std::filesystem::path absolute = workspace_root / relative;
        if (PathExists(absolute)) {
            sg_preflight::native_shell::LoadWicTexture(upload_context, absolute, target, alpha_trim_threshold, fit_square_canvas_size, &optional_error);
        }
    };

    if (
        load_required_texture(std::filesystem::path("images") / "common" / "general_window.dds", g_shell_assets.general_window)
        && load_required_texture(std::filesystem::path("images") / "common" / "select.dds", g_shell_assets.select)
        && load_required_texture(std::filesystem::path("images") / "common" / "light.dds", g_shell_assets.light)
        && load_required_texture(std::filesystem::path("images") / "options_menu" / "options_static.dds", g_shell_assets.options_static)
        && load_required_texture(std::filesystem::path("images") / "options_menu" / "options_static_flash.dds", g_shell_assets.options_static_flash)
        && load_required_texture(std::filesystem::path("images") / "installer" / "miles_electric_icon.dds", g_shell_assets.miles_electric_icon)
    ) {
        load_optional_texture(std::filesystem::path("images") / "common" / "controller.dds", g_shell_assets.controller_icons);
        load_optional_texture(std::filesystem::path("images") / "common" / "kbm.dds", g_shell_assets.kbm_icons);
        load_optional_workspace_texture("kb_key_F1.png", g_shell_assets.help_key_f1, 32U, 128U);
        load_optional_workspace_texture("kb_key_F2.png", g_shell_assets.help_key_f2, 32U, 128U);
        load_optional_workspace_texture("kb_key_F3.png", g_shell_assets.help_key_f3, 32U, 128U);
        load_optional_workspace_texture("kb_key_F4.png", g_shell_assets.help_key_f4, 32U, 128U);
        load_optional_workspace_texture("debug_icon.png", g_shell_assets.debug_icon);
        load_optional_workspace_texture("framework_icon.png", g_shell_assets.framework_icon);
        load_optional_workspace_texture("game_icon.png", g_shell_assets.game_icon);
        load_optional_texture(std::filesystem::path("images") / "installer" / "arrow_circle.dds", g_shell_assets.arrow_circle);
        load_optional_texture(std::filesystem::path("images") / "installer" / "pulse_install.dds", g_shell_assets.pulse_install);
        for (size_t index = 0; index < g_shell_assets.install_images.size(); ++index) {
            const std::string filename = "install_00" + std::to_string(index + 1U) + ".dds";
            load_optional_texture(std::filesystem::path("images") / "installer" / filename, g_shell_assets.install_images[index]);
        }
        g_shell_assets.loaded = true;
    }
}

void LoadShellAudio(const std::filesystem::path& workspace_root) {
    sg_preflight::native_shell::ShutdownAudio();
    sg_preflight::native_shell::StopLoopingWaveMusic();
    g_shell_audio = {};
    g_shell_audio.attempted = true;
    g_shell_audio.sfx_enabled = true;

    const auto resource_root = DiscoverResourceRoot(workspace_root);
    if (!resource_root.has_value()) {
        g_shell_audio.last_error = "Audio bundle was not found locally.";
        return;
    }

    g_shell_audio.cursor = *resource_root / "sounds" / "raw" / "sys_actstg_pausecursor.wav";
    g_shell_audio.confirm = *resource_root / "sounds" / "raw" / "sys_worldmap_finaldecide.wav";
    g_shell_audio.cancel = *resource_root / "sounds" / "raw" / "sys_actstg_pausecansel.wav";
    g_shell_audio.window = *resource_root / "sounds" / "raw" / "sys_actstg_pausewinopen.wav";
    g_shell_audio.page = *resource_root / "sounds" / "raw" / "sys_actstg_pausedecide.wav";
    g_shell_audio.window_close = *resource_root / "sounds" / "raw" / "sys_actstg_pausewinclose.wav";
    g_shell_audio.music_default = workspace_root / "SERGFX.wav";
    if (!PathExists(g_shell_audio.music_default)) {
        g_shell_audio.music_default = workspace_root / "SERGFX.mp3";
    }
    if (!PathExists(g_shell_audio.music_default)) {
        g_shell_audio.music_default = *resource_root / "music" / "raw" / "installer.wav";
    }
    g_shell_audio.music_easter_egg = workspace_root / "BAChefPeePee.wav";
    if (!PathExists(g_shell_audio.music_easter_egg)) {
        g_shell_audio.music_easter_egg = workspace_root / "BAChefPeePee.mp3";
    }
    g_shell_audio.music = g_shell_audio.music_default;
    g_shell_audio.music_easter_egg_selected = false;

    const bool allow_dev_easter_eggs = EnvFlagEnabled(L"SERGFX_DEV_EASTER_EGGS");
    if (allow_dev_easter_eggs && PathExists(g_shell_audio.music_default) && PathExists(g_shell_audio.music_easter_egg)) {
        std::random_device random_device;
        std::mt19937 generator(random_device());
        std::uniform_int_distribution<int> distribution(1, 12);
        if (distribution(generator) == 1) {
            g_shell_audio.music = g_shell_audio.music_easter_egg;
            g_shell_audio.music_easter_egg_selected = true;
        }
    } else if (allow_dev_easter_eggs && !PathExists(g_shell_audio.music_default) && PathExists(g_shell_audio.music_easter_egg)) {
        g_shell_audio.music = g_shell_audio.music_easter_egg;
        g_shell_audio.music_easter_egg_selected = true;
    }

    const std::array<std::filesystem::path, 6> sfx_paths = {
        g_shell_audio.cursor,
        g_shell_audio.confirm,
        g_shell_audio.cancel,
        g_shell_audio.window,
        g_shell_audio.page,
        g_shell_audio.window_close,
    };

    for (const auto& sound_path : sfx_paths) {
        if (!PathExists(sound_path)) {
            g_shell_audio.last_error = "One or more required UI sound files are missing from the local audio bundle.";
            return;
        }
    }

    const bool music_available = PathExists(g_shell_audio.music);

    if (!sg_preflight::native_shell::PrimeAudio(&g_shell_audio.last_error)) {
        if (g_shell_audio.last_error.empty()) {
            g_shell_audio.last_error = "The native audio engine could not be initialized.";
        }
        return;
    }

    for (const auto& sound_path : sfx_paths) {
        std::string preload_error;
        if (!sg_preflight::native_shell::PreloadWave(sound_path, &preload_error)) {
            g_shell_audio.last_error = preload_error.empty()
                ? ("Could not preload SFX WAV: " + sound_path.string())
                : preload_error;
            return;
        }
    }

    g_shell_audio.available = true;
    if (music_available) {
        TraceUi(std::string("music_track=") + g_shell_audio.music.filename().string());
    }
    g_shell_audio.last_error = music_available
        ? std::string()
        : "Background music is missing from the local workspace.";
}

void SetMusicEnabled(bool enabled) {
    g_shell_audio.music_enabled = enabled;
    SaveMusicPreferenceToIni(enabled);
    if (!enabled) {
        sg_preflight::native_shell::StopLoopingWaveMusic();
        g_shell_audio.music_playing = false;
        g_shell_audio.last_error.clear();
        return;
    }
    if (PathExists(g_shell_audio.music) && sg_preflight::native_shell::StartLoopingWaveMusic(g_shell_audio.music, 45U)) {
        g_shell_audio.music_playing = true;
        g_shell_audio.last_error.clear();
    } else {
        g_shell_audio.music_playing = false;
        g_shell_audio.last_error = sg_preflight::native_shell::GetAudioLastError();
        if (g_shell_audio.last_error.empty()) {
            g_shell_audio.last_error = "Background music is not available for looping playback.";
        }
    }
}

void SetSfxEnabled(bool enabled) {
    g_shell_audio.sfx_enabled = enabled;
    SaveSfxPreferenceToIni(enabled);
}

void SetDisplayMode(ShellDisplayMode mode) {
    g_shell_display_mode = mode;
    SaveDisplayModePreferenceToIni(mode);
    TraceUi(std::string("display_mode=") + (mode == ShellDisplayMode::Work ? "work" : "cinematic"));
}

ImFont* CurrentBodyFont() {
    if (g_body_font != nullptr) {
        return g_body_font;
    }
    if (g_readable_body_font != nullptr) {
        return g_readable_body_font;
    }
    return ImGui::GetFont();
}

ImFont* CurrentSmallFont() {
    if (g_small_font != nullptr) {
        return g_small_font;
    }
    if (g_readable_small_font != nullptr) {
        return g_readable_small_font;
    }
    return ImGui::GetFont();
}

ImFont* CurrentMonoFont() {
    if (g_mono_font != nullptr) {
        return g_mono_font;
    }
    return CurrentSmallFont();
}

void SetScreen(ShellState& state, ShellScreen screen, bool play_cursor = true) {
    if (state.current_screen == screen) {
        return;
    }
    TraceUi(std::string("screen_change from=") + ScreenLabel(state.current_screen) + " to=" + ScreenLabel(screen));
    state.previous_screen = state.current_screen;
    state.current_screen = screen;
    state.screen_transition_started_at = ImGui::GetTime();
    UpdateRunPollingDeadline(state);
    if (play_cursor) {
        PlayCue(UiCue::Page);
    }
}

int ScreenStepNumber(ShellScreen screen) {
    switch (screen) {
    case ShellScreen::Language:
        return 0;
    case ShellScreen::Introduction:
        return 1;
    case ShellScreen::Select:
        return 2;
    case ShellScreen::Review:
        return 3;
    case ShellScreen::Run:
        return 4;
    case ShellScreen::Evidence:
        return 5;
    case ShellScreen::Files:
        return 6;
    case ShellScreen::Environment:
        return 7;
    case ShellScreen::Stages:
        return 8;
    default:
        return 1;
    }
}

constexpr int kWizardStepCount = 8;

const char* ScreenLabel(ShellScreen screen) {
    switch (screen) {
    case ShellScreen::Language:
        return "LANG";
    case ShellScreen::Introduction:
        return "INTRO";
    case ShellScreen::Select:
        return "SELECT";
    case ShellScreen::Review:
        return "REVIEW";
    case ShellScreen::Run:
        return "RUN";
    case ShellScreen::Evidence:
        return "EVIDENCE";
    case ShellScreen::Files:
        return "FILES";
    case ShellScreen::Environment:
        return "ENV";
    case ShellScreen::Stages:
        return "STAGES";
    default:
        return "SCREEN";
    }
}

const char* ScreenTitle(ShellScreen screen) {
    switch (screen) {
    case ShellScreen::Language:
        return "LANGUAGE SELECT";
    case ShellScreen::Introduction:
        return "INSTALLER INTRO";
    case ShellScreen::Select:
        return "SOURCE SELECT";
    case ShellScreen::Review:
        return "CHECK READINESS";
    case ShellScreen::Run:
        return "RUN LOCAL QA";
    case ShellScreen::Evidence:
        return "OPEN FIRST";
    case ShellScreen::Files:
        return "FILES / EXPORTS";
    case ShellScreen::Environment:
        return "ENVIRONMENT DOCTOR";
    case ShellScreen::Stages:
        return "BLOCKERS / SETTINGS";
    default:
        return "SCREEN";
    }
}

const char* ScreenSummary(ShellScreen screen) {
    switch (screen) {
    case ShellScreen::Language:
        return "Choose the shell language before opening the main workflow.";
    case ShellScreen::Introduction:
        return "Start here to see what the tool is for and what the next step is.";
    case ShellScreen::Select:
        return "Pick the slice and the check you want to run. This page is only for choosing inputs.";
    case ShellScreen::Review:
        return "Confirm the selected slice and check before you start.";
    case ShellScreen::Run:
        return "Stay here while the check runs and its status updates.";
    case ShellScreen::Evidence:
        return "Open the first files that need attention.";
    case ShellScreen::Files:
        return "Open reports, generated files, and ready-to-copy exports.";
    case ShellScreen::Environment:
        return "Check what this machine can actually run before pretending Blender, RaCo, or BMW stages are ready.";
    case ShellScreen::Stages:
        return "Check blocked BMW/manual steps, attach manual evidence, and keep the shell settings honest.";
    default:
        return "Screen flow";
    }
}

ShellScreen FirstOperationalScreen() {
    return ShellScreen::Introduction;
}

bool HasEvidenceReady(const ShellState& state) {
    return state.snapshot.has_value() && !state.snapshot->top_paths.empty();
}

bool HasArtifactsReady(const ShellState& state) {
    return state.snapshot.has_value() || state.run_snapshot.has_value();
}

bool HasCompletedRun(const ShellState& state) {
    return state.snapshot.has_value() && state.snapshot->status == "completed";
}

bool ShouldShowInstallerLoadingChrome(const ShellState& state) {
    return state.current_screen == ShellScreen::Run
        && state.snapshot.has_value()
        && (state.snapshot->status == "queued" || state.snapshot->status == "running");
}

size_t InstallerTextureIndexForState(const ShellState& state) {
    size_t index = 0U;
    switch (state.current_screen) {
    case ShellScreen::Language:
        index = 0U;
        break;
    case ShellScreen::Introduction:
        index = 0U;
        break;
    case ShellScreen::Select:
        index = 1U;
        break;
    case ShellScreen::Review:
        index = 2U;
        break;
    case ShellScreen::Run:
        index = 4U;
        if (ShouldShowInstallerLoadingChrome(state)) {
            const double elapsed = std::max(0.0, ImGui::GetTime() - std::max(0.0, g_shell_appear_time));
            index += static_cast<size_t>(elapsed / 0.45);
        }
        break;
    case ShellScreen::Evidence:
        index = 7U;
        break;
    case ShellScreen::Files:
        index = 3U;
        break;
    case ShellScreen::Environment:
        index = 6U;
        break;
    case ShellScreen::Stages:
        index = 5U;
        break;
    }
    return index % g_shell_assets.install_images.size();
}

const DdsTextureHandle* ChooseHeaderDebugIcon() {
    if (HasTexture(g_shell_assets.debug_icon)) {
        return &g_shell_assets.debug_icon;
    }
    if (HasTexture(g_shell_assets.miles_electric_icon)) {
        return &g_shell_assets.miles_electric_icon;
    }
    return nullptr;
}

bool UsesFrameworkBrandingScreen(ShellScreen screen) {
    return screen == ShellScreen::Language || screen == ShellScreen::Introduction;
}

const DdsTextureHandle* ChooseScreenPrimaryLogo(const ShellState& state) {
    if (UsesFrameworkBrandingScreen(state.current_screen) && HasTexture(g_shell_assets.framework_icon)) {
        return &g_shell_assets.framework_icon;
    }
    if (HasTexture(g_shell_assets.game_icon)) {
        return &g_shell_assets.game_icon;
    }
    if (HasTexture(g_shell_assets.framework_icon)) {
        return &g_shell_assets.framework_icon;
    }
    return nullptr;
}

const DdsTextureHandle* ChooseScreenSecondaryLogo(const ShellState& state) {
    (void)state;
    return nullptr;
}

std::string MakeVisibleLogTail(const std::string& log_tail, bool running) {
    if (!running || log_tail.size() <= 14000U) {
        return log_tail;
    }

    constexpr size_t kMaxChars = 14000U;
    constexpr size_t kMaxLines = 140U;
    size_t start = log_tail.size() - kMaxChars;
    const size_t line_start = log_tail.find_first_of("\r\n", start);
    if (line_start != std::string::npos) {
        start = line_start + 1U;
    }

    std::string trimmed = log_tail.substr(start);
    size_t line_count = 0U;
    size_t cursor = trimmed.size();
    while (cursor > 0U) {
        --cursor;
        if (trimmed[cursor] == '\n') {
            ++line_count;
            if (line_count >= kMaxLines) {
                trimmed.erase(0U, cursor + 1U);
                break;
            }
        }
    }

    return trimmed;
}

std::string PrimaryActionId(const ShellState& state) {
    return CurrentActionId(state);
}

bool SelectedActionReady(const ShellState& state) {
    const std::string action_id = PrimaryActionId(state);
    if (action_id == "daily_live_matrix") {
        return true;
    }
    const ActionItem* action = FindSelectedAction(state);
    return action != nullptr && action->ready;
}

bool CanAdvanceFromPage(const ShellState& state, ShellScreen screen) {
    switch (screen) {
    case ShellScreen::Language:
        return true;
    case ShellScreen::Introduction:
        return true;
    case ShellScreen::Select:
        return !state.profile_panel_loading && !state.profiles.empty() && !PrimaryActionId(state).empty();
    case ShellScreen::Review:
        return SelectedActionReady(state);
    case ShellScreen::Run:
        return HasCompletedRun(state);
    case ShellScreen::Evidence:
        return HasArtifactsReady(state);
    case ShellScreen::Files:
        return true;
    case ShellScreen::Environment:
        return true;
    case ShellScreen::Stages:
        return true;
    default:
        return false;
    }
}

ShellScreen NextScreen(const ShellState& state, ShellScreen screen) {
    switch (screen) {
    case ShellScreen::Language:
        return ShellScreen::Introduction;
    case ShellScreen::Introduction:
        return ShellScreen::Select;
    case ShellScreen::Select:
        return ShellScreen::Review;
    case ShellScreen::Review:
        return ShellScreen::Run;
    case ShellScreen::Run:
        if (HasEvidenceReady(state)) {
            return ShellScreen::Evidence;
        }
        if (HasArtifactsReady(state)) {
            return ShellScreen::Files;
        }
        return ShellScreen::Environment;
    case ShellScreen::Evidence:
        return ShellScreen::Files;
    case ShellScreen::Files:
        return ShellScreen::Environment;
    case ShellScreen::Environment:
        return ShellScreen::Stages;
    case ShellScreen::Stages:
        return ShellScreen::Select;
    default:
        return ShellScreen::Select;
    }
}

ShellScreen PreviousScreen(const ShellState& state, ShellScreen screen) {
    switch (screen) {
    case ShellScreen::Language:
        return ShellScreen::Language;
    case ShellScreen::Introduction:
        return ShellScreen::Language;
    case ShellScreen::Select:
        return ShellScreen::Introduction;
    case ShellScreen::Review:
        return ShellScreen::Select;
    case ShellScreen::Run:
        return ShellScreen::Review;
    case ShellScreen::Evidence:
        return ShellScreen::Run;
    case ShellScreen::Files:
        return HasEvidenceReady(state) ? ShellScreen::Evidence : ShellScreen::Run;
    case ShellScreen::Environment:
        return HasArtifactsReady(state) ? ShellScreen::Files : ShellScreen::Run;
    case ShellScreen::Stages:
        return ShellScreen::Environment;
    default:
        return ShellScreen::Introduction;
    }
}

std::string NextButtonLabel(const ShellState& state) {
    switch (state.current_screen) {
    case ShellScreen::Language:
        return Tr(state, UiText::Next);
    case ShellScreen::Introduction:
        return Tr(state, UiText::Continue);
    case ShellScreen::Select:
        return Tr(state, UiText::Review);
    case ShellScreen::Review:
        return Tr(state, UiText::Run);
    case ShellScreen::Run:
        if (!HasCompletedRun(state)) {
            return Tr(state, UiText::Wait);
        }
        if (HasEvidenceReady(state)) {
            return Tr(state, UiText::OpenFirst);
        }
        if (HasArtifactsReady(state)) {
            return Tr(state, UiText::Files);
        }
        return Tr(state, UiText::Environment);
    case ShellScreen::Evidence:
        return Tr(state, UiText::Files);
    case ShellScreen::Files:
        return Tr(state, UiText::Environment);
    case ShellScreen::Environment:
        return Tr(state, UiText::Stages);
    case ShellScreen::Stages:
        return Tr(state, UiText::Return);
    default:
        return Tr(state, UiText::Next);
    }
}

bool IsActionStillRunning(const ShellState& state) {
    if (!state.snapshot.has_value()) {
        return false;
    }
    return state.snapshot->status == "queued" || state.snapshot->status == "running";
}

bool ShouldAutoRefreshRunInCurrentScreen(const ShellState& state) {
    switch (state.current_screen) {
    case ShellScreen::Run:
    case ShellScreen::Evidence:
    case ShellScreen::Files:
    case ShellScreen::Environment:
    case ShellScreen::Stages:
        return true;
    case ShellScreen::Language:
    case ShellScreen::Introduction:
    case ShellScreen::Select:
    case ShellScreen::Review:
    default:
        return false;
    }
}

double AutoRunPollDelaySeconds(const ShellState& state) {
    switch (state.current_screen) {
    case ShellScreen::Run:
        return 5.0;
    case ShellScreen::Evidence:
    case ShellScreen::Files:
    case ShellScreen::Environment:
    case ShellScreen::Stages:
        return 6.0;
    case ShellScreen::Review:
        return 3.5;
    case ShellScreen::Language:
    case ShellScreen::Introduction:
    case ShellScreen::Select:
    default:
        return 3.0;
    }
}

void UpdateRunPollingDeadline(ShellState& state, double delay_seconds) {
    const double resolved_delay_seconds = delay_seconds >= 0.0 ? delay_seconds : AutoRunPollDelaySeconds(state);
    state.next_poll_at = (!state.current_run_id.empty() && IsActionStillRunning(state) && ShouldAutoRefreshRunInCurrentScreen(state))
        ? (ImGui::GetTime() + resolved_delay_seconds)
        : DBL_MAX;
}

void RefreshActiveRunState(ShellState& state, bool refresh_recent_lists) {
    if (state.current_run_id.empty()) {
        state.snapshot.reset();
        state.current_result_run_id.clear();
        state.run_snapshot.reset();
        state.next_poll_at = DBL_MAX;
        ClampSelections(state);
        return;
    }

    const std::string previous_result_run_id = state.current_result_run_id;
    RefreshSnapshot(state);
    const bool still_running = IsActionStillRunning(state);
    const bool result_changed = state.current_result_run_id != previous_result_run_id;

    if (refresh_recent_lists || !still_running) {
        RefreshResultPanels(state);
    } else if (result_changed) {
        if (!state.current_result_run_id.empty()) {
            RefreshRunSnapshot(state);
        } else {
            state.run_snapshot.reset();
            ClampSelections(state);
        }
    }

    UpdateRunPollingDeadline(state);
}

void OpenPrompt(
    ShellState& state,
    const std::string& title,
    const std::string& message,
    bool confirmation,
    bool accepts_exit,
    bool accepts_leave_run
) {
    state.prompt_visible = true;
    state.prompt_confirmation = confirmation;
    state.prompt_accepts_exit = accepts_exit;
    state.prompt_accepts_leave_run = accepts_leave_run;
    state.prompt_title = title;
    state.prompt_message = message;
    state.prompt_accept_label = confirmation ? Tr(state, UiText::Yes) : Tr(state, UiText::Ok);
    state.prompt_cancel_label = Tr(state, UiText::No);
    state.prompt_closing = false;
    state.prompt_accept_pending = false;
    state.prompt_cancel_pending = false;
    state.prompt_opened_at = ImGui::GetTime();
    state.prompt_closing_started_at = -1.0;
    state.prompt_selected_index = 0;
    state.prompt_previous_selected_index = 0;
    state.prompt_controls_visible = false;
    state.prompt_controls_opened_at = -1.0;
    state.prompt_selection_changed_at = state.prompt_opened_at;
    TraceUi(
        "prompt_open title=\"" + title
        + "\" confirmation=" + std::string(confirmation ? "true" : "false")
        + " accepts_exit=" + std::string(accepts_exit ? "true" : "false")
        + " accepts_leave_run=" + std::string(accepts_leave_run ? "true" : "false")
    );
    PlayCue(UiCue::Window);
}

void ClosePrompt(ShellState& state) {
    state.prompt_visible = false;
    state.prompt_confirmation = false;
    state.prompt_accepts_exit = false;
    state.prompt_accepts_leave_run = false;
    state.prompt_title.clear();
    state.prompt_message.clear();
    state.prompt_accept_label = sg_preflight::native_shell::Translate(UiText::Yes, state.language);
    state.prompt_cancel_label = sg_preflight::native_shell::Translate(UiText::No, state.language);
    state.prompt_closing = false;
    state.prompt_accept_pending = false;
    state.prompt_cancel_pending = false;
    state.prompt_opened_at = -1.0;
    state.prompt_closing_started_at = -1.0;
    state.prompt_selected_index = 0;
    state.prompt_previous_selected_index = 0;
    state.prompt_controls_visible = false;
    state.prompt_controls_opened_at = -1.0;
    state.prompt_selection_changed_at = -1.0;
}

void SetPromptSelection(ShellState& state, int index, bool play_cursor = true) {
    if (!state.prompt_confirmation || !state.prompt_controls_visible) {
        return;
    }
    const int clamped_index = std::clamp(index, 0, 1);
    if (clamped_index == state.prompt_selected_index) {
        return;
    }
    state.prompt_previous_selected_index = state.prompt_selected_index;
    state.prompt_selected_index = clamped_index;
    state.prompt_selection_changed_at = ImGui::GetTime();
    if (play_cursor) {
        PlayCue(UiCue::Cursor);
    }
}

void OpenPromptControls(ShellState& state) {
    if (!state.prompt_visible || state.prompt_closing || state.prompt_controls_visible || !state.prompt_confirmation) {
        return;
    }
    state.prompt_controls_visible = true;
    state.prompt_controls_opened_at = ImGui::GetTime();
    state.prompt_previous_selected_index = 0;
    state.prompt_selected_index = 0;
    state.prompt_selection_changed_at = state.prompt_controls_opened_at;
    TraceUi("prompt_controls_open title=\"" + state.prompt_title + "\"");
    PlayCue(UiCue::Window);
}

void BeginExitTransition(ShellState& state) {
    if (state.exit_transition_active) {
        return;
    }
    CancelInitialShellLoad();
    state.initial_state_loading = false;
    state.exit_transition_active = true;
    state.exit_transition_started_at = ImGui::GetTime();
    g_shell_disappear_time = state.exit_transition_started_at;
    TraceUi("exit_begin");
}

void BeginPromptClose(ShellState& state, bool accepted) {
    if (!state.prompt_visible || state.prompt_closing) {
        return;
    }
    state.prompt_closing = true;
    state.prompt_accept_pending = accepted;
    state.prompt_cancel_pending = !accepted;
    state.prompt_closing_started_at = ImGui::GetTime();
    TraceUi(
        "prompt_close_begin title=\"" + state.prompt_title
        + "\" accepted=" + std::string(accepted ? "true" : "false")
        + " accepts_exit=" + std::string(state.prompt_accepts_exit ? "true" : "false")
        + " accepts_leave_run=" + std::string(state.prompt_accepts_leave_run ? "true" : "false")
    );
    if (accepted && state.prompt_accepts_exit) {
        BeginExitTransition(state);
    }
    PlayCue(accepted ? UiCue::Page : UiCue::Error);
    PlayCue(UiCue::WindowClose);
}

float PromptVisibilityAlpha(const ShellState& state) {
    if (!state.prompt_visible || state.prompt_opened_at < 0.0) {
        return 0.0f;
    }

    const double now = ImGui::GetTime();
    const float open_motion = SmoothStep(static_cast<float>(std::clamp((now - state.prompt_opened_at) * 60.0 / 11.0, 0.0, 1.0)));
    if (!state.prompt_closing || state.prompt_closing_started_at < 0.0) {
        return open_motion;
    }

    const float close_motion = 1.0f - SmoothStep(static_cast<float>(std::clamp((now - state.prompt_closing_started_at) * 60.0 / 8.0, 0.0, 1.0)));
    return open_motion * close_motion;
}

float ExitBlackFadeProgress(const ShellState& state) {
    if (!state.exit_transition_active || state.exit_transition_started_at < 0.0) {
        return 0.0f;
    }
    constexpr double kExitBlackFadeFrames = 60.0;
    const double elapsed_frames = (ImGui::GetTime() - state.exit_transition_started_at) * 60.0;
    const double fade_start_frames = std::max(0.0, kExitTransitionDurationFrames - kExitBlackFadeFrames);
    return SmoothStep(static_cast<float>(std::clamp((elapsed_frames - fade_start_frames) / kExitBlackFadeFrames, 0.0, 1.0)));
}

void FinalizePromptIfReady(ShellState& state) {
    if (!state.prompt_visible || !state.prompt_closing || state.prompt_closing_started_at < 0.0) {
        return;
    }

    const double elapsed_frames = (ImGui::GetTime() - state.prompt_closing_started_at) * 60.0;
    if (elapsed_frames < 8.0) {
        return;
    }

    const bool accepted = state.prompt_accept_pending;
    const bool accepts_exit = state.prompt_accepts_exit;
    const bool accepts_leave_run = state.prompt_accepts_leave_run;
    TraceUi(
        "prompt_close_complete accepted=" + std::string(accepted ? "true" : "false")
        + " accepts_exit=" + std::string(accepts_exit ? "true" : "false")
        + " accepts_leave_run=" + std::string(accepts_leave_run ? "true" : "false")
    );
    ClosePrompt(state);

    if (!accepted) {
        return;
    }

    if (accepts_exit) {
        return;
    }

    if (accepts_leave_run) {
        SetScreen(state, PreviousScreen(state, ShellScreen::Run));
    }
}

void RequestBackAction(ShellState& state) {
    if (state.prompt_visible) {
        return;
    }

    if (state.current_screen == FirstOperationalScreen()) {
        OpenPrompt(
            state,
            Tr(state, UiText::PromptQuitTitle),
            IsActionStillRunning(state)
                ? Tr(state, UiText::PromptQuitRunningMessage)
                : Tr(state, UiText::PromptQuitMessage),
            true,
            true,
            false
        );
        return;
    }

    if (state.current_screen == ShellScreen::Run && IsActionStillRunning(state)) {
        OpenPrompt(
            state,
            Tr(state, UiText::PromptLeaveRunTitle),
            Tr(state, UiText::PromptLeaveRunMessage),
            true,
            false,
            true
        );
        return;
    }

    SetScreen(state, PreviousScreen(state, state.current_screen));
}

void AcceptPrompt(ShellState& state) {
    BeginPromptClose(state, true);
}

void PlayCue(UiCue cue) {
    static double last_cursor = 0.0;
    static double last_confirm = 0.0;
    static double last_error = 0.0;
    static double last_window = 0.0;
    static double last_page = 0.0;
    static double last_window_close = 0.0;

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
    case UiCue::Page:
        last_time = &last_page;
        beep = MB_ICONASTERISK;
        break;
    case UiCue::WindowClose:
        last_time = &last_window_close;
        beep = MB_ICONQUESTION;
        break;
    }
    if ((now - *last_time) < 0.08) {
        return;
    }
    *last_time = now;

    if (!g_shell_audio.sfx_enabled) {
        return;
    }

    if (g_shell_audio.available) {
        const std::filesystem::path* sound_path = nullptr;
        switch (cue) {
        case UiCue::Cursor:
            sound_path = &g_shell_audio.cursor;
            break;
        case UiCue::Confirm:
            sound_path = &g_shell_audio.confirm;
            break;
        case UiCue::Error:
            sound_path = &g_shell_audio.cancel;
            break;
        case UiCue::Window:
            sound_path = &g_shell_audio.window;
            break;
        case UiCue::Page:
            sound_path = &g_shell_audio.page;
            break;
        case UiCue::WindowClose:
            sound_path = &g_shell_audio.window_close;
            break;
        }
        if (sound_path != nullptr && PathExists(*sound_path)) {
            if (sg_preflight::native_shell::PlayWaveOneShot(*sound_path)) {
                g_shell_audio.last_error.clear();
                return;
            }

            const std::string audio_error = sg_preflight::native_shell::GetAudioLastError();
            if (!audio_error.empty()) {
                g_shell_audio.last_error = audio_error;
            }
        }
    }

    MessageBeep(beep);
}

void WaitForPendingOperations() {
    if (g_command_queue == nullptr || g_fence == nullptr || g_fence_event == nullptr) {
        return;
    }
    g_command_queue->Signal(g_fence, ++g_fence_last_signaled_value);
    g_fence->SetEventOnCompletion(g_fence_last_signaled_value, g_fence_event);
    WaitForSingleObject(g_fence_event, INFINITE);
}

FrameContext* WaitForNextFrameContext() {
    FrameContext* frame_context = &g_frame_contexts[g_frame_index % kFrameCount];
    if (g_fence->GetCompletedValue() < frame_context->fence_value) {
        g_fence->SetEventOnCompletion(frame_context->fence_value, g_fence_event);
        WaitForSingleObject(g_fence_event, INFINITE);
    }
    return frame_context;
}

void CreateRenderTarget() {
    for (UINT index = 0; index < kFrameCount; ++index) {
        ID3D12Resource* back_buffer = nullptr;
        if (SUCCEEDED(g_swap_chain->GetBuffer(index, IID_PPV_ARGS(&back_buffer))) && back_buffer != nullptr) {
            g_device->CreateRenderTargetView(back_buffer, nullptr, g_main_render_target_descriptors[index]);
            g_main_render_targets[index] = back_buffer;
        }
    }
}

void CleanupRenderTarget() {
    WaitForPendingOperations();
    for (UINT index = 0; index < kFrameCount; ++index) {
        if (g_main_render_targets[index] != nullptr) {
            g_main_render_targets[index]->Release();
            g_main_render_targets[index] = nullptr;
        }
    }
}

void CapturePendingFrameIfRequested(UINT back_buffer_index) {
    const bool queued_verifier_capture = !g_pending_capture_name.empty() && !g_capture_dir.empty();
    const bool queued_manual_capture = !g_pending_capture_output_path.empty();
    if (!queued_verifier_capture && !queued_manual_capture) {
        return;
    }

    const std::filesystem::path output_path = queued_manual_capture
        ? g_pending_capture_output_path
        : (g_capture_dir / (g_pending_capture_name + ".png"));
    std::error_code directory_error;
    std::filesystem::create_directories(output_path.parent_path(), directory_error);
    TraceUi(
        "capture_begin stage=\"" + g_pending_capture_name
        + "\" path=\"" + sg_preflight::native_shell::ToUtf8(output_path.wstring()) + "\""
    );

    std::string capture_error;
    const sg_preflight::native_shell::D3d12PngCaptureContext capture_context{
        g_device,
        g_command_queue,
        g_fence,
        g_fence_event,
        &g_fence_last_signaled_value,
    };
    const bool captured = sg_preflight::native_shell::CapturePresentedBackBufferToPng(
        capture_context,
        g_main_render_targets[back_buffer_index],
        DXGI_FORMAT_R8G8B8A8_UNORM,
        output_path,
        &capture_error
    );

    if (!captured) {
        TraceUi("capture_failed stage=\"" + g_pending_capture_name + "\" error=\"" + SanitiseTraceText(capture_error) + "\"");
        if (g_live_shell_state != nullptr) {
            g_live_shell_state->last_error = capture_error.empty()
                ? "Screenshot capture failed."
                : capture_error;
        }
    } else {
        TraceUi("capture_complete stage=\"" + g_pending_capture_name + "\"");
        if (g_pending_manual_capture.active) {
            try {
                const ManualEvidenceItem item = sg_preflight::native_shell::AttachManualEvidence(
                    g_live_shell_state != nullptr ? g_live_shell_state->backend : BackendConfig{},
                    g_pending_manual_capture.run_id,
                    "screenshot",
                    std::string(),
                    output_path.wstring(),
                    g_pending_manual_capture.note
                );
                if (g_live_shell_state != nullptr) {
                    g_live_shell_state->last_error.clear();
                    g_live_shell_state->status_line = item.label.empty()
                        ? "Manual screenshot evidence attached."
                        : ("Manual screenshot evidence attached: " + item.label);
                    ClearManualEvidenceNote(*g_live_shell_state);
                    StartRunRefresh(*g_live_shell_state, true);
                }
            } catch (const std::exception& ex) {
                if (g_live_shell_state != nullptr) {
                    g_live_shell_state->last_error = ex.what();
                }
            }
        }
    }

    g_pending_capture_output_path.clear();
    g_pending_capture_name.clear();
    g_pending_manual_capture = PendingManualEvidenceCapture{};
}

RECT PrimaryMonitorRect() {
    POINT origin{0, 0};
    MONITORINFO monitor_info{};
    monitor_info.cbSize = sizeof(monitor_info);
    const HMONITOR monitor = MonitorFromPoint(origin, MONITOR_DEFAULTTOPRIMARY);
    if (monitor != nullptr && GetMonitorInfoW(monitor, &monitor_info)) {
        return monitor_info.rcMonitor;
    }
    RECT fallback{0, 0, 1920, 1080};
    return fallback;
}

UINT SystemDpi() {
    using GetDpiForSystemFn = UINT(WINAPI*)();
    const HMODULE user32 = GetModuleHandleW(L"user32.dll");
    if (user32 != nullptr) {
        const auto get_dpi_for_system = reinterpret_cast<GetDpiForSystemFn>(GetProcAddress(user32, "GetDpiForSystem"));
        if (get_dpi_for_system != nullptr) {
            return get_dpi_for_system();
        }
    }
    return 96U;
}

void AdjustWindowRectForDpi(RECT& rect, DWORD style, UINT dpi) {
    using AdjustWindowRectExForDpiFn = BOOL(WINAPI*)(LPRECT, DWORD, BOOL, DWORD, UINT);
    const HMODULE user32 = GetModuleHandleW(L"user32.dll");
    if (user32 != nullptr) {
        const auto adjust_for_dpi = reinterpret_cast<AdjustWindowRectExForDpiFn>(GetProcAddress(user32, "AdjustWindowRectExForDpi"));
        if (adjust_for_dpi != nullptr) {
            adjust_for_dpi(&rect, style, FALSE, 0, dpi);
            return;
        }
    }
    AdjustWindowRect(&rect, style, FALSE);
}

bool CreateDeviceD3D(HWND window_handle) {
    DXGI_SWAP_CHAIN_DESC1 swap_chain_desc{};
    swap_chain_desc.BufferCount = kFrameCount;
    swap_chain_desc.Width = 0;
    swap_chain_desc.Height = 0;
    swap_chain_desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    swap_chain_desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    swap_chain_desc.SampleDesc.Count = 1;
    swap_chain_desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
    swap_chain_desc.Scaling = DXGI_SCALING_STRETCH;
    swap_chain_desc.AlphaMode = DXGI_ALPHA_MODE_UNSPECIFIED;

    IDXGIFactory4* dxgi_factory = nullptr;
    if (FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&dxgi_factory))) || dxgi_factory == nullptr) {
        return false;
    }

    IDXGIAdapter1* adapter = nullptr;
    for (UINT index = 0; dxgi_factory->EnumAdapters1(index, &adapter) != DXGI_ERROR_NOT_FOUND; ++index) {
        DXGI_ADAPTER_DESC1 description{};
        adapter->GetDesc1(&description);
        if ((description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0) {
            adapter->Release();
            adapter = nullptr;
            continue;
        }
        if (SUCCEEDED(D3D12CreateDevice(adapter, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&g_device)))) {
            g_using_warp = false;
            break;
        }
        adapter->Release();
        adapter = nullptr;
    }

    if (g_device == nullptr) {
        IDXGIAdapter* warp_adapter = nullptr;
        if (SUCCEEDED(dxgi_factory->EnumWarpAdapter(IID_PPV_ARGS(&warp_adapter))) && warp_adapter != nullptr) {
            if (SUCCEEDED(D3D12CreateDevice(warp_adapter, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&g_device)))) {
                g_using_warp = true;
            }
            warp_adapter->Release();
        }
    }
    if (adapter != nullptr) {
        adapter->Release();
        adapter = nullptr;
    }
    if (g_device == nullptr) {
        dxgi_factory->Release();
        return false;
    }

    D3D12_DESCRIPTOR_HEAP_DESC rtv_desc{};
    rtv_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    rtv_desc.NumDescriptors = kFrameCount;
    if (FAILED(g_device->CreateDescriptorHeap(&rtv_desc, IID_PPV_ARGS(&g_rtv_descriptor_heap))) || g_rtv_descriptor_heap == nullptr) {
        dxgi_factory->Release();
        return false;
    }
    const UINT rtv_descriptor_size = g_device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
    D3D12_CPU_DESCRIPTOR_HANDLE rtv_handle = g_rtv_descriptor_heap->GetCPUDescriptorHandleForHeapStart();
    for (UINT index = 0; index < kFrameCount; ++index) {
        g_main_render_target_descriptors[index] = rtv_handle;
        rtv_handle.ptr += rtv_descriptor_size;
    }

    D3D12_DESCRIPTOR_HEAP_DESC srv_desc{};
    srv_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    srv_desc.NumDescriptors = kSrvHeapSize;
    srv_desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    if (FAILED(g_device->CreateDescriptorHeap(&srv_desc, IID_PPV_ARGS(&g_srv_descriptor_heap))) || g_srv_descriptor_heap == nullptr) {
        dxgi_factory->Release();
        return false;
    }
    g_srv_descriptor_allocator.Create(g_device, g_srv_descriptor_heap);

    D3D12_COMMAND_QUEUE_DESC queue_desc{};
    queue_desc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    if (FAILED(g_device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&g_command_queue))) || g_command_queue == nullptr) {
        dxgi_factory->Release();
        return false;
    }

    for (UINT index = 0; index < kFrameCount; ++index) {
        if (FAILED(g_device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&g_frame_contexts[index].allocator))) || g_frame_contexts[index].allocator == nullptr) {
            dxgi_factory->Release();
            return false;
        }
    }

    if (FAILED(g_device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&g_upload_command_allocator))) || g_upload_command_allocator == nullptr) {
        dxgi_factory->Release();
        return false;
    }

    if (
        FAILED(g_device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, g_frame_contexts[0].allocator, nullptr, IID_PPV_ARGS(&g_command_list)))
        || g_command_list == nullptr
        || FAILED(g_command_list->Close())
    ) {
        dxgi_factory->Release();
        return false;
    }

    if (
        FAILED(g_device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, g_upload_command_allocator, nullptr, IID_PPV_ARGS(&g_upload_command_list)))
        || g_upload_command_list == nullptr
        || FAILED(g_upload_command_list->Close())
    ) {
        dxgi_factory->Release();
        return false;
    }

    if (FAILED(g_device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&g_fence))) || g_fence == nullptr) {
        dxgi_factory->Release();
        return false;
    }
    g_fence_event = CreateEvent(nullptr, FALSE, FALSE, nullptr);
    if (g_fence_event == nullptr) {
        dxgi_factory->Release();
        return false;
    }

    IDXGISwapChain1* swap_chain1 = nullptr;
    if (FAILED(dxgi_factory->CreateSwapChainForHwnd(g_command_queue, window_handle, &swap_chain_desc, nullptr, nullptr, &swap_chain1)) || swap_chain1 == nullptr) {
        dxgi_factory->Release();
        return false;
    }
    const HRESULT swap_chain_result = swap_chain1->QueryInterface(IID_PPV_ARGS(&g_swap_chain));
    swap_chain1->Release();
    dxgi_factory->Release();
    if (FAILED(swap_chain_result) || g_swap_chain == nullptr) {
        return false;
    }

    CreateRenderTarget();
    return true;
}

void CleanupDeviceD3D() {
    sg_preflight::native_shell::StopLoopingWaveMusic();
    g_shell_audio.music_playing = false;
    ReleaseShellAssets();
    CleanupRenderTarget();
    if (g_swap_chain != nullptr) {
        g_swap_chain->SetFullscreenState(FALSE, nullptr);
        g_swap_chain->Release();
        g_swap_chain = nullptr;
    }
    if (g_upload_command_list != nullptr) {
        g_upload_command_list->Release();
        g_upload_command_list = nullptr;
    }
    if (g_upload_command_allocator != nullptr) {
        g_upload_command_allocator->Release();
        g_upload_command_allocator = nullptr;
    }
    for (FrameContext& frame_context : g_frame_contexts) {
        if (frame_context.allocator != nullptr) {
            frame_context.allocator->Release();
            frame_context.allocator = nullptr;
        }
        frame_context.fence_value = 0;
    }
    if (g_command_queue != nullptr) {
        g_command_queue->Release();
        g_command_queue = nullptr;
    }
    if (g_command_list != nullptr) {
        g_command_list->Release();
        g_command_list = nullptr;
    }
    if (g_rtv_descriptor_heap != nullptr) {
        g_rtv_descriptor_heap->Release();
        g_rtv_descriptor_heap = nullptr;
    }
    if (g_srv_descriptor_heap != nullptr) {
        g_srv_descriptor_heap->Release();
        g_srv_descriptor_heap = nullptr;
    }
    g_srv_descriptor_allocator.Destroy();
    if (g_fence != nullptr) {
        g_fence->Release();
        g_fence = nullptr;
    }
    if (g_fence_event != nullptr) {
        CloseHandle(g_fence_event);
        g_fence_event = nullptr;
    }
    g_fence_last_signaled_value = 0;
    g_frame_index = 0;
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
            DXGI_SWAP_CHAIN_DESC1 description{};
            g_swap_chain->GetDesc1(&description);
            g_swap_chain->ResizeBuffers(0, static_cast<UINT>(LOWORD(l_param)), static_cast<UINT>(HIWORD(l_param)), description.Format, description.Flags);
            CreateRenderTarget();
        }
        return 0;
    case WM_DPICHANGED:
        if (const RECT* suggested = reinterpret_cast<const RECT*>(l_param)) {
            SetWindowPos(
                window_handle,
                nullptr,
                suggested->left,
                suggested->top,
                suggested->right - suggested->left,
                suggested->bottom - suggested->top,
                SWP_NOZORDER | SWP_NOACTIVATE
            );
        }
        return 0;
    case WM_SYSCOMMAND:
        if ((w_param & 0xfff0) == SC_KEYMENU) {
            return 0;
        }
        break;
    case WM_CLOSE:
        g_request_close_prompt = true;
        return 0;
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

std::wstring EnvironmentVariableValue(const wchar_t* name) {
    const DWORD required = GetEnvironmentVariableW(name, nullptr, 0);
    if (required == 0) {
        return {};
    }
    std::wstring value(static_cast<size_t>(required), L'\0');
    if (GetEnvironmentVariableW(name, value.data(), required) == 0) {
        return {};
    }
    if (!value.empty() && value.back() == L'\0') {
        value.pop_back();
    }
    return value;
}

void ConfigureCaptureRequestDirectory() {
    g_capture_dir.clear();
    g_capture_request_path.clear();
    g_pending_capture_output_path.clear();
    g_pending_capture_name.clear();
    g_pending_manual_capture = PendingManualEvidenceCapture{};

    const std::wstring capture_dir = EnvironmentVariableValue(L"SG_PREFLIGHT_NATIVE_CAPTURE_DIR");
    if (capture_dir.empty()) {
        return;
    }

    std::error_code error;
    g_capture_dir = std::filesystem::path(capture_dir);
    std::filesystem::create_directories(g_capture_dir, error);
    if (error) {
        g_capture_dir.clear();
        return;
    }

    g_capture_request_path = g_capture_dir / "capture-request.txt";
}

std::string SanitiseCaptureStageName(std::string stage_name) {
    while (!stage_name.empty() && std::isspace(static_cast<unsigned char>(stage_name.front()))) {
        stage_name.erase(stage_name.begin());
    }
    while (!stage_name.empty() && std::isspace(static_cast<unsigned char>(stage_name.back()))) {
        stage_name.pop_back();
    }
    for (char& ch : stage_name) {
        switch (ch) {
        case '<':
        case '>':
        case ':':
        case '"':
        case '/':
        case '\\':
        case '|':
        case '?':
        case '*':
            ch = '_';
            break;
        default:
            if (std::isspace(static_cast<unsigned char>(ch))) {
                ch = '_';
            }
            break;
        }
    }
    return stage_name;
}

void PollCaptureRequest() {
    if (g_capture_request_path.empty() || !g_pending_capture_name.empty() || !std::filesystem::exists(g_capture_request_path)) {
        return;
    }

    std::ifstream stream(g_capture_request_path);
    if (!stream) {
        return;
    }

    std::string request_name;
    std::getline(stream, request_name);
    stream.close();
    std::error_code error;
    std::filesystem::remove(g_capture_request_path, error);
    if (error && std::filesystem::exists(g_capture_request_path)) {
        std::ofstream clear_stream(g_capture_request_path, std::ios::trunc);
    }

    request_name = SanitiseCaptureStageName(request_name);
    if (request_name.empty()) {
        return;
    }

    g_pending_capture_name = request_name;
    TraceUi("capture_request stage=\"" + request_name + "\"");
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
        if (arg == L"--profile" && index + 1 < __argc) {
            config.initial_profile_id = sg_preflight::native_shell::ToUtf8(__wargv[++index]);
            continue;
        }
        if (StartsWithInsensitive(std::wstring(arg), L"--profile=")) {
            config.initial_profile_id = sg_preflight::native_shell::ToUtf8(std::wstring(arg.substr(10)));
            continue;
        }
        if (arg == L"--action" && index + 1 < __argc) {
            config.initial_action_id = sg_preflight::native_shell::ToUtf8(__wargv[++index]);
            continue;
        }
        if (StartsWithInsensitive(std::wstring(arg), L"--action=")) {
            config.initial_action_id = sg_preflight::native_shell::ToUtf8(std::wstring(arg.substr(9)));
            continue;
        }
        if (arg == L"--windowed") {
            g_window_options.fullscreen = false;
            continue;
        }
        if (arg == L"--fullscreen") {
            g_window_options.fullscreen = true;
            continue;
        }
        if ((arg == L"--width" || arg == L"--window-width") && index + 1 < __argc) {
            g_window_options.width = std::max(0, _wtoi(__wargv[++index]));
            continue;
        }
        if ((arg == L"--height" || arg == L"--window-height") && index + 1 < __argc) {
            g_window_options.height = std::max(0, _wtoi(__wargv[++index]));
            continue;
        }
        if (StartsWithInsensitive(std::wstring(arg), L"--width=")) {
            g_window_options.width = std::max(0, _wtoi(std::wstring(arg.substr(8)).c_str()));
            continue;
        }
        if (StartsWithInsensitive(std::wstring(arg), L"--height=")) {
            g_window_options.height = std::max(0, _wtoi(std::wstring(arg.substr(9)).c_str()));
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

std::string SanitiseTraceText(std::string text) {
    for (char& ch : text) {
        if (ch == '\r' || ch == '\n' || ch == '\t') {
            ch = ' ';
        }
    }
    return text;
}

void TraceUi(std::string message) {
    sg_preflight::native_shell::AppendNativeTrace("UI " + SanitiseTraceText(std::move(message)));
}

void StoreProfileSelectionCache(
    const std::string& profile_id,
    const std::vector<ActionItem>& actions,
    const std::vector<BlockerItem>& blockers,
    const std::vector<ManualCard>& manual_cards
) {
    if (profile_id.empty()) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_profile_selection_cache_mutex);
    g_profile_selection_cache[profile_id] = ProfileSelectionCacheEntry{actions, blockers, manual_cards};
}

bool TryLoadProfileSelectionCache(
    const std::string& profile_id,
    std::vector<ActionItem>& actions,
    std::vector<BlockerItem>& blockers,
    std::vector<ManualCard>& manual_cards
) {
    std::lock_guard<std::mutex> lock(g_profile_selection_cache_mutex);
    const auto found = g_profile_selection_cache.find(profile_id);
    if (found == g_profile_selection_cache.end()) {
        return false;
    }
    actions = found->second.actions;
    blockers = found->second.blockers;
    manual_cards = found->second.manual_cards;
    return true;
}

std::string FriendlyActionDescription(std::string_view action_id) {
    const std::string short_label = ShortActionLabel(std::string(action_id));
    if (short_label == "DAILY") {
        return "Run the recommended local checks across every ready slice and collect one shared review surface.";
    }
    if (short_label == "STACK") {
        return "Run the standard per-slice SG preflight stack for the selected slice.";
    }
    if (short_label == "REPO") {
        return "Run the SG repository-wide checker pass to catch broader issues outside one slice.";
    }
    if (short_label == "SCENE") {
        return "Run the scene-specific check for the selected slice.";
    }
    if (short_label == "UNUSED") {
        return "Scan the selected slice for unused resources that should be cleaned up or reviewed.";
    }
    if (short_label == "DELIVERY") {
        return "Prepare the delivery-readiness view and show the follow-up items that still need attention.";
    }
    return {};
}

std::string BuildHelpPromptMessage(const ShellState& state) {
    switch (state.current_screen) {
    case ShellScreen::Introduction:
        return "SERGFX is the local desktop operator shell for SG-side 3D Car QA review.\n\nUse the workflow from left to right: choose a slice, choose a check, review it, run it, open the first files that need attention, then review reports, exports, and follow-up work.\n\nIt does not replace Blender visual review, RaCo / RaCoHeadless, rack sessions, or BMW screenshot smoke. Use it to get deterministic SG-side evidence first and keep blocked/manual steps visible.";
    case ShellScreen::Select:
        return "Choose one slice on the right, then choose the local check to run for that slice.\n\nDAILY: runs the recommended local check flow across every ready slice.\nSTACK: runs the standard per-slice QA stack.\nREPO: runs the broader repository checker pass.\nSCENE: runs the scene-specific local check.\nUNUSED: scans the selected slice for unused resources.\nDELIVERY: shows delivery-readiness follow-up for the selected slice.";
    case ShellScreen::Review:
        return "Review confirms what is about to run.\n\nCheck that the selected slice and the selected check are correct before you start the run.";
    case ShellScreen::Run:
        return "Run shows live status while the selected check is queued or running.\n\nStay here to watch progress, refresh the state, and open the raw log or linked result when they are available.";
    case ShellScreen::Evidence:
        return "Open First points to the first files that need attention.\n\nUse this page when you want the most important evidence first instead of searching through every output manually.";
    case ShellScreen::Files:
        return "Files collects generated outputs, reports, source files, and copy-ready exports.\n\nUse it when you need to open deliverables or copy material into Jira, QA Hero, or handoff notes.";
    case ShellScreen::Environment:
        return "Environment Doctor shows what this machine can actually do right now.\n\nUse it to confirm Python/backend readiness, mirrored SG checker coverage, local RaCo or Blender adapters, BMW blockers, and output write access before you overclaim later stages.";
    case ShellScreen::Stages:
        return "Stages keeps the remaining follow-up visible.\n\nUse it to review blocked BMW/manual items, attach manual evidence into the active action bundle, and keep audio/settings honest before you loop back to the next slice.";
    case ShellScreen::Language:
        return "Choose the language used by the shell interface.\n\nProject data, checker output, and generated files stay the same.";
    default:
        return "Use SERGFX from left to right: choose a slice, choose the check, review it, run it, open the first results, then review files and follow-up.";
    }
}

InitialShellLoadResult BuildInitialShellLoad(const BackendConfig& backend) {
    InitialShellLoadResult result;
    result.environment_items = sg_preflight::native_shell::LoadEnvironmentDoctor(backend);
    result.profiles = sg_preflight::native_shell::LoadProfiles(backend);
    if (result.profiles.empty()) {
        return result;
    }

    result.selected_profile_index = 0;
    if (!backend.initial_profile_id.empty()) {
        const auto match = std::find_if(
            result.profiles.begin(),
            result.profiles.end(),
            [&](const ProfileItem& item) { return item.profile_id == backend.initial_profile_id; });
        if (match != result.profiles.end()) {
            result.selected_profile_index = static_cast<int>(std::distance(result.profiles.begin(), match));
        }
    }
    const ProfileItem& profile = result.profiles[static_cast<size_t>(result.selected_profile_index)];
    result.selected_action_id = profile.recommended_action_id;
    result.actions = sg_preflight::native_shell::LoadActions(backend, profile.profile_id);
    result.blockers = sg_preflight::native_shell::LoadBlockers(backend, profile.profile_id);
    result.manual_cards = sg_preflight::native_shell::LoadManualCards(backend, profile.profile_id);
    StoreProfileSelectionCache(profile.profile_id, result.actions, result.blockers, result.manual_cards);
    if (!backend.initial_action_id.empty()) {
        const auto action_match = std::find_if(
            result.actions.begin(),
            result.actions.end(),
            [&](const ActionItem& item) { return item.action_id == backend.initial_action_id; });
        if (action_match != result.actions.end()) {
            result.selected_action_id = action_match->action_id;
        }
    }
    if (result.selected_action_id.empty()) {
        result.selected_action_id = result.actions.empty() ? "daily_live_matrix" : result.actions.front().action_id;
    }

    const std::string recent_actions_profile = result.selected_action_id == "daily_live_matrix"
        ? std::string{}
        : profile.profile_id;
    result.recent_actions = sg_preflight::native_shell::LoadRecentActions(backend, recent_actions_profile, 18);
    result.recent_runs = sg_preflight::native_shell::LoadRecentRuns(backend, profile.profile_id, 18);

    if (!result.recent_actions.empty()) {
        result.current_run_id = result.recent_actions.front().run_id;
        result.snapshot = sg_preflight::native_shell::LoadSnapshot(backend, result.current_run_id);
        if (result.snapshot.has_value() && !result.snapshot->linked_run_id.empty()) {
            result.current_result_run_id = result.snapshot->linked_run_id;
        }
    }

    if (result.current_result_run_id.empty() && !result.recent_runs.empty()) {
        result.current_result_run_id = result.recent_runs.front().run_id;
    }
    if (!result.current_result_run_id.empty()) {
        result.run_snapshot = sg_preflight::native_shell::LoadRunSnapshot(backend, result.current_result_run_id);
    }

    return result;
}

void StartInitialShellLoad(ShellState& state) {
    if (g_initial_load_started) {
        return;
    }

    g_initial_load_started = true;
    g_initial_load_thread = std::jthread([backend = state.backend]() {
        InitialShellLoadResult result;
        try {
            result = BuildInitialShellLoad(backend);
        } catch (const std::exception& error) {
            result.error = error.what();
        }

        std::lock_guard<std::mutex> lock(g_initial_load_mutex);
        g_initial_load_result = std::move(result);
    });
}

void PollInitialShellLoad(ShellState& state) {
    std::optional<InitialShellLoadResult> pending;
    {
        std::lock_guard<std::mutex> lock(g_initial_load_mutex);
        if (!g_initial_load_result.has_value()) {
            return;
        }
        pending = std::move(g_initial_load_result);
        g_initial_load_result.reset();
    }
    if (g_initial_load_thread.joinable()) {
        g_initial_load_thread.join();
    }
    g_initial_load_started = false;

    state.initial_state_loading = false;
    state.profiles = std::move(pending->profiles);
    state.actions = std::move(pending->actions);
    state.blockers = std::move(pending->blockers);
    state.manual_cards = std::move(pending->manual_cards);
    state.environment_items = std::move(pending->environment_items);
    state.recent_actions = std::move(pending->recent_actions);
    state.recent_runs = std::move(pending->recent_runs);
    state.snapshot = std::move(pending->snapshot);
    state.run_snapshot = std::move(pending->run_snapshot);
    state.selected_profile_index = pending->selected_profile_index;
    state.selected_action_id = std::move(pending->selected_action_id);
    state.current_run_id = std::move(pending->current_run_id);
    state.current_result_run_id = std::move(pending->current_result_run_id);
    state.last_error = std::move(pending->error);
    ClampSelections(state);
    if (!CurrentProfileId(state).empty()) {
        StoreProfileSelectionCache(CurrentProfileId(state), state.actions, state.blockers, state.manual_cards);
    }

    if (!state.last_error.empty()) {
        state.status_line = sg_preflight::native_shell::FormatInitialLoadFailedStatus(state.language);
        PlayCue(UiCue::Error);
        TraceUi("initial_load_failed error=" + state.last_error);
    } else if (state.profiles.empty()) {
        state.status_line = sg_preflight::native_shell::FormatNoProfilesDiscoveredStatus(state.language);
        TraceUi("initial_load_complete profiles=0");
    } else {
        state.status_line = sg_preflight::native_shell::FormatLoadedDesktopStateStatus(state.language, CurrentProfileId(state));
        TraceUi(
            "initial_load_complete profiles=" + std::to_string(state.profiles.size())
            + " current_profile=" + CurrentProfileId(state)
        );
    }
    UpdateRunPollingDeadline(state);
}

void CancelInitialShellLoad() {
    if (!g_initial_load_thread.joinable()) {
        g_initial_load_started = false;
        return;
    }
    g_initial_load_thread.request_stop();
    g_initial_load_thread.detach();
    {
        std::lock_guard<std::mutex> lock(g_initial_load_mutex);
        g_initial_load_result.reset();
    }
    g_initial_load_started = false;
}

void StartProfilePanelLoad(ShellState& state, const std::string& profile_id) {
    if (profile_id.empty()) {
        state.profile_panel_loading = false;
        state.profile_panel_loading_id.clear();
        state.profile_panel_load_token = 0;
        return;
    }

    if (g_profile_panel_load_thread.joinable()) {
        g_profile_panel_load_thread.request_stop();
        g_profile_panel_load_thread.detach();
    }

    const uint64_t token = ++g_profile_panel_load_next_token;
    state.profile_panel_loading = true;
    state.profile_panel_loading_id = profile_id;
    state.profile_panel_load_token = token;
    state.last_error.clear();
    state.status_line = "Loading checks for " + profile_id + ".";
    TraceUi("profile_load_start token=" + std::to_string(token) + " profile=" + profile_id);

    g_profile_panel_load_thread = std::jthread([backend = state.backend, profile_id, token](std::stop_token stop_token) {
        ProfilePanelLoadResult result;
        result.token = token;
        result.profile_id = profile_id;
        try {
            result.actions = sg_preflight::native_shell::LoadActions(backend, profile_id);
            result.blockers = sg_preflight::native_shell::LoadBlockers(backend, profile_id);
            result.manual_cards = sg_preflight::native_shell::LoadManualCards(backend, profile_id);
        } catch (const std::exception& error) {
            result.error = error.what();
        }

        if (stop_token.stop_requested()) {
            TraceUi("profile_load_cancelled token=" + std::to_string(token) + " profile=" + profile_id);
            return;
        }

        std::lock_guard<std::mutex> lock(g_profile_panel_load_mutex);
        g_profile_panel_load_result = std::move(result);
    });
}

void PollProfilePanelLoad(ShellState& state) {
    std::optional<ProfilePanelLoadResult> pending;
    {
        std::lock_guard<std::mutex> lock(g_profile_panel_load_mutex);
        if (!g_profile_panel_load_result.has_value()) {
            return;
        }
        pending = std::move(g_profile_panel_load_result);
        g_profile_panel_load_result.reset();
    }
    if (g_profile_panel_load_thread.joinable()) {
        g_profile_panel_load_thread.join();
    }

    if (!pending.has_value() || pending->token != state.profile_panel_load_token || pending->profile_id != CurrentProfileId(state)) {
        if (pending.has_value()) {
            TraceUi("profile_load_ignored token=" + std::to_string(pending->token) + " profile=" + pending->profile_id);
        }
        return;
    }

    state.profile_panel_loading = false;
    state.profile_panel_loading_id.clear();
    if (!pending->error.empty()) {
        state.last_error = pending->error;
        state.status_line = "Loading checks failed for " + pending->profile_id + ".";
        TraceUi("profile_load_failed token=" + std::to_string(pending->token) + " profile=" + pending->profile_id + " error=" + pending->error);
        PlayCue(UiCue::Error);
        return;
    }

    state.actions = std::move(pending->actions);
    state.blockers = std::move(pending->blockers);
    state.manual_cards = std::move(pending->manual_cards);
    StoreProfileSelectionCache(CurrentProfileId(state), state.actions, state.blockers, state.manual_cards);
    state.selected_action_id = state.actions.empty()
        ? std::string("daily_live_matrix")
        : state.profiles[static_cast<size_t>(state.selected_profile_index)].recommended_action_id;
    if (state.selected_action_id != "daily_live_matrix" && FindSelectedAction(state) == nullptr) {
        state.selected_action_id = state.actions.empty() ? "daily_live_matrix" : state.actions.front().action_id;
    }
    state.status_line = sg_preflight::native_shell::FormatLoadedDesktopStateStatus(state.language, CurrentProfileId(state));
    state.last_error.clear();
    TraceUi(
        "profile_load_complete token=" + std::to_string(pending->token)
        + " profile=" + CurrentProfileId(state)
        + " actions=" + std::to_string(state.actions.size())
        + " blockers=" + std::to_string(state.blockers.size())
        + " manual=" + std::to_string(state.manual_cards.size())
    );
}

RunRefreshResult BuildRunRefresh(
    const BackendConfig& backend,
    const std::string& run_id,
    const std::string& requested_result_run_id,
    const std::string& profile_id,
    const std::string& action_id,
    uint64_t token,
    bool refresh_recent_lists,
    bool has_cached_result_snapshot
) {
    RunRefreshResult result;
    result.token = token;
    result.run_id = run_id;
    result.requested_result_run_id = requested_result_run_id;
    result.current_result_run_id = requested_result_run_id;
    result.profile_id = profile_id;
    result.action_id = action_id;
    result.refresh_recent_lists = refresh_recent_lists;

    result.snapshot = sg_preflight::native_shell::LoadSnapshot(backend, run_id);
    if (result.snapshot.has_value() && !result.snapshot->linked_run_id.empty()) {
        result.current_result_run_id = result.snapshot->linked_run_id;
    }
    result.still_running =
        result.snapshot.has_value()
        && (result.snapshot->status == "queued" || result.snapshot->status == "running");

    if (refresh_recent_lists || !result.still_running) {
        const std::string recent_actions_profile = action_id == "daily_live_matrix" ? std::string{} : profile_id;
        result.recent_actions = sg_preflight::native_shell::LoadRecentActions(backend, recent_actions_profile, 18);
        result.recent_runs = sg_preflight::native_shell::LoadRecentRuns(backend, profile_id, 18);
    }

    const bool linked_result_changed = result.current_result_run_id != requested_result_run_id;
    const bool should_refresh_result_snapshot =
        !result.current_result_run_id.empty()
        && (
            refresh_recent_lists
            || !has_cached_result_snapshot
            || linked_result_changed
            || !result.still_running
            || (token % 12U) == 1U
        );

    if (should_refresh_result_snapshot) {
        result.run_snapshot = sg_preflight::native_shell::LoadRunSnapshot(backend, result.current_result_run_id);
    }

    if (
        (refresh_recent_lists || !result.still_running)
        && (!result.run_snapshot.has_value() || result.run_snapshot->profile_id != profile_id)
        && !result.recent_runs.empty()
    ) {
        result.current_result_run_id = result.recent_runs.front().run_id;
        result.run_snapshot = sg_preflight::native_shell::LoadRunSnapshot(backend, result.current_result_run_id);
    }

    return result;
}

void StartRunRefresh(ShellState& state, bool refresh_recent_lists) {
    if (state.current_run_id.empty()) {
        state.run_refresh_loading = false;
        state.run_refresh_token = 0;
        return;
    }

    if (g_run_refresh_thread.joinable()) {
        g_run_refresh_thread.request_stop();
        g_run_refresh_thread.detach();
    }

    const uint64_t token = ++g_run_refresh_next_token;
    state.run_refresh_loading = true;
    state.run_refresh_token = token;
    state.next_poll_at = DBL_MAX;
    TraceUi("run_refresh_start token=" + std::to_string(token) + " run=" + state.current_run_id);

    g_run_refresh_thread = std::jthread([
        backend = state.backend,
        run_id = state.current_run_id,
        requested_result_run_id = state.current_result_run_id,
        profile_id = CurrentProfileId(state),
        action_id = CurrentActionId(state),
        token,
        refresh_recent_lists,
        has_cached_result_snapshot = state.run_snapshot.has_value()
    ](std::stop_token stop_token) {
        RunRefreshResult result;
        try {
            result = BuildRunRefresh(
                backend,
                run_id,
                requested_result_run_id,
                profile_id,
                action_id,
                token,
                refresh_recent_lists,
                has_cached_result_snapshot
            );
        } catch (const std::exception& error) {
            result.token = token;
            result.run_id = run_id;
            result.error = error.what();
        }

        if (stop_token.stop_requested()) {
            TraceUi("run_refresh_cancelled token=" + std::to_string(token) + " run=" + run_id);
            return;
        }

        std::lock_guard<std::mutex> lock(g_run_refresh_mutex);
        g_run_refresh_result = std::move(result);
    });
}

void PollRunRefresh(ShellState& state) {
    std::optional<RunRefreshResult> pending;
    {
        std::lock_guard<std::mutex> lock(g_run_refresh_mutex);
        if (!g_run_refresh_result.has_value()) {
            return;
        }
        pending = std::move(g_run_refresh_result);
        g_run_refresh_result.reset();
    }

    if (g_run_refresh_thread.joinable()) {
        g_run_refresh_thread.join();
    }

    if (!pending.has_value()) {
        return;
    }

    if (pending->token != state.run_refresh_token || pending->run_id != state.current_run_id) {
        TraceUi("run_refresh_ignored token=" + std::to_string(pending->token) + " run=" + pending->run_id);
        return;
    }

    state.run_refresh_loading = false;
    if (!pending->error.empty()) {
        state.last_error = pending->error;
        state.status_line = "Refreshing the selected check failed.";
        TraceUi("run_refresh_failed token=" + std::to_string(pending->token) + " run=" + pending->run_id + " error=" + pending->error);
        PlayCue(UiCue::Error);
        UpdateRunPollingDeadline(state, AutoRunPollDelaySeconds(state));
        return;
    }

    state.snapshot = std::move(pending->snapshot);
    const bool keep_existing_run_snapshot =
        !pending->run_snapshot.has_value()
        && !pending->current_result_run_id.empty()
        && pending->current_result_run_id == state.current_result_run_id;
    state.current_result_run_id = std::move(pending->current_result_run_id);
    if (pending->refresh_recent_lists) {
        state.recent_actions = std::move(pending->recent_actions);
        state.recent_runs = std::move(pending->recent_runs);
    }
    if (!keep_existing_run_snapshot) {
        state.run_snapshot = std::move(pending->run_snapshot);
    }
    state.last_error.clear();
    state.status_line = sg_preflight::native_shell::FormatRefreshedRunStateStatus(state.language);
    ClampSelections(state);
    TraceUi(
        "run_refresh_complete token=" + std::to_string(pending->token)
        + " run=" + state.current_run_id
        + " still_running=" + std::string(pending->still_running ? "true" : "false")
    );
    UpdateRunPollingDeadline(state, AutoRunPollDelaySeconds(state));
}

void ClampSelections(ShellState& state) {
    const size_t top_paths = state.snapshot.has_value() ? state.snapshot->top_paths.size() : 0U;
    const size_t environment_items = state.environment_items.size();
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
    state.selected_environment_index = environment_items == 0
        ? 0
        : std::clamp(state.selected_environment_index, 0, static_cast<int>(environment_items) - 1);
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

void RefreshProfilePanels(ShellState& state, bool refresh_results) {
    const std::string profile_id = CurrentProfileId(state);
    if (profile_id.empty()) {
        state.actions.clear();
        state.blockers.clear();
        state.manual_cards.clear();
        if (refresh_results) {
            state.recent_actions.clear();
            state.recent_runs.clear();
            state.run_snapshot.reset();
        }
        return;
    }

    try {
        if (!TryLoadProfileSelectionCache(profile_id, state.actions, state.blockers, state.manual_cards)) {
            state.actions = sg_preflight::native_shell::LoadActions(state.backend, profile_id);
            state.blockers = sg_preflight::native_shell::LoadBlockers(state.backend, profile_id);
            state.manual_cards = sg_preflight::native_shell::LoadManualCards(state.backend, profile_id);
            StoreProfileSelectionCache(profile_id, state.actions, state.blockers, state.manual_cards);
        }
        if (state.selected_action_id.empty() || (state.selected_action_id != "daily_live_matrix" && FindSelectedAction(state) == nullptr)) {
            state.selected_action_id = state.actions.empty() ? "daily_live_matrix" : state.actions.front().action_id;
        }
        state.last_error.clear();
        state.status_line = sg_preflight::native_shell::FormatLoadedDesktopStateStatus(state.language, profile_id);
    } catch (const std::exception& error) {
        state.last_error = error.what();
        PlayCue(UiCue::Error);
    }
    if (refresh_results) {
        RefreshResultPanels(state);
    }
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
    if (CurrentProfileId(state) == profile_id && !state.profile_panel_loading) {
        return;
    }
    state.selected_profile_index = static_cast<int>(std::distance(state.profiles.begin(), match));
    state.selected_action_id = match->recommended_action_id;
    TraceUi("profile_select profile=" + profile_id);
    if (!TryLoadProfileSelectionCache(profile_id, state.actions, state.blockers, state.manual_cards)) {
        StartProfilePanelLoad(state, profile_id);
    } else {
        state.profile_panel_loading = false;
        state.profile_panel_loading_id.clear();
        RefreshProfilePanels(state, false);
    }
    SetScreen(state, ShellScreen::Select, false);
}

void StartAction(ShellState& state, const std::string& action_id) {
    try {
        TraceUi("action_launch id=" + action_id + " profile=" + CurrentProfileId(state));
        state.current_run_id = sg_preflight::native_shell::LaunchAction(state.backend, action_id);
        state.status_line = sg_preflight::native_shell::FormatQueuedActionStatus(state.language, ShortActionLabel(action_id));
        state.last_error.clear();
        RefreshSnapshot(state);
        if (state.snapshot.has_value() && !state.snapshot->linked_run_id.empty()) {
            state.current_result_run_id = state.snapshot->linked_run_id;
            RefreshRunSnapshot(state);
        }
        UpdateRunPollingDeadline(state, kRunInitialPollDelaySeconds);
        SetScreen(state, ShellScreen::Run);
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

std::wstring QuoteLaunchArgument(const std::wstring& value) {
    std::wstring quoted = L"\"";
    for (wchar_t character : value) {
        if (character == L'"') {
            quoted += L"\\\"";
        } else {
            quoted.push_back(character);
        }
    }
    quoted.push_back(L'"');
    return quoted;
}

bool OpenFolderPath(const std::wstring& path) {
    if (path.empty()) {
        return false;
    }
    std::filesystem::path target(path);
    std::error_code error;
    if (!std::filesystem::is_directory(target, error)) {
        if (target.has_parent_path()) {
            target = target.parent_path();
        }
    }
    if (target.empty()) {
        return false;
    }
    const HINSTANCE result = ShellExecuteW(nullptr, L"open", target.wstring().c_str(), nullptr, nullptr, SW_SHOWNORMAL);
    return reinterpret_cast<INT_PTR>(result) > 32;
}

bool LaunchExternalProgram(
    const std::wstring& executable_path,
    const std::wstring& arguments = L"",
    const std::wstring& working_directory = L""
) {
    if (executable_path.empty()) {
        return false;
    }
    const HINSTANCE result = ShellExecuteW(
        nullptr,
        L"open",
        executable_path.c_str(),
        arguments.empty() ? nullptr : arguments.c_str(),
        working_directory.empty() ? nullptr : working_directory.c_str(),
        SW_SHOWNORMAL
    );
    return reinterpret_cast<INT_PTR>(result) > 32;
}

std::wstring PromptForSingleFile() {
    std::array<wchar_t, 32768> buffer{};
    OPENFILENAMEW dialog{};
    dialog.lStructSize = sizeof(dialog);
    dialog.lpstrFilter = L"All Files\0*.*\0";
    dialog.lpstrFile = buffer.data();
    dialog.nMaxFile = static_cast<DWORD>(buffer.size());
    dialog.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY;
    if (!GetOpenFileNameW(&dialog)) {
        return {};
    }
    return std::wstring(buffer.data());
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

std::wstring EnvironmentDoctorPath(const ShellState& state, const std::string& key) {
    const auto match = std::find_if(
        state.environment_items.begin(),
        state.environment_items.end(),
        [&](const EnvironmentDoctorItem& item) { return item.key == key; }
    );
    if (match == state.environment_items.end() || match->path.empty()) {
        return {};
    }
    return sg_preflight::native_shell::ToWide(match->path);
}

std::filesystem::path CurrentActionOutputRoot(const ShellState& state) {
    if (state.snapshot.has_value() && !state.snapshot->output_root.empty()) {
        return std::filesystem::path(sg_preflight::native_shell::ToWide(state.snapshot->output_root));
    }
    if (state.snapshot.has_value() && !state.snapshot->log_path.empty()) {
        return std::filesystem::path(sg_preflight::native_shell::ToWide(state.snapshot->log_path)).parent_path();
    }
    if (!state.current_run_id.empty()) {
        return std::filesystem::path(state.backend.workspace_root) / "out" / "operator-ui" / "actions" / sg_preflight::native_shell::ToWide(state.current_run_id);
    }
    return {};
}

std::wstring CurrentProjectRoot(const ShellState& state) {
    if (state.snapshot.has_value() && !state.snapshot->project_root.empty()) {
        return sg_preflight::native_shell::ToWide(state.snapshot->project_root);
    }
    return {};
}

bool PathHasExtension(const std::wstring& path, const std::wstring& expected_extension) {
    if (path.empty()) {
        return false;
    }
    const std::filesystem::path file_path(path);
    return Lowercase(file_path.extension().wstring()) == Lowercase(expected_extension);
}

std::string ActiveManualEvidenceNote(const ShellState& state) {
    return std::string(state.manual_evidence_note.data());
}

void ClearManualEvidenceNote(ShellState& state) {
    state.manual_evidence_note.fill('\0');
}

bool AttachManualEvidenceToCurrentRun(
    ShellState& state,
    const std::string& kind,
    const std::wstring& source_path = L"",
    const std::wstring& note_text = L""
) {
    if (state.current_run_id.empty()) {
        state.last_error = "Load or run one action first so manual evidence has a real action bundle.";
        return false;
    }
    try {
        const ManualEvidenceItem item = sg_preflight::native_shell::AttachManualEvidence(
            state.backend,
            state.current_run_id,
            kind,
            std::string(),
            source_path,
            note_text
        );
        state.last_error.clear();
        state.status_line = item.label.empty()
            ? "Manual evidence attached."
            : ("Manual evidence attached: " + item.label);
        StartRunRefresh(state, true);
        return true;
    } catch (const std::exception& ex) {
        state.last_error = ex.what();
        return false;
    }
}

std::wstring TimestampedScreenshotFileName() {
    SYSTEMTIME utc_now{};
    GetSystemTime(&utc_now);
    wchar_t buffer[128] = {};
    swprintf_s(
        buffer,
        L"%04u%02u%02uT%02u%02u%02uZ-native-screenshot-%04x.png",
        utc_now.wYear,
        utc_now.wMonth,
        utc_now.wDay,
        utc_now.wHour,
        utc_now.wMinute,
        utc_now.wSecond,
        GetTickCount() & 0xffffU
    );
    return std::wstring(buffer);
}

bool QueueManualScreenshotCapture(ShellState& state, const std::wstring& note_text) {
    if (state.current_run_id.empty()) {
        state.last_error = "Load or run one action first so screenshot evidence has a real action bundle.";
        return false;
    }
    const std::filesystem::path action_root = CurrentActionOutputRoot(state);
    if (action_root.empty()) {
        state.last_error = "The active action bundle path is not available yet.";
        return false;
    }
    const std::filesystem::path manual_root = action_root / "manual-evidence";
    std::error_code error;
    std::filesystem::create_directories(manual_root, error);
    if (error) {
        state.last_error = "Could not create the manual-evidence folder for the active action bundle.";
        return false;
    }
    g_pending_capture_name = "manual-evidence";
    g_pending_capture_output_path = manual_root / TimestampedScreenshotFileName();
    g_pending_manual_capture.active = true;
    g_pending_manual_capture.run_id = state.current_run_id;
    g_pending_manual_capture.note = note_text;
    g_pending_manual_capture.output_path = g_pending_capture_output_path;
    state.last_error.clear();
    state.status_line = "Manual screenshot capture queued for the current action bundle.";
    TraceUi(
        "manual_capture_queue run_id=\"" + state.current_run_id
        + "\" path=\"" + sg_preflight::native_shell::ToUtf8(g_pending_capture_output_path.wstring()) + "\""
    );
    return true;
}

std::string BuildActionDiagnosticsText(const ActionSnapshot& snapshot) {
    std::string text;
    text += "Command:\n";
    text += snapshot.current_command.empty() ? "(not reported)\n\n" : (snapshot.current_command + "\n\n");
    text += "Exit code:\n";
    text += std::to_string(snapshot.exit_code);
    text += "\n\nWorking directory:\n";
    text += snapshot.workspace_root.empty() ? "(not reported)\n" : snapshot.workspace_root + "\n";
    if (!snapshot.project_root.empty()) {
        text += "\nProject root:\n";
        text += snapshot.project_root + "\n";
    }
    if (!snapshot.output_root.empty()) {
        text += "\nAction folder:\n";
        text += snapshot.output_root + "\n";
    }
    if (!snapshot.error_message.empty()) {
        text += "\nError:\n";
        text += snapshot.error_message + "\n";
    }
    return text;
}

void RenderPathAdapterButtons(ShellState& state, const char* prefix, const std::wstring& target_path) {
    if (target_path.empty()) {
        return;
    }

    const std::wstring blender_executable = EnvironmentDoctorPath(state, "blender_executable");
    const std::wstring raco_gui_executable = EnvironmentDoctorPath(state, "raco_gui");
    const std::wstring project_root = CurrentProjectRoot(state);
    const bool is_blend = PathHasExtension(target_path, L".blend");
    const bool is_rca = PathHasExtension(target_path, L".rca");

    if (DrawPanelButton((std::string(prefix) + "-open-folder").c_str(), "OPEN FOLDER", ImVec2(ShellUi(170.0f), ShellUi(30.0f)), false, true)) {
        OpenFolderPath(target_path);
    }
    ImGui::SameLine();
    if (DrawPanelButton((std::string(prefix) + "-open-project-root").c_str(), "OPEN PROJECT ROOT", ImVec2(ShellUi(210.0f), ShellUi(30.0f)), false, !project_root.empty())) {
        OpenFolderPath(project_root);
    }
    ImGui::Spacing();

    if (DrawPanelButton((std::string(prefix) + "-open-in-raco").c_str(), "OPEN IN RACO", ImVec2(ShellUi(170.0f), ShellUi(30.0f)), false, is_rca && !raco_gui_executable.empty())) {
        LaunchExternalProgram(
            raco_gui_executable,
            L"--project " + QuoteLaunchArgument(target_path),
            std::filesystem::path(raco_gui_executable).parent_path().wstring()
        );
    }
    ImGui::SameLine();
    if (DrawPanelButton((std::string(prefix) + "-open-in-blender").c_str(), "OPEN IN BLENDER", ImVec2(ShellUi(190.0f), ShellUi(30.0f)), false, is_blend && !blender_executable.empty())) {
        LaunchExternalProgram(
            blender_executable,
            QuoteLaunchArgument(target_path),
            std::filesystem::path(blender_executable).parent_path().wstring()
        );
    }

    if (is_rca && raco_gui_executable.empty()) {
        ImGui::TextDisabled("%s", "RaCo path not configured.");
    }
    if (is_blend && blender_executable.empty()) {
        ImGui::TextDisabled("%s", "Blender path not configured.");
    }
}

std::string Ellipsize(const std::string& text, size_t limit = 180U) {
    if (text.size() <= limit) {
        return text;
    }
    return text.substr(0, limit > 3U ? limit - 3U : limit) + "...";
}

bool EnvFlagEnabled(const wchar_t* name) {
    const DWORD required = GetEnvironmentVariableW(name, nullptr, 0);
    if (required == 0) {
        return false;
    }

    std::wstring buffer(required, L'\0');
    const DWORD copied = GetEnvironmentVariableW(name, buffer.data(), required);
    if (copied == 0 || copied >= required) {
        return false;
    }
    buffer.resize(copied);

    const std::wstring lowered = Lowercase(buffer);
    return lowered == L"1" || lowered == L"true" || lowered == L"yes" || lowered == L"on";
}

ImFont* TryLoadFont(ImGuiIO& io, const std::filesystem::path& path, float size) {
    if (!PathExists(path)) {
        return nullptr;
    }
    return io.Fonts->AddFontFromFileTTF(path.string().c_str(), size);
}

void LoadShellFonts(ImGuiIO& io, const std::filesystem::path& workspace_root) {
    const std::vector<std::filesystem::path> seurat_candidates = {
        std::filesystem::path("fot-seurat-pro-m") / "FOT-Seurat Pro M" / "FOT-Seurat Pro M.otf",
        std::filesystem::path("FOT-SeuratPro-M.otf"),
    };
    const std::vector<std::filesystem::path> new_rodin_candidates = {
        std::filesystem::path("fot-newrodin-pro-db") / "FOT-NewRodin Pro DB" / "FOT-NewRodin Pro DB.otf",
        std::filesystem::path("FOT-NewRodinPro-DB.otf"),
    };
    const std::vector<std::filesystem::path> dfs_candidates = {
        std::filesystem::path("DFSoGeiStd-W7.otf"),
        std::filesystem::path("DFHeiStd-W7.otf"),
    };

    const auto resolve_font = [&](const std::vector<std::filesystem::path>& candidates, const std::vector<std::wstring>& needles) {
        const auto bundled = ResolveBundledFont(workspace_root, candidates, needles);
        return bundled.has_value() ? bundled : ResolveDownloadedFont(candidates, needles);
    };

    const auto seurat_font = resolve_font(seurat_candidates, {L"seurat"});
    const auto new_rodin_font = resolve_font(new_rodin_candidates, {L"newrodin", L"new rodin"});
    const auto dfs_font = resolve_font(dfs_candidates, {L"dfsogei", L"dfheistd-w7"});

    g_title_font = new_rodin_font.has_value() ? TryLoadFont(io, *new_rodin_font, 31.0f) : nullptr;
    g_body_font = seurat_font.has_value() ? TryLoadFont(io, *seurat_font, 18.0f) : nullptr;
    g_small_font = dfs_font.has_value() ? TryLoadFont(io, *dfs_font, 15.0f) : nullptr;
    g_readable_body_font = TryLoadFont(io, R"(C:\Windows\Fonts\segoeui.ttf)", 18.0f);
    g_readable_small_font = TryLoadFont(io, R"(C:\Windows\Fonts\segoeui.ttf)", 15.0f);
    g_mono_font = TryLoadFont(io, R"(C:\Windows\Fonts\consola.ttf)", 15.0f);

    if (g_title_font == nullptr) {
        g_title_font = TryLoadFont(io, R"(C:\Windows\Fonts\segoeuib.ttf)", 31.0f);
    }
    if (g_body_font == nullptr) {
        g_body_font = TryLoadFont(io, R"(C:\Windows\Fonts\segoeuil.ttf)", 18.0f);
    }
    if (g_small_font == nullptr) {
        g_small_font = TryLoadFont(io, R"(C:\Windows\Fonts\segoeui.ttf)", 15.0f);
    }

    if (g_body_font == nullptr) {
        g_body_font = TryLoadFont(io, R"(C:\Windows\Fonts\segoeui.ttf)", 18.0f);
    }
    if (g_title_font == nullptr) {
        g_title_font = TryLoadFont(io, R"(C:\Windows\Fonts\bahnschrift.ttf)", 31.0f);
    }
    if (g_readable_body_font == nullptr) {
        g_readable_body_font = g_body_font;
    }
    if (g_readable_small_font == nullptr) {
        g_readable_small_font = g_small_font;
    }
    if (g_mono_font == nullptr) {
        g_mono_font = g_readable_small_font;
    }

    if (g_body_font == nullptr) {
        g_body_font = io.Fonts->AddFontDefault();
    }
    if (g_small_font == nullptr) {
        g_small_font = g_body_font;
    }
    if (g_title_font == nullptr) {
        g_title_font = g_body_font;
    }
    if (g_readable_body_font == nullptr) {
        g_readable_body_font = g_body_font;
    }
    if (g_readable_small_font == nullptr) {
        g_readable_small_font = g_small_font;
    }
    if (g_mono_font == nullptr) {
        g_mono_font = g_readable_small_font;
    }
    io.FontDefault = CurrentBodyFont();
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

void DrawInstallerHorizontalBorder(float min_x, float max_x, float y, bool bottom_border) {
    ImDrawList* draw_list = ImGui::GetBackgroundDrawList();
    const double border_scale = 1.0 - ComputeMotionFrames(kContainerLineAnimationDuration, kContainerLineAnimationDuration);
    const float overshoot = ShellUi(36.0f);
    const float mid_x = min_x + ((max_x - min_x) / 5.0f);
    const float animated_min_x = LerpFloat(min_x - overshoot, mid_x, static_cast<float>(border_scale));
    const float animated_max_x = LerpFloat(max_x + overshoot, mid_x, static_cast<float>(border_scale));
    const float min_y = bottom_border ? y : (y - ShellUi(1.0f));
    const float max_y = min_y + ShellUi(1.0f);
    const ImU32 solid_color = IM_COL32(155, 200, 155, 255);
    const ImU32 fade_left = IM_COL32(155, 155, 155, 0);
    const ImU32 fade_right = IM_COL32(155, 225, 155, 0);

    draw_list->AddRectFilledMultiColor(
        ImVec2(animated_min_x, min_y),
        ImVec2(mid_x, max_y),
        fade_left,
        solid_color,
        solid_color,
        fade_left
    );
    draw_list->AddRectFilledMultiColor(
        ImVec2(mid_x, min_y),
        ImVec2(animated_max_x, max_y),
        solid_color,
        fade_right,
        fade_right,
        solid_color
    );
}

void DrawInstallerVerticalBorder(float x, float min_y, float max_y, bool right_border) {
    ImDrawList* draw_list = ImGui::GetBackgroundDrawList();
    const double border_scale = 1.0 - ComputeMotionFrames(kContainerLineAnimationDuration, kContainerLineAnimationDuration);
    const float overshoot = ShellUi(36.0f);
    const float mid_y = min_y + ((max_y - min_y) * 0.5f);
    const float animated_min_y = LerpFloat(min_y - overshoot, mid_y, static_cast<float>(border_scale));
    const float animated_max_y = LerpFloat(max_y + overshoot, mid_y, static_cast<float>(border_scale));
    const float max_x = x + ShellUi(1.0f);
    const ImU32 solid_color = right_border ? IM_COL32(155, 225, 155, 255) : IM_COL32(155, 155, 155, 255);
    const ImU32 fade_color = right_border ? IM_COL32(155, 225, 155, 0) : IM_COL32(155, 155, 155, 0);

    draw_list->AddRectFilledMultiColor(
        ImVec2(x, animated_min_y),
        ImVec2(max_x, mid_y),
        fade_color,
        fade_color,
        solid_color,
        solid_color
    );
    draw_list->AddRectFilledMultiColor(
        ImVec2(x, mid_y),
        ImVec2(max_x, animated_max_y),
        solid_color,
        solid_color,
        fade_color,
        fade_color
    );
}

void DrawInstallerBorders() {
    const float full_left = ShellPoint(kInstallerContainerX - 1.0f, 0.0f).x;
    const float full_right = ShellPoint(1270.0f, 0.0f).x;
    const float top_y = ShellPoint(0.0f, kInstallerContainerY - 1.0f).y;
    const float bottom_y = ShellPoint(0.0f, kInstallerContainerY + kInstallerContainerHeight).y;
    const float split_x = ShellPoint(kInstallerContainerX + kInstallerContainerWidth, 0.0f).x;
    DrawInstallerHorizontalBorder(full_left, full_right, top_y, false);
    DrawInstallerHorizontalBorder(full_left, full_right, bottom_y, true);
    DrawInstallerVerticalBorder(full_left, top_y, bottom_y, false);
    DrawInstallerVerticalBorder(full_right, top_y, bottom_y, true);
    DrawInstallerVerticalBorder(split_x, top_y, bottom_y, true);
}

void DrawInstallerButtonContainer(const ImVec2& min, const ImVec2& max, int base_r, int base_g, float alpha) {
    ImDrawList* draw = ImGui::GetWindowDrawList();
    draw->AddRectFilledMultiColor(
        min,
        max,
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(255.0f * alpha)),
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(216.0f * alpha)),
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(255.0f * alpha)),
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(216.0f * alpha))
    );
    draw->AddRectFilledMultiColor(
        min,
        max,
        IM_COL32(base_r, base_g, 0, static_cast<int>(18.0f * alpha)),
        IM_COL32(base_r, base_g, 0, 0),
        IM_COL32(base_r, base_g, 0, static_cast<int>(66.0f * alpha)),
        IM_COL32(base_r, base_g, 0, static_cast<int>(8.0f * alpha))
    );
    draw->AddRectFilledMultiColor(
        min,
        max,
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(18.0f * alpha)),
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(132.0f * alpha)),
        IM_COL32(base_r, base_g + 130, 0, 0),
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(70.0f * alpha))
    );
    draw->AddRectFilled(
        ImVec2(min.x + ShellUi(2.0f), min.y + ShellUi(2.0f)),
        ImVec2(max.x - ShellUi(2.0f), min.y + ShellUi(8.0f)),
        IM_COL32(248, 255, 170, static_cast<int>(26.0f * alpha)),
        ShellUi(2.0f)
    );
    draw->AddRect(min, max, IM_COL32(122 + base_r, 228, 180 + base_g / 2, static_cast<int>(214.0f * alpha)), ShellUi(2.0f), 0, 1.1f);
}

void PlayHoverCueIfNeeded(bool hovered, bool enabled = true) {
    if (!enabled) {
        return;
    }

    const ImGuiID item_id = ImGui::GetItemID();
    if (hovered) {
        if (g_last_hovered_control != item_id) {
            g_last_hovered_control = item_id;
            PlayCue(UiCue::Cursor);
        }
        return;
    }

    if (g_last_hovered_control == item_id) {
        g_last_hovered_control = 0;
    }
}

void UpdateGuideInputMode() {
    const ImGuiIO& io = ImGui::GetIO();
    const bool keyboard_active =
        ImGui::IsKeyPressed(ImGuiKey_Enter, false) ||
        ImGui::IsKeyPressed(ImGuiKey_KeypadEnter, false) ||
        ImGui::IsKeyPressed(ImGuiKey_Escape, false) ||
        ImGui::IsKeyPressed(ImGuiKey_F1, false) ||
        ImGui::IsKeyPressed(ImGuiKey_F2, false) ||
        ImGui::IsKeyPressed(ImGuiKey_F3, false) ||
        ImGui::IsKeyPressed(ImGuiKey_F4, false) ||
        ImGui::IsKeyPressed(ImGuiKey_LeftArrow, false) ||
        ImGui::IsKeyPressed(ImGuiKey_RightArrow, false) ||
        ImGui::IsKeyPressed(ImGuiKey_UpArrow, false) ||
        ImGui::IsKeyPressed(ImGuiKey_DownArrow, false) ||
        ImGui::IsKeyPressed(ImGuiKey_O, false) ||
        ImGui::IsKeyPressed(ImGuiKey_R, false) ||
        ImGui::IsKeyPressed(ImGuiKey_P, false) ||
        ImGui::IsKeyPressed(ImGuiKey_L, false) ||
        ImGui::IsKeyPressed(ImGuiKey_J, false) ||
        ImGui::IsKeyPressed(ImGuiKey_Q, false) ||
        ImGui::IsKeyPressed(ImGuiKey_H, false);
    const bool mouse_active =
        ImGui::IsMouseClicked(ImGuiMouseButton_Left, false) ||
        ImGui::IsMouseClicked(ImGuiMouseButton_Right, false) ||
        std::abs(io.MouseDelta.x) > 0.0f ||
        std::abs(io.MouseDelta.y) > 0.0f;

    if (mouse_active) {
        g_guide_input_mode = GuideInputMode::Mouse;
    } else if (keyboard_active) {
        g_guide_input_mode = GuideInputMode::Keyboard;
    }
}

bool IsBackgroundInteractionBlocked() {
    return g_live_shell_state != nullptr && g_live_shell_state->prompt_visible;
}

bool DrawInstallerNavButton(const char* id, const std::string& label, ImVec2 size, bool accent = false, bool enabled = true) {
    const bool interaction_enabled = enabled && !IsBackgroundInteractionBlocked();
    const float lifecycle_alpha = ShellChromeLifecycleMotion();
    const float text_alpha = (enabled ? 1.0f : 0.5f) * lifecycle_alpha * g_shell_text_visibility;
    if (!interaction_enabled) {
        ImGui::BeginDisabled();
    }
    const bool pressed = ImGui::InvisibleButton(id, size);
    const bool hovered = interaction_enabled && ImGui::IsItemHovered();
    if (!interaction_enabled) {
        ImGui::EndDisabled();
    }

    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();
    const float alpha = (enabled ? 1.0f : 0.5f) * lifecycle_alpha;
    const int base_r = (hovered && interaction_enabled) ? 48 : (accent ? 18 : 0);
    const int base_g = (hovered && interaction_enabled) ? 32 : (accent ? 42 : 0);
    DrawInstallerButtonContainer(min, max, base_r, base_g, alpha);
    if (HasTexture(g_shell_assets.options_static)) {
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.options_static,
            min,
            max,
            ApplyAlpha(IM_COL32(126, 214, 102, accent ? 16 : 8), lifecycle_alpha),
            ShellUi(2.0f)
        );
    }
    PlayHoverCueIfNeeded(hovered, enabled);

    ImFont* font = g_body_font != nullptr ? g_body_font : (g_small_font != nullptr ? g_small_font : ImGui::GetFont());
    const float font_size =
        font == g_body_font ? std::max(ShellUi(16.0f), g_body_font->LegacySize * 0.88f) :
        (font == g_small_font ? g_small_font->LegacySize : ImGui::GetFontSize());
    const ImVec2 text_size = font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, label.c_str());
    const ImVec2 text_pos(
        min.x + ((max.x - min.x) - text_size.x) * 0.5f,
        min.y + ((max.y - min.y) - text_size.y) * 0.5f - ShellUi(1.0f)
    );
    draw->AddText(
        font,
        font_size,
        ImVec2(text_pos.x + ShellUi(1.0f), text_pos.y + ShellUi(1.0f)),
        IM_COL32(base_r, base_g, 0, static_cast<int>(255.0f * text_alpha)),
        label.c_str()
    );
    draw->AddText(font, font_size, text_pos, IM_COL32(204 + base_r / 4, 255, 0, static_cast<int>(255.0f * text_alpha)), label.c_str());

    if (pressed && interaction_enabled) {
        PlayCue(UiCue::Confirm);
    }
    return pressed && interaction_enabled;
}

void DrawInstallerLeftImage(const ShellState& state) {
    ImDrawList* draw_list = ImGui::GetBackgroundDrawList();
    const float alpha = static_cast<float>(ComputeMotionFrames(25.0, 15.0));
    const bool compact_work_surface = IsWorkDisplayMode() && IsDenseWorkScreen(state.current_screen);
    const float art_scale = compact_work_surface ? 0.68f : 1.0f;
    const ImVec2 base_min = ShellPoint(kInstallerImageX, kInstallerImageY);
    const ImVec2 base_max = ImVec2(base_min.x + ShellUi(kInstallerImageWidth), base_min.y + ShellUi(kInstallerImageHeight));
    const ImVec2 base_center((base_min.x + base_max.x) * 0.5f, (base_min.y + base_max.y) * 0.5f);
    const ImVec2 half_size((base_max.x - base_min.x) * 0.5f * art_scale, (base_max.y - base_min.y) * 0.5f * art_scale);
    const ImVec2 min(base_center.x - half_size.x, base_center.y - half_size.y);
    const ImVec2 max(base_center.x + half_size.x, base_center.y + half_size.y);

    if (!kRenderPlaceholderInstallerCharacters) {
        draw_list->AddRectFilled(min, max, IM_COL32(0, 20, 0, static_cast<int>((compact_work_surface ? 28.0f : 46.0f) * alpha)));

        if (HasTexture(g_shell_assets.general_window)) {
            DrawTexturedRect(
                draw_list,
                g_shell_assets.general_window,
                min,
                max,
                IM_COL32(86, 182, 172, static_cast<int>((compact_work_surface ? 5.0f : 10.0f) * alpha))
            );
        }
        if (HasTexture(g_shell_assets.options_static)) {
            const float time = static_cast<float>(ImGui::GetTime());
            const ImVec2 uv_min(std::fmod(time * 0.008f, 1.0f), std::fmod(time * 0.004f, 1.0f));
            const ImVec2 uv_max(
                uv_min.x + ((max.x - min.x) / std::max(1U, g_shell_assets.options_static.width)),
                uv_min.y + ((max.y - min.y) / std::max(1U, g_shell_assets.options_static.height))
            );
            DrawTexturedRect(
                draw_list,
                g_shell_assets.options_static,
                min,
                max,
                IM_COL32(112, 214, 188, static_cast<int>((compact_work_surface ? 2.0f : 7.0f) * alpha)),
                uv_min,
                uv_max
            );
        }

        const ImVec2 inner_min(min.x + ShellUi(18.0f), min.y + ShellUi(18.0f));
        const ImVec2 inner_max(max.x - ShellUi(18.0f), max.y - ShellUi(18.0f));
        draw_list->AddRect(min, max, IM_COL32(74, 140, 118, static_cast<int>(72.0f * alpha)), 0.0f, 0, 1.0f);
        draw_list->AddRect(inner_min, inner_max, IM_COL32(74, 140, 118, static_cast<int>(48.0f * alpha)), 0.0f, 0, 1.0f);

        const ImVec2 center((min.x + max.x) * 0.5f, (min.y + max.y) * 0.5f);
        const DdsTextureHandle* primary_logo = ChooseScreenPrimaryLogo(state);
        const bool has_primary_logo = primary_logo != nullptr && HasTexture(*primary_logo);
        if (has_primary_logo) {
            const float art_phase = static_cast<float>(ImGui::GetTime());
            const bool framework_phase = UsesFrameworkBrandingScreen(state.current_screen);
            const bool run_phase = ShouldShowInstallerLoadingChrome(state);
            const ImGuiIO& io = ImGui::GetIO();
            const bool art_hovered =
                io.MousePos.x >= min.x && io.MousePos.x <= max.x &&
                io.MousePos.y >= min.y && io.MousePos.y <= max.y;
            const bool art_pressed = art_hovered && ImGui::IsMouseDown(ImGuiMouseButton_Left);
            const float hover_boost = art_hovered ? 0.04f : 0.0f;
            const float click_boost = art_pressed ? 0.05f : 0.0f;
            const float logo_scale = framework_phase ? 0.78f : (run_phase ? 0.84f : 0.80f);
            const float pulse_scale = logo_scale + hover_boost + click_boost + 0.018f * std::sin((art_phase * 1.2f) + 0.4f);
            const ImVec2 base_offset =
                framework_phase
                    ? ImVec2(ShellUi(-138.0f), ShellUi(8.0f))
                    : ImVec2(ShellUi(-118.0f), ShellUi(12.0f));
            const ImVec2 motion_offset(
                base_offset.x + ShellUi((framework_phase ? 12.0f : 16.0f) * std::sin(art_phase * 0.84f)),
                base_offset.y + ShellUi((framework_phase ? 8.0f : 10.0f) * std::sin((art_phase * 1.18f) + 0.7f))
            );
            const ImVec2 glow_offset(
                motion_offset.x + ShellUi(framework_phase ? 28.0f : 34.0f),
                motion_offset.y + ShellUi(framework_phase ? -12.0f : -18.0f)
            );

            if (has_primary_logo) {
                DrawContainedTexture(
                    draw_list,
                    *primary_logo,
                    inner_min,
                    inner_max,
                    IM_COL32(255, 164, 48, static_cast<int>((framework_phase ? 38.0f : 26.0f) * alpha)),
                    pulse_scale,
                    glow_offset
                );
                DrawContainedTexture(
                    draw_list,
                    *primary_logo,
                    inner_min,
                    inner_max,
                    IM_COL32(255, 255, 255, static_cast<int>((art_hovered ? 248.0f : 236.0f) * alpha)),
                    pulse_scale,
                    motion_offset
                );
            }
        }

        if (HasTexture(g_shell_assets.arrow_circle)) {
            const bool emphasise_motion = ShouldShowInstallerLoadingChrome(state);
            DrawRotatedTexture(
                draw_list,
                g_shell_assets.arrow_circle,
                center,
                ImVec2(ShellUi(emphasise_motion ? 136.0f : 126.0f), ShellUi(emphasise_motion ? 136.0f : 126.0f)),
                static_cast<float>(ImGui::GetTime()) * (emphasise_motion ? -1.15f : -0.55f),
                IM_COL32(255, 255, 255, static_cast<int>((has_primary_logo ? 28.0f : 42.0f) * alpha))
            );
        }
        if (HasTexture(g_shell_assets.pulse_install)) {
            const float pulse_speed = ShouldShowInstallerLoadingChrome(state) ? 2.6f : 1.6f;
            const float pulse = 0.82f + 0.18f * (0.5f + 0.5f * std::sin(static_cast<float>(ImGui::GetTime()) * pulse_speed));
            DrawTexturedRectRounded(
                draw_list,
                g_shell_assets.pulse_install,
                ImVec2(center.x - ShellUi(88.0f) * pulse, center.y - ShellUi(88.0f) * pulse),
                ImVec2(center.x + ShellUi(88.0f) * pulse, center.y + ShellUi(88.0f) * pulse),
                IM_COL32(255, 255, 255, static_cast<int>((has_primary_logo ? 18.0f : 24.0f) * alpha)),
                ShellUi(18.0f)
            );
        }

        return;
    }

    const size_t index = InstallerTextureIndexForState(state);
    if (index >= g_shell_assets.install_images.size() || !HasTexture(g_shell_assets.install_images[index])) {
        return;
    }

    draw_list->AddImage(
        ToTextureId(g_shell_assets.install_images[index]),
        min,
        max,
        ImVec2(0.0f, 0.0f),
        ImVec2(1.0f, 1.0f),
        IM_COL32(255, 255, 255, static_cast<int>(255.0f * alpha))
    );
}

void DrawBackdropChrome(const ShellState& state) {
    ImDrawList* draw_list = ImGui::GetBackgroundDrawList();
    const ImVec2 display_size = ImGui::GetIO().DisplaySize;
    draw_list->AddRectFilled(ImVec2(0.0f, 0.0f), display_size, IM_COL32(0, 0, 0, 255));

    DrawInstallerLeftImage(state);

    const bool work_mode = IsWorkDisplayMode();
    const double scanline_alpha = ComputeMotionFrames(0.0, 15.0) * (work_mode ? 0.34 : 1.0);
    const float bar_height = ShellUi(work_mode ? 68.0f : 105.0f) * static_cast<float>(scanline_alpha);
    if (bar_height > 1.0f) {
        const auto draw_scanline_band = [&](float min_y, float max_y, bool top_band) {
            draw_list->AddRectFilledMultiColor(
                ImVec2(0.0f, min_y),
                ImVec2(display_size.x, max_y),
                IM_COL32(164, 204, 0, top_band ? static_cast<int>(26.0 * scanline_alpha) : static_cast<int>(84.0 * scanline_alpha)),
                IM_COL32(164, 204, 0, top_band ? static_cast<int>(26.0 * scanline_alpha) : static_cast<int>(84.0 * scanline_alpha)),
                IM_COL32(164, 204, 0, top_band ? static_cast<int>(84.0 * scanline_alpha) : static_cast<int>(26.0 * scanline_alpha)),
                IM_COL32(164, 204, 0, top_band ? static_cast<int>(84.0 * scanline_alpha) : static_cast<int>(26.0 * scanline_alpha))
            );

            const float line_step = std::max(1.0f, ShellUi(3.0f));
            for (float y = min_y; y < max_y; y += line_step) {
                const float normalized = (y - min_y) / std::max(1.0f, max_y - min_y);
                const float emphasis = top_band ? normalized : (1.0f - normalized);
                const int line_alpha = static_cast<int>((12.0f + (22.0f * emphasis)) * scanline_alpha);
                draw_list->AddRectFilled(
                    ImVec2(0.0f, y),
                    ImVec2(display_size.x, y + ShellUi(1.0f)),
                    IM_COL32(132, 172, 82, line_alpha)
                );
            }

            const float column_step = std::max(6.0f, ShellUi(24.0f));
            for (float x = 0.0f; x < display_size.x; x += column_step) {
                const int column_alpha = static_cast<int>((5.0f + (4.0f * std::sin((x / column_step) * 0.65f))) * scanline_alpha);
                draw_list->AddRectFilled(
                    ImVec2(x, min_y),
                    ImVec2(x + ShellUi(1.0f), max_y),
                    IM_COL32(173, 255, 156, std::max(0, column_alpha))
                );
            }
        };

        draw_scanline_band(0.0f, bar_height, true);
        draw_scanline_band(display_size.y - bar_height, display_size.y, false);
    }

    const auto draw_bar_line = [&](bool top) {
        const float y = top ? bar_height : (display_size.y - bar_height);
        const ImU32 top0 = IM_COL32(222, 255, 189, static_cast<int>(7.0 * scanline_alpha));
        const ImU32 top1 = IM_COL32(222, 255, 189, static_cast<int>(65.0 * scanline_alpha));
        const ImU32 bottom0 = IM_COL32(173, 255, 156, static_cast<int>(65.0 * scanline_alpha));
        const ImU32 bottom1 = IM_COL32(173, 255, 156, static_cast<int>(7.0 * scanline_alpha));
        draw_list->AddRectFilledMultiColor(
            ImVec2(0.0f, y - ShellUi(2.0f)),
            ImVec2(display_size.x, y),
            top ? top0 : bottom1,
            top ? top0 : bottom1,
            top ? top1 : bottom0,
            top ? top1 : bottom0
        );
        draw_list->AddRectFilledMultiColor(
            ImVec2(0.0f, y + ShellUi(1.0f)),
            ImVec2(display_size.x, y + ShellUi(3.0f)),
            top ? bottom0 : top1,
            top ? bottom0 : top1,
            top ? bottom1 : top0,
            top ? bottom1 : top0
        );
        draw_list->AddRectFilled(
            ImVec2(0.0f, y),
            ImVec2(display_size.x, y + ShellUi(1.0f)),
            IM_COL32(115, 178, 104, static_cast<int>(255.0 * scanline_alpha))
        );
        for (int index = 1; index <= 4; ++index) {
            const float offset = ShellUi(static_cast<float>(index) * 3.0f);
            const float line_y = top ? (y + offset) : (y - offset);
            const int line_alpha = std::max(0, static_cast<int>((38.0f - static_cast<float>(index) * 7.0f) * scanline_alpha));
            draw_list->AddRectFilled(
                ImVec2(0.0f, line_y),
                ImVec2(display_size.x, line_y + ShellUi(1.0f)),
                IM_COL32(103, 164, 94, line_alpha)
            );
        }
    };
    draw_bar_line(true);
    draw_bar_line(false);

    const float chrome_title_alpha = static_cast<float>(ComputeMotionFrames(15.0, 30.0)) * ShellExitTextVisibility(state);
    const float header_text_alpha = ShellHeaderTextLifecycleMotion() * ShellExitTextVisibility(state);
    const char* header_text = ShouldShowInstallerLoadingChrome(state) ? Tr(state, UiText::HeaderChecking) : Tr(state, UiText::HeaderPreflight);
    const DdsTextureHandle* header_icon = ChooseHeaderDebugIcon();
    if (header_icon != nullptr) {
        const float icon_base_scale = 48.0f;
        const float effect_scale = 54.0f;
        const float scale = icon_base_scale * (2.0f - chrome_title_alpha);
        const ImVec2 center = ShellPoint(246.0f, 72.0f);
        const ImVec2 min(center.x - ShellUi(scale) * 0.5f, center.y - ShellUi(scale) * 0.5f);
        const ImVec2 max(center.x + ShellUi(scale) * 0.5f, center.y + ShellUi(scale) * 0.5f);
        draw_list->AddImage(
            ToTextureId(*header_icon),
            min,
            max,
            ImVec2(0.0f, 0.0f),
            ImVec2(1.0f, 1.0f),
            IM_COL32(255, 255, 255, static_cast<int>(255.0f * chrome_title_alpha))
        );

        if (HasTexture(g_shell_assets.arrow_circle)) {
            const float rotation_speed = ShouldShowInstallerLoadingChrome(state) ? -2.1f : -1.0f;
            DrawRotatedTexture(
                draw_list,
                g_shell_assets.arrow_circle,
                center,
                ImVec2(ShellUi(effect_scale), ShellUi(effect_scale)),
                static_cast<float>(ImGui::GetTime()) * rotation_speed,
                IM_COL32(255, 255, 255, static_cast<int>(82.0 * chrome_title_alpha))
            );
        }
        if (HasTexture(g_shell_assets.pulse_install)) {
            const float pulse = 0.68f + 0.30f * (0.5f + 0.5f * std::sin(static_cast<float>(ImGui::GetTime()) * (ShouldShowInstallerLoadingChrome(state) ? 2.8f : 1.6f)));
            DrawTexturedRectRounded(
                draw_list,
                g_shell_assets.pulse_install,
                ImVec2(center.x - ShellUi(28.0f) * pulse, center.y - ShellUi(28.0f) * pulse),
                ImVec2(center.x + ShellUi(28.0f) * pulse, center.y + ShellUi(28.0f) * pulse),
                IM_COL32(255, 255, 255, static_cast<int>(36.0 * pulse * chrome_title_alpha)),
                ShellUi(20.0f)
            );
        }
    }

    if (g_title_font != nullptr) {
        const size_t header_length = std::strlen(header_text);
        const float size =
            header_length > 28U ? ShellUi(24.0f) :
            (header_length > 20U ? ShellUi(28.0f) :
            (header_length > 10U ? ShellUi(36.0f) : ShellUi(42.0f)));
        const ImVec2 pos = ShellPoint(280.0f, header_length > 20U ? 60.0f : 54.0f);
        draw_list->AddText(g_title_font, size, ImVec2(pos.x + ShellUi(3.0f), pos.y + ShellUi(3.0f)), IM_COL32(0, 0, 0, static_cast<int>(255.0f * header_text_alpha)), header_text);
        draw_list->AddText(g_title_font, size, pos, IM_COL32(255, 195, 0, static_cast<int>(255.0f * header_text_alpha)), header_text);
    }

    if (g_body_font != nullptr && kShellVersionLabel[0] != '\0') {
        const std::string version_label = std::string("v") + kShellVersionLabel;
        const float version_alpha = ShellChromeLifecycleMotion() * ShellExitTextVisibility(state);
        ImFont* version_font = g_body_font != nullptr ? g_body_font : (g_small_font != nullptr ? g_small_font : ImGui::GetFont());
        const float font_size = version_font == g_body_font ? std::max(ShellUi(14.0f), g_body_font->LegacySize * 0.74f) : (g_small_font != nullptr ? g_small_font->LegacySize : ImGui::GetFontSize());
        const ImVec2 text_size = version_font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, version_label.c_str());
        const ImVec2 pos(display_size.x - text_size.x - ShellUi(10.0f), display_size.y - text_size.y - ShellUi(7.0f));
        draw_list->AddText(
            version_font,
            font_size,
            ImVec2(pos.x + ShellUi(1.0f), pos.y + ShellUi(1.0f)),
            IM_COL32(0, 0, 0, static_cast<int>(230.0f * version_alpha)),
            version_label.c_str()
        );
        draw_list->AddText(
            version_font,
            font_size,
            pos,
            IM_COL32(173, 255, 156, static_cast<int>(255.0f * version_alpha)),
            version_label.c_str()
        );
    }
}

bool BeginDecoratedPanel(const char* id, const char* title, ImVec2 size, bool static_overlay = false) {
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0.0f, 0.0f));
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImVec4(0.0f, 0.0f, 0.0f, 0.0f));
    const bool open = ImGui::BeginChild(id, size, false, ImGuiWindowFlags_NoScrollWithMouse);

    ImDrawList* draw_list = ImGui::GetWindowDrawList();
    ImVec2 min = ImGui::GetWindowPos();
    ImVec2 max = ImVec2(min.x + ImGui::GetWindowSize().x, min.y + ImGui::GetWindowSize().y);
    const float grid = ShellUi(kPanelGrid);
    const float label_height = ShellUi(32.0f);
    const float content_pad = grid * 2.0f;

    const float container_height = static_cast<float>(ComputeMotionFrames(0.0, kContainerLineAnimationDuration));
    const float outer_alpha = static_cast<float>(ComputeMotionFrames(kContainerOuterTime, kContainerOuterDuration));
    const float inner_alpha = static_cast<float>(ComputeMotionFrames(kContainerInnerTime, kContainerInnerDuration));
    const float background_alpha = static_cast<float>(ComputeMotionFrames(kContainerBackgroundTime, kContainerBackgroundDuration));

    const float center_y = (min.y + max.y) * 0.5f;
    min.y = LerpFloat(center_y, min.y, container_height);
    max.y = LerpFloat(center_y, max.y, container_height);

    const ImU32 line_color = IM_COL32(22, 92, 90, static_cast<int>(180.0f * container_height));
    const ImU32 outer_color = IM_COL32(7, 36, 40, static_cast<int>(215.0f * outer_alpha));
    const ImU32 inner_color = IM_COL32(5, 22, 26, static_cast<int>(230.0f * inner_alpha));
    const ImU32 background_color = IM_COL32(4, 10, 12, static_cast<int>(232.0f * background_alpha));

    draw_list->AddRectFilled(min, max, background_color);
    draw_list->AddRectFilled(ImVec2(min.x, min.y + grid), ImVec2(min.x + grid, max.y - grid), outer_color);
    draw_list->AddRectFilled(ImVec2(max.x - grid, min.y + grid), ImVec2(max.x, max.y - grid), outer_color);
    draw_list->AddRectFilled(min, ImVec2(max.x, min.y + grid), outer_color);
    draw_list->AddRectFilled(ImVec2(min.x, max.y - grid), max, outer_color);
    draw_list->AddRectFilled(ImVec2(min.x + grid, min.y + grid), ImVec2(max.x - grid, max.y - grid), inner_color);
    DrawTexturedRect(
        draw_list,
        g_shell_assets.general_window,
        ImVec2(min.x + grid, min.y + grid),
        ImVec2(max.x - grid, max.y - grid),
        IM_COL32(94, 188, 176, static_cast<int>(18.0f * background_alpha))
    );

    const float line_size = std::max(1.0f, ShellUi(2.0f));
    draw_list->AddLine(ImVec2(min.x + grid, min.y + grid), ImVec2(min.x + grid, min.y + grid * 2.0f), line_color, line_size);
    draw_list->AddLine(ImVec2(min.x + grid, min.y + grid), ImVec2(max.x - grid, min.y + grid), line_color, line_size);
    draw_list->AddLine(ImVec2(max.x - grid, min.y + grid), ImVec2(max.x - grid, min.y + grid * 2.0f), line_color, line_size);
    draw_list->AddLine(ImVec2(min.x + grid, max.y - grid), ImVec2(min.x + grid, max.y - grid * 2.0f), line_color, line_size);
    draw_list->AddLine(ImVec2(min.x + grid, max.y - grid), ImVec2(max.x - grid, max.y - grid), line_color, line_size);
    draw_list->AddLine(ImVec2(max.x - grid, max.y - grid), ImVec2(max.x - grid, max.y - grid * 2.0f), line_color, line_size);

    draw_list->AddRectFilled(
        ImVec2(min.x + grid, min.y + grid),
        ImVec2(min.x + ShellUi(102.0f), min.y + grid + label_height),
        IM_COL32(23, 24, 17, static_cast<int>(248.0f * inner_alpha))
    );
    draw_list->AddLine(
        ImVec2(min.x + grid, min.y + grid + label_height + ShellUi(2.0f)),
        ImVec2(max.x - grid, min.y + grid + label_height + ShellUi(2.0f)),
        IM_COL32(32, 88, 86, static_cast<int>(94.0f * outer_alpha)),
        1.0f
    );

    if (static_overlay) {
        const ImVec2 clip_min(min.x + content_pad, min.y + label_height + grid + ShellUi(6.0f));
        const ImVec2 clip_max(max.x - content_pad, max.y - content_pad);
        draw_list->PushClipRect(clip_min, clip_max, true);
        if (HasTexture(g_shell_assets.options_static)) {
            const float time = static_cast<float>(ImGui::GetTime());
            const ImVec2 uv_min(std::fmod(time * 0.008f, 1.0f), std::fmod(time * 0.004f, 1.0f));
            const ImVec2 uv_max(
                uv_min.x + ((clip_max.x - clip_min.x) / std::max(1U, g_shell_assets.options_static.width)),
                uv_min.y + ((clip_max.y - clip_min.y) / std::max(1U, g_shell_assets.options_static.height))
            );
            DrawTexturedRect(
                draw_list,
                g_shell_assets.options_static,
                clip_min,
                clip_max,
                IM_COL32(112, 214, 188, static_cast<int>(8.0f * background_alpha)),
                uv_min,
                uv_max
            );
        }
        draw_list->PopClipRect();
    }

    if (g_small_font != nullptr) {
        draw_list->AddText(
            g_small_font,
            ShellUi(14.0f),
            ImVec2(min.x + ShellUi(10.0f), min.y + ShellUi(7.0f)),
            IM_COL32(238, 181, 42, static_cast<int>(255.0f * inner_alpha)),
            title
        );
    }

    ImGui::SetCursorPos(ImVec2(content_pad, label_height + content_pad));
    return open;
}

void EndDecoratedPanel() {
    ImGui::EndChild();
    ImGui::PopStyleColor();
    ImGui::PopStyleVar();
}

ImVec2 ShellSize(float width, float height) {
    return ImVec2(width * ShellScale(), height * ShellScale());
}

bool BeginShellPanelAt(
    const char* id,
    const char* title,
    float x,
    float y,
    float width,
    float height,
    bool static_overlay = false
) {
    ImGui::SetCursorScreenPos(ShellPoint(x, y));
    return BeginDecoratedPanel(id, title, ShellSize(width, height), static_overlay);
}

bool BeginLayoutRegionAt(const char* id, float x, float y, float width, float height) {
    ImGui::SetCursorScreenPos(ShellPoint(x, y));
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0.0f, 0.0f));
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImVec4(0.0f, 0.0f, 0.0f, 0.0f));
    return ImGui::BeginChild(
        id,
        ShellSize(width, height),
        false,
        ImGuiWindowFlags_NoBackground | ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse
    );
}

void EndLayoutRegion() {
    ImGui::EndChild();
    ImGui::PopStyleColor();
    ImGui::PopStyleVar();
}

struct InstallerCanvasLayout {
    ImVec2 description_min;
    ImVec2 description_max;
    ImVec2 side_min;
    ImVec2 side_max;
    ImVec2 description_content_min;
    ImVec2 description_content_max;
    ImVec2 side_content_min;
    ImVec2 side_content_max;
};

InstallerCanvasLayout GetInstallerCanvasLayout(
    float description_width = kInstallerContainerWidth,
    float description_pad_x = 26.0f,
    float side_pad_x = 26.0f,
    float top_pad = 18.0f,
    float side_bottom_pad = 18.0f,
    float description_bottom_reserve = 38.0f
) {
    InstallerCanvasLayout layout{};
    layout.description_min = ShellPoint(kInstallerContainerX + 0.5f, kInstallerContainerY + 0.5f);
    layout.description_max = ShellPoint(
        kInstallerContainerX + description_width + 0.5f,
        kInstallerContainerY + kInstallerContainerHeight + 0.5f
    );
    layout.side_min = ImVec2(layout.description_max.x, layout.description_min.y);
    layout.side_max = ShellPoint(1270.0f, kInstallerContainerY + kInstallerContainerHeight + 0.5f);

    const float description_horizontal_pad = ShellUi(description_pad_x);
    const float side_horizontal_pad = ShellUi(side_pad_x);
    const float resolved_top_pad = ShellUi(top_pad);
    const float resolved_side_bottom_pad = ShellUi(side_bottom_pad);
    const float resolved_description_bottom_reserve = ShellUi(description_bottom_reserve);
    layout.description_content_min = ImVec2(layout.description_min.x + description_horizontal_pad, layout.description_min.y + resolved_top_pad);
    layout.description_content_max = ImVec2(layout.description_max.x - description_horizontal_pad, layout.description_max.y - resolved_description_bottom_reserve);
    layout.side_content_min = ImVec2(layout.side_min.x + side_horizontal_pad, layout.side_min.y + resolved_top_pad);
    layout.side_content_max = ImVec2(layout.side_max.x - side_horizontal_pad, layout.side_max.y - resolved_side_bottom_pad);
    return layout;
}

InstallerCanvasLayout GetScreenCanvasLayout(ShellScreen screen) {
    const bool work_mode = IsWorkDisplayMode();
    switch (screen) {
    case ShellScreen::Introduction:
        return GetInstallerCanvasLayout(404.0f, 24.0f, 18.0f, 18.0f, 18.0f, 48.0f);
    case ShellScreen::Select:
        return GetInstallerCanvasLayout(276.0f, 16.0f, 10.0f, 16.0f, 10.0f, 46.0f);
    case ShellScreen::Review:
        return GetInstallerCanvasLayout(394.0f, 24.0f, 18.0f, 18.0f, 16.0f, 48.0f);
    case ShellScreen::Run:
        return work_mode
            ? GetInstallerCanvasLayout(440.0f, 22.0f, 14.0f, 16.0f, 12.0f, 18.0f)
            : GetInstallerCanvasLayout(376.0f, 20.0f, 14.0f, 18.0f, 12.0f, 18.0f);
    case ShellScreen::Evidence:
        return work_mode
            ? GetInstallerCanvasLayout(432.0f, 22.0f, 14.0f, 16.0f, 12.0f, 18.0f)
            : GetInstallerCanvasLayout(386.0f, 20.0f, 14.0f, 18.0f, 12.0f, 18.0f);
    case ShellScreen::Files:
        return work_mode
            ? GetInstallerCanvasLayout(424.0f, 22.0f, 14.0f, 16.0f, 12.0f, 18.0f)
            : GetInstallerCanvasLayout(376.0f, 20.0f, 14.0f, 18.0f, 12.0f, 18.0f);
    case ShellScreen::Environment:
        return work_mode
            ? GetInstallerCanvasLayout(420.0f, 22.0f, 14.0f, 16.0f, 12.0f, 18.0f)
            : GetInstallerCanvasLayout(382.0f, 20.0f, 14.0f, 18.0f, 12.0f, 18.0f);
    case ShellScreen::Stages:
        return work_mode
            ? GetInstallerCanvasLayout(414.0f, 22.0f, 14.0f, 16.0f, 12.0f, 18.0f)
            : GetInstallerCanvasLayout(390.0f, 20.0f, 14.0f, 18.0f, 12.0f, 18.0f);
    case ShellScreen::Language:
    default:
        return GetInstallerCanvasLayout();
    }
}

void DrawInstallerCanvasSurface(const ImVec2& min, const ImVec2& max, bool text_area) {
    ImDrawList* draw_list = ImGui::GetBackgroundDrawList();
    const float outer_alpha = static_cast<float>(ComputeMotionFrames(kContainerOuterTime, kContainerOuterDuration));
    const float inner_alpha = static_cast<float>(ComputeMotionFrames(kContainerInnerTime, kContainerInnerDuration));
    const float background_alpha = static_cast<float>(ComputeMotionFrames(kContainerBackgroundTime, kContainerBackgroundDuration));
    const bool work_mode = IsWorkDisplayMode();
    const ImU32 background = IM_COL32(
        0,
        work_mode ? 26 : 33,
        0,
        static_cast<int>(((text_area ? (work_mode ? 242.0f : 223.0f) : (work_mode ? 255.0f : 255.0f))) * background_alpha)
    );
    const ImU32 overlay = IM_COL32(
        0,
        work_mode ? 24 : 32,
        0,
        static_cast<int>(((text_area ? (work_mode ? 76.0f : 128.0f) : (work_mode ? 48.0f : 82.0f))) * inner_alpha)
    );

    draw_list->AddRectFilled(min, max, background);
    draw_list->AddRectFilled(min, max, overlay);

    if (HasTexture(g_shell_assets.general_window)) {
        DrawTexturedRect(
            draw_list,
            g_shell_assets.general_window,
            min,
            max,
            IM_COL32(86, 182, 172, static_cast<int>(((work_mode ? 6.0f : 14.0f)) * outer_alpha))
        );
    }

    if (HasTexture(g_shell_assets.options_static)) {
        const float time = static_cast<float>(ImGui::GetTime());
        const ImVec2 uv_min(std::fmod(time * 0.008f, 1.0f), std::fmod(time * 0.004f, 1.0f));
        const ImVec2 uv_max(
            uv_min.x + ((max.x - min.x) / std::max(1U, g_shell_assets.options_static.width)),
            uv_min.y + ((max.y - min.y) / std::max(1U, g_shell_assets.options_static.height))
        );
        DrawTexturedRect(
            draw_list,
            g_shell_assets.options_static,
            min,
            max,
            IM_COL32(112, 214, 188, static_cast<int>(((text_area ? (work_mode ? 3.0f : 12.0f) : (work_mode ? 2.0f : 8.0f))) * background_alpha)),
            uv_min,
            uv_max
        );
    }

    const float grid_step = ShellUi(12.0f);
    const ImU32 grid_major = IM_COL32(96, 180, 94, static_cast<int>(((text_area ? (work_mode ? 18.0f : 34.0f) : (work_mode ? 14.0f : 28.0f))) * inner_alpha));
    const ImU32 grid_minor = IM_COL32(76, 138, 74, static_cast<int>(((text_area ? (work_mode ? 8.0f : 18.0f) : (work_mode ? 6.0f : 14.0f))) * inner_alpha));
    for (float x = min.x; x <= max.x; x += grid_step) {
        const int index = static_cast<int>((x - min.x) / grid_step);
        draw_list->AddLine(ImVec2(x, min.y), ImVec2(x, max.y), (index % 4) == 0 ? grid_major : grid_minor, 1.0f);
    }
    for (float y = min.y; y <= max.y; y += grid_step) {
        const int index = static_cast<int>((y - min.y) / grid_step);
        draw_list->AddLine(ImVec2(min.x, y), ImVec2(max.x, y), (index % 4) == 0 ? grid_major : grid_minor, 1.0f);
    }
}

void DrawInstallerCanvasBackground(const InstallerCanvasLayout& layout = GetInstallerCanvasLayout()) {
    DrawInstallerCanvasSurface(layout.description_min, layout.description_max, true);
    DrawInstallerCanvasSurface(layout.side_min, layout.side_max, false);
}

bool BeginCanvasOverlayRegion(const char* id, const ImVec2& min, const ImVec2& max) {
    ImGui::SetCursorScreenPos(min);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0.0f, 0.0f));
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImVec4(0.0f, 0.0f, 0.0f, 0.0f));
    return ImGui::BeginChild(
        id,
        ImVec2(max.x - min.x, max.y - min.y),
        false,
        ImGuiWindowFlags_NoBackground | ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse
    );
}

void EndCanvasOverlayRegion() {
    ImGui::EndChild();
    ImGui::PopStyleColor();
    ImGui::PopStyleVar();
}

bool BeginCanvasOverlayWindow(const char* id, const ImVec2& min, const ImVec2& max) {
    ImGui::SetNextWindowPos(min);
    ImGui::SetNextWindowSize(ImVec2(max.x - min.x, max.y - min.y));
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0.0f, 0.0f));
    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
    ImGui::PushStyleColor(ImGuiCol_WindowBg, ImVec4(0.0f, 0.0f, 0.0f, 0.0f));
    return ImGui::Begin(
        id,
        nullptr,
        ImGuiWindowFlags_NoDecoration
        | ImGuiWindowFlags_NoMove
        | ImGuiWindowFlags_NoSavedSettings
        | ImGuiWindowFlags_NoBackground
        | ImGuiWindowFlags_NoScrollbar
        | ImGuiWindowFlags_NoScrollWithMouse
        | ImGuiWindowFlags_NoFocusOnAppearing
    );
}

void EndCanvasOverlayWindow() {
    ImGui::End();
    ImGui::PopStyleColor();
    ImGui::PopStyleVar(2);
}

void DrawCanvasPageTitle(const char* text, float wrap_x) {
    if (g_body_font != nullptr) {
        ImGui::PushFont(g_body_font);
    }
    ImGui::PushTextWrapPos(wrap_x);
    ImGui::TextWrapped("%s", text);
    ImGui::PopTextWrapPos();
    if (g_body_font != nullptr) {
        ImGui::PopFont();
    }
}

bool DrawPanelButton(const char* id, const std::string& label, ImVec2 size, bool accent = false, bool enabled = true) {
    const bool interaction_enabled = enabled && !IsBackgroundInteractionBlocked();
    const float lifecycle_alpha = ShellChromeLifecycleMotion();
    if (!interaction_enabled) {
        ImGui::BeginDisabled();
    }
    const bool pressed = ImGui::InvisibleButton(id, size);
    const bool hovered = interaction_enabled && ImGui::IsItemHovered();
    if (!interaction_enabled) {
        ImGui::EndDisabled();
    }

    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();
    const ImU32 bg = ApplyAlpha(
        accent
            ? IM_COL32(18, 120, 16, hovered ? 234 : 220)
            : IM_COL32(8, 52, 14, hovered ? 220 : 204),
        lifecycle_alpha
    );
    const ImU32 border = ApplyAlpha(accent ? IM_COL32(168, 255, 198, 214) : IM_COL32(100, 180, 124, 188), lifecycle_alpha);
    const ImU32 text = ApplyAlpha(interaction_enabled ? IM_COL32(236, 246, 239, 255) : IM_COL32(114, 134, 127, 255), lifecycle_alpha);
    PlayHoverCueIfNeeded(hovered, interaction_enabled);

    draw->AddRectFilled(min, max, bg, ShellUi(4.0f));
    DrawSelectionContainerChrome(draw, min, max, lifecycle_alpha * (hovered || accent ? 1.0f : 0.74f), false);
    if (HasTexture(g_shell_assets.options_static)) {
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.options_static,
            min,
            max,
            ApplyAlpha(IM_COL32(114, 210, 102, accent ? 22 : 14), lifecycle_alpha),
            ShellUi(4.0f)
        );
    }
    draw->AddRect(min, max, border, ShellUi(4.0f), 0, 1.1f);

    if (g_small_font != nullptr) {
        const ImVec2 text_size = g_small_font->CalcTextSizeA(g_small_font->LegacySize, FLT_MAX, 0.0f, label.c_str());
        const ImVec2 text_pos(
            min.x + ((max.x - min.x) - text_size.x) * 0.5f,
            min.y + ((max.y - min.y) - text_size.y) * 0.5f
        );
        draw->AddText(g_small_font, g_small_font->LegacySize, text_pos, ApplyAlpha(text, g_shell_text_visibility), label.c_str());
    }

    if (pressed && interaction_enabled) {
        PlayCue(UiCue::Confirm);
    }
    return pressed && interaction_enabled;
}

bool DrawGuideButton(const char* id, const char* key, const char* label, bool enabled) {
    const ImVec2 start = ImGui::GetCursorScreenPos();
    const ImVec2 size(165.0f, 30.0f);
    const bool interaction_enabled = enabled && !IsBackgroundInteractionBlocked();
    if (!interaction_enabled) {
        ImGui::BeginDisabled();
    }
    const bool pressed = ImGui::InvisibleButton(id, size);
    const bool hovered = interaction_enabled && ImGui::IsItemHovered();
    if (!interaction_enabled) {
        ImGui::EndDisabled();
    }
    PlayHoverCueIfNeeded(hovered, interaction_enabled);
    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();
    draw->AddRectFilled(min, max, hovered ? IM_COL32(24, 75, 55, 235) : IM_COL32(17, 50, 38, 235), 4.0f);
    draw->AddRect(min, max, IM_COL32(89, 175, 123, 180), 4.0f);
    draw->AddRectFilled(ImVec2(min.x + 6.0f, min.y + 5.0f), ImVec2(min.x + 30.0f, max.y - 5.0f), IM_COL32(21, 20, 18, 255), 3.0f);
    draw->AddRect(ImVec2(min.x + 6.0f, min.y + 5.0f), ImVec2(min.x + 30.0f, max.y - 5.0f), IM_COL32(255, 188, 0, 210), 3.0f);
    if (g_small_font != nullptr) {
        draw->AddText(g_small_font, g_small_font->LegacySize, ImVec2(min.x + 13.0f, min.y + 7.0f), IM_COL32(255, 188, 0, 255), key);
        draw->AddText(g_small_font, g_small_font->LegacySize, ImVec2(min.x + 40.0f, min.y + 7.0f), interaction_enabled ? IM_COL32(235, 244, 239, 255) : IM_COL32(122, 134, 127, 255), label);
    }
    ImGui::SetCursorScreenPos(ImVec2(start.x + size.x + 8.0f, start.y));
    if (pressed && interaction_enabled) {
        PlayCue(UiCue::Confirm);
    }
    return pressed && interaction_enabled;
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
    const bool interaction_enabled = !IsBackgroundInteractionBlocked();
    const float lifecycle_alpha = ShellChromeLifecycleMotion();
    const float text_alpha = lifecycle_alpha * g_shell_text_visibility;
    if (!interaction_enabled) {
        ImGui::BeginDisabled();
    }
    const bool pressed = ImGui::InvisibleButton(id, size);
    const bool hovered = interaction_enabled && ImGui::IsItemHovered();
    if (!interaction_enabled) {
        ImGui::EndDisabled();
    }
    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();
    const bool work_mode = IsWorkDisplayMode();

    const float pulse = 0.5f + 0.5f * std::sin(static_cast<float>(ImGui::GetTime()) * 3.2f);
    const int base_r = selected || hovered ? 48 : 0;
    const int base_g = selected ? 32 : (hovered ? 18 : 0);
    PlayHoverCueIfNeeded(hovered, interaction_enabled);
    DrawInstallerButtonContainer(min, max, base_r, base_g, lifecycle_alpha);
    draw->AddRect(
        min,
        max,
        ApplyAlpha(
            selected
                ? (work_mode
                    ? IM_COL32(162, 214, 188, static_cast<int>(188.0f + 14.0f * pulse))
                    : IM_COL32(140, 236, 204, static_cast<int>(210.0f + 22.0f * pulse)))
                : IM_COL32(120, 174, 150, hovered ? 178 : 132),
            lifecycle_alpha
        ),
        ShellUi(4.0f),
        0,
        selected ? 1.4f : 1.0f
    );

    if (selected) {
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.select,
            min,
            max,
            ApplyAlpha(IM_COL32(102, 222, 168, static_cast<int>(((work_mode ? 26.0f : 52.0f) + 12.0f * pulse))), lifecycle_alpha),
            ShellUi(4.0f)
        );
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.light,
            ImVec2(min.x, min.y - ShellUi(2.0f)),
            ImVec2(max.x, min.y + (max.y - min.y) * 0.42f),
            ApplyAlpha(IM_COL32(240, 225, 146, 28), lifecycle_alpha),
            ShellUi(4.0f)
        );
    }

    const ImVec2 light_min(min.x + ShellUi(9.0f), min.y + ShellUi(10.0f));
    const ImVec2 light_max(min.x + ShellUi(22.0f), max.y - ShellUi(10.0f));
    const float card_width = max.x - min.x;
    const size_t title_budget = static_cast<size_t>(std::clamp((card_width - ShellUi(44.0f)) / ShellUi(8.1f), 18.0f, 60.0f));
    const size_t subtitle_budget = static_cast<size_t>(std::clamp((card_width - ShellUi(44.0f)) / ShellUi(8.8f), 16.0f, 54.0f));
    const size_t detail_budget = static_cast<size_t>(std::clamp((card_width - ShellUi(44.0f)) / ShellUi(8.4f), 24.0f, 78.0f));
    const std::string display_title = Ellipsize(title, title_budget);
    const std::string display_subtitle = Ellipsize(subtitle, subtitle_budget);
    draw->AddRectFilled(
        light_min,
        light_max,
        ApplyAlpha(selected ? IM_COL32(255, 188, 0, 255) : IM_COL32(64, 106, 84, hovered ? 190 : 142), lifecycle_alpha),
        ShellUi(2.0f)
    );
    draw->AddRect(
        light_min,
        light_max,
        ApplyAlpha(selected ? IM_COL32(255, 222, 130, 220) : IM_COL32(104, 154, 128, hovered ? 176 : 124), lifecycle_alpha),
        ShellUi(2.0f),
        0,
        1.0f
    );

    const float text_x = min.x + ShellUi(32.0f);
    if (ImFont* body_font = CurrentBodyFont(); body_font != nullptr) {
        const float body_font_size = body_font == g_body_font ? g_body_font->LegacySize : body_font->LegacySize;
        draw->AddText(body_font, body_font_size, ImVec2(text_x, min.y + ShellUi(9.0f)), ApplyAlpha(IM_COL32(240, 247, 243, 255), text_alpha), display_title.c_str());
    }
    if (!subtitle.empty() && CurrentSmallFont() != nullptr) {
        draw->AddText(CurrentSmallFont(), CurrentSmallFont()->LegacySize, ImVec2(text_x, min.y + ShellUi(30.0f)), ApplyAlpha(IM_COL32(255, 188, 0, work_mode ? 245 : 220), text_alpha), display_subtitle.c_str());
    }
    if (!detail.empty() && CurrentSmallFont() != nullptr) {
        draw->AddText(
            CurrentSmallFont(),
            CurrentSmallFont()->LegacySize,
            ImVec2(text_x, min.y + ShellUi(47.0f)),
            ApplyAlpha(work_mode ? IM_COL32(208, 224, 214, 232) : IM_COL32(169, 190, 180, 220), text_alpha),
            Ellipsize(detail, detail_budget).c_str()
        );
    }

    if (pressed && interaction_enabled) {
        PlayCue(UiCue::Confirm);
    }
    return pressed && interaction_enabled;
}

bool DrawLanguageOptionButton(const char* id, const char* label, bool selected, ImVec2 size) {
    const bool interaction_enabled = !IsBackgroundInteractionBlocked();
    const float lifecycle_alpha = ShellChromeLifecycleMotion();
    const float text_alpha = lifecycle_alpha * g_shell_text_visibility;
    if (!interaction_enabled) {
        ImGui::BeginDisabled();
    }
    const bool pressed = ImGui::InvisibleButton(id, size);
    const bool hovered = interaction_enabled && ImGui::IsItemHovered();
    if (!interaction_enabled) {
        ImGui::EndDisabled();
    }
    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();

    const int base_r = selected || hovered ? 48 : 0;
    const int base_g = selected ? 32 : (hovered ? 18 : 0);
    DrawInstallerButtonContainer(min, max, base_r, base_g, lifecycle_alpha);
    PlayHoverCueIfNeeded(hovered, interaction_enabled);

    const ImVec2 indicator_min(min.x + ShellUi(10.0f), min.y + ShellUi(8.0f));
    const ImVec2 indicator_max(min.x + ShellUi(22.0f), max.y - ShellUi(8.0f));
    draw->AddRectFilled(
        indicator_min,
        indicator_max,
        ApplyAlpha(selected ? IM_COL32(255, 188, 0, 255) : IM_COL32(64, 106, 84, hovered ? 190 : 142), lifecycle_alpha),
        ShellUi(2.0f)
    );
    draw->AddRect(
        indicator_min,
        indicator_max,
        ApplyAlpha(selected ? IM_COL32(255, 222, 130, 220) : IM_COL32(104, 154, 128, hovered ? 176 : 124), lifecycle_alpha),
        ShellUi(2.0f),
        0,
        1.0f
    );

    ImFont* font = g_body_font != nullptr ? g_body_font : ImGui::GetFont();
    const float font_size = font == g_body_font ? g_body_font->LegacySize : ImGui::GetFontSize();
    const ImVec2 text_size = font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, label);
    const ImVec2 text_pos(
        min.x + ((max.x - min.x) - text_size.x) * 0.5f + ShellUi(6.0f),
        min.y + ((max.y - min.y) - text_size.y) * 0.5f - ShellUi(1.0f)
    );
    draw->AddText(font, font_size, text_pos, ApplyAlpha(IM_COL32(245, 245, 235, 255), text_alpha), label);

    if (pressed && interaction_enabled) {
        PlayCue(UiCue::Confirm);
    }
    return pressed && interaction_enabled;
}

void DrawProgressMeter(float progress, const std::string& label) {
    const ImVec2 size(ImGui::GetContentRegionAvail().x, 22.0f);
    const ImVec2 start = ImGui::GetCursorScreenPos();
    ImGui::InvisibleButton("##progress-meter", size);
    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();
    const float width = (max.x - min.x) * Saturate(progress);
    const float lifecycle_alpha = ShellChromeLifecycleMotion();
    const float text_alpha = lifecycle_alpha * g_shell_text_visibility;
    draw->AddRectFilled(min, max, ApplyAlpha(IM_COL32(8, 18, 20, 255), lifecycle_alpha), 3.0f);
    DrawTexturedRectRounded(
        draw,
        g_shell_assets.general_window,
        min,
        max,
        ApplyAlpha(IM_COL32(106, 240, 172, 72), lifecycle_alpha),
        ShellUi(3.0f)
    );
    draw->AddRect(min, max, ApplyAlpha(IM_COL32(55, 109, 114, 210), lifecycle_alpha), 3.0f);
    draw->AddRectFilledMultiColor(
        min,
        ImVec2(min.x + width, max.y),
        ApplyAlpha(IM_COL32(48, 184, 168, 255), lifecycle_alpha),
        ApplyAlpha(IM_COL32(207, 222, 90, 255), lifecycle_alpha),
        ApplyAlpha(IM_COL32(48, 184, 168, 235), lifecycle_alpha),
        ApplyAlpha(IM_COL32(207, 222, 90, 235), lifecycle_alpha)
    );
    DrawTexturedRectRounded(
        draw,
        g_shell_assets.select,
        min,
        ImVec2(min.x + width, max.y),
        ApplyAlpha(IM_COL32(132, 232, 180, 92), lifecycle_alpha),
        ShellUi(3.0f),
        ImVec2(0.0f, 0.0f),
        ImVec2(std::max(0.12f, progress * 3.2f), 1.0f)
    );
    DrawTexturedRectRounded(
        draw,
        g_shell_assets.light,
        ImVec2(min.x, min.y - ShellUi(4.0f)),
        ImVec2(min.x + width, max.y + ShellUi(4.0f)),
        ApplyAlpha(IM_COL32(240, 225, 146, 34), lifecycle_alpha),
        ShellUi(3.0f)
    );
    for (float x = min.x; x < min.x + width; x += 12.0f) {
        draw->AddLine(ImVec2(x, min.y + 1.0f), ImVec2(x + 8.0f, max.y - 1.0f), ApplyAlpha(IM_COL32(255, 255, 255, 25), lifecycle_alpha), 1.0f);
    }
    if (g_small_font != nullptr) {
        draw->AddText(g_small_font, g_small_font->LegacySize, ImVec2(min.x + 10.0f, min.y + 3.0f), ApplyAlpha(IM_COL32(8, 13, 11, 240), text_alpha), label.c_str());
    }
    ImGui::SetCursorScreenPos(ImVec2(start.x, start.y + size.y + 6.0f));
}

void InlineSectionLabel(const char* text) {
    ImFont* font = CurrentSmallFont();
    if (font != nullptr) {
        ImGui::PushFont(font);
    }
    ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", text);
    if (font != nullptr) {
        ImGui::PopFont();
    }
    ImGui::Separator();
}

ImVec4 EnvironmentStateColor(std::string_view state) {
    std::string lowered(state);
    std::transform(
        lowered.begin(),
        lowered.end(),
        lowered.begin(),
        [](unsigned char character) { return static_cast<char>(std::tolower(character)); }
    );
    if (lowered == "ready" || lowered == "covered") {
        return ImVec4(0.52f, 0.92f, 0.63f, 1.0f);
    }
    if (lowered == "partial" || lowered == "manual") {
        return ImVec4(0.95f, 0.78f, 0.25f, 1.0f);
    }
    if (lowered == "missing" || lowered == "blocked") {
        return ImVec4(0.95f, 0.46f, 0.34f, 1.0f);
    }
    return ImVec4(0.78f, 0.84f, 0.88f, 1.0f);
}

void DrawReadonlyTextBox(const char* id, const std::string& text, bool monospace = false, float height = 0.0f) {
    std::vector<char> buffer(text.begin(), text.end());
    buffer.push_back('\0');
    if (monospace) {
        if (ImFont* font = CurrentMonoFont(); font != nullptr) {
            ImGui::PushFont(font);
        }
    }
    ImGui::PushStyleColor(
        ImGuiCol_FrameBg,
        IsWorkDisplayMode() ? ImVec4(0.05f, 0.08f, 0.10f, 0.92f) : ImVec4(0.04f, 0.07f, 0.08f, 0.88f)
    );
    const ImVec2 size = height > 0.0f
        ? ImVec2(0.0f, height)
        : ImVec2(0.0f, ImGui::GetTextLineHeightWithSpacing() * (monospace ? 5.0f : 1.8f));
    ImGui::InputTextMultiline(id, buffer.data(), buffer.size(), size, ImGuiInputTextFlags_ReadOnly);
    ImGui::PopStyleColor();
    if (monospace) {
        if (CurrentMonoFont() != nullptr) {
            ImGui::PopFont();
        }
    }
}

float ScreenTransitionMotion(const ShellState& state) {
    if (state.screen_transition_started_at < 0.0) {
        return 1.0f;
    }
    const double frames = (ImGui::GetTime() - state.screen_transition_started_at) * 60.0;
    return SmoothStep(static_cast<float>(std::sqrt(std::clamp(frames / 23.0, 0.0, 1.0))));
}

float ShellTextLifecycleMotion() {
    return static_cast<float>(ComputeMotionFramesAsymmetric(
        kContainerInnerTime,
        kContainerInnerDuration,
        0.0,
        8.0
    ));
}

float ShellChromeLifecycleMotion() {
    constexpr double kChromeDisappearDelayFrames = kContainerLineAnimationDuration;
    return static_cast<float>(ComputeMotionFramesAsymmetric(
        kContainerInnerTime,
        kContainerInnerDuration,
        kChromeDisappearDelayFrames,
        kContainerInnerDuration
    ));
}

float ShellHeaderTextLifecycleMotion() {
    return static_cast<float>(ComputeMotionFramesAsymmetric(
        15.0,
        30.0,
        0.0,
        8.0
    ));
}

float ShellExitTextVisibility(const ShellState& state) {
    if (!state.exit_transition_active || state.exit_transition_started_at < 0.0) {
        return 1.0f;
    }
    const double elapsed_frames = (ImGui::GetTime() - state.exit_transition_started_at) * 60.0;
    return 1.0f - SmoothStep(static_cast<float>(std::clamp(elapsed_frames / 1.0, 0.0, 1.0)));
}

float ShellTransitionAlpha(float motion) {
    return 0.18f + 0.82f * motion;
}

void BeginScreenTransition(const ShellState& state) {
    const float motion = ScreenTransitionMotion(state) * ShellChromeLifecycleMotion();
    const ImVec2 cursor = ImGui::GetCursorPos();
    ImGui::SetCursorPos(ImVec2(cursor.x + (1.0f - motion) * ShellUi(52.0f), cursor.y + (1.0f - motion) * ShellUi(4.0f)));
    ImGui::PushStyleVar(ImGuiStyleVar_Alpha, ShellTransitionAlpha(motion));
}

void EndScreenTransition() {
    ImGui::PopStyleVar();
}

void BeginScreenTextTransition(const ShellState& state) {
    const float screen_motion = ScreenTransitionMotion(state);
    const float chrome_alpha = ShellTransitionAlpha(screen_motion * ShellChromeLifecycleMotion());
    const float text_alpha = ShellTransitionAlpha(screen_motion * ShellTextLifecycleMotion());
    const float relative_alpha = chrome_alpha > 0.001f
        ? std::clamp((text_alpha / chrome_alpha) * ShellExitTextVisibility(state), 0.0f, 1.0f)
        : 0.0f;
    ImGui::PushStyleVar(ImGuiStyleVar_Alpha, relative_alpha);
}

void EndScreenTextTransition() {
    ImGui::PopStyleVar();
}

bool DrawSettingToggle(
    const char* id,
    const std::string& label,
    const std::string& summary,
    bool value
) {
    const float height = ShellUi(82.0f);
    const ImVec2 size(ImGui::GetContentRegionAvail().x, height);
    const bool interaction_enabled = !IsBackgroundInteractionBlocked();
    const float lifecycle_alpha = ShellChromeLifecycleMotion();
    const float text_alpha = lifecycle_alpha * g_shell_text_visibility;
    const bool work_mode = IsWorkDisplayMode();
    if (!interaction_enabled) {
        ImGui::BeginDisabled();
    }
    const bool pressed = ImGui::InvisibleButton(id, size);
    const bool hovered = interaction_enabled && ImGui::IsItemHovered();
    if (!interaction_enabled) {
        ImGui::EndDisabled();
    }
    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();
    const ImU32 border = ApplyAlpha(value ? IM_COL32(122, 255, 168, 208) : IM_COL32(67, 128, 113, hovered ? 196 : 160), lifecycle_alpha);
    PlayHoverCueIfNeeded(hovered, interaction_enabled);

    draw->AddRectFilled(min, max, ApplyAlpha(hovered ? IM_COL32(11, 26, 29, 234) : IM_COL32(8, 17, 19, 228), lifecycle_alpha), ShellUi(4.0f));
    DrawTexturedRectRounded(
        draw,
        g_shell_assets.general_window,
        min,
        max,
        ApplyAlpha(value ? IM_COL32(102, 226, 168, work_mode ? 42 : 92) : IM_COL32(72, 160, 120, work_mode ? 20 : 42), lifecycle_alpha),
        ShellUi(4.0f)
    );
    draw->AddRect(min, max, border, ShellUi(4.0f), 0, 1.1f);

    const ImVec2 toggle_min(max.x - ShellUi(102.0f), min.y + ShellUi(21.0f));
    const ImVec2 toggle_max(max.x - ShellUi(24.0f), min.y + ShellUi(53.0f));
    draw->AddRectFilled(toggle_min, toggle_max, ApplyAlpha(value ? IM_COL32(30, 118, 66, 240) : IM_COL32(18, 32, 36, 240), lifecycle_alpha), ShellUi(16.0f));
    draw->AddRect(toggle_min, toggle_max, ApplyAlpha(value ? IM_COL32(130, 255, 147, 220) : IM_COL32(78, 110, 104, 210), lifecycle_alpha), ShellUi(16.0f), 0, 1.0f);
    if (value) {
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.select,
            toggle_min,
            toggle_max,
            ApplyAlpha(IM_COL32(130, 255, 122, 118), lifecycle_alpha),
            ShellUi(16.0f)
        );
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.light,
            ImVec2(toggle_min.x - ShellUi(4.0f), toggle_min.y - ShellUi(6.0f)),
            ImVec2(toggle_max.x + ShellUi(4.0f), toggle_max.y + ShellUi(6.0f)),
            ApplyAlpha(IM_COL32(225, 255, 188, 76), lifecycle_alpha),
            ShellUi(16.0f)
        );
    }
    const float knob_radius = ShellUi(11.0f);
    const float knob_x = value ? toggle_max.x - ShellUi(20.0f) : toggle_min.x + ShellUi(20.0f);
    draw->AddCircleFilled(ImVec2(knob_x, (toggle_min.y + toggle_max.y) * 0.5f), knob_radius, ApplyAlpha(IM_COL32(235, 243, 239, 255), lifecycle_alpha), 24);

    if (ImFont* body_font = CurrentBodyFont(); body_font != nullptr) {
        draw->AddText(body_font, body_font->LegacySize, ImVec2(min.x + ShellUi(18.0f), min.y + ShellUi(14.0f)), ApplyAlpha(IM_COL32(237, 245, 241, 255), text_alpha), label.c_str());
    }
    if (ImFont* small_font = CurrentSmallFont(); small_font != nullptr) {
        draw->AddText(small_font, small_font->LegacySize, ImVec2(min.x + ShellUi(18.0f), min.y + ShellUi(40.0f)), ApplyAlpha(work_mode ? IM_COL32(198, 216, 208, 236) : IM_COL32(167, 189, 180, 220), text_alpha), summary.c_str());
        draw->AddText(small_font, small_font->LegacySize, ImVec2(toggle_min.x, min.y + ShellUi(58.0f)), ApplyAlpha(value ? IM_COL32(255, 188, 0, 240) : IM_COL32(136, 152, 148, 220), text_alpha), value ? "ON" : "OFF");
    }

    if (pressed && interaction_enabled) {
        PlayCue(UiCue::Confirm);
    }
    return pressed && interaction_enabled;
}

void DrawInstallerHero(ImVec2 top_left, ImVec2 size, float alpha, bool animated = true) {
    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = top_left;
    const ImVec2 max(top_left.x + size.x, top_left.y + size.y);
    draw->AddRectFilled(min, max, IM_COL32(7, 13, 16, static_cast<int>(192.0f * alpha)), ShellUi(4.0f));
    draw->AddRect(min, max, IM_COL32(56, 108, 112, static_cast<int>(160.0f * alpha)), ShellUi(4.0f), 0, 1.0f);
    draw->AddRectFilledMultiColor(
        ImVec2(min.x + ShellUi(14.0f), min.y + ShellUi(14.0f)),
        ImVec2(max.x - ShellUi(14.0f), max.y - ShellUi(14.0f)),
        IM_COL32(15, 34, 38, static_cast<int>(168.0f * alpha)),
        IM_COL32(10, 23, 28, static_cast<int>(168.0f * alpha)),
        IM_COL32(5, 12, 14, static_cast<int>(206.0f * alpha)),
        IM_COL32(5, 12, 14, static_cast<int>(206.0f * alpha))
    );

    if (animated) {
        const ImVec2 center(max.x - size.x * 0.26f, min.y + size.y * 0.46f);
        const float pulse = 0.72f + 0.28f * std::sin(static_cast<float>(ImGui::GetTime()) * 1.8f);
        const float angle = static_cast<float>(ImGui::GetTime()) * 0.72f;
        DrawRotatedTexture(
            draw,
            g_shell_assets.arrow_circle,
            center,
            ImVec2(size.y * 0.34f, size.y * 0.34f),
            angle,
            IM_COL32(236, 181, 42, static_cast<int>(152.0f * alpha))
        );
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.pulse_install,
            ImVec2(center.x - size.y * 0.20f * pulse, center.y - size.y * 0.20f * pulse),
            ImVec2(center.x + size.y * 0.20f * pulse, center.y + size.y * 0.20f * pulse),
            IM_COL32(112, 214, 188, static_cast<int>(22.0f * alpha * pulse)),
            ShellUi(12.0f)
        );
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.light,
            ImVec2(center.x - size.y * 0.72f, min.y + ShellUi(18.0f)),
            ImVec2(max.x - ShellUi(22.0f), min.y + size.y * 0.40f),
            IM_COL32(240, 225, 146, static_cast<int>(18.0f * alpha)),
            ShellUi(8.0f)
        );
    }

    const float time = static_cast<float>(ImGui::GetTime());
    for (float y = min.y + ShellUi(18.0f); y < max.y; y += ShellUi(28.0f)) {
        const float wobble = std::sin((time * 0.8f) + y * 0.03f) * ShellUi(7.0f);
        draw->AddBezierCubic(
            ImVec2(min.x + ShellUi(12.0f), y),
            ImVec2(min.x + size.x * 0.34f, y - ShellUi(8.0f) + wobble),
            ImVec2(min.x + size.x * 0.66f, y + ShellUi(8.0f) - wobble),
            ImVec2(max.x - ShellUi(12.0f), y),
            IM_COL32(128, 202, 194, static_cast<int>(10.0f * alpha)),
            1.0f
        );
    }
}

void RenderLocalStatePanel(
    ShellState& state,
    const char* id,
    const char* title,
    float height,
    const std::string& loading_copy
) {
    if (!BeginDecoratedPanel(id, title, ImVec2(ImGui::GetContentRegionAvail().x, height), true)) {
        EndDecoratedPanel();
        return;
    }

    InlineSectionLabel(state.initial_state_loading ? "LOCAL STATE" : "LOCAL STATE READY");
    ImGui::TextWrapped("%s", loading_copy.c_str());
    ImGui::Spacing();
    ImGui::TextWrapped("%s", state.status_line.c_str());

    if (state.initial_state_loading) {
        ImGui::Spacing();
        const float pulse = 0.18f + 0.22f * (0.5f + 0.5f * std::sin(static_cast<float>(ImGui::GetTime()) * 2.4f));
        DrawProgressMeter(pulse, "LOADING LOCAL DATA");
        ImGui::TextDisabled("Loading slices, checks, recent runs, and generated results.");
    }

    if (!state.last_error.empty()) {
        ImGui::Spacing();
        ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", state.last_error.c_str());
    }

    EndDecoratedPanel();
}

void RenderProfilesPanel(ShellState& state) {
    if (state.profiles.empty()) {
        ImGui::TextDisabled("%s", Tr(state, UiText::NoProfilesDiscovered));
        return;
    }
    const float card_height = state.current_screen == ShellScreen::Select ? ShellUi(96.0f) : ShellUi(82.0f);
    for (size_t index = 0; index < state.profiles.size(); ++index) {
        const ProfileItem& profile = state.profiles[index];
        const bool selected = static_cast<int>(index) == state.selected_profile_index;
        const std::string row_id = "profile-" + profile.profile_id;
        const std::string title = profile.profile_id + "  " + profile.label;
        const std::string subtitle = "Suggested check: " + ShortActionLabel(profile.recommended_action_id);
        const std::string detail = profile.summary;
        if (DrawSelectableCard(row_id.c_str(), title, subtitle, detail, selected, card_height)) {
            SelectProfileById(state, profile.profile_id);
        }
    }
}

void RenderRecentActionsPanel(ShellState& state) {
    if (state.recent_actions.empty()) {
        ImGui::TextDisabled("%s", Tr(state, UiText::NoRecentActions));
        return;
    }
    for (const RecentActionItem& item : state.recent_actions) {
        const bool selected = state.current_run_id == item.run_id;
        const std::string row_id = "recent-" + item.run_id;
        const std::string subtitle = item.status + " | " + item.created_at_utc;
        if (DrawSelectableCard(row_id.c_str(), item.title, subtitle, item.summary, selected, ShellUi(76.0f))) {
            state.current_run_id = item.run_id;
            if (!item.profile_id.empty()) {
                SelectProfileById(state, item.profile_id);
            }
            RefreshSnapshot(state);
            RefreshRunSnapshot(state);
            UpdateRunPollingDeadline(state);
            SetScreen(state, ShellScreen::Run);
        }
    }
}

void RenderRecentResultsPanel(ShellState& state) {
    if (state.recent_runs.empty()) {
        ImGui::TextDisabled("%s", Tr(state, UiText::NoRecentRuns));
        return;
    }
    for (const RecentRunItem& item : state.recent_runs) {
        const bool selected = state.current_result_run_id == item.run_id;
        const std::string row_id = "recent-run-" + item.run_id;
        const std::string title = item.profile_id + "  " + item.title;
        const std::string subtitle = item.status + " | " + item.created_at_utc;
        if (DrawSelectableCard(row_id.c_str(), title, subtitle, item.summary, selected, ShellUi(76.0f))) {
            state.current_result_run_id = item.run_id;
            RefreshRunSnapshot(state);
            SetScreen(state, ShellScreen::Run);
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
            FriendlyActionDescription("daily_live_matrix"),
            "python -m sg_preflight run-action daily_live_matrix",
            {},
            true,
        }
    );
    for (const ActionItem& action : state.actions) {
        const std::string friendly_description = FriendlyActionDescription(action.action_id);
        tabs.push_back(
            {
                action.action_id,
                ShortActionLabel(action.action_id),
                friendly_description.empty() ? action.description : friendly_description,
                action.command_preview,
                action.blocker_message,
                action.ready,
            }
        );
    }

    const float motion = static_cast<float>(ComputeMotionFrames(kContainerCategoryTime, kContainerCategoryDuration));
    if (motion <= 0.0f || tabs.empty()) {
        return;
    }

    const bool compact_select_tabs = state.current_screen == ShellScreen::Select;
    const float gap_x = ShellUi(compact_select_tabs ? 6.0f : 8.0f);
    const float gap_y = ShellUi(compact_select_tabs ? 6.0f : 8.0f);
    const float button_height = ShellUi(compact_select_tabs ? 32.0f : 34.0f);
    const float clip_width = ImGui::GetContentRegionAvail().x;
    const int columns = compact_select_tabs
        ? (tabs.size() >= 5U ? 3 : (tabs.size() > 1 ? 2 : 1))
        : (tabs.size() >= 6U ? (clip_width < ShellUi(430.0f) ? 2 : 3) : (tabs.size() > 1 ? 2 : 1));
    const float button_width = std::max(ShellUi(compact_select_tabs ? 72.0f : 76.0f), (clip_width - gap_x * static_cast<float>(columns - 1)) / static_cast<float>(columns));

    g_tab_highlight_ready = false;

    for (size_t index = 0; index < tabs.size(); ++index) {
        const TabItem& tab = tabs[index];
        if (index > 0 && (index % static_cast<size_t>(columns)) != 0U) {
            ImGui::SameLine(0.0f, gap_x);
        }

        const bool selected = state.selected_action_id == tab.action_id;
        const size_t label_budget = compact_select_tabs
            ? (button_width < ShellUi(84.0f) ? 8U : 10U)
            : (button_width < ShellUi(78.0f) ? 7U : 10U);
        const std::string label = Ellipsize(tab.label, label_budget);
        if (DrawLanguageOptionButton(("tab-" + tab.action_id).c_str(), label.c_str(), selected, ImVec2(button_width, button_height))) {
            if (state.selected_action_id != tab.action_id) {
                state.selected_action_id = tab.action_id;
                state.last_error.clear();
            }
        }

        if (((index + 1U) % static_cast<size_t>(columns)) == 0U && index + 1U < tabs.size()) {
            ImGui::Dummy(ImVec2(0.0f, gap_y));
        }
    }

    if ((tabs.size() % static_cast<size_t>(columns)) != 0U) {
        ImGui::Dummy(ImVec2(0.0f, gap_y));
    }

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

    const bool show_selected_tab_copy = state.current_screen != ShellScreen::Select;
    if (show_selected_tab_copy && !selected_tab->ready && !selected_tab->blocker_message.empty()) {
        ImGui::Spacing();
        ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", selected_tab->blocker_message.c_str());
    } else if (show_selected_tab_copy && !selected_tab->description.empty()) {
        ImGui::Spacing();
        ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x);
        ImGui::TextDisabled("%s", selected_tab->description.c_str());
        ImGui::PopTextWrapPos();
    }
}

void RenderRunStatusContent(ShellState& state) {
    const std::string selected_action = CurrentActionId(state);
    const ActionItem* action = FindSelectedAction(state);
    const bool action_ready = selected_action == "daily_live_matrix" || (action != nullptr && action->ready);
    const bool running = IsActionStillRunning(state);
    const std::string button_label = state.run_refresh_loading
        ? "Refreshing Active Run"
        : (running ? RefreshActiveRunLabel(state.language) : RunSelectedActionLabel(state.language));
    const bool button_enabled = state.run_refresh_loading ? false : (running || action_ready);

    if (DrawPanelButton("run-selected-action", button_label, ImVec2(ShellUi(248.0f), ShellUi(34.0f)), true, button_enabled)) {
        if (running) {
            StartRunRefresh(state, false);
        } else if (button_enabled) {
            StartAction(state, selected_action);
        }
    }
    ImGui::Spacing();
    ImGui::TextDisabled("%s", state.status_line.c_str());

    if (!state.last_error.empty()) {
        ImGui::Spacing();
        InlineSectionLabel("Last Error");
        const float error_height = std::min(ShellUi(132.0f), std::max(ShellUi(88.0f), ImGui::GetContentRegionAvail().y * 0.42f));
        if (ImGui::BeginChild("run-last-error", ImVec2(0.0f, error_height), false, ImGuiWindowFlags_AlwaysVerticalScrollbar)) {
            ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x - ShellUi(10.0f));
            ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", state.last_error.c_str());
            ImGui::PopTextWrapPos();
        }
        ImGui::EndChild();
    }

    ImGui::Spacing();
    if (state.snapshot.has_value()) {
        const ActionSnapshot& snapshot = *state.snapshot;
        ImGui::Text("%s", snapshot.title.c_str());
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
            ImGui::TextDisabled("%s", sg_preflight::native_shell::FormatCommandLabel(state.language, snapshot.current_command).c_str());
        }

        ImGui::Spacing();
        InlineSectionLabel(Tr(state, UiText::Summary));
        if (snapshot.summary_lines.empty()) {
            ImGui::TextDisabled("%s", Tr(state, UiText::NoSummaryLines));
        } else {
            for (const std::string& line : snapshot.summary_lines) {
                ImGui::BulletText("%s", line.c_str());
            }
        }

        const bool show_diagnostics =
            snapshot.status == "failed"
            || snapshot.exit_code != 0
            || !snapshot.error_message.empty();
        if (show_diagnostics) {
            ImGui::Spacing();
            InlineSectionLabel("DIAGNOSTICS");
            DrawReadonlyTextBox("run-diagnostics-summary", BuildActionDiagnosticsText(snapshot), true, ShellUi(138.0f));
            ImGui::Spacing();
            if (DrawPanelButton("copy-run-diagnostics", "COPY DIAGNOSTICS", ImVec2(ShellUi(190.0f), ShellUi(30.0f)), false, true)) {
                if (CopyText(sg_preflight::native_shell::ToWide(BuildActionDiagnosticsText(snapshot)))) {
                    state.status_line = sg_preflight::native_shell::FormatCopiedItemStatus(state.language, "diagnostics");
                }
            }
            ImGui::SameLine();
            if (DrawPanelButton("open-run-trace", "OPEN TRACE", ImVec2(ShellUi(160.0f), ShellUi(30.0f)), false, !snapshot.log_path.empty())) {
                OpenPath(sg_preflight::native_shell::ToWide(snapshot.log_path));
            }
            ImGui::SameLine();
            if (DrawPanelButton("reveal-run-action-folder", "REVEAL ACTION FOLDER", ImVec2(ShellUi(220.0f), ShellUi(30.0f)), false, !snapshot.output_root.empty())) {
                OpenFolderPath(sg_preflight::native_shell::ToWide(snapshot.output_root));
            }
            ImGui::Spacing();
            if (DrawPanelButton("retry-selected-action", "RETRY", ImVec2(ShellUi(120.0f), ShellUi(30.0f)), true, !running && action_ready)) {
                StartAction(state, selected_action);
            }
        }
        return;
    }

    if (state.run_snapshot.has_value()) {
        const RunSnapshot& run_snapshot = *state.run_snapshot;
        ImGui::Text("%s", run_snapshot.summary_title.empty() ? run_snapshot.profile_label.c_str() : run_snapshot.summary_title.c_str());
        ImGui::SameLine();
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "[%s]", run_snapshot.status.c_str());
        for (const std::string& line : run_snapshot.summary_lines) {
            ImGui::BulletText("%s", line.c_str());
        }
        return;
    }

    ImGui::TextDisabled("%s", Tr(state, UiText::NoActiveActionLoaded));
}

void RenderRunLinkedResultContent(ShellState& state) {
    if (!state.run_snapshot.has_value()) {
        ImGui::TextDisabled("%s", IsActionStillRunning(state) ? "Waiting for the linked result snapshot." : Tr(state, UiText::NoLinkedRunSnapshot));
        return;
    }

    const RunSnapshot& run_snapshot = *state.run_snapshot;
    const bool running = IsActionStillRunning(state);
    ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x);
    ImGui::TextWrapped("%s", run_snapshot.profile_label.c_str());
    ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "[%s]", run_snapshot.status.c_str());
    if (!run_snapshot.workflow_stage_label.empty()) {
        ImGui::TextWrapped("%s", run_snapshot.workflow_stage_label.c_str());
    }
    if (!run_snapshot.created_at_utc.empty()) {
        ImGui::TextWrapped("%s", run_snapshot.created_at_utc.c_str());
    }
    ImGui::PopTextWrapPos();

    if (!run_snapshot.summary_lines.empty()) {
        ImGui::Spacing();
        InlineSectionLabel(Tr(state, UiText::Snapshot));
        for (const std::string& line : run_snapshot.summary_lines) {
            ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x);
            ImGui::BulletText("%s", line.c_str());
            ImGui::PopTextWrapPos();
        }
    }

    if (!run_snapshot.grouped_lines.empty()) {
        ImGui::Spacing();
        InlineSectionLabel(Tr(state, UiText::GroupedFindings));
        const float findings_height = running
            ? ShellUi(108.0f)
            : std::max(ShellUi(84.0f), ImGui::GetContentRegionAvail().y * 0.48f);
        if (ImGui::BeginChild("run-linked-findings", ImVec2(0.0f, findings_height), false, ImGuiWindowFlags_AlwaysVerticalScrollbar)) {
            const size_t limit = running
                ? std::min<size_t>(run_snapshot.grouped_lines.size(), 6U)
                : std::min<size_t>(run_snapshot.grouped_lines.size(), 12U);
            for (size_t index = 0; index < limit; ++index) {
                ImGui::TextWrapped("%s", run_snapshot.grouped_lines[index].c_str());
            }
            if (run_snapshot.grouped_lines.size() > limit) {
                ImGui::TextDisabled("%s", running ? "More findings will stay available after the active check finishes." : Tr(state, UiText::FilesTitle));
            }
        }
        ImGui::EndChild();
    }

    if (!run_snapshot.notes.empty()) {
        ImGui::Spacing();
        InlineSectionLabel(Tr(state, UiText::RunNotes));
        for (const std::string& note : run_snapshot.notes) {
            ImGui::BulletText("%s", note.c_str());
        }
    }
}

void RenderRunSignalLogContent(ShellState& state) {
    if (!state.snapshot.has_value()) {
        ImGui::TextDisabled("%s", Tr(state, UiText::NoActionLog));
        return;
    }

    const ActionSnapshot& snapshot = *state.snapshot;
    if (!snapshot.log_path.empty()) {
        InlineSectionLabel("LOG PATH");
        DrawReadonlyTextBox("run-log-path", snapshot.log_path, true, ShellUi(44.0f));
        ImGui::Spacing();
    }

    ImGui::BeginChild(
        "log-tail",
        ImVec2(0.0f, std::max(ShellUi(96.0f), ImGui::GetContentRegionAvail().y)),
        true,
        ImGuiWindowFlags_HorizontalScrollbar
    );
    if (snapshot.log_tail.empty()) {
        ImGui::TextDisabled("%s", Tr(state, UiText::NoActionLog));
    } else {
        const bool running = snapshot.status == "queued" || snapshot.status == "running";
        const std::string visible_tail = MakeVisibleLogTail(snapshot.log_tail, running);
        if (running && visible_tail.size() < snapshot.log_tail.size()) {
            ImGui::TextDisabled("%s", "Showing the latest live log tail while the check is still running.");
            ImGui::Spacing();
        }
        if (ImFont* mono_font = CurrentMonoFont(); mono_font != nullptr) {
            ImGui::PushFont(mono_font);
        }
        ImGui::TextUnformatted(visible_tail.c_str());
        if (CurrentMonoFont() != nullptr) {
            ImGui::PopFont();
        }
    }
    ImGui::EndChild();
}

void RenderRunHistoryContent(ShellState& state) {
    if (IsActionStillRunning(state)) {
        ImGui::TextDisabled("%s", "Recent history refreshes after the active check settles.");
        return;
    }

    InlineSectionLabel(Tr(state, UiText::RecentActions));
    ImGui::BeginChild("run-recent-actions-list", ImVec2(0.0f, ShellUi(88.0f)), false);
    RenderRecentActionsPanel(state);
    ImGui::EndChild();

    ImGui::Spacing();
    InlineSectionLabel(Tr(state, UiText::RecentResults));
    ImGui::BeginChild(
        "run-recent-results-list",
        ImVec2(0.0f, std::max(ShellUi(72.0f), ImGui::GetContentRegionAvail().y)),
        false
    );
    RenderRecentResultsPanel(state);
    ImGui::EndChild();
}

void RenderSelectedEvidenceContent(ShellState& state) {
    if (!state.snapshot.has_value() || state.snapshot->top_paths.empty()) {
        ImGui::TextDisabled("%s", Tr(state, UiText::NoEvidenceAvailable));
        return;
    }

    const int selected_index = std::clamp(state.selected_evidence_index, 0, static_cast<int>(state.snapshot->top_paths.size()) - 1);
    const EvidenceItem& item = state.snapshot->top_paths[static_cast<size_t>(selected_index)];
    DrawReadonlyTextBox("selected-evidence-path", item.path, true, ShellUi(46.0f));
    ImGui::Spacing();
    if (!item.checker.empty()) {
        ImGui::Text("%s", sg_preflight::native_shell::FormatCheckerLabel(state.language, item.checker).c_str());
    }
    if (!item.source_kind.empty()) {
        ImGui::TextDisabled("%s", item.source_kind.c_str());
    }
    if (!item.severity.empty()) {
        ImGui::SameLine();
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "[%s]", item.severity.c_str());
    }
    if (item.line >= 0) {
        ImGui::TextDisabled("%s", sg_preflight::native_shell::FormatLineNumberLabel(state.language, item.line).c_str());
    }

    ImGui::Spacing();
    InlineSectionLabel(Tr(state, UiText::Finding));
    ImGui::TextWrapped("%s", item.message.c_str());

    const std::wstring evidence_path = SelectedEvidencePath(state);
    if (!evidence_path.empty()) {
        ImGui::Spacing();
        if (DrawPanelButton("copy-evidence-path", "COPY PATH", ImVec2(ShellUi(152.0f), ShellUi(30.0f)), false, true)) {
            if (CopyText(evidence_path)) {
                state.status_line = sg_preflight::native_shell::FormatCopiedItemStatus(state.language, "path");
            }
        }
        ImGui::SameLine();
        if (DrawPanelButton("open-evidence-file", Tr(state, UiText::OpenFile), ImVec2(ShellUi(180.0f), ShellUi(30.0f)), true, true)) {
            OpenPath(evidence_path);
        }
        ImGui::SameLine();
        if (DrawPanelButton("reveal-evidence-file", Tr(state, UiText::Reveal), ImVec2(ShellUi(220.0f), ShellUi(30.0f)), false, true)) {
            RevealPath(evidence_path);
        }
        ImGui::Spacing();
        RenderPathAdapterButtons(state, "evidence-adapters", evidence_path);
    }
}

void RenderFollowupContent(ShellState& state) {
    if (state.snapshot.has_value() && !state.snapshot->manual_followups.empty()) {
        InlineSectionLabel(Tr(state, UiText::FollowUp));
        for (const std::string& followup : state.snapshot->manual_followups) {
            ImGui::BulletText("%s", followup.c_str());
        }
        return;
    }

    if (state.snapshot.has_value() && !state.snapshot->summary_lines.empty()) {
        InlineSectionLabel(Tr(state, UiText::Snapshot));
        for (const std::string& line : state.snapshot->summary_lines) {
            ImGui::BulletText("%s", line.c_str());
        }
        return;
    }

    if (state.run_snapshot.has_value() && !state.run_snapshot->notes.empty()) {
        InlineSectionLabel(Tr(state, UiText::RunNotes));
        for (const std::string& note : state.run_snapshot->notes) {
            ImGui::BulletText("%s", note.c_str());
        }
        return;
    }

    ImGui::TextDisabled("%s", Tr(state, UiText::NoManualFollowUp));
}

void RenderArtifactListOnly(ShellState& state) {
    const std::vector<ArtifactChoice> artifacts = CombinedArtifacts(state);
    if (artifacts.empty()) {
        ImGui::TextDisabled("%s", Tr(state, UiText::NoGeneratedArtifacts));
        return;
    }

    std::string current_section;
    for (size_t index = 0; index < artifacts.size(); ++index) {
        const ArtifactChoice& artifact = artifacts[index];
        if (artifact.section != current_section) {
            current_section = artifact.section;
            if (index > 0) {
                ImGui::Spacing();
            }
            ImGui::TextColored(ImVec4(0.40f, 0.88f, 0.64f, 1.0f), "%s", current_section.c_str());
        }

        const bool selected = static_cast<int>(index) == state.selected_artifact_index;
        const std::string row_id = "artifact-" + std::to_string(index);
        if (DrawSelectableCard(row_id.c_str(), artifact.label, artifact.section, artifact.path, selected, ShellUi(68.0f))) {
            state.selected_artifact_index = static_cast<int>(index);
        }
    }
}

void RenderSelectedArtifactContent(ShellState& state) {
    const std::vector<ArtifactChoice> artifacts = CombinedArtifacts(state);
    if (artifacts.empty()) {
        ImGui::TextDisabled("%s", Tr(state, UiText::NoArtifactsAvailable));
        return;
    }

    const int selected_index = std::clamp(state.selected_artifact_index, 0, static_cast<int>(artifacts.size()) - 1);
    const ArtifactChoice& artifact = artifacts[static_cast<size_t>(selected_index)];
    const std::wstring selected_artifact_path = SelectedArtifactPath(state);

    ImGui::Text("%s", artifact.label.c_str());
    ImGui::SameLine();
    ImGui::TextDisabled("%s", artifact.section.c_str());
    ImGui::Spacing();
    DrawReadonlyTextBox("selected-artifact-path", artifact.path, true, ShellUi(46.0f));

    ImGui::Spacing();
    if (DrawPanelButton("copy-selected-artifact-path", "COPY PATH", ImVec2(ShellUi(152.0f), ShellUi(30.0f)), false, !selected_artifact_path.empty())) {
        if (CopyText(selected_artifact_path)) {
            state.status_line = sg_preflight::native_shell::FormatCopiedItemStatus(state.language, "path");
        }
    }
    ImGui::SameLine();
    if (DrawPanelButton("open-selected-artifact", Tr(state, UiText::OpenSelected), ImVec2(ShellUi(180.0f), ShellUi(30.0f)), true, !selected_artifact_path.empty())) {
        OpenPath(selected_artifact_path);
    }
    ImGui::SameLine();
    if (DrawPanelButton("reveal-selected-artifact", Tr(state, UiText::RevealSelected), ImVec2(ShellUi(180.0f), ShellUi(30.0f)), false, !selected_artifact_path.empty())) {
        RevealPath(selected_artifact_path);
    }
    ImGui::Spacing();
    if (DrawPanelButton("open-html-report", Tr(state, UiText::OpenHtmlReport), ImVec2(ShellUi(190.0f), ShellUi(30.0f)), false, state.run_snapshot.has_value())) {
        for (const auto& run_artifact : state.run_snapshot->artifacts) {
            if (run_artifact.label == "HTML report") {
                OpenPath(sg_preflight::native_shell::ToWide(run_artifact.path));
                break;
            }
        }
    }
    if (!selected_artifact_path.empty()) {
        ImGui::Spacing();
        RenderPathAdapterButtons(state, "artifact-adapters", selected_artifact_path);
    }
}

void RenderEnvironmentDoctorListOnly(ShellState& state) {
    if (state.environment_items.empty()) {
        ImGui::TextDisabled("%s", "No environment doctor items are available.");
        return;
    }

    std::string current_category;
    for (size_t index = 0; index < state.environment_items.size(); ++index) {
        const EnvironmentDoctorItem& item = state.environment_items[index];
        if (item.category != current_category) {
            current_category = item.category;
            if (index > 0) {
                ImGui::Spacing();
            }
            ImGui::TextColored(ImVec4(0.40f, 0.88f, 0.64f, 1.0f), "%s", current_category.c_str());
        }

        std::string subtitle = item.category + " | " + item.state;
        const bool selected = static_cast<int>(index) == state.selected_environment_index;
        const std::string row_id = "environment-item-" + std::to_string(index);
        if (DrawSelectableCard(row_id.c_str(), item.label, subtitle, item.summary, selected, ShellUi(76.0f))) {
            state.selected_environment_index = static_cast<int>(index);
        }
    }
}

void RenderSelectedEnvironmentDoctorContent(ShellState& state) {
    if (state.environment_items.empty()) {
        ImGui::TextDisabled("%s", "No environment doctor items are available.");
        return;
    }

    const int selected_index = std::clamp(state.selected_environment_index, 0, static_cast<int>(state.environment_items.size()) - 1);
    const EnvironmentDoctorItem& item = state.environment_items[static_cast<size_t>(selected_index)];

    ImGui::Text("%s", item.label.c_str());
    ImGui::SameLine();
    ImGui::TextColored(EnvironmentStateColor(item.state), "[%s]", item.state.c_str());
    ImGui::Spacing();
    ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x);
    ImGui::TextUnformatted(item.summary.c_str());
    ImGui::PopTextWrapPos();

    if (!item.path.empty()) {
        ImGui::Spacing();
        InlineSectionLabel("PATH");
        DrawReadonlyTextBox("environment-item-path", item.path, true, ShellUi(46.0f));
    }

    if (!item.next_action.empty()) {
        ImGui::Spacing();
        InlineSectionLabel("NEXT ACTION");
        ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x);
        ImGui::TextUnformatted(item.next_action.c_str());
        ImGui::PopTextWrapPos();
    }
}

void RenderCopyExportContent(ShellState& state) {
    const std::vector<CopyItem> copy_items = CombinedCopyItems(state);
    if (copy_items.empty()) {
        ImGui::TextDisabled("%s", Tr(state, UiText::CopyExport));
        return;
    }

    const float button_width = ImGui::GetContentRegionAvail().x;
    for (const CopyItem& item : copy_items) {
        const std::string button_id = "copy-item-" + item.key;
        if (DrawPanelButton(button_id.c_str(), item.label, ImVec2(button_width, ShellUi(30.0f)), false, !item.text.empty())) {
            if (CopyText(sg_preflight::native_shell::ToWide(item.text))) {
                state.status_line = sg_preflight::native_shell::FormatCopiedItemStatus(state.language, item.label);
            }
        }
        ImGui::Spacing();
    }
}

void RenderBlockedStagesOnly(ShellState& state) {
    if (state.blockers.empty()) {
        ImGui::TextDisabled("%s", Tr(state, UiText::BlockedStageStatus));
        return;
    }

    for (const BlockerItem& item : state.blockers) {
        ImGui::Text("%s [%s]", item.label.c_str(), item.state.c_str());
        ImGui::Indent(ShellUi(12.0f));
        ImGui::TextWrapped("%s", item.summary.c_str());
        for (const std::string& blocker : item.blockers) {
            ImGui::BulletText("%s", blocker.c_str());
        }
        ImGui::Unindent(ShellUi(12.0f));
        ImGui::Spacing();
    }
}

void RenderManualReviewOnly(ShellState& state) {
    if (state.manual_cards.empty()) {
        ImGui::TextDisabled("%s", Tr(state, UiText::ManualReview));
        return;
    }

    for (const ManualCard& card : state.manual_cards) {
        ImGui::Text("%s [%s]", card.label.c_str(), card.state.c_str());
        ImGui::Indent(ShellUi(12.0f));
        ImGui::TextWrapped("%s", card.summary.c_str());
        ImGui::TextDisabled("%s", card.note.c_str());
        ImGui::Unindent(ShellUi(12.0f));
        ImGui::Spacing();
    }
}

void RenderManualEvidenceContent(ShellState& state) {
    const bool has_active_run = !state.current_run_id.empty();
    const std::filesystem::path action_root = CurrentActionOutputRoot(state);
    const auto full_width_button = [&]() {
        return ImVec2(std::max(ShellUi(210.0f), ImGui::GetContentRegionAvail().x), ShellUi(30.0f));
    };

    ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x);
    ImGui::TextUnformatted(
        "Attach local proof into the active action bundle so screenshots and review notes stay next to the deterministic SG evidence."
    );
    ImGui::PopTextWrapPos();

    if (!action_root.empty()) {
        ImGui::Spacing();
        InlineSectionLabel("ACTIVE ACTION BUNDLE");
        DrawReadonlyTextBox("manual-evidence-output-root", sg_preflight::native_shell::ToUtf8(action_root.wstring()), true, ShellUi(46.0f));
    }

    ImGui::Spacing();
    InlineSectionLabel("MANUAL NOTE");
    ImGui::InputTextMultiline(
        "manual-evidence-note",
        state.manual_evidence_note.data(),
        state.manual_evidence_note.size(),
        ImVec2(0.0f, ShellUi(110.0f))
    );

    const std::wstring note_text = sg_preflight::native_shell::ToWide(ActiveManualEvidenceNote(state));
    const auto attach_note = [&](const std::string& kind) {
        if (AttachManualEvidenceToCurrentRun(state, kind, L"", note_text)) {
            ClearManualEvidenceNote(state);
        }
    };

    ImGui::Spacing();
    if (DrawPanelButton("attach-manual-screenshot", "ATTACH SCREENSHOT", full_width_button(), true, has_active_run)) {
        if (QueueManualScreenshotCapture(state, note_text)) {
            ClearManualEvidenceNote(state);
        }
    }
    ImGui::Spacing();
    if (DrawPanelButton("attach-blender-note", "ATTACH BLENDER NOTE", full_width_button(), false, has_active_run)) {
        attach_note("blender_note");
    }
    ImGui::Spacing();
    if (DrawPanelButton("attach-raco-note", "ATTACH RACO NOTE", full_width_button(), false, has_active_run)) {
        attach_note("raco_note");
    }
    ImGui::Spacing();
    if (DrawPanelButton("attach-verification-note", "ATTACH VERIFICATION NOTE", full_width_button(), false, has_active_run)) {
        attach_note("verification_note");
    }
    ImGui::Spacing();
    if (DrawPanelButton("attach-external-file", "ATTACH EXTERNAL FILE", full_width_button(), false, has_active_run)) {
        const std::wstring selected_file = PromptForSingleFile();
        if (!selected_file.empty() && AttachManualEvidenceToCurrentRun(state, "external_file", selected_file, note_text)) {
            ClearManualEvidenceNote(state);
        }
    }

    if (!has_active_run) {
        ImGui::Spacing();
        ImGui::TextDisabled("%s", "Load or run one action first so manual evidence lands in a real action bundle.");
    }
}

void RenderDisplayModeContent(ShellState& state) {
    const ImVec2 display = ImGui::GetIO().DisplaySize;
    const std::string display_line = sg_preflight::native_shell::FormatDisplayModeLine(state.language, display.x, display.y, g_using_warp);
    const bool work_mode = IsWorkDisplayMode();
    if (DrawLanguageOptionButton("display-mode-work", "WORK", work_mode, ImVec2(ImGui::GetContentRegionAvail().x * 0.48f, ShellUi(34.0f)))) {
        SetDisplayMode(ShellDisplayMode::Work);
        state.status_line = sg_preflight::native_shell::FormatDisplayModeStatus(state.language, true);
    }
    ImGui::SameLine();
    if (DrawLanguageOptionButton("display-mode-cinematic", "CINEMATIC", !work_mode, ImVec2(ImGui::GetContentRegionAvail().x, ShellUi(34.0f)))) {
        SetDisplayMode(ShellDisplayMode::Cinematic);
        state.status_line = sg_preflight::native_shell::FormatDisplayModeStatus(state.language, false);
    }
    ImGui::Spacing();
    ImGui::TextWrapped("%s", display_line.c_str());
    ImGui::Spacing();
    ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x);
    ImGui::TextUnformatted(
        work_mode
            ? "Work mode keeps the shell sharp: smaller left art on work screens, lower scanlines, stronger contrast, readable body text, and no background music."
            : "Cinematic mode keeps the full SERGFX chrome: larger artwork, heavier motion/static treatment, and optional background music."
    );
    ImGui::PopTextWrapPos();
    ImGui::Spacing();
    ImGui::TextWrapped("%s", Tr(state, UiText::CurrentOutputHelp));
    ImGui::Spacing();
    ImGui::TextDisabled("%s", state.status_line.c_str());
}

void RenderAudioSettingsContent(ShellState& state) {
    if (!g_shell_audio.sfx_enabled) {
        SetSfxEnabled(true);
    }
    ImGui::BeginDisabled();
    DrawSettingToggle("toggle-sfx", Tr(state, UiText::UiSoundEffects), Tr(state, UiText::UiSoundEffectsSummary), true);
    ImGui::EndDisabled();
    ImGui::Spacing();
    if (DrawSettingToggle("toggle-bgm", Tr(state, UiText::InstallerBackgroundMusic), Tr(state, UiText::InstallerBackgroundMusicSummary), g_shell_audio.music_enabled)) {
        SetMusicEnabled(!g_shell_audio.music_enabled);
        state.status_line = sg_preflight::native_shell::FormatMusicStatus(state.language, g_shell_audio.music_enabled);
    }
    if (!g_shell_audio.last_error.empty()) {
        ImGui::Spacing();
        ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", g_shell_audio.last_error.c_str());
    }
}

void RenderWizardFlow(ShellState& state) {
    struct StepItem {
        ShellScreen screen;
        const char* label;
    };
    const std::array<StepItem, 8> steps = {{
        {ShellScreen::Introduction, "INTRO"},
        {ShellScreen::Select, "SELECT"},
        {ShellScreen::Review, "REVIEW"},
        {ShellScreen::Run, "RUN"},
        {ShellScreen::Evidence, "EVIDENCE"},
        {ShellScreen::Files, "FILES"},
        {ShellScreen::Environment, "ENV"},
        {ShellScreen::Stages, "STAGES"},
    }};

    InlineSectionLabel("Wizard Flow");
    const float width = ImGui::GetContentRegionAvail().x;
    const float item_gap = ShellUi(10.0f);
    const float item_width = std::max(ShellUi(110.0f), (width - item_gap * static_cast<float>(steps.size() - 1U)) / static_cast<float>(steps.size()));
    for (size_t index = 0; index < steps.size(); ++index) {
        const StepItem& item = steps[index];
        const bool current = state.current_screen == item.screen;
        const bool completed = ScreenStepNumber(state.current_screen) > ScreenStepNumber(item.screen);
        const bool accessible = completed || current;
        std::string label = std::to_string(ScreenStepNumber(item.screen)) + ". " + item.label;
        if (completed) {
            label += " ✓";
        }
        if (DrawPanelButton(
            ("wizard-step-" + std::string(item.label)).c_str(),
            label,
            ImVec2(item_width, ShellUi(30.0f)),
            current || completed,
            accessible
        )) {
            SetScreen(state, item.screen);
        }
        if (index + 1U < steps.size()) {
            ImGui::SameLine();
        }
    }
    ImGui::Spacing();
    ImGui::TextWrapped("%s", ScreenSummary(state.current_screen));
}

void RenderLanguageScreen(ShellState& state) {
    BeginScreenTransition(state);
    DrawInstallerCanvasBackground();
    const InstallerCanvasLayout layout = GetScreenCanvasLayout(ShellScreen::Language);

    if (BeginCanvasOverlayRegion("language-description", layout.description_content_min, layout.description_content_max)) {
        BeginScreenTextTransition(state);
        const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
        DrawCanvasPageTitle(Tr(state, UiText::LanguageScreenTitle), wrap_x);

        ImGui::Spacing();
        ImGui::PushTextWrapPos(wrap_x);
        ImGui::TextWrapped("%s", Tr(state, UiText::LanguageScreenBody));
        ImGui::Spacing();
        ImGui::TextDisabled("%s", Tr(state, UiText::LanguageScreenHint));
        ImGui::PopTextWrapPos();

        ImGui::Spacing();
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::AvailableLanguages));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        ImGui::Spacing();
        EndScreenTextTransition();

        const float gap = ShellUi(12.0f);
        const float button_width = (ImGui::GetContentRegionAvail().x - gap) * 0.5f;
        const ImVec2 button_size(button_width, ShellUi(42.0f));
        const auto& languages = sg_preflight::native_shell::SupportedLanguages();
        for (size_t index = 0; index < languages.size(); ++index) {
            const auto& option = languages[index];
            const bool selected = static_cast<int>(index) == state.selected_language_index;
            if (DrawLanguageOptionButton(
                    ("language-option-" + std::string(option.code)).c_str(),
                    sg_preflight::native_shell::LanguageNativeName(option.language),
                    selected,
                    button_size
                )) {
                state.selected_language_index = static_cast<int>(index);
                SetShellLanguage(state, option.language, true);
            }
            if ((index % 2U) == 0U && index + 1U < languages.size()) {
                ImGui::SameLine(0.0f, gap);
            }
        }
    }
    EndCanvasOverlayRegion();

    if (BeginCanvasOverlayRegion("language-side", layout.side_content_min, layout.side_content_max)) {
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::CurrentSelection));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        ImGui::Spacing();
        ImGui::Text("%s", sg_preflight::native_shell::LanguageNativeName(state.language));
        ImGui::TextDisabled("%s", sg_preflight::native_shell::LanguageCode(state.language));
        ImGui::Spacing();
        ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x);
        ImGui::TextWrapped("%s", sg_preflight::native_shell::FormatLanguageAppliedStatus(state.language, state.language).c_str());
        ImGui::PopTextWrapPos();
        EndScreenTextTransition();
    }
    EndCanvasOverlayRegion();
    EndScreenTransition();
}

void RenderIntroductionScreen(ShellState& state) {
    BeginScreenTransition(state);
    const InstallerCanvasLayout layout = GetScreenCanvasLayout(ShellScreen::Introduction);
    DrawInstallerCanvasBackground(layout);

    if (BeginCanvasOverlayRegion("intro-description", layout.description_content_min, layout.description_content_max)) {
        BeginScreenTextTransition(state);
        const float wrap_x = ImGui::GetCursorPosX() + std::min(ImGui::GetContentRegionAvail().x, ShellUi(348.0f));
        DrawCanvasPageTitle(Tr(state, UiText::IntroWelcome), wrap_x);

        ImGui::Dummy(ImVec2(0.0f, ShellUi(6.0f)));
        ImGui::PushTextWrapPos(wrap_x);
        ImGui::TextWrapped("%s", Tr(state, UiText::IntroBodyPrimary));
        ImGui::Dummy(ImVec2(0.0f, ShellUi(10.0f)));
        ImGui::TextWrapped("%s", Tr(state, UiText::IntroBodySecondary));
        ImGui::PopTextWrapPos();
        EndScreenTextTransition();
    }
    EndCanvasOverlayRegion();

    if (BeginCanvasOverlayRegion("intro-side", layout.side_content_min, layout.side_content_max)) {
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::CurrentDefault));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        ImGui::Spacing();

        const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
        ImGui::PushTextWrapPos(wrap_x);
        if (state.initial_state_loading) {
            ImGui::TextWrapped("%s", Tr(state, UiText::SelectLoadingTitle));
            ImGui::Spacing();
            ImGui::TextDisabled("%s", state.status_line.c_str());
        } else if (!state.profiles.empty()) {
            const ProfileItem& profile = state.profiles[static_cast<size_t>(state.selected_profile_index)];
            ImGui::Text("%s", profile.profile_id.c_str());
            ImGui::SameLine();
            ImGui::TextDisabled("%s", profile.label.c_str());
            ImGui::Spacing();
            ImGui::TextWrapped("%s", profile.summary.c_str());
            ImGui::Spacing();
            ImGui::Text("%s", sg_preflight::native_shell::FormatActionLabel(state.language, ShortActionLabel(profile.recommended_action_id)).c_str());
        } else {
            ImGui::TextDisabled("%s", Tr(state, UiText::NoProfilesDiscovered));
            ImGui::Spacing();
            ImGui::TextWrapped("%s", state.status_line.c_str());
        }
        ImGui::PopTextWrapPos();
        EndScreenTextTransition();
    }
    EndCanvasOverlayRegion();
    EndScreenTransition();
}

void RenderSelectScreen(ShellState& state) {
    BeginScreenTransition(state);
    const InstallerCanvasLayout layout = GetScreenCanvasLayout(ShellScreen::Select);
    DrawInstallerCanvasBackground(layout);

    if (state.initial_state_loading) {
        if (BeginCanvasOverlayRegion("select-loading-description", layout.description_content_min, layout.description_content_max)) {
            BeginScreenTextTransition(state);
            const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
            DrawCanvasPageTitle(Tr(state, UiText::SelectLoadingTitle), wrap_x);
            ImGui::Spacing();
            ImGui::PushTextWrapPos(wrap_x);
            ImGui::TextWrapped("%s", Tr(state, UiText::SelectLoadingBody));
            ImGui::Spacing();
            ImGui::TextDisabled("%s", state.status_line.c_str());
            ImGui::PopTextWrapPos();
            EndScreenTextTransition();
        }
        EndCanvasOverlayRegion();
        EndScreenTransition();
        return;
    }

    if (BeginCanvasOverlayRegion("select-description", layout.description_content_min, layout.description_content_max)) {
        BeginScreenTextTransition(state);
        const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
        DrawCanvasPageTitle(Tr(state, UiText::SelectTitle), wrap_x);
        ImGui::Dummy(ImVec2(0.0f, ShellUi(4.0f)));

        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::ActionPath));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();

        if (state.profile_panel_loading) {
            ImGui::Spacing();
            ImGui::TextDisabled("%s", "Loading the available checks for this slice.");
            const float pulse = 0.28f + 0.20f * (0.5f + 0.5f * std::sin(static_cast<float>(ImGui::GetTime()) * 2.2f));
            DrawProgressMeter(pulse, "LOADING CHECKS");
        } else {
            ImGui::Dummy(ImVec2(0.0f, ShellUi(2.0f)));
            RenderActionTabs(state);
        }
    }
    EndCanvasOverlayRegion();

    if (BeginCanvasOverlayRegion("select-side", layout.side_content_min, layout.side_content_max)) {
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::LiveSlices));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();
        ImGui::Spacing();
        ImGui::PushStyleColor(ImGuiCol_ChildBg, ImVec4(0.0f, 0.0f, 0.0f, 0.0f));
        if (ImGui::BeginChild("select-live-slices-scroll", ImVec2(0.0f, ImGui::GetContentRegionAvail().y), false, ImGuiWindowFlags_AlwaysVerticalScrollbar)) {
            RenderProfilesPanel(state);
        }
        ImGui::EndChild();
        ImGui::PopStyleColor();
    }
    EndCanvasOverlayRegion();
    EndScreenTransition();
}

void RenderReviewScreen(ShellState& state) {
    BeginScreenTransition(state);
    const InstallerCanvasLayout layout = GetScreenCanvasLayout(ShellScreen::Review);
    DrawInstallerCanvasBackground(layout);

    if (state.initial_state_loading) {
        if (BeginCanvasOverlayRegion("review-loading-description", layout.description_content_min, layout.description_content_max)) {
            BeginScreenTextTransition(state);
            const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
            DrawCanvasPageTitle(Tr(state, UiText::ReviewLoadingTitle), wrap_x);
            ImGui::Spacing();
            ImGui::PushTextWrapPos(wrap_x);
            ImGui::TextWrapped("%s", Tr(state, UiText::ReviewLoadingBody));
            ImGui::Spacing();
            ImGui::TextDisabled("%s", state.status_line.c_str());
            ImGui::PopTextWrapPos();
            EndScreenTextTransition();
        }
        EndCanvasOverlayRegion();
        EndScreenTransition();
        return;
    }

    const ActionItem* action = FindSelectedAction(state);
    if (BeginCanvasOverlayRegion("review-description", layout.description_content_min, layout.description_content_max)) {
        BeginScreenTextTransition(state);
        const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
        DrawCanvasPageTitle(Tr(state, UiText::ReviewTitle), wrap_x);

        ImGui::Spacing();
        if (!state.profiles.empty()) {
            const ProfileItem& profile = state.profiles[static_cast<size_t>(state.selected_profile_index)];
            ImGui::Text("%s", profile.profile_id.c_str());
            ImGui::SameLine();
            ImGui::TextDisabled("%s", profile.label.c_str());
            ImGui::PushTextWrapPos(wrap_x);
            ImGui::TextWrapped("%s", profile.summary.c_str());
            ImGui::PopTextWrapPos();
            ImGui::Spacing();
        }

        ImGui::Text("%s", sg_preflight::native_shell::FormatActionLabel(state.language, ShortActionLabel(CurrentActionId(state))).c_str());
        ImGui::PushTextWrapPos(wrap_x);
        if (action != nullptr) {
            ImGui::TextWrapped("%s", action->description.c_str());
        } else if (CurrentActionId(state) == "daily_live_matrix") {
            ImGui::TextWrapped("%s", Tr(state, UiText::SelectDailyMatrixBody));
        } else {
            ImGui::TextDisabled("%s", Tr(state, UiText::NoCommandPreview));
        }
        ImGui::PopTextWrapPos();
        EndScreenTextTransition();
    }
    EndCanvasOverlayRegion();

    if (BeginCanvasOverlayRegion("review-side", layout.side_content_min, layout.side_content_max)) {
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::ReadyBlocked));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        ImGui::Spacing();
        if (SelectedActionReady(state)) {
            ImGui::TextColored(ImVec4(0.40f, 0.88f, 0.64f, 1.0f), "%s", Tr(state, UiText::ReadyToRun));
        } else if (action != nullptr && !action->blocker_message.empty()) {
            ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", action->blocker_message.c_str());
        } else {
            ImGui::TextDisabled("%s", Tr(state, UiText::ActionNotReady));
        }
        if (!state.blockers.empty()) {
            ImGui::Spacing();
            for (const BlockerItem& item : state.blockers) {
                ImGui::Text("%s", item.label.c_str());
                ImGui::TextDisabled("%s", item.summary.c_str());
                break;
            }
        }
        EndScreenTextTransition();
    }
    EndCanvasOverlayRegion();
    EndScreenTransition();
}

void RenderRunScreen(ShellState& state) {
    BeginScreenTransition(state);
    const InstallerCanvasLayout layout = GetScreenCanvasLayout(ShellScreen::Run);
    DrawInstallerCanvasBackground(layout);
    const bool live_console_mode = IsActionStillRunning(state) || state.run_refresh_loading;

    if (BeginCanvasOverlayRegion("run-description", layout.description_content_min, layout.description_content_max)) {
        if (ImGui::BeginChild("run-description-scroll", ImVec2(0.0f, ImGui::GetContentRegionAvail().y), false, ImGuiWindowFlags_AlwaysVerticalScrollbar)) {
            BeginScreenTextTransition(state);
            const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
            if (g_title_font != nullptr) {
                ImGui::PushFont(g_title_font);
            }
            if (live_console_mode) {
                ImGui::PushTextWrapPos(wrap_x);
                ImGui::TextWrapped("%s", "Live check console");
                ImGui::PopTextWrapPos();
            } else {
                ImGui::PushTextWrapPos(wrap_x);
                ImGui::TextWrapped("%s", Tr(state, UiText::RunTitle));
                ImGui::PopTextWrapPos();
            }
            if (g_title_font != nullptr) {
                ImGui::PopFont();
            }

            ImGui::Spacing();
            if (g_small_font != nullptr) {
                ImGui::PushFont(g_small_font);
            }
            ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::CurrentExecution));
            if (g_small_font != nullptr) {
                ImGui::PopFont();
            }
            EndScreenTextTransition();
            RenderRunStatusContent(state);

            ImGui::Spacing();
            BeginScreenTextTransition(state);
            if (g_small_font != nullptr) {
                ImGui::PushFont(g_small_font);
            }
            ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", live_console_mode ? "LIVE SIGNAL LOG" : Tr(state, UiText::ActionSignalLog));
            if (g_small_font != nullptr) {
                ImGui::PopFont();
            }
            EndScreenTextTransition();
            ImGui::BeginChild(
                "run-log-inline",
                ImVec2(
                    0.0f,
                    std::max(
                        live_console_mode
                            ? ShellUi(IsWorkDisplayMode() ? 262.0f : 220.0f)
                            : ShellUi(IsWorkDisplayMode() ? 156.0f : 134.0f),
                        ImGui::GetContentRegionAvail().y
                    )
                ),
                false,
                ImGuiWindowFlags_AlwaysVerticalScrollbar
            );
            RenderRunSignalLogContent(state);
            ImGui::EndChild();
        }
        ImGui::EndChild();
    }
    EndCanvasOverlayRegion();

    if (BeginCanvasOverlayRegion("run-side", layout.side_content_min, layout.side_content_max)) {
        if (ImGui::BeginChild("run-side-scroll", ImVec2(0.0f, ImGui::GetContentRegionAvail().y), false, ImGuiWindowFlags_AlwaysVerticalScrollbar)) {
            BeginScreenTextTransition(state);
            if (g_small_font != nullptr) {
                ImGui::PushFont(g_small_font);
            }
            ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", live_console_mode ? "LIVE RESULT SNAPSHOT" : Tr(state, UiText::LinkedResult));
            if (g_small_font != nullptr) {
                ImGui::PopFont();
            }
            EndScreenTextTransition();
            RenderRunLinkedResultContent(state);

            ImGui::Spacing();
            if (live_console_mode) {
                BeginScreenTextTransition(state);
                if (g_small_font != nullptr) {
                    ImGui::PushFont(g_small_font);
                }
                ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", "RUN FLOW");
                if (g_small_font != nullptr) {
                    ImGui::PopFont();
                }
                EndScreenTextTransition();
                ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x);
                ImGui::TextWrapped("%s", "The live console stays focused on the current check while it is running. Full local history, files, and follow-up material stay available once the run settles.");
                ImGui::PopTextWrapPos();
            } else {
                BeginScreenTextTransition(state);
                if (g_small_font != nullptr) {
                    ImGui::PushFont(g_small_font);
                }
                ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::RecentLocalHistory));
                if (g_small_font != nullptr) {
                    ImGui::PopFont();
                }
                EndScreenTextTransition();
                ImGui::BeginChild("run-history-inline", ImVec2(0.0f, std::max(ShellUi(106.0f), ImGui::GetContentRegionAvail().y)), false, ImGuiWindowFlags_AlwaysVerticalScrollbar);
                RenderRunHistoryContent(state);
                ImGui::EndChild();
            }
        }
        ImGui::EndChild();
    }
    EndCanvasOverlayRegion();
    EndScreenTransition();
}

void RenderEvidenceScreen(ShellState& state) {
    BeginScreenTransition(state);
    const InstallerCanvasLayout layout = GetScreenCanvasLayout(ShellScreen::Evidence);
    DrawInstallerCanvasBackground(layout);

    if (BeginCanvasOverlayRegion("evidence-description", layout.description_content_min, layout.description_content_max)) {
        BeginScreenTextTransition(state);
        const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
        if (g_title_font != nullptr) {
            ImGui::PushFont(g_title_font);
        }
        ImGui::PushTextWrapPos(wrap_x);
        ImGui::TextWrapped("%s", Tr(state, UiText::EvidenceTitle));
        ImGui::PopTextWrapPos();
        if (g_title_font != nullptr) {
            ImGui::PopFont();
        }

        ImGui::Spacing();
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::SelectedTarget));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();
        RenderSelectedEvidenceContent(state);

        ImGui::Spacing();
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::OpenFirstPaths));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();
        ImGui::BeginChild("evidence-list-inline", ImVec2(0.0f, std::max(ShellUi(110.0f), ImGui::GetContentRegionAvail().y)), false);
        RenderEvidencePanel(state);
        ImGui::EndChild();
    }
    EndCanvasOverlayRegion();

    if (BeginCanvasOverlayRegion("evidence-side", layout.side_content_min, layout.side_content_max)) {
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::FollowUp));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();
        RenderFollowupContent(state);
    }
    EndCanvasOverlayRegion();
    EndScreenTransition();
}

void RenderFilesScreen(ShellState& state) {
    BeginScreenTransition(state);
    const InstallerCanvasLayout layout = GetScreenCanvasLayout(ShellScreen::Files);
    DrawInstallerCanvasBackground(layout);

    if (BeginCanvasOverlayRegion("files-description", layout.description_content_min, layout.description_content_max)) {
        BeginScreenTextTransition(state);
        const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
        if (g_title_font != nullptr) {
            ImGui::PushFont(g_title_font);
        }
        ImGui::PushTextWrapPos(wrap_x);
        ImGui::TextWrapped("%s", Tr(state, UiText::FilesTitle));
        ImGui::PopTextWrapPos();
        if (g_title_font != nullptr) {
            ImGui::PopFont();
        }

        ImGui::Spacing();
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::SelectedTarget));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();
        RenderSelectedArtifactContent(state);

        ImGui::Spacing();
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::GeneratedFiles));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();
        ImGui::BeginChild("files-list-inline", ImVec2(0.0f, std::max(ShellUi(110.0f), ImGui::GetContentRegionAvail().y)), false);
        RenderArtifactListOnly(state);
        ImGui::EndChild();
    }
    EndCanvasOverlayRegion();

    if (BeginCanvasOverlayRegion("files-side", layout.side_content_min, layout.side_content_max)) {
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::CopyExport));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();
        RenderCopyExportContent(state);
    }
    EndCanvasOverlayRegion();
    EndScreenTransition();
}

void RenderEnvironmentScreen(ShellState& state) {
    BeginScreenTransition(state);
    const InstallerCanvasLayout layout = GetScreenCanvasLayout(ShellScreen::Environment);
    DrawInstallerCanvasBackground(layout);
    ImDrawList* draw = ImGui::GetWindowDrawList();
    ImFont* title_font = g_title_font != nullptr ? g_title_font : CurrentBodyFont();
    ImFont* body_font = CurrentBodyFont() != nullptr ? CurrentBodyFont() : ImGui::GetFont();
    ImFont* small_font = CurrentSmallFont() != nullptr ? CurrentSmallFont() : body_font;
    const float chrome_alpha = std::clamp(ShellChromeLifecycleMotion() * ShellExitTextVisibility(state), 0.0f, 1.0f);
    const float text_alpha = std::clamp(ShellTextLifecycleMotion() * ShellExitTextVisibility(state), 0.0f, 1.0f);
    const ImVec2 desc_min = layout.description_content_min;
    const ImVec2 desc_max = layout.description_content_max;
    const ImVec2 side_min = layout.side_content_min;
    const ImVec2 side_max = layout.side_content_max;
    const float desc_width = std::max(1.0f, desc_max.x - desc_min.x);
    draw->AddRectFilled(desc_min, desc_max, ApplyAlpha(IM_COL32(4, 18, 8, 208), chrome_alpha), ShellUi(4.0f));
    draw->AddRect(desc_min, desc_max, ApplyAlpha(IM_COL32(108, 176, 116, 164), chrome_alpha), ShellUi(4.0f), 0, 1.0f);
    draw->AddRectFilled(side_min, side_max, ApplyAlpha(IM_COL32(4, 18, 8, 192), chrome_alpha), ShellUi(4.0f));
    draw->AddRect(side_min, side_max, ApplyAlpha(IM_COL32(98, 166, 108, 148), chrome_alpha), ShellUi(4.0f), 0, 1.0f);

    float y = desc_min.y + ShellUi(18.0f);
    draw->PushClipRect(desc_min, desc_max, true);
    DrawPromptTextStyled(
        draw,
        title_font,
        title_font == g_title_font ? ShellUi(28.0f) : body_font->LegacySize,
        ImVec2(desc_min.x + ShellUi(12.0f), y),
        IM_COL32(236, 244, 238, 255),
        text_alpha,
        "Environment Doctor",
        0.0f
    );
    y += ShellUi(40.0f);
    DrawPromptTextStyled(
        draw,
        small_font,
        small_font->LegacySize,
        ImVec2(desc_min.x + ShellUi(12.0f), y),
        IM_COL32(255, 188, 0, 255),
        text_alpha,
        "SELECTED READINESS CHECK",
        0.0f
    );
    y += ShellUi(26.0f);

    if (state.environment_items.empty()) {
        y = DrawLeftAlignedPromptParagraphStyled(
            draw,
            body_font,
            body_font->LegacySize,
            desc_width - ShellUi(24.0f),
            ImVec2(desc_min.x + ShellUi(12.0f), y),
            5.0f,
            IM_COL32(228, 236, 230, 255),
            text_alpha,
            "No environment doctor items are available."
        );
    } else {
        const int selected_index = std::clamp(state.selected_environment_index, 0, static_cast<int>(state.environment_items.size()) - 1);
        const EnvironmentDoctorItem& item = state.environment_items[static_cast<size_t>(selected_index)];
        const std::string selected_title = item.label + " [" + item.state + "]";
        DrawPromptTextStyled(
            draw,
            body_font,
            body_font->LegacySize,
            ImVec2(desc_min.x + ShellUi(12.0f), y),
            ImGui::ColorConvertFloat4ToU32(EnvironmentStateColor(item.state)),
            text_alpha,
            selected_title.c_str(),
            0.0f
        );
        y += ShellUi(28.0f);
        y = DrawLeftAlignedPromptParagraphStyled(
            draw,
            body_font,
            body_font->LegacySize,
            desc_width - ShellUi(24.0f),
            ImVec2(desc_min.x + ShellUi(12.0f), y),
            6.0f,
            IM_COL32(232, 239, 234, 255),
            text_alpha,
            item.summary
        );
        y += ShellUi(16.0f);
        if (!item.path.empty()) {
            DrawPromptTextStyled(
                draw,
                small_font,
                small_font->LegacySize,
                ImVec2(desc_min.x + ShellUi(12.0f), y),
                IM_COL32(255, 188, 0, 255),
                text_alpha,
                "PATH",
                0.0f
            );
            y += ShellUi(22.0f);
            y = DrawLeftAlignedPromptParagraphStyled(
                draw,
                small_font,
                small_font->LegacySize,
                desc_width - ShellUi(24.0f),
                ImVec2(desc_min.x + ShellUi(12.0f), y),
                4.0f,
                IM_COL32(204, 214, 208, 255),
                text_alpha,
                item.path
            );
            y += ShellUi(14.0f);
        }
        if (!item.next_action.empty()) {
            DrawPromptTextStyled(
                draw,
                small_font,
                small_font->LegacySize,
                ImVec2(desc_min.x + ShellUi(12.0f), y),
                IM_COL32(255, 188, 0, 255),
                text_alpha,
                "NEXT ACTION",
                0.0f
            );
            y += ShellUi(22.0f);
            y = DrawLeftAlignedPromptParagraphStyled(
                draw,
                small_font,
                small_font->LegacySize,
                desc_width - ShellUi(24.0f),
                ImVec2(desc_min.x + ShellUi(12.0f), y),
                4.0f,
                IM_COL32(214, 224, 218, 255),
                text_alpha,
                item.next_action
            );
        }
    }
    y += ShellUi(16.0f);
    DrawPromptTextStyled(
        draw,
        small_font,
        small_font->LegacySize,
        ImVec2(desc_min.x + ShellUi(12.0f), y),
        IM_COL32(255, 188, 0, 255),
        text_alpha,
        "DOCTOR ROLE",
        0.0f
    );
    y += ShellUi(22.0f);
    DrawLeftAlignedPromptParagraphStyled(
        draw,
        small_font,
        small_font->LegacySize,
        desc_width - ShellUi(24.0f),
        ImVec2(desc_min.x + ShellUi(12.0f), y),
        4.0f,
        IM_COL32(214, 224, 218, 255),
        text_alpha,
        "This page keeps the shell honest. It shows what this machine can really do now: shared Python backend, mirrored SG checker coverage, local RaCo and Blender adapters, BMW blockers, and output writeability."
    );
    draw->PopClipRect();

    float side_y = side_min.y + ShellUi(18.0f);
    draw->PushClipRect(side_min, side_max, true);
    DrawPromptTextStyled(
        draw,
        small_font,
        small_font->LegacySize,
        ImVec2(side_min.x + ShellUi(12.0f), side_y),
        IM_COL32(255, 188, 0, 255),
        text_alpha,
        "LOCAL TOOL READINESS",
        0.0f
    );
    draw->PopClipRect();
    side_y += ShellUi(30.0f);

    for (size_t index = 0; index < state.environment_items.size(); ++index) {
        const EnvironmentDoctorItem& row = state.environment_items[index];
        const float row_height = ShellUi(74.0f);
        const ImVec2 row_min(side_min.x + ShellUi(8.0f), side_y);
        const ImVec2 row_max(side_max.x - ShellUi(8.0f), side_y + row_height);
        if (row_max.y > side_max.y - ShellUi(8.0f)) {
            break;
        }

        ImGui::SetCursorScreenPos(row_min);
        const bool interaction_enabled = !IsBackgroundInteractionBlocked();
        if (!interaction_enabled) {
            ImGui::BeginDisabled();
        }
        const std::string row_id = "environment-row-" + std::to_string(index);
        const bool pressed = ImGui::InvisibleButton(row_id.c_str(), ImVec2(row_max.x - row_min.x, row_max.y - row_min.y));
        const bool hovered = interaction_enabled && ImGui::IsItemHovered();
        if (!interaction_enabled) {
            ImGui::EndDisabled();
        }
        const bool selected = static_cast<int>(index) == state.selected_environment_index;
        PlayHoverCueIfNeeded(hovered, interaction_enabled);
        if (pressed && interaction_enabled) {
            state.selected_environment_index = static_cast<int>(index);
            PlayCue(UiCue::Confirm);
        }

        draw->AddRectFilled(
            row_min,
            row_max,
            ApplyAlpha(
                selected
                    ? IM_COL32(18, 88, 30, 224)
                    : (hovered ? IM_COL32(12, 34, 16, 228) : IM_COL32(8, 20, 10, 212)),
                chrome_alpha
            ),
            ShellUi(4.0f)
        );
        draw->AddRect(
            row_min,
            row_max,
            ApplyAlpha(
                selected
                    ? IM_COL32(128, 255, 160, 224)
                    : IM_COL32(74, 132, 84, hovered ? 188 : 148),
                chrome_alpha
            ),
            ShellUi(4.0f),
            0,
            1.0f
        );

        draw->PushClipRect(row_min, row_max, true);
        DrawPromptTextStyled(
            draw,
            small_font,
            small_font->LegacySize,
            ImVec2(row_min.x + ShellUi(12.0f), row_min.y + ShellUi(10.0f)),
            ImGui::ColorConvertFloat4ToU32(EnvironmentStateColor(row.state)),
            text_alpha,
            row.label.c_str(),
            0.0f
        );
        const std::string summary_line = "[" + row.state + "] " + Ellipsize(row.summary, 110U);
        DrawLeftAlignedPromptParagraphStyled(
            draw,
            small_font,
            small_font->LegacySize,
            row_max.x - row_min.x - ShellUi(24.0f),
            ImVec2(row_min.x + ShellUi(12.0f), row_min.y + ShellUi(32.0f)),
            3.0f,
            IM_COL32(212, 220, 216, 255),
            text_alpha,
            summary_line
        );
        draw->PopClipRect();
        side_y += row_height + ShellUi(8.0f);
    }
    EndScreenTransition();
}

void RenderStagesScreen(ShellState& state) {
    BeginScreenTransition(state);
    const InstallerCanvasLayout layout = GetScreenCanvasLayout(ShellScreen::Stages);
    DrawInstallerCanvasBackground(layout);

    if (BeginCanvasOverlayRegion("stages-description", layout.description_content_min, layout.description_content_max)) {
        BeginScreenTextTransition(state);
        const float wrap_x = ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x;
        if (g_title_font != nullptr) {
            ImGui::PushFont(g_title_font);
        }
        ImGui::PushTextWrapPos(wrap_x);
        ImGui::TextWrapped("%s", Tr(state, UiText::StagesTitle));
        ImGui::PopTextWrapPos();
        if (g_title_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();

        ImGui::Spacing();
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::BlockedStageStatus));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();
        ImGui::BeginChild("stages-blocked-inline", ImVec2(0.0f, std::max(ShellUi(116.0f), ImGui::GetContentRegionAvail().y * 0.54f)), false);
        RenderBlockedStagesOnly(state);
        ImGui::EndChild();

        ImGui::Spacing();
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::ManualReview));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();
        ImGui::BeginChild("stages-manual-inline", ImVec2(0.0f, std::max(ShellUi(82.0f), ImGui::GetContentRegionAvail().y)), false);
        RenderManualReviewOnly(state);
        ImGui::EndChild();
    }
    EndCanvasOverlayRegion();

    if (BeginCanvasOverlayRegion("stages-side", layout.side_content_min, layout.side_content_max)) {
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", "MANUAL EVIDENCE");
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();
        RenderManualEvidenceContent(state);

        ImGui::Spacing();
        BeginScreenTextTransition(state);
        if (g_small_font != nullptr) {
            ImGui::PushFont(g_small_font);
        }
        ImGui::TextColored(ImVec4(0.95f, 0.68f, 0.19f, 1.0f), "%s", Tr(state, UiText::ShellAudio));
        if (g_small_font != nullptr) {
            ImGui::PopFont();
        }
        EndScreenTextTransition();
        RenderAudioSettingsContent(state);
    }
    EndCanvasOverlayRegion();
    EndScreenTransition();
}

void RenderCurrentScreen(ShellState& state) {
    switch (state.current_screen) {
    case ShellScreen::Language:
        RenderLanguageScreen(state);
        break;
    case ShellScreen::Introduction:
        RenderIntroductionScreen(state);
        break;
    case ShellScreen::Select:
        RenderSelectScreen(state);
        break;
    case ShellScreen::Review:
        RenderReviewScreen(state);
        break;
    case ShellScreen::Run:
        RenderRunScreen(state);
        break;
    case ShellScreen::Evidence:
        RenderEvidenceScreen(state);
        break;
    case ShellScreen::Files:
        RenderFilesScreen(state);
        break;
    case ShellScreen::Environment:
        RenderEnvironmentScreen(state);
        break;
    case ShellScreen::Stages:
        RenderStagesScreen(state);
        break;
    }
}

void RenderWizardNavigation(ShellState& state) {
    const bool can_go_next = CanAdvanceFromPage(state, state.current_screen);
    const std::string next_label = NextButtonLabel(state);
    const float lifecycle_motion = ShellChromeLifecycleMotion();
    const bool source_style_page =
        state.current_screen == ShellScreen::Language
        || state.current_screen == ShellScreen::Introduction
        || state.current_screen == ShellScreen::Select
        || state.current_screen == ShellScreen::Review;

    if (source_style_page) {
        if (lifecycle_motion <= 0.02f) {
            return;
        }
        const InstallerCanvasLayout layout = GetScreenCanvasLayout(state.current_screen);
        ImFont* font = g_small_font != nullptr ? g_small_font : ImGui::GetFont();
        const float font_size = font == g_small_font ? g_small_font->LegacySize : ImGui::GetFontSize();
        const float max_text_width = ShellUi(90.0f);
        ImVec2 text_size = font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, next_label.c_str());
        float squash_ratio = 1.0f;
        if (text_size.x > max_text_width && text_size.x > 0.0f) {
            squash_ratio = max_text_width / text_size.x;
        }
        const float button_width = std::max(ShellUi(112.0f), text_size.x * squash_ratio + ShellUi(30.0f));
        const float button_height = ShellUi(32.0f);
        const ImVec2 min(
            layout.description_max.x - button_width - ShellUi(14.0f) + (1.0f - lifecycle_motion) * ShellUi(24.0f),
            layout.description_max.y - button_height - ShellUi(14.0f) + (1.0f - lifecycle_motion) * ShellUi(4.0f)
        );

        ImGui::SetCursorScreenPos(min);
        if (DrawInstallerNavButton("wizard-next-source", next_label.c_str(), ImVec2(button_width, button_height), true, can_go_next)) {
            if (state.current_screen == ShellScreen::Review) {
                StartAction(state, CurrentActionId(state));
            } else {
                SetScreen(state, NextScreen(state, state.current_screen));
            }
        }
        return;
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
    ImGui::Spacing();
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
        ImGui::TextDisabled("%s", Tr(state, UiText::NoEvidenceAvailable));
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
        if (DrawSelectableCard(row_id.c_str(), item.path, subtitle, item.message, selected, ShellUi(88.0f))) {
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
            if (DrawSelectableCard(row_id.c_str(), artifact.label, artifact.section, artifact.path, selected, ShellUi(68.0f))) {
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
    if (state.exit_transition_active) {
        return;
    }
    const float guide_alpha = ShellChromeLifecycleMotion();
    if (guide_alpha <= 0.02f) {
        return;
    }

    UpdateGuideInputMode();

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

    struct GuideItem {
        const char* id;
        const char* key;
        std::string label;
        bool enabled;
        bool right_aligned;
        bool primary;
    };

    const std::wstring evidence_path = SelectedEvidencePath(state);
    const std::wstring artifact_path = SelectedArtifactPath(state);
    const bool has_report = state.run_snapshot.has_value() || (state.snapshot.has_value() && !state.snapshot->latest_run_links.html_report.empty());
    const std::string run_primary_label = IsActionStillRunning(state) ? RefreshShortLabel(state.language) : NextButtonLabel(state);
    std::vector<GuideItem> guide_items;
    if (state.prompt_visible) {
        if (state.prompt_confirmation && !state.prompt_controls_visible) {
            guide_items = {
                {"guide-prompt-next", "Enter", Tr(state, UiText::Next), true, false, true},
            };
        } else {
            guide_items = state.prompt_confirmation
                ? std::vector<GuideItem>{
                    {"guide-prompt-select", "Enter", Tr(state, UiText::Select), true, false, true},
                    {"guide-prompt-back", "Esc", Tr(state, UiText::Back), true, true, true},
                }
                : std::vector<GuideItem>{
                    {"guide-prompt-ok", "Enter", Tr(state, UiText::Next), true, false, true},
                };
        }
    } else {
    switch (state.current_screen) {
    case ShellScreen::Language:
        guide_items = {
            {"guide-next", "Enter", Tr(state, UiText::Select), true, false, true},
            {"guide-back", "Esc", Tr(state, UiText::Quit), true, true, true},
        };
        break;
    case ShellScreen::Introduction:
        guide_items = {
            {"guide-next", "Enter", Tr(state, UiText::Continue), true, false, true},
            {"guide-back", "Esc", Tr(state, UiText::Quit), true, true, true},
        };
        break;
    case ShellScreen::Select:
        guide_items = {
            {"guide-next", "Enter", Tr(state, UiText::Review), CanAdvanceFromPage(state, state.current_screen), false, true},
            {"guide-back", "Esc", Tr(state, UiText::Back), true, true, true},
        };
        break;
    case ShellScreen::Review:
        guide_items = {
            {"guide-next", "Enter", Tr(state, UiText::Run), SelectedActionReady(state), false, true},
            {"guide-back", "Esc", Tr(state, UiText::Back), true, true, true},
        };
        break;
    case ShellScreen::Run:
        guide_items = {
            {"guide-next", "Enter", run_primary_label, IsActionStillRunning(state) || CanAdvanceFromPage(state, state.current_screen), false, true},
            {"guide-log", "F2", Tr(state, UiText::RawLog), state.snapshot.has_value(), false, true},
            {"guide-report", "F3", Tr(state, UiText::Report), has_report, false, true},
            {"guide-back", "Esc", Tr(state, UiText::Back), true, true, true},
        };
        break;
    case ShellScreen::Evidence:
        guide_items = {
            {"guide-next", "Enter", Tr(state, UiText::Files), HasArtifactsReady(state), false, true},
            {"guide-back", "Esc", Tr(state, UiText::Back), true, true, true},
            {"guide-open", "O", Tr(state, UiText::OpenFile), !evidence_path.empty(), false, false},
            {"guide-reveal", "R", Tr(state, UiText::Reveal), !evidence_path.empty(), false, false},
            {"guide-jira", "J", Tr(state, UiText::CopyJira), true, true, false},
        };
        break;
    case ShellScreen::Files:
        guide_items = {
            {"guide-next", "Enter", Tr(state, UiText::Environment), true, false, true},
            {"guide-back", "Esc", Tr(state, UiText::Back), true, true, true},
            {"guide-open", "O", Tr(state, UiText::OpenFile), !artifact_path.empty(), false, false},
            {"guide-reveal", "R", Tr(state, UiText::Reveal), !artifact_path.empty(), false, false},
            {"guide-report", "P", Tr(state, UiText::Report), has_report, false, false},
            {"guide-jira", "J", Tr(state, UiText::CopyJira), true, true, false},
            {"guide-hero", "Q", Tr(state, UiText::CopyQaHero), true, true, false},
            {"guide-handoff", "H", Tr(state, UiText::CopyHandoff), true, true, false},
        };
        break;
    case ShellScreen::Environment:
        guide_items = {
            {"guide-next", "Enter", Tr(state, UiText::Stages), true, false, true},
            {"guide-back", "Esc", Tr(state, UiText::Back), true, true, true},
            {"guide-jira", "J", Tr(state, UiText::CopyJira), true, true, false},
            {"guide-hero", "Q", Tr(state, UiText::CopyQaHero), true, true, false},
            {"guide-handoff", "H", Tr(state, UiText::CopyHandoff), true, true, false},
        };
        break;
    case ShellScreen::Stages:
        guide_items = {
            {"guide-next", "Enter", Tr(state, UiText::Return), true, false, true},
            {"guide-back", "Esc", Tr(state, UiText::Back), true, true, true},
            {"guide-jira", "J", Tr(state, UiText::CopyJira), true, true, false},
            {"guide-hero", "Q", Tr(state, UiText::CopyQaHero), true, true, false},
            {"guide-handoff", "H", Tr(state, UiText::CopyHandoff), true, true, false},
        };
        break;
    }
    guide_items.push_back({"guide-help", "F1", Tr(state, UiText::Help), true, false, true});
    }

    enum class GuideAtlasIcon {
        None,
        A,
        B,
        F1,
        F2,
        F3,
        F4,
        Lmb,
        Enter,
        Escape,
    };

    const auto activate_item = [&](const GuideItem& item) {
        if (std::strcmp(item.id, "guide-prompt-next") == 0) {
            OpenPromptControls(state);
        } else if (std::strcmp(item.id, "guide-prompt-select") == 0 || std::strcmp(item.id, "guide-prompt-ok") == 0) {
            AcceptPrompt(state);
        } else if (std::strcmp(item.id, "guide-prompt-back") == 0) {
            BeginPromptClose(state, false);
        } else if (std::strcmp(item.id, "guide-next") == 0) {
            if (state.current_screen == ShellScreen::Review) {
                StartAction(state, CurrentActionId(state));
            } else if (state.current_screen == ShellScreen::Run && IsActionStillRunning(state)) {
                StartRunRefresh(state, false);
            } else {
                SetScreen(state, NextScreen(state, state.current_screen));
            }
        } else if (std::strcmp(item.id, "guide-back") == 0) {
            RequestBackAction(state);
        } else if (std::strcmp(item.id, "guide-open") == 0) {
            if (!evidence_path.empty()) {
                OpenPath(evidence_path);
            } else {
                OpenPath(artifact_path);
            }
        } else if (std::strcmp(item.id, "guide-reveal") == 0) {
            if (!evidence_path.empty()) {
                RevealPath(evidence_path);
            } else {
                RevealPath(artifact_path);
            }
        } else if (std::strcmp(item.id, "guide-log") == 0 && state.snapshot.has_value()) {
            OpenPath(sg_preflight::native_shell::ToWide(state.snapshot->log_path));
        } else if (std::strcmp(item.id, "guide-report") == 0) {
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
        } else if (std::strcmp(item.id, "guide-jira") == 0) {
            copy_by_key("jira", sg_preflight::native_shell::FormatCopiedJiraStatus(state.language));
        } else if (std::strcmp(item.id, "guide-hero") == 0) {
            copy_by_key("qa_hero", sg_preflight::native_shell::FormatCopiedQaHeroStatus(state.language));
        } else if (std::strcmp(item.id, "guide-handoff") == 0) {
            copy_by_key("handoff", sg_preflight::native_shell::FormatCopiedHandoffStatus(state.language));
        } else if (std::strcmp(item.id, "guide-help") == 0) {
            OpenPrompt(state, Tr(state, UiText::Help), BuildHelpPromptMessage(state), false, false, false);
        }
    };

    const auto resolve_atlas_icon = [&](const GuideItem& item) {
        const bool back_item =
            std::strcmp(item.id, "guide-back") == 0 ||
            std::strcmp(item.id, "guide-prompt-back") == 0;
        if (std::strcmp(item.id, "guide-help") == 0 && HasTexture(g_shell_assets.help_key_f1)) {
            return GuideAtlasIcon::F1;
        }
        if (std::strcmp(item.id, "guide-log") == 0 && HasTexture(g_shell_assets.help_key_f2)) {
            return GuideAtlasIcon::F2;
        }
        if (std::strcmp(item.id, "guide-report") == 0 && HasTexture(g_shell_assets.help_key_f3)) {
            return GuideAtlasIcon::F3;
        }
        if (back_item) {
            return GuideAtlasIcon::Escape;
        }
        if (item.primary) {
            return GuideAtlasIcon::Enter;
        }
        return GuideAtlasIcon::None;
    };

    const auto try_get_atlas = [&](GuideAtlasIcon icon, DdsTextureHandle*& texture, ImVec2& uv_min, ImVec2& uv_max, ImVec2& size) {
        texture = nullptr;
        uv_min = ImVec2(0.0f, 0.0f);
        uv_max = ImVec2(1.0f, 1.0f);
        size = ImVec2(ShellUi(40.0f), ShellUi(40.0f));
        switch (icon) {
        case GuideAtlasIcon::A:
            texture = &g_shell_assets.controller_icons;
            uv_min = ImVec2(0.0f / 512.0f, 0.0f / 128.0f);
            uv_max = ImVec2(40.0f / 512.0f, 40.0f / 128.0f);
            break;
        case GuideAtlasIcon::B:
            texture = &g_shell_assets.controller_icons;
            uv_min = ImVec2(40.0f / 512.0f, 0.0f / 128.0f);
            uv_max = ImVec2(80.0f / 512.0f, 40.0f / 128.0f);
            break;
        case GuideAtlasIcon::F1:
            texture = &g_shell_assets.help_key_f1;
            break;
        case GuideAtlasIcon::F2:
            texture = &g_shell_assets.help_key_f2;
            break;
        case GuideAtlasIcon::F3:
            texture = &g_shell_assets.help_key_f3;
            break;
        case GuideAtlasIcon::F4:
            texture = &g_shell_assets.help_key_f4;
            break;
        case GuideAtlasIcon::Lmb:
            texture = &g_shell_assets.kbm_icons;
            uv_min = ImVec2(0.0f / 384.0f, 0.0f);
            uv_max = ImVec2(128.0f / 384.0f, 1.0f);
            break;
        case GuideAtlasIcon::Enter:
            texture = &g_shell_assets.kbm_icons;
            uv_min = ImVec2(128.0f / 384.0f, 0.0f);
            uv_max = ImVec2(256.0f / 384.0f, 1.0f);
            break;
        case GuideAtlasIcon::Escape:
            texture = &g_shell_assets.kbm_icons;
            uv_min = ImVec2(256.0f / 384.0f, 0.0f);
            uv_max = ImVec2(1.0f, 1.0f);
            break;
        case GuideAtlasIcon::None:
            break;
        }
        return texture != nullptr && HasTexture(*texture);
    };

    const bool compact_guide = IsWorkDisplayMode() && IsDenseWorkScreen(state.current_screen);
    const ImVec2 primary_region_min = ShellPoint(76.0f, compact_guide ? 628.0f : 618.0f);
    const ImVec2 primary_region_max = ShellPoint(1204.0f, 720.0f);
    const ImVec2 secondary_left_region_min = ShellPoint(42.0f, compact_guide ? 688.0f : 680.0f);
    const ImVec2 secondary_left_region_max = ShellPoint(420.0f, 720.0f);
    const ImVec2 secondary_right_region_min = ShellPoint(862.0f, compact_guide ? 688.0f : 680.0f);
    const ImVec2 secondary_right_region_max = ShellPoint(1220.0f, 720.0f);
    ImDrawList* draw = ImGui::GetForegroundDrawList();
    ImFont* primary_font = g_title_font != nullptr ? g_title_font : ImGui::GetFont();
    const float primary_font_size = primary_font == g_title_font ? ShellUi(compact_guide ? 18.8f : 21.8f) : ImGui::GetFontSize();
    ImFont* secondary_font = CurrentSmallFont();
    const float secondary_font_size = secondary_font != nullptr ? (compact_guide ? secondary_font->LegacySize * 0.92f : secondary_font->LegacySize) : ImGui::GetFontSize();

    const auto primary_item_width = [&](const GuideItem& item) {
        DdsTextureHandle* texture = nullptr;
        ImVec2 uv_min;
        ImVec2 uv_max;
        ImVec2 icon_size;
        if (try_get_atlas(resolve_atlas_icon(item), texture, uv_min, uv_max, icon_size)) {
            const ImVec2 text_size = primary_font->CalcTextSizeA(primary_font_size, FLT_MAX, 0.0f, item.label.c_str());
            return icon_size.x + ShellUi(4.0f) + text_size.x;
        }
        const ImVec2 label_size = primary_font->CalcTextSizeA(primary_font_size, FLT_MAX, 0.0f, item.label.c_str());
        const ImVec2 key_size = secondary_font->CalcTextSizeA(secondary_font_size, FLT_MAX, 0.0f, item.key);
        const float key_width = std::max(ShellUi(34.0f), key_size.x + ShellUi(16.0f));
        return key_width + ShellUi(10.0f) + label_size.x;
    };

    const auto secondary_item_width = [&](const GuideItem& item) {
        const ImVec2 label_size = secondary_font->CalcTextSizeA(secondary_font_size, FLT_MAX, 0.0f, item.label.c_str());
        const ImVec2 key_size = secondary_font->CalcTextSizeA(secondary_font_size, FLT_MAX, 0.0f, item.key);
        const float key_width = std::max(ShellUi(24.0f), key_size.x + ShellUi(12.0f));
        return key_width + ShellUi(7.0f) + label_size.x + ShellUi(10.0f);
    };

    const auto draw_primary_item = [&](const GuideItem& item, float x) {
        DdsTextureHandle* texture = nullptr;
        ImVec2 uv_min;
        ImVec2 uv_max;
        ImVec2 icon_size;
        const bool has_atlas = try_get_atlas(resolve_atlas_icon(item), texture, uv_min, uv_max, icon_size);
        const ImVec2 text_size = primary_font->CalcTextSizeA(primary_font_size, FLT_MAX, 0.0f, item.label.c_str());
        const ImVec2 key_size = secondary_font->CalcTextSizeA(secondary_font_size, FLT_MAX, 0.0f, item.key);
        const float key_width = std::max(ShellUi(34.0f), key_size.x + ShellUi(16.0f));
        const float total_width = has_atlas
            ? (icon_size.x + ShellUi(4.0f) + text_size.x)
            : (key_width + ShellUi(10.0f) + text_size.x);
        const ImVec2 min(x, primary_region_min.y);
        const ImVec2 max(x + total_width, primary_region_min.y + std::max(icon_size.y, text_size.y + ShellUi(18.0f)));
        const ImVec2 hit_min(min.x - ShellUi(8.0f), min.y - ShellUi(6.0f));
        const ImVec2 hit_max(max.x + ShellUi(10.0f), max.y + ShellUi(6.0f));

        ImGui::SetCursorScreenPos(hit_min);
        if (!item.enabled) {
            ImGui::BeginDisabled();
        }
        const bool pressed = ImGui::InvisibleButton(item.id, ImVec2(hit_max.x - hit_min.x, hit_max.y - hit_min.y));
        const bool hovered = ImGui::IsItemHovered();
        if (!item.enabled) {
            ImGui::EndDisabled();
        }
        PlayHoverCueIfNeeded(hovered, item.enabled);

        ImVec2 text_pos;
        if (has_atlas) {
            const ImVec2 icon_min(min.x, primary_region_min.y);
            const ImVec2 icon_max(icon_min.x + icon_size.x, icon_min.y + icon_size.y);
            draw->AddImage(ToTextureId(*texture), icon_min, icon_max, uv_min, uv_max, ApplyAlpha(IM_COL32(255, 255, 255, item.enabled ? (hovered ? 255 : 238) : 110), guide_alpha));
            text_pos = ImVec2(icon_max.x + ShellUi(4.0f), primary_region_min.y + ShellUi(9.0f));
        } else {
            const float key_text_alpha = guide_alpha * g_shell_text_visibility;
            const bool help_item = std::strcmp(item.id, "guide-help") == 0;
            const ImU32 key_border = ApplyAlpha(
                help_item
                    ? IM_COL32(244, 244, 236, hovered ? 245 : 228)
                    : (hovered ? IM_COL32(255, 225, 136, 220) : IM_COL32(255, 209, 112, 210)),
                guide_alpha
            );
            const ImU32 key_fill = ApplyAlpha(
                help_item
                    ? IM_COL32(198, 202, 200, hovered ? 244 : 230)
                    : (hovered ? IM_COL32(52, 50, 26, 245) : IM_COL32(38, 36, 22, 228)),
                guide_alpha
            );
            const ImVec2 key_min(min.x, min.y + ShellUi(6.0f));
            const ImVec2 key_max(min.x + key_width, key_min.y + ShellUi(28.0f));
            draw->AddRectFilled(key_min, key_max, key_fill, ShellUi(4.0f));
            draw->AddRect(key_min, key_max, key_border, ShellUi(4.0f), 0, 1.1f);
            if (HasTexture(g_shell_assets.options_static)) {
                DrawTexturedRectRounded(
                    draw,
                    g_shell_assets.options_static,
                    key_min,
                    key_max,
                    ApplyAlpha(
                        help_item ? IM_COL32(255, 255, 255, hovered ? 12 : 8) : IM_COL32(228, 214, 120, hovered ? 22 : 14),
                        guide_alpha
                    ),
                    ShellUi(4.0f)
                );
            }
            draw->AddText(
                secondary_font,
                secondary_font_size,
                ImVec2(key_min.x + ((key_width - key_size.x) * 0.5f), key_min.y + ((key_max.y - key_min.y) - key_size.y) * 0.5f),
                ApplyAlpha(help_item ? IM_COL32(62, 68, 70, item.enabled ? 255 : 170) : IM_COL32(255, 188, 0, item.enabled ? 255 : 170), key_text_alpha),
                item.key
            );
            text_pos = ImVec2(key_max.x + ShellUi(10.0f), primary_region_min.y + ShellUi(9.0f));
        }
        const int label_alpha = item.enabled ? 255 : 148;
        draw->AddText(primary_font, primary_font_size, ImVec2(text_pos.x + ShellUi(2.0f), text_pos.y + ShellUi(2.0f)), ApplyAlpha(IM_COL32(0, 0, 0, label_alpha), guide_alpha * g_shell_text_visibility), item.label.c_str());
        draw->AddText(primary_font, primary_font_size, text_pos, ApplyAlpha(IM_COL32(255, 255, 255, label_alpha), guide_alpha * g_shell_text_visibility), item.label.c_str());

        if (pressed && item.enabled && std::strncmp(item.id, "guide-prompt", 12) != 0) {
            PlayCue(UiCue::Confirm);
        }
        if (pressed && item.enabled) {
            activate_item(item);
        }
        return pressed && item.enabled;
    };

    const auto draw_secondary_item = [&](const GuideItem& item, float x) {
        const ImVec2 label_size = secondary_font->CalcTextSizeA(secondary_font_size, FLT_MAX, 0.0f, item.label.c_str());
        const ImVec2 key_size = secondary_font->CalcTextSizeA(secondary_font_size, FLT_MAX, 0.0f, item.key);
        const float key_width = std::max(ShellUi(24.0f), key_size.x + ShellUi(12.0f));
        const ImVec2 min(x, secondary_left_region_min.y);
        const ImVec2 max(x + secondary_item_width(item), secondary_left_region_min.y + ShellUi(26.0f));
        const ImVec2 hit_min(min.x - ShellUi(6.0f), min.y - ShellUi(4.0f));
        const ImVec2 hit_max(max.x + ShellUi(8.0f), max.y + ShellUi(4.0f));

        ImGui::SetCursorScreenPos(hit_min);
        if (!item.enabled) {
            ImGui::BeginDisabled();
        }
        const bool pressed = ImGui::InvisibleButton(item.id, ImVec2(hit_max.x - hit_min.x, hit_max.y - hit_min.y));
        const bool hovered = ImGui::IsItemHovered();
        if (!item.enabled) {
            ImGui::EndDisabled();
        }
        PlayHoverCueIfNeeded(hovered, item.enabled);

        const float text_alpha = guide_alpha * g_shell_text_visibility;
        const ImU32 key_border = ApplyAlpha(hovered ? IM_COL32(255, 211, 88, 218) : IM_COL32(255, 188, 0, 180), guide_alpha);
        const ImU32 key_fill = ApplyAlpha(hovered ? IM_COL32(38, 48, 28, 225) : IM_COL32(20, 24, 20, 214), guide_alpha);
        const ImU32 label_color = ApplyAlpha(item.enabled ? IM_COL32(226, 237, 231, hovered ? 255 : 222) : IM_COL32(122, 132, 126, 180), text_alpha);
        const ImVec2 key_min(min.x, min.y + ShellUi(1.0f));
        const ImVec2 key_max(min.x + key_width, max.y - ShellUi(1.0f));
        draw->AddRectFilled(key_min, key_max, key_fill, ShellUi(3.0f));
        draw->AddRect(key_min, key_max, key_border, ShellUi(3.0f), 0, 1.0f);
        draw->AddText(secondary_font, secondary_font_size, ImVec2(key_min.x + ((key_width - key_size.x) * 0.5f), key_min.y + ((key_max.y - key_min.y) - key_size.y) * 0.5f), ApplyAlpha(IM_COL32(255, 188, 0, item.enabled ? 255 : 170), text_alpha), item.key);
        draw->AddText(secondary_font, secondary_font_size, ImVec2(key_max.x + ShellUi(7.0f), key_min.y + ((key_max.y - key_min.y) - label_size.y) * 0.5f), label_color, item.label.c_str());

        if (pressed && item.enabled) {
            PlayCue(UiCue::Confirm);
            activate_item(item);
        }
        return pressed && item.enabled;
    };

    std::vector<GuideItem> primary_items;
    std::vector<GuideItem> secondary_items;
    std::optional<GuideItem> centered_primary_item;
    primary_items.reserve(guide_items.size());
    secondary_items.reserve(guide_items.size());
    for (const GuideItem& item : guide_items) {
        if (std::strcmp(item.id, "guide-help") == 0) {
            centered_primary_item = item;
            continue;
        }
        if (item.primary) {
            primary_items.push_back(item);
        } else {
            secondary_items.push_back(item);
        }
    }

    float primary_left_offset = 0.0f;
    const float primary_gap = ShellUi(28.0f);
    for (const GuideItem& item : primary_items) {
        if (item.right_aligned) {
            continue;
        }
        draw_primary_item(item, primary_region_min.x + primary_left_offset);
        primary_left_offset += primary_item_width(item) + primary_gap;
    }

    float primary_right_offset = 0.0f;
    for (auto it = primary_items.rbegin(); it != primary_items.rend(); ++it) {
        if (!it->right_aligned) {
            continue;
        }
        const float width = primary_item_width(*it);
        draw_primary_item(*it, primary_region_max.x - primary_right_offset - width);
        primary_right_offset += width + primary_gap;
    }

    if (centered_primary_item.has_value()) {
        const float width = primary_item_width(*centered_primary_item);
        draw_primary_item(*centered_primary_item, primary_region_min.x + ((primary_region_max.x - primary_region_min.x) - width) * 0.5f);
    }

    float secondary_left_offset = 0.0f;
    const float secondary_gap = ShellUi(10.0f);
    for (const GuideItem& item : secondary_items) {
        if (item.right_aligned) {
            continue;
        }
        const float width = secondary_item_width(item);
        if ((secondary_left_region_min.x + secondary_left_offset + width) > secondary_left_region_max.x) {
            break;
        }
        draw_secondary_item(item, secondary_left_region_min.x + secondary_left_offset);
        secondary_left_offset += width + secondary_gap;
    }

    float secondary_right_offset = 0.0f;
    for (auto it = secondary_items.rbegin(); it != secondary_items.rend(); ++it) {
        if (!it->right_aligned) {
            continue;
        }
        const float width = secondary_item_width(*it);
        const float x = secondary_right_region_max.x - secondary_right_offset - width;
        if (x < secondary_right_region_min.x) {
            continue;
        }
        draw_secondary_item(*it, x);
        secondary_right_offset += width + secondary_gap;
    }

    ImGui::SetCursorScreenPos(ShellPoint(0.0f, 718.0f));
    ImGui::Dummy(ShellSize(1.0f, 1.0f));
}

void HandleShellHotkeys(ShellState& state) {
    if (state.exit_transition_active) {
        return;
    }

    if (state.prompt_visible) {
        if (state.prompt_closing) {
            return;
        }

        if (state.prompt_confirmation && state.prompt_controls_visible && (ImGui::IsKeyPressed(ImGuiKey_UpArrow, false) || ImGui::IsKeyPressed(ImGuiKey_LeftArrow, false))) {
            SetPromptSelection(state, 0);
            return;
        }

        if (state.prompt_confirmation && state.prompt_controls_visible && (ImGui::IsKeyPressed(ImGuiKey_DownArrow, false) || ImGui::IsKeyPressed(ImGuiKey_RightArrow, false))) {
            SetPromptSelection(state, 1);
            return;
        }

        if (ImGui::IsKeyPressed(ImGuiKey_Escape, false)) {
            BeginPromptClose(state, false);
            return;
        }

        if (ImGui::IsKeyPressed(ImGuiKey_Enter, false) || ImGui::IsKeyPressed(ImGuiKey_KeypadEnter, false)) {
            if (state.prompt_confirmation && !state.prompt_controls_visible) {
                OpenPromptControls(state);
            } else if (!state.prompt_confirmation || state.prompt_selected_index == 0) {
                AcceptPrompt(state);
            } else {
                BeginPromptClose(state, false);
            }
            return;
        }

        return;
    }

    if (ImGui::IsKeyPressed(ImGuiKey_Escape, false)) {
        RequestBackAction(state);
        return;
    }

    if (ImGui::IsKeyPressed(ImGuiKey_F1, false)) {
        OpenPrompt(state, Tr(state, UiText::Help), BuildHelpPromptMessage(state), false, false, false);
        return;
    }

    if (state.current_screen == ShellScreen::Run) {
        if (ImGui::IsKeyPressed(ImGuiKey_F2, false) && state.snapshot.has_value()) {
            OpenPath(sg_preflight::native_shell::ToWide(state.snapshot->log_path));
            return;
        }
        if (ImGui::IsKeyPressed(ImGuiKey_F3, false)) {
            if (state.run_snapshot.has_value()) {
                for (const auto& artifact : state.run_snapshot->artifacts) {
                    if (artifact.label == "HTML report") {
                        OpenPath(sg_preflight::native_shell::ToWide(artifact.path));
                        return;
                    }
                }
            } else if (state.snapshot.has_value() && !state.snapshot->latest_run_links.html_report.empty()) {
                OpenPath(sg_preflight::native_shell::ToWide(state.snapshot->latest_run_links.html_report));
                return;
            }
        }
    }

    if (!ImGui::IsKeyPressed(ImGuiKey_Enter, false) && !ImGui::IsKeyPressed(ImGuiKey_KeypadEnter, false)) {
        switch (state.current_screen) {
        case ShellScreen::Language:
            if (ImGui::IsKeyPressed(ImGuiKey_LeftArrow, false)) {
                MoveLanguageSelection(state, -1, 0);
            } else if (ImGui::IsKeyPressed(ImGuiKey_RightArrow, false)) {
                MoveLanguageSelection(state, 1, 0);
            } else if (ImGui::IsKeyPressed(ImGuiKey_UpArrow, false)) {
                MoveLanguageSelection(state, 0, -1);
            } else if (ImGui::IsKeyPressed(ImGuiKey_DownArrow, false)) {
                MoveLanguageSelection(state, 0, 1);
            }
            break;
        case ShellScreen::Run:
            if (ImGui::IsKeyPressed(ImGuiKey_L, false) && state.snapshot.has_value()) {
                OpenPath(sg_preflight::native_shell::ToWide(state.snapshot->log_path));
            }
            if (ImGui::IsKeyPressed(ImGuiKey_P, false)) {
                if (state.run_snapshot.has_value()) {
                    for (const auto& artifact : state.run_snapshot->artifacts) {
                        if (artifact.label == "HTML report") {
                            OpenPath(sg_preflight::native_shell::ToWide(artifact.path));
                            break;
                        }
                    }
                } else if (state.snapshot.has_value() && !state.snapshot->latest_run_links.html_report.empty()) {
                    OpenPath(sg_preflight::native_shell::ToWide(state.snapshot->latest_run_links.html_report));
                }
            }
            break;
        case ShellScreen::Evidence:
            if (ImGui::IsKeyPressed(ImGuiKey_O, false)) {
                const std::wstring path = SelectedEvidencePath(state);
                if (!path.empty()) {
                    OpenPath(path);
                }
            }
            if (ImGui::IsKeyPressed(ImGuiKey_R, false)) {
                const std::wstring path = SelectedEvidencePath(state);
                if (!path.empty()) {
                    RevealPath(path);
                }
            }
            if (ImGui::IsKeyPressed(ImGuiKey_J, false)) {
                for (const CopyItem& item : CombinedCopyItems(state)) {
                    if (item.key == "jira" && !item.text.empty() && CopyText(sg_preflight::native_shell::ToWide(item.text))) {
                        state.status_line = sg_preflight::native_shell::FormatCopiedJiraStatus(state.language);
                        break;
                    }
                }
            }
            break;
        case ShellScreen::Files:
            if (ImGui::IsKeyPressed(ImGuiKey_O, false)) {
                const std::wstring path = SelectedArtifactPath(state);
                if (!path.empty()) {
                    OpenPath(path);
                }
            }
            if (ImGui::IsKeyPressed(ImGuiKey_R, false)) {
                const std::wstring path = SelectedArtifactPath(state);
                if (!path.empty()) {
                    RevealPath(path);
                }
            }
            if (ImGui::IsKeyPressed(ImGuiKey_P, false) && state.run_snapshot.has_value()) {
                for (const auto& artifact : state.run_snapshot->artifacts) {
                    if (artifact.label == "HTML report") {
                        OpenPath(sg_preflight::native_shell::ToWide(artifact.path));
                        break;
                    }
                }
            }
            [[fallthrough]];
        case ShellScreen::Stages:
        {
            const bool copy_jira = ImGui::IsKeyPressed(ImGuiKey_J, false);
            const bool copy_hero = ImGui::IsKeyPressed(ImGuiKey_Q, false);
            const bool copy_handoff = ImGui::IsKeyPressed(ImGuiKey_H, false);
            if (copy_jira || copy_hero || copy_handoff) {
                const std::string wanted_key =
                    copy_jira ? "jira" :
                    copy_hero ? "qa_hero" :
                    "handoff";
                const std::string status =
                    wanted_key == "jira" ? sg_preflight::native_shell::FormatCopiedJiraStatus(state.language) :
                    wanted_key == "qa_hero" ? sg_preflight::native_shell::FormatCopiedQaHeroStatus(state.language) :
                    sg_preflight::native_shell::FormatCopiedHandoffStatus(state.language);
                for (const CopyItem& item : CombinedCopyItems(state)) {
                    if (item.key == wanted_key && !item.text.empty() && CopyText(sg_preflight::native_shell::ToWide(item.text))) {
                        state.status_line = status;
                        break;
                    }
                }
            }
            break;
        }
        default:
            break;
        }
        return;
    }

    if (state.current_screen == ShellScreen::Review) {
        if (SelectedActionReady(state)) {
            StartAction(state, CurrentActionId(state));
        }
        return;
    }

    if (state.current_screen == ShellScreen::Run && IsActionStillRunning(state)) {
        StartRunRefresh(state, false);
        return;
    }

    if (CanAdvanceFromPage(state, state.current_screen)) {
        SetScreen(state, NextScreen(state, state.current_screen));
    }
}

void DrawPromptPlate(ImDrawList* draw, const ImVec2& min, const ImVec2& max, float alpha, bool selected = false) {
    const float cut = ShellUi(28.0f);
    const std::array<ImVec2, 5> points = {{
        min,
        ImVec2(max.x, min.y),
        ImVec2(max.x, max.y - cut),
        ImVec2(max.x - cut, max.y),
        ImVec2(min.x, max.y),
    }};
    std::array<ImVec2, 5> shadow_points = points;
    for (ImVec2& point : shadow_points) {
        point.x += ShellUi(3.0f);
        point.y += ShellUi(4.0f);
    }

    const bool work_mode = IsWorkDisplayMode();
    draw->AddConvexPolyFilled(shadow_points.data(), static_cast<int>(shadow_points.size()), IM_COL32(0, 0, 0, static_cast<int>((work_mode ? 42.0f : 92.0f) * alpha)));
    draw->AddConvexPolyFilled(points.data(), static_cast<int>(points.size()), IM_COL32(224, 228, 226, static_cast<int>((work_mode ? 244.0f : 232.0f) * alpha)));
    draw->AddConvexPolyFilled(points.data(), static_cast<int>(points.size()), selected ? IM_COL32(255, 214, 92, static_cast<int>((work_mode ? 84.0f : 118.0f) * alpha)) : IM_COL32(130, 134, 136, static_cast<int>((work_mode ? 18.0f : 42.0f) * alpha)));
    draw->AddPolyline(points.data(), static_cast<int>(points.size()), IM_COL32(250, 250, 245, static_cast<int>(255.0f * alpha)), ImDrawFlags_Closed, 1.3f);
}

void DrawPromptTextureSlice(
    ImDrawList* draw,
    const DdsTextureHandle& texture,
    const ImVec2& min,
    const ImVec2& max,
    const ImVec2& uv_min,
    const ImVec2& uv_max,
    ImU32 tint
) {
    if (!HasTexture(texture)) {
        return;
    }
    draw->AddImage(ToTextureId(texture), min, max, uv_min, uv_max, tint);
}

void DrawPromptTextStyled(
    ImDrawList* draw,
    ImFont* font,
    float font_size,
    const ImVec2& position,
    ImU32 text_color,
    float alpha,
    const char* text,
    float wrap_width = 0.0f
) {
    if (font == nullptr || text == nullptr || *text == '\0') {
        return;
    }

    const ImVec2 snapped_position(std::round(position.x), std::round(position.y));
    const float shadow_offset = ShellUi(2.0f);
    const ImVec2 shadow_pos(
        std::round(snapped_position.x + shadow_offset),
        std::round(snapped_position.y + shadow_offset)
    );
    draw->AddText(font, font_size, shadow_pos, IM_COL32(0, 0, 0, static_cast<int>(180.0f * alpha)), text, nullptr, wrap_width);
    draw->AddText(font, font_size, snapped_position, text_color, text, nullptr, wrap_width);
}

std::vector<std::string> SplitPromptParagraph(ImFont* font, float font_size, float max_width, const std::string& text) {
    std::vector<std::string> lines;
    if (font == nullptr || text.empty()) {
        return lines;
    }

    const float scale = font_size / font->LegacySize;
    const char* text_start = text.c_str();
    const char* text_end = text_start + text.size();
    const char* cursor = text_start;

    while (cursor < text_end) {
        while (cursor < text_end && (*cursor == '\r' || *cursor == '\n')) {
            ++cursor;
        }
        if (cursor >= text_end) {
            break;
        }

        const char* line_end = max_width > 0.0f
            ? font->CalcWordWrapPositionA(scale, cursor, text_end, max_width)
            : text_end;
        if (line_end == cursor) {
            line_end = cursor + 1;
        }

        const char* newline = static_cast<const char*>(memchr(cursor, '\n', static_cast<size_t>(text_end - cursor)));
        if (newline != nullptr && newline < line_end) {
            line_end = newline;
        }

        const char* trimmed_end = line_end;
        while (trimmed_end > cursor && (trimmed_end[-1] == ' ' || trimmed_end[-1] == '\t' || trimmed_end[-1] == '\r')) {
            --trimmed_end;
        }
        lines.emplace_back(cursor, trimmed_end);

        cursor = line_end;
        while (cursor < text_end && (*cursor == ' ' || *cursor == '\t')) {
            ++cursor;
        }
        if (cursor < text_end && *cursor == '\r') {
            ++cursor;
        }
        if (cursor < text_end && *cursor == '\n') {
            ++cursor;
        }
    }

    if (lines.empty()) {
        lines.emplace_back();
    }
    return lines;
}

ImVec2 MeasurePromptParagraph(ImFont* font, float font_size, float line_margin, const std::vector<std::string>& lines) {
    float width = 0.0f;
    float height = 0.0f;
    for (size_t index = 0; index < lines.size(); ++index) {
        const ImVec2 line_size = font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, lines[index].c_str());
        width = std::max(width, line_size.x);
        height += line_size.y;
        if (index + 1U < lines.size()) {
            height += ShellUi(line_margin);
        }
    }
    return ImVec2(width, height);
}

void DrawPromptParagraphStyled(
    ImDrawList* draw,
    ImFont* font,
    float font_size,
    float max_width,
    const ImVec2& center,
    float line_margin,
    ImU32 text_color,
    float alpha,
    const std::string& text
) {
    const std::vector<std::string> lines = SplitPromptParagraph(font, font_size, max_width, text);
    const ImVec2 paragraph_size = MeasurePromptParagraph(font, font_size, line_margin, lines);
    float y = std::round(center.y - paragraph_size.y * 0.5f);

    for (size_t index = 0; index < lines.size(); ++index) {
        const ImVec2 line_size = font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, lines[index].c_str());
        const ImVec2 line_pos(
            std::round(center.x - line_size.x * 0.5f),
            y
        );
        DrawPromptTextStyled(draw, font, font_size, line_pos, text_color, alpha, lines[index].c_str());
        y += line_size.y;
        if (index + 1U < lines.size()) {
            y += ShellUi(line_margin);
        }
    }
}

float DrawLeftAlignedPromptParagraphStyled(
    ImDrawList* draw,
    ImFont* font,
    float font_size,
    float max_width,
    const ImVec2& min,
    float line_margin,
    ImU32 text_color,
    float alpha,
    const std::string& text
) {
    const std::vector<std::string> lines = SplitPromptParagraph(font, font_size, max_width, text);
    float y = std::round(min.y);
    for (size_t index = 0; index < lines.size(); ++index) {
        DrawPromptTextStyled(
            draw,
            font,
            font_size,
            ImVec2(std::round(min.x), y),
            text_color,
            alpha,
            lines[index].c_str()
        );
        const ImVec2 line_size = font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, lines[index].c_str());
        y += line_size.y;
        if (index + 1U < lines.size()) {
            y += ShellUi(line_margin);
        }
    }
    return y;
}

void DrawPauseContainerChrome(ImDrawList* draw, const ImVec2& min, const ImVec2& max, float alpha) {
    if (!HasTexture(g_shell_assets.general_window)) {
        DrawPromptPlate(draw, min, max, alpha);
        return;
    }

    const float common_width = ShellUi(35.0f);
    const float common_height = ShellUi(35.0f);
    const float bottom_height = ShellUi(5.0f);
    const ImU32 tint = IM_COL32(255, 255, 255, static_cast<int>(255.0f * alpha));

    DrawPromptTextureSlice(draw, g_shell_assets.general_window, min, ImVec2(min.x + common_width, min.y + common_height), ImVec2(0.0f / 128.0f, 0.0f / 512.0f), ImVec2(35.0f / 128.0f, 35.0f / 512.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.general_window, ImVec2(min.x + common_width, min.y), ImVec2(max.x - common_width, min.y + common_height), ImVec2(51.0f / 128.0f, 0.0f / 512.0f), ImVec2(56.0f / 128.0f, 35.0f / 512.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.general_window, ImVec2(max.x - common_width, min.y), ImVec2(max.x, min.y + common_height), ImVec2(70.0f / 128.0f, 0.0f / 512.0f), ImVec2(105.0f / 128.0f, 35.0f / 512.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.general_window, ImVec2(min.x, min.y + common_height), ImVec2(min.x + common_width, max.y - common_height), ImVec2(0.0f / 128.0f, 35.0f / 512.0f), ImVec2(35.0f / 128.0f, 270.0f / 512.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.general_window, ImVec2(min.x + common_width, min.y + common_height), ImVec2(max.x - common_width, max.y - common_height), ImVec2(51.0f / 128.0f, 35.0f / 512.0f), ImVec2(56.0f / 128.0f, 270.0f / 512.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.general_window, ImVec2(max.x - common_width, min.y + common_height), ImVec2(max.x, max.y - common_height), ImVec2(70.0f / 128.0f, 35.0f / 512.0f), ImVec2(105.0f / 128.0f, 270.0f / 512.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.general_window, ImVec2(min.x, max.y - common_height), ImVec2(min.x + common_width, max.y + bottom_height), ImVec2(0.0f / 128.0f, 270.0f / 512.0f), ImVec2(35.0f / 128.0f, 310.0f / 512.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.general_window, ImVec2(min.x + common_width, max.y - common_height), ImVec2(max.x - common_width, max.y + bottom_height), ImVec2(51.0f / 128.0f, 270.0f / 512.0f), ImVec2(56.0f / 128.0f, 310.0f / 512.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.general_window, ImVec2(max.x - common_width, max.y - common_height), ImVec2(max.x, max.y + bottom_height), ImVec2(70.0f / 128.0f, 270.0f / 512.0f), ImVec2(105.0f / 128.0f, 310.0f / 512.0f), tint);
}

void DrawSelectionContainerChrome(ImDrawList* draw, const ImVec2& min, const ImVec2& max, float alpha, bool fade_top) {
    if (!HasTexture(g_shell_assets.select)) {
        DrawPromptPlate(draw, min, max, alpha, true);
        return;
    }

    const float common_width = ShellUi(11.0f);
    const float common_height = ShellUi(24.0f);
    const ImU32 tint = IM_COL32(255, 255, 255, static_cast<int>(255.0f * alpha));

    if (fade_top) {
        DrawPromptTextureSlice(draw, g_shell_assets.select, min, ImVec2(min.x + common_width, max.y), ImVec2(0.0f / 64.0f, 0.0f / 64.0f), ImVec2(11.0f / 64.0f, 50.0f / 64.0f), tint);
        DrawPromptTextureSlice(draw, g_shell_assets.select, ImVec2(min.x + common_width, min.y), ImVec2(max.x - common_width, max.y), ImVec2(11.0f / 64.0f, 0.0f / 64.0f), ImVec2(19.0f / 64.0f, 50.0f / 64.0f), tint);
        DrawPromptTextureSlice(draw, g_shell_assets.select, ImVec2(max.x - common_width, min.y), max, ImVec2(19.0f / 64.0f, 0.0f / 64.0f), ImVec2(30.0f / 64.0f, 50.0f / 64.0f), tint);
        return;
    }

    DrawPromptTextureSlice(draw, g_shell_assets.select, min, ImVec2(min.x + common_width, min.y + common_height), ImVec2(34.0f / 64.0f, 0.0f / 64.0f), ImVec2(45.0f / 64.0f, 24.0f / 64.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.select, ImVec2(min.x + common_width, min.y), ImVec2(max.x - common_width, min.y + common_height), ImVec2(45.0f / 64.0f, 0.0f / 64.0f), ImVec2(53.0f / 64.0f, 24.0f / 64.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.select, ImVec2(max.x - common_width, min.y), ImVec2(max.x, min.y + common_height), ImVec2(53.0f / 64.0f, 0.0f / 64.0f), ImVec2(1.0f, 24.0f / 64.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.select, ImVec2(min.x, min.y + common_height), ImVec2(min.x + common_width, max.y - common_height), ImVec2(34.0f / 64.0f, 24.0f / 64.0f), ImVec2(45.0f / 64.0f, 26.0f / 64.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.select, ImVec2(min.x + common_width, min.y + common_height), ImVec2(max.x - common_width, max.y - common_height), ImVec2(45.0f / 64.0f, 24.0f / 64.0f), ImVec2(53.0f / 64.0f, 26.0f / 64.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.select, ImVec2(max.x - common_width, min.y + common_height), ImVec2(max.x, max.y - common_height), ImVec2(53.0f / 64.0f, 24.0f / 64.0f), ImVec2(1.0f, 26.0f / 64.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.select, ImVec2(min.x, max.y - common_height), ImVec2(min.x + common_width, max.y), ImVec2(34.0f / 64.0f, 26.0f / 64.0f), ImVec2(45.0f / 64.0f, 50.0f / 64.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.select, ImVec2(min.x + common_width, max.y - common_height), ImVec2(max.x - common_width, max.y), ImVec2(45.0f / 64.0f, 26.0f / 64.0f), ImVec2(53.0f / 64.0f, 50.0f / 64.0f), tint);
    DrawPromptTextureSlice(draw, g_shell_assets.select, ImVec2(max.x - common_width, max.y - common_height), max, ImVec2(53.0f / 64.0f, 26.0f / 64.0f), ImVec2(1.0f, 50.0f / 64.0f), tint);
}

void RenderPromptModal(ShellState& state) {
    if (!state.prompt_visible) {
        return;
    }
    ImGui::SetNextFrameWantCaptureMouse(true);
    ImGui::SetNextFrameWantCaptureKeyboard(true);

    const float alpha = PromptVisibilityAlpha(state);
    if (alpha <= 0.0f) {
        return;
    }

    ImDrawList* draw = ImGui::GetForegroundDrawList();
    const ImVec2 display = ImGui::GetIO().DisplaySize;
    const float chooser_open = state.prompt_controls_visible
        ? SmoothStep(static_cast<float>(std::clamp((ImGui::GetTime() - state.prompt_controls_opened_at) * 60.0 / 11.0, 0.0, 1.0)))
        : 0.0f;
    const bool information_prompt = !state.prompt_confirmation;
    const float background_overlay_alpha = alpha * (state.prompt_controls_visible ? (1.0f - chooser_open) : 1.0f);
    draw->AddRectFilled(ImVec2(0.0f, 0.0f), display, IM_COL32(0, 0, 0, static_cast<int>(190.0f * background_overlay_alpha)));

    if (BeginCanvasOverlayRegion("prompt-blocker", ImVec2(0.0f, 0.0f), display)) {
        const bool blocker_clicked = ImGui::InvisibleButton("prompt-blocker-input", display);
        if (blocker_clicked && !state.prompt_closing) {
            if (state.prompt_confirmation && !state.prompt_controls_visible) {
                OpenPromptControls(state);
            } else if (!state.prompt_confirmation) {
                AcceptPrompt(state);
            }
        }
        EndCanvasOverlayRegion();
    }

    ImFont* prompt_banner_font = CurrentBodyFont();
    const float prompt_banner_font_size = information_prompt ? ShellUi(19.0f) : ShellUi(28.0f);
    const float prompt_banner_wrap_width = information_prompt
        ? std::min(ShellUi(640.0f), display.x - ShellUi(220.0f))
        : std::min(ShellUi(820.0f), display.x - ShellUi(110.0f));
    const ImVec2 prompt_center(
        display.x * 0.5f,
        information_prompt ? (display.y * 0.47f) : (display.y * 0.5f + ShellUi(3.0f))
    );
    const std::vector<std::string> prompt_lines = SplitPromptParagraph(
        prompt_banner_font,
        prompt_banner_font_size,
        prompt_banner_wrap_width,
        state.prompt_message
    );
    const ImVec2 prompt_text_size = MeasurePromptParagraph(
        prompt_banner_font,
        prompt_banner_font_size,
        5.0f,
        prompt_lines
    );
    const ImVec2 banner_half(
        std::max(information_prompt ? ShellUi(220.0f) : ShellUi(190.0f), prompt_text_size.x * 0.5f + ShellUi(37.0f)),
        std::max(information_prompt ? ShellUi(120.0f) : ShellUi(54.0f), prompt_text_size.y * 0.5f + ShellUi(45.0f))
    );
    const float banner_open = SmoothStep(static_cast<float>(std::clamp((ImGui::GetTime() - state.prompt_opened_at) * 60.0 / 11.0, 0.0, 1.0)));
    const float banner_alpha = alpha * (state.prompt_controls_visible ? LerpFloat(1.0f, 0.34f, chooser_open) : 1.0f);
    const ImVec2 banner_current_half(banner_half.x * banner_open, banner_half.y * banner_open);
    const ImVec2 banner_min(prompt_center.x - banner_current_half.x, prompt_center.y - banner_current_half.y);
    const ImVec2 banner_max(prompt_center.x + banner_current_half.x, prompt_center.y + banner_current_half.y);
    DrawPauseContainerChrome(draw, banner_min, banner_max, banner_alpha);

    if (banner_open > 0.0f) {
        draw->PushClipRect(banner_min, banner_max, true);
        DrawPromptParagraphStyled(
            draw,
            prompt_banner_font,
            prompt_banner_font_size,
            prompt_banner_wrap_width,
            prompt_center,
            5.0f,
            IM_COL32(255, 255, 255, static_cast<int>(255.0f * banner_alpha)),
            banner_alpha,
            state.prompt_message
        );
        draw->PopClipRect();
    }

    if (!state.prompt_controls_visible) {
        return;
    }

    const bool confirmation = state.prompt_confirmation;
    draw->AddRectFilled(ImVec2(0.0f, 0.0f), display, IM_COL32(0, 0, 0, static_cast<int>(190.0f * alpha * chooser_open)));
    const std::vector<std::string> labels = confirmation
        ? std::vector<std::string>{state.prompt_accept_label, state.prompt_cancel_label}
        : std::vector<std::string>{state.prompt_accept_label};
    ImFont* font = CurrentBodyFont();
    const float font_size = ShellUi(28.0f);
    float widest_label = 0.0f;
    for (const std::string& label : labels) {
        widest_label = std::max(widest_label, font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, label.c_str()).x);
    }
    const float row_height = ShellUi(57.0f);
    const float row_gap = 0.0f;
    const float button_width = std::max(ShellUi(162.0f), widest_label + ShellUi(40.0f));
    const float chooser_pad_x = ShellUi(23.0f);
    const float chooser_pad_y = ShellUi(30.0f);
    const ImVec2 chooser_center = prompt_center;
    const ImVec2 chooser_half(button_width * 0.5f + chooser_pad_x, (row_height * 0.5f * static_cast<float>(labels.size())) + chooser_pad_y);
    const ImVec2 chooser_current_half(chooser_half.x * chooser_open, chooser_half.y * chooser_open);
    const ImVec2 chooser_min(chooser_center.x - chooser_current_half.x, chooser_center.y - chooser_current_half.y);
    const ImVec2 chooser_max(chooser_center.x + chooser_current_half.x, chooser_center.y + chooser_current_half.y);
    DrawPauseContainerChrome(draw, chooser_min, chooser_max, alpha * chooser_open);
    if (chooser_open < 0.999f) {
        return;
    }

    if (!BeginCanvasOverlayRegion("prompt-choice-content", ImVec2(chooser_min.x + chooser_pad_x, chooser_min.y + chooser_pad_y), ImVec2(chooser_max.x - chooser_pad_x, chooser_max.y - chooser_pad_y))) {
        EndCanvasOverlayRegion();
        return;
    }
    std::vector<ImVec2> row_mins;
    std::vector<ImVec2> row_maxs;
    row_mins.reserve(labels.size());
    row_maxs.reserve(labels.size());
    ImVec2 selected_min;
    ImVec2 selected_max;
    bool selected_rect_set = false;
    for (size_t index = 0; index < labels.size(); ++index) {
        if (index > 0U) {
            ImGui::Dummy(ImVec2(0.0f, row_gap));
        }

        const bool selected = state.prompt_selected_index == static_cast<int>(index);
        const std::string row_id = "prompt-choice-" + std::to_string(index);
        const ImVec2 row_size(button_width, row_height);
        const bool pressed = ImGui::InvisibleButton(row_id.c_str(), row_size);
        const bool hovered = ImGui::IsItemHovered();
        if (hovered) {
            SetPromptSelection(state, static_cast<int>(index), false);
        }
        PlayHoverCueIfNeeded(hovered, !state.prompt_closing);

        const ImVec2 min = ImGui::GetItemRectMin();
        const ImVec2 max = ImGui::GetItemRectMax();
        row_mins.push_back(min);
        row_maxs.push_back(max);
        if (selected) {
            selected_min = min;
            selected_max = max;
            selected_rect_set = true;
        }

        if (pressed && !state.prompt_closing) {
            if (!confirmation || index == 0U) {
                AcceptPrompt(state);
            } else {
                BeginPromptClose(state, false);
            }
        }
    }

    if (selected_rect_set) {
        float selection_offset = 0.0f;
        if (state.prompt_selection_changed_at >= 0.0) {
            const float motion = std::clamp(static_cast<float>((ImGui::GetTime() - state.prompt_selection_changed_at) * 60.0 / 8.0), 0.0f, 1.0f);
            selection_offset = static_cast<float>(state.prompt_previous_selected_index - state.prompt_selected_index) * (row_height + row_gap) * std::pow(1.0f - motion, 3.0f);
        }
        DrawSelectionContainerChrome(
            draw,
            ImVec2(selected_min.x, selected_min.y + selection_offset),
            ImVec2(selected_max.x, selected_max.y + selection_offset),
            alpha,
            true
        );
    }

    for (size_t index = 0; index < labels.size(); ++index) {
        const bool selected = state.prompt_selected_index == static_cast<int>(index);
        const ImVec2 text_size = font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, labels[index].c_str());
        const ImVec2 text_pos(
            row_mins[index].x + ((row_maxs[index].x - row_mins[index].x) - text_size.x) * 0.5f,
            row_mins[index].y + ((row_maxs[index].y - row_mins[index].y) - text_size.y) * 0.5f - ShellUi(1.0f)
        );
        DrawPromptTextStyled(
            draw,
            font,
            font_size,
            text_pos,
            selected ? IM_COL32(255, 128, 0, static_cast<int>(255.0f * alpha)) : IM_COL32(255, 255, 255, static_cast<int>(255.0f * alpha)),
            alpha,
            labels[index].c_str()
        );
    }

    EndCanvasOverlayRegion();
}

float ShellContentAlpha(const ShellState& state) {
    if (!state.exit_transition_active) {
        return 1.0f - ExitBlackFadeProgress(state);
    }
    return std::clamp(ShellChromeLifecycleMotion(), 0.0f, 1.0f);
}

void RenderExitFade(const ShellState& state) {
    if (!state.exit_transition_active || state.exit_transition_started_at < 0.0) {
        return;
    }
    const float motion = ExitBlackFadeProgress(state);
    ImGui::GetForegroundDrawList()->AddRectFilled(ImVec2(0.0f, 0.0f), ImGui::GetIO().DisplaySize, IM_COL32(0, 0, 0, static_cast<int>(255.0f * motion)));
}

void RenderShell(ShellState& state) {
    g_shell_text_visibility = ShellExitTextVisibility(state);
    ImGui::GetIO().FontDefault = CurrentBodyFont();
    DrawBackdropChrome(state);

    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(viewport->Pos);
    ImGui::SetNextWindowSize(viewport->Size);
    ImGui::SetNextWindowViewport(viewport->ID);

    constexpr ImGuiWindowFlags flags =
        ImGuiWindowFlags_NoDecoration |
        ImGuiWindowFlags_NoMove |
        ImGuiWindowFlags_NoResize |
        ImGuiWindowFlags_NoBackground |
        ImGuiWindowFlags_NoSavedSettings;

    if (!ImGui::Begin("sg-preflight-native-shell", nullptr, flags)) {
        ImGui::End();
        return;
    }

    FinalizePromptIfReady(state);
    HandleShellHotkeys(state);
    ImGui::PushStyleVar(ImGuiStyleVar_Alpha, ShellContentAlpha(state));
    if (state.prompt_visible) {
        ImGui::PushItemFlag(ImGuiItemFlags_Disabled, true);
    }

    switch (state.current_screen) {
    case ShellScreen::Language:
    case ShellScreen::Introduction:
    case ShellScreen::Select:
    case ShellScreen::Review:
    case ShellScreen::Run:
    case ShellScreen::Evidence:
    case ShellScreen::Files:
    case ShellScreen::Environment:
    case ShellScreen::Stages:
        if (BeginLayoutRegionAt("screen-region", 0.0f, 0.0f, 1280.0f, 720.0f)) {
            RenderCurrentScreen(state);
            RenderWizardNavigation(state);
        }
        EndLayoutRegion();
        break;
    }

    if (state.prompt_visible) {
        ImGui::PopItemFlag();
    }

    ImGui::PopStyleVar();
    DrawInstallerBorders();
    RenderButtonGuide(state);
    RenderPromptModal(state);
    RenderExitFade(state);
    ImGui::End();
}

}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    BackendConfig backend = ParseArguments();
    ConfigureCaptureRequestDirectory();

    ImGui_ImplWin32_EnableDpiAwareness();

    WNDCLASSEXW window_class{};
    window_class.cbSize = sizeof(window_class);
    window_class.style = CS_CLASSDC;
    window_class.lpfnWndProc = WndProc;
    window_class.hInstance = instance;
    window_class.lpszClassName = L"SGPreflightNativeShell";
    RegisterClassExW(&window_class);

    const RECT monitor_rect = PrimaryMonitorRect();
    const int monitor_width = monitor_rect.right - monitor_rect.left;
    const int monitor_height = monitor_rect.bottom - monitor_rect.top;
    const int requested_width = g_window_options.width > 0 ? g_window_options.width : monitor_width;
    const int requested_height = g_window_options.height > 0 ? g_window_options.height : monitor_height;
    const bool use_fullscreen = g_window_options.fullscreen && g_window_options.width <= 0 && g_window_options.height <= 0;
    const DWORD window_style = use_fullscreen ? WS_POPUP : WS_OVERLAPPEDWINDOW;
    const UINT system_dpi = SystemDpi();
    const int windowed_physical_width = MulDiv(requested_width, static_cast<int>(system_dpi), 96);
    const int windowed_physical_height = MulDiv(requested_height, static_cast<int>(system_dpi), 96);

    RECT window_rect{
        0,
        0,
        use_fullscreen ? requested_width : windowed_physical_width,
        use_fullscreen ? requested_height : windowed_physical_height
    };
    if (!use_fullscreen) {
        AdjustWindowRectForDpi(window_rect, window_style, system_dpi);
    }
    const int window_width = window_rect.right - window_rect.left;
    const int window_height = window_rect.bottom - window_rect.top;
    const int window_x = use_fullscreen
        ? monitor_rect.left
        : monitor_rect.left + std::max(0, (monitor_width - window_width) / 2);
    const int window_y = use_fullscreen
        ? monitor_rect.top
        : monitor_rect.top + std::max(0, (monitor_height - window_height) / 2);

    HWND window_handle = CreateWindowW(
        window_class.lpszClassName,
        L"SERGFX QA Review",
        window_style,
        window_x,
        window_y,
        window_width,
        window_height,
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

    ShowWindow(window_handle, SW_SHOW);
    UpdateWindow(window_handle);

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    BindShellIniFile(io, GetExecutableDirectory() / "imgui.ini");
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    io.ConfigWindowsMoveFromTitleBarOnly = true;
    LoadShellFonts(io, std::filesystem::path(backend.workspace_root));
    ImGui::StyleColorsDark();
    ApplyStyle();

    ImGui_ImplWin32_Init(window_handle);
    ImGui_ImplDX12_InitInfo init_info{};
    init_info.Device = g_device;
    init_info.CommandQueue = g_command_queue;
    init_info.NumFramesInFlight = static_cast<int>(kFrameCount);
    init_info.RTVFormat = DXGI_FORMAT_R8G8B8A8_UNORM;
    init_info.DSVFormat = DXGI_FORMAT_UNKNOWN;
    init_info.SrvDescriptorHeap = g_srv_descriptor_heap;
    init_info.SrvDescriptorAllocFn = [](ImGui_ImplDX12_InitInfo*, D3D12_CPU_DESCRIPTOR_HANDLE* out_cpu_handle, D3D12_GPU_DESCRIPTOR_HANDLE* out_gpu_handle) {
        g_srv_descriptor_allocator.Alloc(out_cpu_handle, out_gpu_handle);
    };
    init_info.SrvDescriptorFreeFn = [](ImGui_ImplDX12_InitInfo*, D3D12_CPU_DESCRIPTOR_HANDLE cpu_handle, D3D12_GPU_DESCRIPTOR_HANDLE gpu_handle) {
        g_srv_descriptor_allocator.Free(cpu_handle, gpu_handle);
    };
    ImGui_ImplDX12_Init(&init_info);

    g_shell_display_mode = ShellDisplayMode::Cinematic;
    const bool music_enabled_preference = LoadMusicPreferenceFromIni();
    const bool sfx_enabled_preference = LoadSfxPreferenceFromIni();
    LoadShellAssets(std::filesystem::path(backend.workspace_root));
    LoadShellAudio(std::filesystem::path(backend.workspace_root));
    g_shell_audio.sfx_enabled = sfx_enabled_preference;
    g_shell_audio.music_enabled = music_enabled_preference;
    if (g_shell_audio.music_enabled) {
        SetMusicEnabled(true);
    }
    g_shell_appear_time = ImGui::GetTime();
    g_shell_disappear_time = -1.0;
    PlayCue(UiCue::Window);

    ShellState state;
    g_live_shell_state = &state;
    state.backend = backend;
    state.status_line = sg_preflight::native_shell::FormatLoadedChromeStatus(state.language);
    if (!g_shell_assets.loaded && g_shell_assets.attempted && !g_shell_assets.error.empty()) {
        state.status_line = sg_preflight::native_shell::FormatFallbackChromeStatus(state.language, g_shell_assets.error);
    }
    if (g_using_warp) {
        state.status_line += " Graphics fallback active.";
    }
    StartInitialShellLoad(state);

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

        if (g_request_close_prompt && !state.exit_transition_active && !state.prompt_visible) {
            OpenPrompt(
                state,
                Tr(state, UiText::PromptQuitTitle),
                IsActionStillRunning(state)
                    ? Tr(state, UiText::PromptQuitRunningMessage)
                    : Tr(state, UiText::PromptQuitMessage),
                true,
                true,
                false
            );
            g_request_close_prompt = false;
        }

        if (state.exit_transition_active && state.exit_transition_started_at >= 0.0 && ((ImGui::GetTime() - state.exit_transition_started_at) * 60.0) >= kExitTransitionDurationFrames) {
            TraceUi("exit_complete");
            done = true;
            break;
        }

        PollInitialShellLoad(state);
        PollProfilePanelLoad(state);
        PollRunRefresh(state);
        PollCaptureRequest();

        if (
            !state.exit_transition_active
            && !state.prompt_visible
            && !state.run_refresh_loading
            && !state.current_run_id.empty()
            && IsActionStillRunning(state)
            && ShouldAutoRefreshRunInCurrentScreen(state)
            && ImGui::GetTime() >= state.next_poll_at
        ) {
            StartRunRefresh(state, false);
        }

        ImGui_ImplDX12_NewFrame();
        ImGui_ImplWin32_NewFrame();
        ImGui::NewFrame();

        RenderShell(state);

        ImGui::Render();
        FrameContext* frame_context = WaitForNextFrameContext();
        const UINT back_buffer_index = g_swap_chain->GetCurrentBackBufferIndex();
        frame_context->allocator->Reset();

        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition.pResource = g_main_render_targets[back_buffer_index];
        barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_PRESENT;
        barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_RENDER_TARGET;
        g_command_list->Reset(frame_context->allocator, nullptr);
        g_command_list->ResourceBarrier(1, &barrier);

        const float clear_color[4] = {0.03f, 0.05f, 0.06f, 1.0f};
        g_command_list->ClearRenderTargetView(g_main_render_target_descriptors[back_buffer_index], clear_color, 0, nullptr);
        g_command_list->OMSetRenderTargets(1, &g_main_render_target_descriptors[back_buffer_index], FALSE, nullptr);
        g_command_list->SetDescriptorHeaps(1, &g_srv_descriptor_heap);
        ImGui_ImplDX12_RenderDrawData(ImGui::GetDrawData(), g_command_list);
        barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_RENDER_TARGET;
        barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_PRESENT;
        g_command_list->ResourceBarrier(1, &barrier);
        g_command_list->Close();

        ID3D12CommandList* command_lists[] = { g_command_list };
        g_command_queue->ExecuteCommandLists(1, command_lists);
        g_command_queue->Signal(g_fence, ++g_fence_last_signaled_value);
        frame_context->fence_value = g_fence_last_signaled_value;
        CapturePendingFrameIfRequested(back_buffer_index);
        g_swap_chain->Present(1, 0);
        ++g_frame_index;
    }

    g_live_shell_state = nullptr;

    WaitForPendingOperations();
    SaveShellIniFile();
    sg_preflight::native_shell::ShutdownAudio();
    ImGui_ImplDX12_Shutdown();
    ImGui_ImplWin32_Shutdown();
    ImGui::DestroyContext();

    CleanupDeviceD3D();
    DestroyWindow(window_handle);
    UnregisterClassW(window_class.lpszClassName, window_class.hInstance);
    return 0;
}
