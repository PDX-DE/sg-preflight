#include "backend_bridge.hpp"
#include "audio_player.hpp"
#include "texture_loader.hpp"

#include <d3d11.h>
#include <shellapi.h>
#include <windows.h>

#include <algorithm>
#include <array>
#include <cfloat>
#include <cmath>
#include <cstdint>
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
using sg_preflight::native_shell::DdsTextureHandle;
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
bool g_using_warp = false;
bool g_request_close_prompt = false;

constexpr float kInstallerImageX = 161.5f;
constexpr float kInstallerImageY = 103.5f;
constexpr float kInstallerImageWidth = 512.0f;
constexpr float kInstallerImageHeight = 512.0f;
constexpr float kInstallerContainerX = 513.0f;
constexpr float kInstallerContainerY = 226.0f;
constexpr float kInstallerContainerWidth = 526.5f;
constexpr float kInstallerContainerHeight = 246.0f;

struct ShellAssets {
    std::filesystem::path resource_root;
    DdsTextureHandle general_window;
    DdsTextureHandle select;
    DdsTextureHandle light;
    DdsTextureHandle options_static;
    DdsTextureHandle options_static_flash;
    DdsTextureHandle installer_panel;
    DdsTextureHandle miles_electric_icon;
    DdsTextureHandle arrow_circle;
    DdsTextureHandle pulse_install;
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
    std::filesystem::path music;
    bool attempted = false;
    bool available = false;
    bool sfx_enabled = true;
    bool music_enabled = false;
    bool music_playing = false;
    std::string last_error;
};

ShellAudio g_shell_audio;

struct ShellWindowOptions {
    bool fullscreen = true;
    int width = 0;
    int height = 0;
};

ShellWindowOptions g_window_options;

enum class ShellScreen {
    Introduction,
    Select,
    Review,
    Run,
    Evidence,
    Files,
    Stages,
};

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
    ShellScreen current_screen = ShellScreen::Introduction;
    ShellScreen previous_screen = ShellScreen::Introduction;
    double screen_transition_started_at = -1.0;
    bool prompt_visible = false;
    bool prompt_confirmation = false;
    bool prompt_accepts_exit = false;
    bool prompt_accepts_leave_run = false;
    std::string prompt_title;
    std::string prompt_message;
    std::string prompt_accept_label = "YES";
    std::string prompt_cancel_label = "NO";
    bool request_exit = false;
};

ShellState* g_live_shell_state = nullptr;

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

void PlayCue(UiCue cue);
std::string CurrentActionId(const ShellState& state);
const ActionItem* FindSelectedAction(const ShellState& state);
void OpenPrompt(ShellState& state, const std::string& title, const std::string& message, bool confirmation = true, bool accepts_exit = false, bool accepts_leave_run = false);
void RequestBackAction(ShellState& state);
void RenderSummaryPanel(ShellState& state);
void RenderEvidencePanel(ShellState& state);
void RenderArtifactsPanel(ShellState& state);
void RenderBlockersPanel(ShellState& state);

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
    return std::clamp(
        (ImGui::GetTime() - g_shell_appear_time - offset_frames / 60.0) / total_frames * 60.0,
        0.0,
        1.0
    );
}

double ComputeMotionFrames(double offset_frames, double total_frames) {
    return std::sqrt(ComputeLinearMotionFrames(offset_frames, total_frames));
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
    return texture.view != nullptr;
}

ImTextureID ToTextureId(const DdsTextureHandle& texture) {
    return reinterpret_cast<ImTextureID>(texture.view);
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

void ReleaseShellAssets() {
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.general_window);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.select);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.light);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.options_static);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.options_static_flash);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.installer_panel);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.miles_electric_icon);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.arrow_circle);
    sg_preflight::native_shell::ReleaseTexture(g_shell_assets.pulse_install);
    for (auto& texture : g_shell_assets.install_images) {
        sg_preflight::native_shell::ReleaseTexture(texture);
    }
    g_shell_assets = {};
}

void LoadShellAssets(const std::filesystem::path& workspace_root) {
    ReleaseShellAssets();
    g_shell_assets.attempted = true;
    const auto resource_root = DiscoverResourceRoot(workspace_root);
    if (!resource_root.has_value()) {
        g_shell_assets.error = "UnleashedRecomp resource bundle was not found locally.";
        return;
    }

    g_shell_assets.resource_root = *resource_root;
    std::string error;
    auto load_required_texture = [&](const std::filesystem::path& relative, DdsTextureHandle& target) {
        if (!sg_preflight::native_shell::LoadDdsTexture(g_device, *resource_root / relative, target, &error)) {
            g_shell_assets.error = error;
            return false;
        }
        return true;
    };
    auto load_optional_texture = [&](const std::filesystem::path& relative, DdsTextureHandle& target) {
        std::string optional_error;
        sg_preflight::native_shell::LoadDdsTexture(g_device, *resource_root / relative, target, &optional_error);
    };

    if (
        load_required_texture(std::filesystem::path("images") / "common" / "general_window.dds", g_shell_assets.general_window)
        && load_required_texture(std::filesystem::path("images") / "common" / "select.dds", g_shell_assets.select)
        && load_required_texture(std::filesystem::path("images") / "common" / "light.dds", g_shell_assets.light)
        && load_required_texture(std::filesystem::path("images") / "options_menu" / "options_static.dds", g_shell_assets.options_static)
        && load_required_texture(std::filesystem::path("images") / "options_menu" / "options_static_flash.dds", g_shell_assets.options_static_flash)
        && load_required_texture(std::filesystem::path("images") / "installer" / "miles_electric_icon.dds", g_shell_assets.miles_electric_icon)
    ) {
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
    sg_preflight::native_shell::StopLoopingWaveMusic();
    g_shell_audio = {};
    g_shell_audio.attempted = true;

    const auto resource_root = DiscoverResourceRoot(workspace_root);
    if (!resource_root.has_value()) {
        g_shell_audio.last_error = "UnleashedRecomp audio bundle was not found locally.";
        return;
    }

    g_shell_audio.cursor = *resource_root / "sounds" / "raw" / "sys_worldmap_cursor.wav";
    g_shell_audio.confirm = *resource_root / "sounds" / "raw" / "sys_worldmap_finaldecide.wav";
    g_shell_audio.cancel = *resource_root / "sounds" / "raw" / "sys_actstg_pausecansel.wav";
    g_shell_audio.window = *resource_root / "sounds" / "raw" / "sys_actstg_pausewinopen.wav";
    g_shell_audio.music = *resource_root / "music" / "raw" / "installer.wav";

    if (
        PathExists(g_shell_audio.cursor)
        && PathExists(g_shell_audio.confirm)
        && PathExists(g_shell_audio.cancel)
        && PathExists(g_shell_audio.window)
    ) {
        g_shell_audio.available = true;
    } else {
        g_shell_audio.last_error = "One or more UnleashedRecomp WAV files are missing from the local resource bundle.";
    }
}

void SetMusicEnabled(bool enabled) {
    g_shell_audio.music_enabled = enabled;
    if (!enabled) {
        sg_preflight::native_shell::StopLoopingWaveMusic();
        g_shell_audio.music_playing = false;
        return;
    }
    if (PathExists(g_shell_audio.music) && sg_preflight::native_shell::StartLoopingWaveMusic(g_shell_audio.music, 20U)) {
        g_shell_audio.music_playing = true;
        g_shell_audio.last_error.clear();
    } else {
        g_shell_audio.music_playing = false;
        g_shell_audio.last_error = "Installer music WAV is not available for looping playback.";
    }
}

void SetSfxEnabled(bool enabled) {
    g_shell_audio.sfx_enabled = enabled;
}

void SetScreen(ShellState& state, ShellScreen screen, bool play_cursor = true) {
    if (state.current_screen == screen) {
        return;
    }
    state.previous_screen = state.current_screen;
    state.current_screen = screen;
    state.screen_transition_started_at = ImGui::GetTime();
    if (play_cursor) {
        PlayCue(UiCue::Cursor);
    }
}

int ScreenStepNumber(ShellScreen screen) {
    switch (screen) {
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
    case ShellScreen::Stages:
        return 7;
    default:
        return 1;
    }
}

constexpr int kWizardStepCount = 7;

const char* ScreenLabel(ShellScreen screen) {
    switch (screen) {
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
    case ShellScreen::Stages:
        return "STAGES";
    default:
        return "SCREEN";
    }
}

const char* ScreenTitle(ShellScreen screen) {
    switch (screen) {
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
    case ShellScreen::Stages:
        return "BLOCKERS / SETTINGS";
    default:
        return "SCREEN";
    }
}

const char* ScreenSummary(ShellScreen screen) {
    switch (screen) {
    case ShellScreen::Introduction:
        return "Open with the SG-side operator context first: what this pass does, what it does not do, and what the next input step is.";
    case ShellScreen::Select:
        return "Choose the live slice and the SG action path. Keep this page focused on selecting inputs, not reading results.";
    case ShellScreen::Review:
        return "Confirm readiness, blockers, and the exact local command path before starting the action.";
    case ShellScreen::Run:
        return "Stay here for progress, summary lines, grouped findings, and the run/result transition.";
    case ShellScreen::Evidence:
        return "Open the first affected files, inspect checker reasoning, and move through the strongest SG evidence first.";
    case ShellScreen::Files:
        return "Drill into reports, artifacts, source-of-truth files, and copy-ready exports from one calmer screen.";
    case ShellScreen::Stages:
        return "Keep blocked/manual stages visible, and control shell audio without hiding BMW-side honesty.";
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
    case ShellScreen::Stages:
        index = 5U;
        break;
    }
    return index % g_shell_assets.install_images.size();
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
    case ShellScreen::Introduction:
        return true;
    case ShellScreen::Select:
        return !state.profiles.empty() && !PrimaryActionId(state).empty();
    case ShellScreen::Review:
        return SelectedActionReady(state);
    case ShellScreen::Run:
        return HasCompletedRun(state);
    case ShellScreen::Evidence:
        return HasArtifactsReady(state);
    case ShellScreen::Files:
        return true;
    case ShellScreen::Stages:
        return true;
    default:
        return false;
    }
}

