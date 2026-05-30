#include "shell_state.hpp"

#include <algorithm>
#include <cwctype>
#include <system_error>

namespace {

std::wstring Lowercase(const std::wstring& text) {
    std::wstring lowered = text;
    std::transform(
        lowered.begin(),
        lowered.end(),
        lowered.begin(),
        [](wchar_t value) { return static_cast<wchar_t>(std::towlower(value)); }
    );
    return lowered;
}

bool PathExists(const std::filesystem::path& path) {
    std::error_code error;
    return std::filesystem::exists(path, error);
}

}  // namespace

const char* ScreenLabel(sg_preflight::native_shell::ShellScreen screen) {
    switch (screen) {
    case sg_preflight::native_shell::ShellScreen::Language:
        return "LANG";
    case sg_preflight::native_shell::ShellScreen::Introduction:
        return "INTRO";
    case sg_preflight::native_shell::ShellScreen::Select:
        return "SELECT";
    case sg_preflight::native_shell::ShellScreen::Review:
        return "REVIEW";
    case sg_preflight::native_shell::ShellScreen::Run:
        return "RUN";
    case sg_preflight::native_shell::ShellScreen::Evidence:
        return "EVIDENCE";
    case sg_preflight::native_shell::ShellScreen::Files:
        return "FILES";
    case sg_preflight::native_shell::ShellScreen::Environment:
        return "ENV";
    case sg_preflight::native_shell::ShellScreen::Stages:
        return "STAGES";
    case sg_preflight::native_shell::ShellScreen::ReviewBoard:
        return "BOARD";
    default:
        return "SCREEN";
    }
}

