#pragma once

#include "backend_bridge.hpp"
#include "localization.hpp"
#include "shell_types.hpp"

#include <array>
#include <cfloat>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

struct ArtifactChoice {
    std::string section;
    std::string label;
    std::string path;
};

struct ShellState {
    sg_preflight::native_shell::BackendConfig backend;
    sg_preflight::native_shell::ShellLanguage language = sg_preflight::native_shell::ShellLanguage::English;
    std::vector<sg_preflight::native_shell::ProfileItem> profiles;
    std::vector<sg_preflight::native_shell::ActionItem> actions;
    std::vector<sg_preflight::native_shell::BlockerItem> blockers;
    std::vector<sg_preflight::native_shell::ManualCard> manual_cards;
    std::vector<sg_preflight::native_shell::EnvironmentDoctorItem> environment_items;
    std::vector<sg_preflight::native_shell::RecentActionItem> recent_actions;
    std::vector<sg_preflight::native_shell::RecentRunItem> recent_runs;
    std::optional<sg_preflight::native_shell::ActionSnapshot> snapshot;
    std::optional<sg_preflight::native_shell::RunSnapshot> run_snapshot;
    std::optional<sg_preflight::native_shell::ReviewBoardState> review_board;
    int selected_profile_index = 0;
    int selected_evidence_index = 0;
    int selected_artifact_index = 0;
    int selected_environment_index = 0;
    std::string selected_action_id;
    std::string current_run_id;
    std::string current_result_run_id;
    std::string status_line = sg_preflight::native_shell::FormatReadyForNextActionStatus(sg_preflight::native_shell::ShellLanguage::English);
    std::string last_error;
    double next_poll_at = DBL_MAX;
    sg_preflight::native_shell::ShellScreen current_screen = sg_preflight::native_shell::ShellScreen::Introduction;
    sg_preflight::native_shell::ShellScreen previous_screen = sg_preflight::native_shell::ShellScreen::Introduction;
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
    std::vector<sg_preflight::native_shell::ActionItem> actions;
    std::vector<sg_preflight::native_shell::BlockerItem> blockers;
    std::vector<sg_preflight::native_shell::ManualCard> manual_cards;
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
    std::vector<sg_preflight::native_shell::RecentActionItem> recent_actions;
    std::vector<sg_preflight::native_shell::RecentRunItem> recent_runs;
    std::optional<sg_preflight::native_shell::ActionSnapshot> snapshot;
    std::optional<sg_preflight::native_shell::RunSnapshot> run_snapshot;
    std::string error;
};

struct ProfileSelectionCacheEntry {
    std::vector<sg_preflight::native_shell::ActionItem> actions;
    std::vector<sg_preflight::native_shell::BlockerItem> blockers;
    std::vector<sg_preflight::native_shell::ManualCard> manual_cards;
};

struct InitialShellLoadResult {
    std::vector<sg_preflight::native_shell::ProfileItem> profiles;
    std::vector<sg_preflight::native_shell::ActionItem> actions;
    std::vector<sg_preflight::native_shell::BlockerItem> blockers;
    std::vector<sg_preflight::native_shell::ManualCard> manual_cards;
    std::vector<sg_preflight::native_shell::EnvironmentDoctorItem> environment_items;
    std::vector<sg_preflight::native_shell::RecentActionItem> recent_actions;
    std::vector<sg_preflight::native_shell::RecentRunItem> recent_runs;
    std::optional<sg_preflight::native_shell::ActionSnapshot> snapshot;
    std::optional<sg_preflight::native_shell::RunSnapshot> run_snapshot;
    int selected_profile_index = 0;
    std::string selected_action_id;
    std::string current_run_id;
    std::string current_result_run_id;
    std::string error;
};

const char* ScreenLabel(sg_preflight::native_shell::ShellScreen screen);
sg_preflight::native_shell::ShellScreen FirstOperationalScreen();
std::string CurrentProfileId(const ShellState& state);
std::string CurrentActionId(const ShellState& state);
const sg_preflight::native_shell::ActionItem* FindSelectedAction(const ShellState& state);
bool HasEvidenceReady(const ShellState& state);
bool HasArtifactsReady(const ShellState& state);
bool HasCompletedRun(const ShellState& state);
bool SelectedActionReady(const ShellState& state);
bool CanAdvanceFromPage(const ShellState& state, sg_preflight::native_shell::ShellScreen screen);
sg_preflight::native_shell::ShellScreen NextScreen(const ShellState& state, sg_preflight::native_shell::ShellScreen screen);
sg_preflight::native_shell::ShellScreen PreviousScreen(const ShellState& state, sg_preflight::native_shell::ShellScreen screen);
bool IsActionStillRunning(const ShellState& state);
bool ShouldAutoRefreshRunInCurrentScreen(const ShellState& state);
std::vector<ArtifactChoice> CombinedArtifacts(const ShellState& state);
std::vector<sg_preflight::native_shell::CopyItem> CombinedCopyItems(const ShellState& state);
std::wstring SelectedArtifactPath(const ShellState& state);
std::wstring EnvironmentDoctorPath(const ShellState& state, const std::string& key);
std::wstring SelectedEnvironmentDoctorPath(const ShellState& state);
std::wstring CurrentBmwChecklistPath(const ShellState& state);
std::filesystem::path CurrentActionOutputRoot(const ShellState& state);
std::wstring CurrentProjectRoot(const ShellState& state);
bool PathHasExtension(const std::wstring& path, const std::wstring& expected_extension);
std::string ActiveManualEvidenceNote(const ShellState& state);
void ClearManualEvidenceNote(ShellState& state);
void ClampSelections(ShellState& state);