ShellScreen NextScreen(const ShellState& state, ShellScreen screen) {
    switch (screen) {
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
        return ShellScreen::Stages;
    case ShellScreen::Evidence:
        return ShellScreen::Files;
    case ShellScreen::Files:
        return ShellScreen::Stages;
    case ShellScreen::Stages:
        return ShellScreen::Select;
    default:
        return ShellScreen::Select;
    }
}

ShellScreen PreviousScreen(const ShellState& state, ShellScreen screen) {
    switch (screen) {
    case ShellScreen::Introduction:
        return ShellScreen::Introduction;
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
    case ShellScreen::Stages:
        return HasArtifactsReady(state) ? ShellScreen::Files : ShellScreen::Run;
    default:
        return ShellScreen::Introduction;
    }
}

std::string NextButtonLabel(const ShellState& state) {
    switch (state.current_screen) {
    case ShellScreen::Introduction:
        return "CONTINUE";
    case ShellScreen::Select:
        return "REVIEW";
    case ShellScreen::Review:
        return "RUN";
    case ShellScreen::Run:
        if (!HasCompletedRun(state)) {
            return "WAIT";
        }
        if (HasEvidenceReady(state)) {
            return "OPEN FIRST";
        }
        if (HasArtifactsReady(state)) {
            return "FILES";
        }
        return "STAGES";
    case ShellScreen::Evidence:
        return "FILES";
    case ShellScreen::Files:
        return "STAGES";
    case ShellScreen::Stages:
        return "RETURN";
    default:
        return "NEXT";
    }
}

bool IsActionStillRunning(const ShellState& state) {
    if (!state.snapshot.has_value()) {
        return false;
    }
    return state.snapshot->status == "queued" || state.snapshot->status == "running";
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
    state.prompt_accept_label = confirmation ? "YES" : "OK";
    state.prompt_cancel_label = "NO";
    PlayCue(UiCue::Window);
}

void ClosePrompt(ShellState& state) {
    state.prompt_visible = false;
    state.prompt_confirmation = false;
    state.prompt_accepts_exit = false;
    state.prompt_accepts_leave_run = false;
    state.prompt_title.clear();
    state.prompt_message.clear();
    state.prompt_accept_label = "YES";
    state.prompt_cancel_label = "NO";
}

void RequestBackAction(ShellState& state) {
    if (state.prompt_visible) {
        return;
    }

    if (state.current_screen == FirstOperationalScreen()) {
        OpenPrompt(
            state,
            "QUIT OPERATOR SHELL",
            IsActionStillRunning(state)
                ? "Close the shell now? The current SG action will keep running in the background."
                : "Close the operator shell now?",
            true,
            true,
            false
        );
        return;
    }

    if (state.current_screen == ShellScreen::Run && IsActionStillRunning(state)) {
        OpenPrompt(
            state,
            "LEAVE RUN SCREEN",
            "The current SG action is still running. Leave this page anyway? The action will keep running in the background.",
            true,
            false,
            true
        );
        return;
    }

    SetScreen(state, PreviousScreen(state, state.current_screen));
}

void AcceptPrompt(ShellState& state) {
    const bool accepts_exit = state.prompt_accepts_exit;
    const bool accepts_leave_run = state.prompt_accepts_leave_run;
    ClosePrompt(state);
    if (accepts_exit) {
        state.request_exit = true;
        return;
    }
    if (accepts_leave_run) {
        SetScreen(state, PreviousScreen(state, ShellScreen::Run));
    }
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
        }
        if (sound_path != nullptr && PathExists(*sound_path) && sg_preflight::native_shell::PlayWaveOneShot(*sound_path)) {
            return;
        }
    }

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

bool CreateDeviceD3D(HWND window_handle) {
    DXGI_SWAP_CHAIN_DESC swap_chain_desc{};
    swap_chain_desc.BufferCount = 3;
    swap_chain_desc.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    swap_chain_desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    swap_chain_desc.OutputWindow = window_handle;
    swap_chain_desc.SampleDesc.Count = 1;
    swap_chain_desc.Windowed = TRUE;
    swap_chain_desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;

    constexpr D3D_FEATURE_LEVEL feature_levels[] = {
        D3D_FEATURE_LEVEL_11_0,
        D3D_FEATURE_LEVEL_10_0,
    };
    D3D_FEATURE_LEVEL feature_level{};

    const auto create_device = [&](D3D_DRIVER_TYPE driver_type) {
        return D3D11CreateDeviceAndSwapChain(
            nullptr,
            driver_type,
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
    };

    HRESULT result = create_device(D3D_DRIVER_TYPE_HARDWARE);
    g_using_warp = false;
    if (FAILED(result)) {
        result = create_device(D3D_DRIVER_TYPE_WARP);
        g_using_warp = SUCCEEDED(result);
    }
    if (FAILED(result)) {
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
    SetScreen(state, ShellScreen::Select, false);
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
        SetScreen(state, ShellScreen::Run, false);
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
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(223.0f * alpha)),
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(178.0f * alpha)),
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(223.0f * alpha)),
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(178.0f * alpha))
    );
    draw->AddRectFilledMultiColor(
        min,
        max,
        IM_COL32(base_r, base_g, 0, static_cast<int>(13.0f * alpha)),
        IM_COL32(base_r, base_g, 0, 0),
        IM_COL32(base_r, base_g, 0, static_cast<int>(55.0f * alpha)),
        IM_COL32(base_r, base_g, 0, static_cast<int>(6.0f * alpha))
    );
    draw->AddRectFilledMultiColor(
        min,
        max,
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(13.0f * alpha)),
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(111.0f * alpha)),
        IM_COL32(base_r, base_g + 130, 0, 0),
        IM_COL32(base_r, base_g + 130, 0, static_cast<int>(55.0f * alpha))
    );
    draw->AddRect(min, max, IM_COL32(122 + base_r, 228, 180 + base_g / 2, static_cast<int>(190.0f * alpha)), ShellUi(4.0f), 0, 1.1f);
}

bool DrawInstallerNavButton(const char* id, const std::string& label, ImVec2 size, bool accent = false, bool enabled = true) {
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
    const int base_r = accent || hovered ? 48 : 0;
    const int base_g = accent || hovered ? 32 : 0;
    const float alpha = enabled ? 1.0f : 0.5f;
    DrawInstallerButtonContainer(min, max, base_r, base_g, alpha);

    ImFont* font = g_small_font != nullptr ? g_small_font : ImGui::GetFont();
    const float font_size = font == g_small_font ? g_small_font->LegacySize : ImGui::GetFontSize();
    const ImVec2 text_size = font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, label.c_str());
    const ImVec2 text_pos(
        min.x + ((max.x - min.x) - text_size.x) * 0.5f,
        min.y + ((max.y - min.y) - text_size.y) * 0.5f - ShellUi(1.0f)
    );
    draw->AddText(font, font_size, ImVec2(text_pos.x + ShellUi(1.0f), text_pos.y + ShellUi(1.0f)), IM_COL32(base_r, base_g, 0, static_cast<int>(255.0f * alpha)), label.c_str());
    draw->AddText(font, font_size, text_pos, IM_COL32(255, 255, 255, static_cast<int>(255.0f * alpha)), label.c_str());

    if (pressed && enabled) {
        PlayCue(accent ? UiCue::Confirm : UiCue::Cursor);
    }
    return pressed && enabled;
}