sg_preflight::native_shell::ShellScreen FirstOperationalScreen() {
    return sg_preflight::native_shell::ShellScreen::Introduction;
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

const sg_preflight::native_shell::ActionItem* FindSelectedAction(const ShellState& state) {
    for (const auto& action : state.actions) {
        if (action.action_id == state.selected_action_id) {
            return &action;
        }
    }
    return nullptr;
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

bool SelectedActionReady(const ShellState& state) {
    const std::string action_id = CurrentActionId(state);
    if (action_id == "daily_live_matrix") {
        return true;
    }
    const sg_preflight::native_shell::ActionItem* action = FindSelectedAction(state);
    return action != nullptr && action->ready;
}

bool CanAdvanceFromPage(const ShellState& state, sg_preflight::native_shell::ShellScreen screen) {
    switch (screen) {
    case sg_preflight::native_shell::ShellScreen::Language:
        return true;
    case sg_preflight::native_shell::ShellScreen::Introduction:
        return true;
    case sg_preflight::native_shell::ShellScreen::Select:
        return !state.profile_panel_loading && !state.profiles.empty() && !CurrentActionId(state).empty();
    case sg_preflight::native_shell::ShellScreen::Review:
        return SelectedActionReady(state);
    case sg_preflight::native_shell::ShellScreen::Run:
        return HasCompletedRun(state);
    case sg_preflight::native_shell::ShellScreen::Evidence:
        return HasArtifactsReady(state);
    case sg_preflight::native_shell::ShellScreen::Files:
        return true;
    case sg_preflight::native_shell::ShellScreen::Environment:
        return true;
    case sg_preflight::native_shell::ShellScreen::Stages:
        return true;
    case sg_preflight::native_shell::ShellScreen::ReviewBoard:
        return true;
    default:
        return false;
    }
}

sg_preflight::native_shell::ShellScreen NextScreen(const ShellState& state, sg_preflight::native_shell::ShellScreen screen) {
    switch (screen) {
    case sg_preflight::native_shell::ShellScreen::Language:
        return sg_preflight::native_shell::ShellScreen::Introduction;
    case sg_preflight::native_shell::ShellScreen::Introduction:
        return sg_preflight::native_shell::ShellScreen::Select;
    case sg_preflight::native_shell::ShellScreen::Select:
        return sg_preflight::native_shell::ShellScreen::Review;
    case sg_preflight::native_shell::ShellScreen::Review:
        return sg_preflight::native_shell::ShellScreen::Run;
    case sg_preflight::native_shell::ShellScreen::Run:
        if (HasEvidenceReady(state)) {
            return sg_preflight::native_shell::ShellScreen::Evidence;
        }
        if (HasArtifactsReady(state)) {
            return sg_preflight::native_shell::ShellScreen::Files;
        }
        return sg_preflight::native_shell::ShellScreen::Environment;
    case sg_preflight::native_shell::ShellScreen::Evidence:
        return sg_preflight::native_shell::ShellScreen::Files;
    case sg_preflight::native_shell::ShellScreen::Files:
        return sg_preflight::native_shell::ShellScreen::Environment;
    case sg_preflight::native_shell::ShellScreen::Environment:
        return sg_preflight::native_shell::ShellScreen::Stages;
    case sg_preflight::native_shell::ShellScreen::Stages:
        return sg_preflight::native_shell::ShellScreen::ReviewBoard;
    case sg_preflight::native_shell::ShellScreen::ReviewBoard:
        return sg_preflight::native_shell::ShellScreen::Select;
    default:
        return sg_preflight::native_shell::ShellScreen::Select;
    }
}

sg_preflight::native_shell::ShellScreen PreviousScreen(const ShellState& state, sg_preflight::native_shell::ShellScreen screen) {
    switch (screen) {
    case sg_preflight::native_shell::ShellScreen::Language:
        return sg_preflight::native_shell::ShellScreen::Language;
    case sg_preflight::native_shell::ShellScreen::Introduction:
        return sg_preflight::native_shell::ShellScreen::Language;
    case sg_preflight::native_shell::ShellScreen::Select:
        return sg_preflight::native_shell::ShellScreen::Introduction;
    case sg_preflight::native_shell::ShellScreen::Review:
        return sg_preflight::native_shell::ShellScreen::Select;
    case sg_preflight::native_shell::ShellScreen::Run:
        return sg_preflight::native_shell::ShellScreen::Review;
    case sg_preflight::native_shell::ShellScreen::Evidence:
        return sg_preflight::native_shell::ShellScreen::Run;
    case sg_preflight::native_shell::ShellScreen::Files:
        return HasEvidenceReady(state) ? sg_preflight::native_shell::ShellScreen::Evidence : sg_preflight::native_shell::ShellScreen::Run;
    case sg_preflight::native_shell::ShellScreen::Environment:
        return HasArtifactsReady(state) ? sg_preflight::native_shell::ShellScreen::Files : sg_preflight::native_shell::ShellScreen::Run;
    case sg_preflight::native_shell::ShellScreen::Stages:
        return sg_preflight::native_shell::ShellScreen::Environment;
    case sg_preflight::native_shell::ShellScreen::ReviewBoard:
        return sg_preflight::native_shell::ShellScreen::Stages;
    default:
        return sg_preflight::native_shell::ShellScreen::Introduction;
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
    case sg_preflight::native_shell::ShellScreen::Run:
    case sg_preflight::native_shell::ShellScreen::Evidence:
    case sg_preflight::native_shell::ShellScreen::Files:
    case sg_preflight::native_shell::ShellScreen::Environment:
    case sg_preflight::native_shell::ShellScreen::Stages:
        return true;
    case sg_preflight::native_shell::ShellScreen::ReviewBoard:
        return false;
    case sg_preflight::native_shell::ShellScreen::Language:
    case sg_preflight::native_shell::ShellScreen::Introduction:
    case sg_preflight::native_shell::ShellScreen::Select:
    case sg_preflight::native_shell::ShellScreen::Review:
    default:
        return false;
    }
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

std::vector<sg_preflight::native_shell::CopyItem> CombinedCopyItems(const ShellState& state) {
    std::vector<sg_preflight::native_shell::CopyItem> items;
    std::vector<std::string> seen_keys;
    const auto append_items = [&](const std::vector<sg_preflight::native_shell::CopyItem>& source) {
        for (const auto& item : source) {
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
        [&](const auto& item) { return item.key == key; }
    );
    if (match == state.environment_items.end() || match->path.empty()) {
        return {};
    }
    return sg_preflight::native_shell::ToWide(match->path);
}

std::wstring SelectedEnvironmentDoctorPath(const ShellState& state) {
    if (state.environment_items.empty()) {
        return {};
    }
    const int clamped_index = std::clamp(state.selected_environment_index, 0, static_cast<int>(state.environment_items.size()) - 1);
    const std::string& path = state.environment_items[static_cast<size_t>(clamped_index)].path;
    return path.empty() ? std::wstring{} : sg_preflight::native_shell::ToWide(path);
}

std::wstring CurrentBmwChecklistPath(const ShellState& state) {
    const std::filesystem::path candidate = std::filesystem::path(state.backend.workspace_root) / "docs" / "bmw-access-integration-checklist.md";
    return PathExists(candidate) ? candidate.wstring() : std::wstring{};
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