void DrawInstallerLeftImage(const ShellState& state) {
    const size_t index = InstallerTextureIndexForState(state);
    if (index >= g_shell_assets.install_images.size() || !HasTexture(g_shell_assets.install_images[index])) {
        return;
    }

    ImDrawList* draw_list = ImGui::GetBackgroundDrawList();
    const float alpha = static_cast<float>(ComputeMotionFrames(25.0, 15.0));
    const ImVec2 min = ShellPoint(kInstallerImageX, kInstallerImageY);
    const ImVec2 max = ImVec2(min.x + ShellUi(kInstallerImageWidth), min.y + ShellUi(kInstallerImageHeight));
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

    const double scanline_alpha = ComputeMotionFrames(0.0, 15.0);
    const float bar_height = ShellUi(105.0f) * static_cast<float>(scanline_alpha);
    const ImU32 color0 = IM_COL32(203, 255, 0, 0);
    const ImU32 color1 = IM_COL32(203, 255, 0, static_cast<int>(55.0 * scanline_alpha));
    if (bar_height > 1.0f) {
        draw_list->AddRectFilledMultiColor(ImVec2(0.0f, 0.0f), ImVec2(display_size.x, bar_height), color0, color0, color1, color1);
        draw_list->AddRectFilledMultiColor(ImVec2(0.0f, display_size.y - bar_height), ImVec2(display_size.x, display_size.y), color1, color1, color0, color0);
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
    };
    draw_bar_line(true);
    draw_bar_line(false);

    const float title_alpha = static_cast<float>(ComputeMotionFrames(15.0, 30.0));
    const char* header_text = ShouldShowInstallerLoadingChrome(state) ? "INSTALLING" : "INSTALLER";
    if (HasTexture(g_shell_assets.miles_electric_icon)) {
        const float scale = 62.0f * (2.0f - title_alpha);
        const ImVec2 center = ShellPoint(256.0f, 80.0f);
        const ImVec2 min(center.x - ShellUi(scale) * 0.5f, center.y - ShellUi(scale) * 0.5f);
        const ImVec2 max(center.x + ShellUi(scale) * 0.5f, center.y + ShellUi(scale) * 0.5f);
        draw_list->AddImage(
            ToTextureId(g_shell_assets.miles_electric_icon),
            min,
            max,
            ImVec2(0.0f, 0.0f),
            ImVec2(1.0f, 1.0f),
            IM_COL32(255, 255, 255, static_cast<int>(255.0f * title_alpha))
        );
    }

    if (g_title_font != nullptr) {
        const float size = ShellUi(42.0f);
        const ImVec2 pos = ShellPoint(288.0f, 54.0f);
        draw_list->AddText(g_title_font, size, ImVec2(pos.x + ShellUi(3.0f), pos.y + ShellUi(3.0f)), IM_COL32(0, 0, 0, static_cast<int>(255.0f * title_alpha)), header_text);
        draw_list->AddText(g_title_font, size, pos, IM_COL32(255, 195, 0, static_cast<int>(255.0f * title_alpha)), header_text);
    }

    if (ShouldShowInstallerLoadingChrome(state) && HasTexture(g_shell_assets.arrow_circle)) {
        const ImVec2 center = ShellPoint(256.0f, 80.0f);
        DrawRotatedTexture(
            draw_list,
            g_shell_assets.arrow_circle,
            center,
            ImVec2(ShellUi(62.0f), ShellUi(62.0f)),
            static_cast<float>(ImGui::GetTime()) * -2.0f,
            IM_COL32(255, 255, 255, static_cast<int>(96.0 * title_alpha))
        );
        if (HasTexture(g_shell_assets.pulse_install)) {
            const float pulse = 0.65f + 0.35f * (0.5f + 0.5f * std::sin(static_cast<float>(ImGui::GetTime()) * 2.6f));
            DrawTexturedRectRounded(
                draw_list,
                g_shell_assets.pulse_install,
                ImVec2(center.x - ShellUi(34.0f) * pulse, center.y - ShellUi(34.0f) * pulse),
                ImVec2(center.x + ShellUi(34.0f) * pulse, center.y + ShellUi(34.0f) * pulse),
                IM_COL32(255, 255, 255, static_cast<int>(40.0 * pulse * title_alpha)),
                ShellUi(20.0f)
            );
        }
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
        ? (hovered ? IM_COL32(24, 82, 74, 228) : IM_COL32(16, 58, 54, 228))
        : (hovered ? IM_COL32(14, 32, 36, 226) : IM_COL32(9, 20, 24, 226));
    const ImU32 border = accent ? IM_COL32(120, 228, 204, 188) : IM_COL32(60, 114, 118, 178);
    const ImU32 text = enabled ? IM_COL32(236, 246, 239, 255) : IM_COL32(114, 134, 127, 255);

    draw->AddRectFilled(min, max, bg, ShellUi(4.0f));
    if (accent) {
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.select,
            min,
            max,
            IM_COL32(108, 226, 170, hovered ? 42 : 30),
            ShellUi(4.0f)
        );
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.light,
            ImVec2(min.x, min.y - ShellUi(2.0f)),
            ImVec2(max.x, min.y + (max.y - min.y) * 0.56f),
            IM_COL32(240, 225, 146, hovered ? 32 : 24),
            ShellUi(4.0f)
        );
    }
    draw->AddRect(min, max, border, ShellUi(4.0f), 0, 1.2f);
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

    const float pulse = 0.5f + 0.5f * std::sin(static_cast<float>(ImGui::GetTime()) * 3.2f);
    const ImU32 bg = selected
        ? ApplyAlpha(IM_COL32(16, 62, 64, 255), 0.86f)
        : hovered
            ? ApplyAlpha(IM_COL32(10, 26, 30, 255), 0.92f)
            : ApplyAlpha(IM_COL32(8, 17, 21, 255), 0.92f);
    const ImU32 border = selected
        ? ApplyAlpha(IM_COL32(122, 226, 204, 220), 0.82f + 0.10f * pulse)
        : hovered
            ? IM_COL32(72, 124, 128, 196)
            : IM_COL32(31, 73, 78, 168);

    draw->AddRectFilled(min, max, bg, ShellUi(4.0f));
    if (selected) {
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.select,
            min,
            max,
            IM_COL32(108, 226, 170, static_cast<int>(46.0f + 12.0f * pulse)),
            ShellUi(4.0f)
        );
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.light,
            ImVec2(min.x - ShellUi(2.0f), min.y - ShellUi(4.0f)),
            ImVec2(max.x + ShellUi(2.0f), min.y + (max.y - min.y) * 0.28f),
            IM_COL32(240, 225, 146, 26),
            ShellUi(4.0f)
        );
    }
    draw->AddRect(min, max, border, ShellUi(4.0f), 0, selected ? 1.8f : 1.1f);
    draw->AddRectFilled(ImVec2(min.x + 7.0f, min.y + 9.0f), ImVec2(min.x + 13.0f, max.y - 9.0f), selected ? IM_COL32(238, 181, 42, 255) : IM_COL32(52, 86, 90, 150), 3.0f);
    for (float y = min.y + ShellUi(2.0f); y < max.y; y += ShellUi(8.0f)) {
        draw->AddLine(ImVec2(min.x + 16.0f, y), ImVec2(max.x - 8.0f, y), IM_COL32(36, 88, 92, selected ? 18 : 8), 1.0f);
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
    DrawTexturedRectRounded(
        draw,
        g_shell_assets.general_window,
        min,
        max,
        IM_COL32(106, 240, 172, 72),
        ShellUi(3.0f)
    );
    draw->AddRect(min, max, IM_COL32(55, 109, 114, 210), 3.0f);
    draw->AddRectFilledMultiColor(
        min,
        ImVec2(min.x + width, max.y),
        IM_COL32(48, 184, 168, 255),
        IM_COL32(207, 222, 90, 255),
        IM_COL32(48, 184, 168, 235),
        IM_COL32(207, 222, 90, 235)
    );
    DrawTexturedRectRounded(
        draw,
        g_shell_assets.select,
        min,
        ImVec2(min.x + width, max.y),
        IM_COL32(132, 232, 180, 92),
        ShellUi(3.0f),
        ImVec2(0.0f, 0.0f),
        ImVec2(std::max(0.12f, progress * 3.2f), 1.0f)
    );
    DrawTexturedRectRounded(
        draw,
        g_shell_assets.light,
        ImVec2(min.x, min.y - ShellUi(4.0f)),
        ImVec2(min.x + width, max.y + ShellUi(4.0f)),
        IM_COL32(240, 225, 146, 34),
        ShellUi(3.0f)
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

float ScreenTransitionMotion(const ShellState& state) {
    if (state.screen_transition_started_at < 0.0) {
        return 1.0f;
    }
    const double frames = (ImGui::GetTime() - state.screen_transition_started_at) * 60.0;
    return SmoothStep(static_cast<float>(std::sqrt(std::clamp(frames / 23.0, 0.0, 1.0))));
}

void BeginScreenTransition(const ShellState& state) {
    const float motion = ScreenTransitionMotion(state);
    const ImVec2 cursor = ImGui::GetCursorPos();
    ImGui::SetCursorPos(ImVec2(cursor.x + (1.0f - motion) * ShellUi(52.0f), cursor.y + (1.0f - motion) * ShellUi(4.0f)));
    ImGui::PushStyleVar(ImGuiStyleVar_Alpha, 0.18f + 0.82f * motion);
}

void EndScreenTransition() {
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
    const bool pressed = ImGui::InvisibleButton(id, size);
    const bool hovered = ImGui::IsItemHovered();
    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 min = ImGui::GetItemRectMin();
    const ImVec2 max = ImGui::GetItemRectMax();
    const ImU32 border = value ? IM_COL32(122, 255, 168, 208) : IM_COL32(67, 128, 113, hovered ? 196 : 160);

    draw->AddRectFilled(min, max, hovered ? IM_COL32(11, 26, 29, 234) : IM_COL32(8, 17, 19, 228), ShellUi(4.0f));
    DrawTexturedRectRounded(
        draw,
        g_shell_assets.general_window,
        min,
        max,
        value ? IM_COL32(102, 226, 168, 92) : IM_COL32(72, 160, 120, 42),
        ShellUi(4.0f)
    );
    draw->AddRect(min, max, border, ShellUi(4.0f), 0, 1.1f);

    const ImVec2 toggle_min(max.x - ShellUi(102.0f), min.y + ShellUi(21.0f));
    const ImVec2 toggle_max(max.x - ShellUi(24.0f), min.y + ShellUi(53.0f));
    draw->AddRectFilled(toggle_min, toggle_max, value ? IM_COL32(30, 118, 66, 240) : IM_COL32(18, 32, 36, 240), ShellUi(16.0f));
    draw->AddRect(toggle_min, toggle_max, value ? IM_COL32(130, 255, 147, 220) : IM_COL32(78, 110, 104, 210), ShellUi(16.0f), 0, 1.0f);
    if (value) {
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.select,
            toggle_min,
            toggle_max,
            IM_COL32(130, 255, 122, 118),
            ShellUi(16.0f)
        );
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.light,
            ImVec2(toggle_min.x - ShellUi(4.0f), toggle_min.y - ShellUi(6.0f)),
            ImVec2(toggle_max.x + ShellUi(4.0f), toggle_max.y + ShellUi(6.0f)),
            IM_COL32(225, 255, 188, 76),
            ShellUi(16.0f)
        );
    }
    const float knob_radius = ShellUi(11.0f);
    const float knob_x = value ? toggle_max.x - ShellUi(20.0f) : toggle_min.x + ShellUi(20.0f);
    draw->AddCircleFilled(ImVec2(knob_x, (toggle_min.y + toggle_max.y) * 0.5f), knob_radius, IM_COL32(235, 243, 239, 255), 24);

    if (g_body_font != nullptr) {
        draw->AddText(g_body_font, g_body_font->LegacySize, ImVec2(min.x + ShellUi(18.0f), min.y + ShellUi(14.0f)), IM_COL32(237, 245, 241, 255), label.c_str());
    }
    if (g_small_font != nullptr) {
        draw->AddText(g_small_font, g_small_font->LegacySize, ImVec2(min.x + ShellUi(18.0f), min.y + ShellUi(40.0f)), IM_COL32(167, 189, 180, 220), summary.c_str());
        draw->AddText(g_small_font, g_small_font->LegacySize, ImVec2(toggle_min.x, min.y + ShellUi(58.0f)), value ? IM_COL32(255, 188, 0, 240) : IM_COL32(136, 152, 148, 220), value ? "ON" : "OFF");
    }

    if (pressed) {
        PlayCue(UiCue::Cursor);
    }
    return pressed;
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
        if (DrawSelectableCard(row_id.c_str(), title, subtitle, profile.summary, selected, ShellUi(82.0f))) {
            state.selected_profile_index = static_cast<int>(index);
            state.selected_action_id = profile.recommended_action_id;
            RefreshProfilePanels(state);
            SetScreen(state, ShellScreen::Select, false);
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
        if (DrawSelectableCard(row_id.c_str(), item.title, subtitle, item.summary, selected, ShellUi(76.0f))) {
            state.current_run_id = item.run_id;
            if (!item.profile_id.empty()) {
                SelectProfileById(state, item.profile_id);
            }
            RefreshSnapshot(state);
            RefreshRunSnapshot(state);
            SetScreen(state, ShellScreen::Run, false);
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
        if (DrawSelectableCard(row_id.c_str(), title, subtitle, item.summary, selected, ShellUi(76.0f))) {
            state.current_result_run_id = item.run_id;
            RefreshRunSnapshot(state);
            SetScreen(state, ShellScreen::Run, false);
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

    const float motion = static_cast<float>(ComputeMotionFrames(kContainerCategoryTime, kContainerCategoryDuration));
    if (motion <= 0.0f || tabs.empty()) {
        return;
    }

    ImDrawList* draw = ImGui::GetWindowDrawList();
    const ImVec2 strip_origin = ImGui::GetCursorScreenPos();
    const float grid = ShellUi(kPanelGrid);
    const float font_size = ShellUi(18.0f);
    const float tab_height = grid * 4.0f;
    const float clip_width = ImGui::GetContentRegionAvail().x - grid * 2.0f;
    ImFont* tab_font = g_body_font != nullptr ? g_body_font : ImGui::GetFont();
    std::vector<ImVec2> text_sizes(tabs.size());

    float text_width_sum = 0.0f;
    for (size_t index = 0; index < tabs.size(); ++index) {
        text_sizes[index] = tab_font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, tabs[index].label.c_str());
        text_width_sum += text_sizes[index].x;
    }

    float text_squash_ratio = 1.0f;
    const float max_text_width_sum = clip_width - (grid * 4.0f * static_cast<float>(std::max<size_t>(0U, tabs.size() - 1U)));
    if (text_width_sum > max_text_width_sum && text_width_sum > 0.0f) {
        text_squash_ratio = max_text_width_sum / text_width_sum;
        for (ImVec2& size : text_sizes) {
            size.x *= text_squash_ratio;
        }
        text_width_sum = max_text_width_sum;
    }

    float text_padding = (clip_width - text_width_sum) / (static_cast<float>(tabs.size()) + 1.0f);
    float x_offset = text_padding - (1.0f - motion) * grid * 4.0f;
    struct TabRect {
        size_t index = 0U;
        ImVec2 min{};
        ImVec2 max{};
        ImVec2 text_pos{};
    };
    std::vector<TabRect> rectangles;
    rectangles.reserve(tabs.size());

    ImVec2 target_highlight_min{};
    ImVec2 target_highlight_max{};
    bool highlight_found = false;
    for (size_t index = 0; index < tabs.size(); ++index) {
        const TabItem& tab = tabs[index];
        const float tab_padding = std::min(text_padding * 0.5f, grid * 3.0f);
        const ImVec2 min(strip_origin.x + x_offset - tab_padding, strip_origin.y);
        const ImVec2 max(min.x + text_sizes[index].x + tab_padding * 2.0f, min.y + tab_height);
        const ImVec2 text_pos(strip_origin.x + x_offset, strip_origin.y + ShellUi(6.0f));

        ImGui::SetCursorScreenPos(min);
        ImGui::InvisibleButton(("tab-" + tab.action_id).c_str(), ImVec2(max.x - min.x, max.y - min.y));
        if (ImGui::IsItemClicked() && state.selected_action_id != tab.action_id) {
            state.selected_action_id = tab.action_id;
            RefreshResultPanels(state);
            PlayCue(UiCue::Cursor);
        }

        if (state.selected_action_id == tab.action_id) {
            target_highlight_min = min;
            target_highlight_max = max;
            highlight_found = true;
        }
        rectangles.push_back({index, min, max, text_pos});
        x_offset += text_sizes[index].x + text_padding;
    }

    if (highlight_found) {
        if (!g_tab_highlight_ready) {
            g_tab_highlight_min = target_highlight_min;
            g_tab_highlight_max = target_highlight_max;
            g_tab_highlight_ready = true;
        } else {
            const float width = target_highlight_max.x - target_highlight_min.x;
            const float height = target_highlight_max.y - target_highlight_min.y;
            float animated_width = g_tab_highlight_max.x - g_tab_highlight_min.x;
            animated_width = LerpFloat(animated_width, width, 1.0f - std::exp(-64.0f * ImGui::GetIO().DeltaTime));
            const ImVec2 target_center = LerpVec2(target_highlight_min, target_highlight_max, 0.5f);
            const ImVec2 animated_center = LerpVec2(g_tab_highlight_min, g_tab_highlight_max, 0.5f);
            const ImVec2 next_center = LerpVec2(animated_center, target_center, 1.0f - std::exp(-16.0f * ImGui::GetIO().DeltaTime));
            g_tab_highlight_min = ImVec2(next_center.x - animated_width * 0.5f, next_center.y - height * 0.5f);
            g_tab_highlight_max = ImVec2(next_center.x + animated_width * 0.5f, next_center.y + height * 0.5f);
        }

        DrawTexturedRectRounded(
            draw,
            g_shell_assets.select,
            g_tab_highlight_min,
            g_tab_highlight_max,
            IM_COL32(131, 255, 122, static_cast<int>(168.0f * motion)),
            ShellUi(3.0f)
        );
        DrawTexturedRectRounded(
            draw,
            g_shell_assets.light,
            ImVec2(g_tab_highlight_min.x - ShellUi(8.0f), g_tab_highlight_min.y - ShellUi(10.0f)),
            ImVec2(g_tab_highlight_max.x + ShellUi(8.0f), g_tab_highlight_max.y + ShellUi(4.0f)),
            IM_COL32(225, 255, 188, static_cast<int>(78.0f * motion)),
            ShellUi(3.0f)
        );
        draw->AddRectFilledMultiColor(
            g_tab_highlight_min,
            g_tab_highlight_max,
            IM_COL32(0, 130, 0, static_cast<int>(223.0f * motion)),
            IM_COL32(0, 130, 0, static_cast<int>(178.0f * motion)),
            IM_COL32(0, 130, 0, static_cast<int>(223.0f * motion)),
            IM_COL32(0, 130, 0, static_cast<int>(178.0f * motion))
        );
        draw->AddRectFilledMultiColor(
            g_tab_highlight_min,
            g_tab_highlight_max,
            IM_COL32(0, 0, 0, static_cast<int>(13.0f * motion)),
            IM_COL32(0, 0, 0, 0),
            IM_COL32(0, 0, 0, static_cast<int>(55.0f * motion)),
            IM_COL32(0, 0, 0, 6)
        );
        draw->AddRectFilledMultiColor(
            g_tab_highlight_min,
            g_tab_highlight_max,
            IM_COL32(0, 130, 0, static_cast<int>(13.0f * motion)),
            IM_COL32(0, 130, 0, static_cast<int>(111.0f * motion)),
            IM_COL32(0, 130, 0, 0),
            IM_COL32(0, 130, 0, static_cast<int>(55.0f * motion))
        );
        draw->AddRect(g_tab_highlight_min, g_tab_highlight_max, IM_COL32(118, 255, 168, 150), ShellUi(3.0f), 0, 1.1f);
    }

    for (const TabRect& rectangle : rectangles) {
        const TabItem& tab = tabs[rectangle.index];
        const bool selected = state.selected_action_id == tab.action_id;
        const bool hovered = ImGui::IsMouseHoveringRect(rectangle.min, rectangle.max);
        if (!selected) {
            const ImU32 fill = hovered ? IM_COL32(15, 27, 24, 228) : IM_COL32(8, 15, 17, 224);
            const ImU32 border = tab.ready ? IM_COL32(28, 78, 66, 170) : IM_COL32(110, 72, 38, 170);
            draw->AddRectFilled(rectangle.min, rectangle.max, fill, ShellUi(3.0f));
            DrawTexturedRectRounded(
                draw,
                g_shell_assets.general_window,
                rectangle.min,
                rectangle.max,
                hovered ? IM_COL32(103, 230, 172, 74) : IM_COL32(88, 214, 157, 42),
                ShellUi(3.0f)
            );
            draw->AddRect(rectangle.min, rectangle.max, border, ShellUi(3.0f), 0, 1.0f);
        }

        const ImU32 text_color = selected
            ? IM_COL32(245, 245, 235, static_cast<int>(235.0f * motion))
            : IM_COL32(tab.ready ? 176 : 255, tab.ready ? 202 : 192, tab.ready ? 188 : 0, static_cast<int>((hovered ? 214.0f : 170.0f) * motion));
        draw->AddText(tab_font, font_size, rectangle.text_pos, text_color, tab.label.c_str());
    }

    ImGui::SetCursorScreenPos(ImVec2(strip_origin.x, strip_origin.y + tab_height + ShellUi(10.0f)));

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
    if (!selected_tab->ready && !selected_tab->blocker_message.empty()) {
        ImGui::Spacing();
        ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", selected_tab->blocker_message.c_str());
    } else if (!selected_tab->command_preview.empty()) {
        ImGui::Spacing();
        ImGui::TextDisabled("%s", selected_tab->command_preview.c_str());
    }
}

void RenderWizardFlow(ShellState& state) {
    struct StepItem {
        ShellScreen screen;
        const char* label;
    };
    const std::array<StepItem, 7> steps = {{
        {ShellScreen::Introduction, "INTRO"},
        {ShellScreen::Select, "SELECT"},
        {ShellScreen::Review, "REVIEW"},
        {ShellScreen::Run, "RUN"},
        {ShellScreen::Evidence, "EVIDENCE"},
        {ShellScreen::Files, "FILES"},
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
            SetScreen(state, item.screen, false);
        }
        if (index + 1U < steps.size()) {
            ImGui::SameLine();
        }
    }
    ImGui::Spacing();
    ImGui::TextWrapped("%s", ScreenSummary(state.current_screen));
}

void RenderIntroductionScreen(ShellState& state) {
    BeginScreenTransition(state);
    InlineSectionLabel("Step 1 / 7");
    ImGui::TextWrapped("This shell follows a real wizard flow now: choose the SG slice, review the local readiness state, run the action, then move through evidence, files, and blocked/manual stages in order.");
    ImGui::Spacing();
    InlineSectionLabel("What This Covers");
    ImGui::BulletText("Deterministic SG preflight packs plus the wrapped SG checker stack.");
    ImGui::BulletText("Structured checker evidence with file-backed Open First guidance.");
    ImGui::BulletText("Files, exports, and copy-ready handoff text after the run is understood.");
    ImGui::BulletText("Blocked/manual BMW-side stages without hiding missing access.");
    ImGui::Spacing();
    InlineSectionLabel("Current Operator Context");
    if (!state.profiles.empty()) {
        const ProfileItem& profile = state.profiles[static_cast<size_t>(state.selected_profile_index)];
        ImGui::Text("%s", profile.profile_id.c_str());
        ImGui::SameLine();
        ImGui::TextDisabled("%s", profile.label.c_str());
        ImGui::TextWrapped("%s", profile.summary.c_str());
        ImGui::Spacing();
        ImGui::TextDisabled("Recommended path: %s", ShortActionLabel(profile.recommended_action_id).c_str());
    } else {
        ImGui::TextDisabled("No ready live profiles were discovered locally.");
    }
    ImGui::Spacing();
    ImGui::TextDisabled("%s", state.status_line.c_str());
    EndScreenTransition();
}

void RenderSelectScreen(ShellState& state) {
    BeginScreenTransition(state);
    InlineSectionLabel("Step 2 / 7");
    ImGui::TextWrapped("Choose the live slice and the SG action path first. This page should stay about selecting inputs, not result drilling.");
    ImGui::Spacing();
    InlineSectionLabel("Selected Live Slice");
    if (!state.profiles.empty()) {
        const ProfileItem& profile = state.profiles[static_cast<size_t>(state.selected_profile_index)];
        ImGui::Text("%s", profile.profile_id.c_str());
        ImGui::SameLine();
        ImGui::TextDisabled("%s", profile.label.c_str());
        ImGui::TextWrapped("%s", profile.summary.c_str());
    } else {
        ImGui::TextDisabled("No ready live profiles were discovered.");
    }
    ImGui::Spacing();
    InlineSectionLabel("SG Action Path");
    RenderActionTabs(state);
    ImGui::Spacing();
    const ActionItem* action = FindSelectedAction(state);
    if (action != nullptr) {
        ImGui::TextWrapped("%s", action->description.c_str());
        if (!action->command_preview.empty()) {
            ImGui::Spacing();
            ImGui::TextDisabled("%s", action->command_preview.c_str());
        }
        if (!action->ready && !action->blocker_message.empty()) {
            ImGui::Spacing();
            ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", action->blocker_message.c_str());
        }
    } else if (CurrentActionId(state) == "daily_live_matrix") {
        ImGui::TextWrapped("Run the recommended SG QA stack across every ready live profile and collect one aggregated Open First surface.");
        ImGui::Spacing();
        ImGui::TextDisabled("python -m sg_preflight run-action daily_live_matrix");
    } else {
        ImGui::TextDisabled("No action metadata is available for the current selection.");
    }
    EndScreenTransition();
}

void RenderReviewScreen(ShellState& state) {
    BeginScreenTransition(state);
    InlineSectionLabel("Step 3 / 7");
    ImGui::TextWrapped("Confirm the chosen SG path before running it. This mirrors the installer check step: selection is done, readiness is explicit, and blockers stay visible before execution.");
    ImGui::Spacing();
    InlineSectionLabel("Selected Run");
    if (!state.profiles.empty()) {
        const ProfileItem& profile = state.profiles[static_cast<size_t>(state.selected_profile_index)];
        ImGui::Text("%s", profile.profile_id.c_str());
        ImGui::SameLine();
        ImGui::TextDisabled("%s", profile.label.c_str());
    }
    ImGui::Text("Action: %s", ShortActionLabel(CurrentActionId(state)).c_str());
    const ActionItem* action = FindSelectedAction(state);
    if (action != nullptr) {
        ImGui::TextWrapped("%s", action->description.c_str());
    }
    ImGui::Spacing();
    InlineSectionLabel("Command Preview");
    if (action != nullptr && !action->command_preview.empty()) {
        ImGui::TextWrapped("%s", action->command_preview.c_str());
    } else if (CurrentActionId(state) == "daily_live_matrix") {
        ImGui::TextWrapped("python -m sg_preflight run-action daily_live_matrix");
    } else {
        ImGui::TextDisabled("No command preview is available for this action.");
    }
    ImGui::Spacing();
    InlineSectionLabel("Readiness");
    if (SelectedActionReady(state)) {
        ImGui::TextColored(ImVec4(0.40f, 0.88f, 0.64f, 1.0f), "This local SG action is ready to run.");
    } else if (action != nullptr && !action->blocker_message.empty()) {
        ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", action->blocker_message.c_str());
    } else {
        ImGui::TextDisabled("This action is not ready on the current machine.");
    }
    ImGui::Spacing();
    InlineSectionLabel("Known Blockers");
    for (const BlockerItem& item : state.blockers) {
        ImGui::Text("%s [%s]", item.label.c_str(), item.state.c_str());
        ImGui::TextDisabled("%s", item.summary.c_str());
        if (!item.blockers.empty()) {
            ImGui::BulletText("%s", item.blockers.front().c_str());
        }
        if (&item != &state.blockers.back()) {
            ImGui::Spacing();
        }
    }
    EndScreenTransition();
}

void RenderRunScreen(ShellState& state) {
    BeginScreenTransition(state);
    InlineSectionLabel("Step 4 / 7");
    ImGui::TextWrapped("Stay here while the local action runs. Once the result is completed, move forward to evidence first instead of reading every file or report at once.");
    ImGui::Spacing();
    RenderSummaryPanel(state);
    EndScreenTransition();
}

void RenderEvidenceScreen(ShellState& state) {
    BeginScreenTransition(state);
    InlineSectionLabel("Step 5 / 7");
    ImGui::TextDisabled("Open these files first and keep the strongest checker path in front of you.");
    ImGui::Spacing();
    RenderEvidencePanel(state);
    const std::wstring evidence_path = SelectedEvidencePath(state);
    if (!evidence_path.empty()) {
        ImGui::Spacing();
        ImGui::TextWrapped("%s", sg_preflight::native_shell::ToUtf8(evidence_path).c_str());
        ImGui::Spacing();
        if (DrawPanelButton("open-evidence-file", "OPEN FILE", ImVec2(ShellUi(180.0f), ShellUi(30.0f)), true, true)) {
            OpenPath(evidence_path);
        }
        ImGui::SameLine();
        if (DrawPanelButton("reveal-evidence-file", "REVEAL IN EXPLORER", ImVec2(ShellUi(220.0f), ShellUi(30.0f)), false, true)) {
            RevealPath(evidence_path);
        }
    }
    if (state.snapshot.has_value() && !state.snapshot->manual_followups.empty()) {
        ImGui::Spacing();
        InlineSectionLabel("Manual Follow-Ups");
        for (const std::string& followup : state.snapshot->manual_followups) {
            ImGui::BulletText("%s", followup.c_str());
        }
    }
    EndScreenTransition();
}

void RenderFilesScreen(ShellState& state) {
    BeginScreenTransition(state);
    InlineSectionLabel("Step 6 / 7");
    ImGui::TextWrapped("Use this page for reports, exports, and source-of-truth files after you already know what matters from OPEN FIRST.");
    ImGui::Spacing();
    RenderArtifactsPanel(state);
    EndScreenTransition();
}

void RenderStagesScreen(ShellState& state) {
    BeginScreenTransition(state);
    InlineSectionLabel("Step 7 / 7");
    ImGui::TextWrapped("Finish on blockers, manual follow-up, and shell settings. BMW blockers stay visible here instead of being buried under the rest of the UI.");
    ImGui::Spacing();
    RenderBlockersPanel(state);
    ImGui::Spacing();
    InlineSectionLabel("Display Mode");
    const ImVec2 display = ImGui::GetIO().DisplaySize;
    ImGui::TextWrapped(
        "Current output: %.0fx%.0f%s",
        display.x,
        display.y,
        g_using_warp ? " | software renderer fallback (WARP)" : " | hardware D3D11"
    );
    ImGui::TextWrapped("Default startup uses the current monitor size. Use --windowed --width <n> --height <n> if you want an override.");
    ImGui::Spacing();
    InlineSectionLabel("Shell Audio");
    if (DrawSettingToggle("toggle-sfx", "UI sound effects", "Cursor, confirm, cancel, and window-open cues from the local Unleashed resource bundle.", g_shell_audio.sfx_enabled)) {
        SetSfxEnabled(!g_shell_audio.sfx_enabled);
        state.status_line = g_shell_audio.sfx_enabled ? "UI sound effects enabled." : "UI sound effects disabled.";
        PlayCue(g_shell_audio.sfx_enabled ? UiCue::Confirm : UiCue::Error);
    }
    ImGui::Spacing();
    if (DrawSettingToggle("toggle-bgm", "Installer background music", "Loops the local installer music WAV while the shell is open. Toggle it when you want the stronger installer manner.", g_shell_audio.music_enabled)) {
        SetMusicEnabled(!g_shell_audio.music_enabled);
        state.status_line = g_shell_audio.music_enabled ? "Installer background music enabled." : "Installer background music disabled.";
    }
    if (!g_shell_audio.last_error.empty()) {
        ImGui::Spacing();
        ImGui::TextColored(ImVec4(0.92f, 0.48f, 0.35f, 1.0f), "%s", g_shell_audio.last_error.c_str());
    }
    EndScreenTransition();
}

void RenderCurrentScreen(ShellState& state) {
    switch (state.current_screen) {
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
    case ShellScreen::Stages:
        RenderStagesScreen(state);
        break;
    }
}

void RenderWizardNavigation(ShellState& state) {
    const bool can_go_back = state.current_screen != FirstOperationalScreen();
    const bool can_go_next = CanAdvanceFromPage(state, state.current_screen);
    const std::string next_label = NextButtonLabel(state);

    ImGui::Spacing();
    ImGui::Separator();
    ImGui::Spacing();
    if (DrawInstallerNavButton("wizard-back", can_go_back ? "BACK" : "QUIT", ImVec2(ShellUi(162.0f), ShellUi(30.0f)), false, true)) {
        RequestBackAction(state);
    }
    ImGui::SameLine();
    if (DrawInstallerNavButton("wizard-next", next_label.c_str(), ImVec2(ShellUi(190.0f), ShellUi(30.0f)), true, can_go_next)) {
        if (state.current_screen == ShellScreen::Review) {
            StartAction(state, CurrentActionId(state));
        } else {
            SetScreen(state, NextScreen(state, state.current_screen));
        }
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
    };

    const std::wstring evidence_path = SelectedEvidencePath(state);
    const std::wstring artifact_path = SelectedArtifactPath(state);
    const bool has_report = state.run_snapshot.has_value() || (state.snapshot.has_value() && !state.snapshot->latest_run_links.html_report.empty());
    const std::string run_primary_label = IsActionStillRunning(state) ? "REFRESH" : NextButtonLabel(state);
    std::vector<GuideItem> guide_items;
    switch (state.current_screen) {
    case ShellScreen::Introduction:
        guide_items = {
            {"guide-next", "A", "CONTINUE", true, false},
            {"guide-back", "B", "QUIT", true, false},
        };
        break;
    case ShellScreen::Select:
        guide_items = {
            {"guide-next", "A", "REVIEW", CanAdvanceFromPage(state, state.current_screen), false},
            {"guide-back", "B", "BACK", true, false},
        };
        break;
    case ShellScreen::Review:
        guide_items = {
            {"guide-next", "A", "RUN", SelectedActionReady(state), false},
            {"guide-back", "B", "BACK", true, false},
        };
        break;
    case ShellScreen::Run:
        guide_items = {
            {"guide-next", "A", run_primary_label, IsActionStillRunning(state) || CanAdvanceFromPage(state, state.current_screen), false},
            {"guide-back", "B", "BACK", true, false},
            {"guide-log", "LB", "RAW LOG", state.snapshot.has_value(), false},
            {"guide-report", "RB", "REPORT", has_report, false},
        };
        break;
    case ShellScreen::Evidence:
        guide_items = {
            {"guide-next", "A", "FILES", HasArtifactsReady(state), false},
            {"guide-back", "B", "BACK", true, false},
            {"guide-open", "X", "OPEN FILE", !evidence_path.empty(), false},
            {"guide-reveal", "Y", "REVEAL", !evidence_path.empty(), false},
            {"guide-jira", "J", "COPY JIRA", true, true},
        };
        break;
    case ShellScreen::Files:
        guide_items = {
            {"guide-next", "A", "STAGES", true, false},
            {"guide-back", "B", "BACK", true, false},
            {"guide-open", "X", "OPEN FILE", !artifact_path.empty(), false},
            {"guide-reveal", "Y", "REVEAL", !artifact_path.empty(), false},
            {"guide-report", "RB", "REPORT", has_report, false},
            {"guide-jira", "J", "COPY JIRA", true, true},
            {"guide-hero", "Q", "COPY QA HERO", true, true},
            {"guide-handoff", "H", "COPY HANDOFF", true, true},
        };
        break;
    case ShellScreen::Stages:
        guide_items = {
            {"guide-next", "A", "RETURN", true, false},
            {"guide-back", "B", "BACK", true, false},
            {"guide-jira", "J", "COPY JIRA", true, true},
            {"guide-hero", "Q", "COPY QA HERO", true, true},
            {"guide-handoff", "H", "COPY HANDOFF", true, true},
        };
        break;
    }

    const ImVec2 region_min = ShellPoint(84.0f, 676.0f);
    const ImVec2 region_max = ShellPoint(1196.0f, 716.0f);
    const float font_size = ShellUi(15.0f);
    const float key_height = ShellUi(24.0f);
    const float item_gap = ShellUi(18.0f);
    const float label_gap = ShellUi(8.0f);
    const float vertical_padding = ShellUi(4.0f);
    ImFont* guide_font = g_small_font != nullptr ? g_small_font : ImGui::GetFont();
    ImDrawList* draw = ImGui::GetWindowDrawList();

    draw->AddRectFilledMultiColor(
        ImVec2(region_min.x - ShellUi(14.0f), region_min.y - ShellUi(10.0f)),
        ImVec2(region_max.x + ShellUi(14.0f), region_min.y - ShellUi(6.0f)),
        IM_COL32(0, 0, 0, 0),
        IM_COL32(173, 255, 156, 65),
        IM_COL32(173, 255, 156, 65),
        IM_COL32(0, 0, 0, 0)
    );
    draw->AddRectFilled(
        ImVec2(region_min.x - ShellUi(4.0f), region_min.y - ShellUi(2.0f)),
        ImVec2(region_max.x + ShellUi(4.0f), region_min.y - ShellUi(1.0f)),
        IM_COL32(115, 178, 104, 255)
    );

    auto item_width = [&](const GuideItem& item) {
        const ImVec2 label_size = guide_font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, item.label.c_str());
        const ImVec2 key_size = guide_font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, item.key);
        const float key_width = std::max(ShellUi(26.0f), key_size.x + ShellUi(14.0f));
        return key_width + label_gap + label_size.x + ShellUi(12.0f);
    };

    auto draw_guide_item = [&](const GuideItem& item, float x) {
        const ImVec2 label_size = guide_font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, item.label.c_str());
        const ImVec2 key_size = guide_font->CalcTextSizeA(font_size, FLT_MAX, 0.0f, item.key);
        const float key_width = std::max(ShellUi(26.0f), key_size.x + ShellUi(14.0f));
        const float total_width = key_width + label_gap + label_size.x + ShellUi(12.0f);
        const ImVec2 min(x, region_min.y);
        const ImVec2 max(x + total_width, region_min.y + key_height + vertical_padding * 2.0f);

        ImGui::SetCursorScreenPos(min);
        if (!item.enabled) {
            ImGui::BeginDisabled();
        }
        const bool pressed = ImGui::InvisibleButton(item.id, ImVec2(max.x - min.x, max.y - min.y));
        const bool hovered = ImGui::IsItemHovered();
        if (!item.enabled) {
            ImGui::EndDisabled();
        }

        const ImU32 text_color = item.enabled
            ? (hovered ? IM_COL32(248, 250, 242, 255) : IM_COL32(226, 237, 231, 240))
            : IM_COL32(120, 132, 125, 180);
        const ImU32 key_border = hovered ? IM_COL32(255, 211, 88, 240) : IM_COL32(255, 188, 0, 210);
        const ImU32 key_fill = hovered ? IM_COL32(32, 43, 25, 255) : IM_COL32(18, 20, 16, 245);
        const ImVec2 key_min(min.x, min.y + vertical_padding);
        const ImVec2 key_max(min.x + key_width, max.y - vertical_padding);

        draw->AddRectFilled(key_min, key_max, key_fill, ShellUi(4.0f));
        draw->AddRect(key_min, key_max, key_border, ShellUi(4.0f), 0, 1.1f);
        draw->AddText(
            guide_font,
            font_size,
            ImVec2(key_min.x + ((key_width - key_size.x) * 0.5f), key_min.y + ((key_max.y - key_min.y) - key_size.y) * 0.5f),
            IM_COL32(255, 188, 0, item.enabled ? 255 : 170),
            item.key
        );
        draw->AddText(
            guide_font,
            font_size,
            ImVec2(key_max.x + label_gap, key_min.y + ((key_max.y - key_min.y) - label_size.y) * 0.5f),
            text_color,
            item.label.c_str()
        );

        if (pressed && item.enabled) {
            PlayCue(UiCue::Cursor);
        }
        return pressed && item.enabled;
    };

    float left_offset = 0.0f;
    for (const GuideItem& item : guide_items) {
        if (item.right_aligned) {
            continue;
        }
        const float x = region_min.x + left_offset;
        if (draw_guide_item(item, x)) {
            if (std::strcmp(item.id, "guide-next") == 0) {
                if (state.current_screen == ShellScreen::Review) {
                    StartAction(state, CurrentActionId(state));
                } else if (state.current_screen == ShellScreen::Run && IsActionStillRunning(state)) {
                    RefreshSnapshot(state);
                    RefreshRunSnapshot(state);
                    RefreshResultPanels(state);
                    state.status_line = "Refreshed local run state.";
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
            }
        }
        left_offset += item_width(item) + item_gap;
    }

    float right_offset = 0.0f;
    for (auto it = guide_items.rbegin(); it != guide_items.rend(); ++it) {
        if (!it->right_aligned) {
            continue;
        }
        const float width = item_width(*it);
        const float x = region_max.x - right_offset - width;
        if (draw_guide_item(*it, x)) {
            if (std::strcmp(it->id, "guide-jira") == 0) {
                copy_by_key("jira", "Copied Jira note.");
            } else if (std::strcmp(it->id, "guide-hero") == 0) {
                copy_by_key("qa_hero", "Copied QA Hero note.");
            } else if (std::strcmp(it->id, "guide-handoff") == 0) {
                copy_by_key("handoff", "Copied handoff note.");
            }
        }
        right_offset += width + item_gap;
    }

    ImGui::SetCursorScreenPos(ShellPoint(0.0f, 718.0f));
    ImGui::Dummy(ShellSize(1.0f, 1.0f));
}

void HandleShellHotkeys(ShellState& state) {
    if (state.prompt_visible) {
        return;
    }

    if (ImGui::IsKeyPressed(ImGuiKey_Escape, false)) {
        RequestBackAction(state);
        return;
    }

    if (!ImGui::IsKeyPressed(ImGuiKey_Enter, false) && !ImGui::IsKeyPressed(ImGuiKey_KeypadEnter, false)) {
        return;
    }

    if (state.current_screen == ShellScreen::Review) {
        if (SelectedActionReady(state)) {
            StartAction(state, CurrentActionId(state));
        }
        return;
    }

    if (state.current_screen == ShellScreen::Run && IsActionStillRunning(state)) {
        RefreshSnapshot(state);
        RefreshRunSnapshot(state);
        RefreshResultPanels(state);
        state.status_line = "Refreshed local run state.";
        return;
    }

    if (CanAdvanceFromPage(state, state.current_screen)) {
        SetScreen(state, NextScreen(state, state.current_screen));
    }
}

void RenderPromptModal(ShellState& state) {
    if (!state.prompt_visible) {
        return;
    }

    if (ImGui::IsKeyPressed(ImGuiKey_Escape, false)) {
        ClosePrompt(state);
        PlayCue(UiCue::Error);
        return;
    }
    if (ImGui::IsKeyPressed(ImGuiKey_Enter, false) || ImGui::IsKeyPressed(ImGuiKey_KeypadEnter, false)) {
        AcceptPrompt(state);
        PlayCue(UiCue::Confirm);
        return;
    }

    ImDrawList* draw = ImGui::GetForegroundDrawList();
    const ImVec2 display = ImGui::GetIO().DisplaySize;
    draw->AddRectFilled(ImVec2(0.0f, 0.0f), display, IM_COL32(0, 0, 0, 190));

    if (!BeginShellPanelAt("message-prompt-panel", state.prompt_title.c_str(), 360.0f, 222.0f, 560.0f, 196.0f, true)) {
        EndDecoratedPanel();
        return;
    }

    ImGui::TextWrapped("%s", state.prompt_message.c_str());
    ImGui::Spacing();
    ImGui::Dummy(ImVec2(0.0f, ShellUi(8.0f)));
    if (state.prompt_confirmation) {
        if (DrawInstallerNavButton("prompt-accept", state.prompt_accept_label, ImVec2(ShellUi(156.0f), ShellUi(30.0f)), true, true)) {
            AcceptPrompt(state);
        }
        ImGui::SameLine();
        if (DrawInstallerNavButton("prompt-cancel", state.prompt_cancel_label, ImVec2(ShellUi(156.0f), ShellUi(30.0f)), false, true)) {
            ClosePrompt(state);
        }
    } else {
        if (DrawInstallerNavButton("prompt-ok", "OK", ImVec2(ShellUi(156.0f), ShellUi(30.0f)), true, true)) {
            ClosePrompt(state);
        }
    }

    EndDecoratedPanel();
}

void RenderShell(ShellState& state) {
    DrawBackdropChrome(state);

    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(viewport->Pos);
    ImGui::SetNextWindowSize(viewport->Size);
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

    HandleShellHotkeys(state);

    switch (state.current_screen) {
    case ShellScreen::Introduction:
        if (BeginShellPanelAt("screen-panel", ScreenTitle(state.current_screen), kInstallerContainerX, kInstallerContainerY, 757.0f, 432.0f, false)) {
            RenderCurrentScreen(state);
            RenderWizardNavigation(state);
        }
        EndDecoratedPanel();
        break;
    case ShellScreen::Select:
    case ShellScreen::Review:
        if (BeginShellPanelAt("profiles-panel", "PROFILE SOURCE", 22.0f, 402.0f, 282.0f, 266.0f)) {
            RenderProfilesPanel(state);
        }
        EndDecoratedPanel();
        if (BeginShellPanelAt("screen-panel", ScreenTitle(state.current_screen), kInstallerContainerX, kInstallerContainerY, 757.0f, 432.0f, false)) {
            RenderCurrentScreen(state);
            RenderWizardNavigation(state);
        }
        EndDecoratedPanel();
        break;
    case ShellScreen::Run:
    case ShellScreen::Evidence:
    case ShellScreen::Files:
    case ShellScreen::Stages:
        if (BeginShellPanelAt("recent-actions-panel", "RECENT ACTIONS", 22.0f, 402.0f, 282.0f, 124.0f)) {
            RenderRecentActionsPanel(state);
        }
        EndDecoratedPanel();
        if (BeginShellPanelAt("recent-runs-panel", "RECENT RESULTS", 22.0f, 537.0f, 282.0f, 131.0f)) {
            RenderRecentResultsPanel(state);
        }
        EndDecoratedPanel();
        if (BeginShellPanelAt("screen-panel", ScreenTitle(state.current_screen), kInstallerContainerX, kInstallerContainerY, 757.0f, 432.0f, false)) {
            RenderCurrentScreen(state);
            RenderWizardNavigation(state);
        }
        EndDecoratedPanel();
        break;
    }

    DrawInstallerBorders();
    RenderButtonGuide(state);
    RenderPromptModal(state);
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

    const RECT monitor_rect = PrimaryMonitorRect();
    const int monitor_width = monitor_rect.right - monitor_rect.left;
    const int monitor_height = monitor_rect.bottom - monitor_rect.top;
    const int requested_width = g_window_options.width > 0 ? g_window_options.width : monitor_width;
    const int requested_height = g_window_options.height > 0 ? g_window_options.height : monitor_height;
    const bool use_fullscreen = g_window_options.fullscreen && g_window_options.width <= 0 && g_window_options.height <= 0;
    const DWORD window_style = use_fullscreen ? WS_POPUP : WS_OVERLAPPEDWINDOW;

    RECT window_rect{0, 0, requested_width, requested_height};
    if (!use_fullscreen) {
        AdjustWindowRect(&window_rect, window_style, FALSE);
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
        L"SG Preflight - Native Operator Shell",
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
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    io.ConfigWindowsMoveFromTitleBarOnly = true;
    LoadShellFonts(io, std::filesystem::path(backend.workspace_root));
    ImGui::StyleColorsDark();
    ApplyStyle();
    LoadShellAssets(std::filesystem::path(backend.workspace_root));
    LoadShellAudio(std::filesystem::path(backend.workspace_root));
    g_shell_appear_time = ImGui::GetTime();
    PlayCue(UiCue::Window);

    ImGui_ImplWin32_Init(window_handle);
    ImGui_ImplDX11_Init(g_device, g_device_context);

    ShellState state;
    g_live_shell_state = &state;
    state.backend = backend;
    if (g_shell_assets.loaded) {
        state.status_line = "Loaded real UnleashedRecomp DDS chrome.";
    } else if (g_shell_assets.attempted && !g_shell_assets.error.empty()) {
        state.status_line = "Fallback chrome active: " + g_shell_assets.error;
    }
    state.status_line += use_fullscreen
        ? " Display: native fullscreen."
        : " Display: windowed " + std::to_string(requested_width) + "x" + std::to_string(requested_height) + ".";
    if (g_using_warp) {
        state.status_line += " Renderer fallback: D3D11 WARP.";
    }
    if (g_shell_audio.available) {
        state.status_line += " Shell audio is ready; toggle music in Stages.";
    } else if (g_shell_audio.attempted && !g_shell_audio.last_error.empty()) {
        state.status_line += " Audio fallback active: " + g_shell_audio.last_error;
    }
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

        if (g_request_close_prompt) {
            OpenPrompt(
                state,
                "QUIT OPERATOR SHELL",
                IsActionStillRunning(state)
                    ? "Close the shell now? The current SG action will keep running in the background."
                    : "Close the operator shell now?",
                true,
                true,
                false
            );
            g_request_close_prompt = false;
        }

        if (state.request_exit) {
            done = true;
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

    g_live_shell_state = nullptr;

    ImGui_ImplDX11_Shutdown();
    ImGui_ImplWin32_Shutdown();
    ImGui::DestroyContext();

    CleanupDeviceD3D();
    DestroyWindow(window_handle);
    UnregisterClassW(window_class.lpszClassName, window_class.hInstance);
    return 0;
}
