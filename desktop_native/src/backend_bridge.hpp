#pragma once

#include <optional>
#include <string>
#include <vector>

#include <nlohmann/json_fwd.hpp>

namespace sg_preflight::native_shell {

struct BackendConfig {
    std::wstring workspace_root;
    std::wstring python_executable = L"python";
};

struct ProfileItem {
    std::string profile_id;
    std::string label;
    std::string summary;
    std::string recommended_action_id;
};

struct ActionItem {
    std::string action_id;
    std::string label;
    std::string description;
    bool ready = false;
    std::string blocker_message;
    std::string command_preview;
};

struct EvidenceItem {
    std::string path;
    std::string checker;
    std::string message;
    std::string severity;
    int line = -1;
    std::string source_kind;
};

struct ArtifactItem {
    std::string label;
    std::string path;
};

struct CopyItem {
    std::string key;
    std::string label;
    std::string text;
};

struct BlockerItem {
    std::string key;
    std::string label;
    std::string state;
    std::string summary;
    std::vector<std::string> blockers;
};

struct ManualCard {
    std::string key;
    std::string label;
    std::string state;
    std::string summary;
    std::string note;
};

struct RecentActionItem {
    std::string run_id;
    std::string action_id;
    std::string title;
    std::string status;
    std::string profile_id;
    std::string created_at_utc;
    std::string progress_label;
    std::string summary;
};

struct RecentRunItem {
    std::string run_id;
    std::string profile_id;
    std::string profile_label;
    std::string title;
    std::string status;
    std::string created_at_utc;
    std::string summary;
    std::string html_report;
};

struct SnapshotLinks {
    std::string output_root;
    std::string html_report;
    std::string markdown_report;
    std::string json_report;
};

struct ActionSnapshot {
    std::string run_id;
    std::string action_id;
    std::string title;
    std::string status;
    std::string profile_id;
    int progress_percent = 0;
    std::string progress_label;
    std::string progress_detail;
    std::string current_command;
    std::string child_run_id;
    std::string linked_run_id;
    std::vector<std::string> summary_lines;
    std::vector<EvidenceItem> top_paths;
    std::vector<std::string> manual_followups;
    std::vector<ArtifactItem> artifacts;
    std::string log_path;
    std::string log_tail;
    SnapshotLinks latest_run_links;
    std::vector<CopyItem> copy_items;
    bool summary_only = true;
};

struct RunSnapshot {
    std::string run_id;
    std::string profile_id;
    std::string profile_label;
    std::string status;
    std::string created_at_utc;
    std::string workflow_stage_label;
    std::string summary_title;
    std::vector<std::string> summary_lines;
    std::vector<std::string> grouped_lines;
    std::vector<std::string> notes;
    std::vector<std::string> packs;
    std::vector<ArtifactItem> artifacts;
    std::vector<ArtifactItem> source_files;
    std::vector<CopyItem> copy_items;
};

std::wstring ToWide(const std::string& text);
std::string ToUtf8(const std::wstring& text);

std::vector<ProfileItem> LoadProfiles(const BackendConfig& config);
std::vector<ActionItem> LoadActions(const BackendConfig& config, const std::string& profile_id);
std::vector<BlockerItem> LoadBlockers(const BackendConfig& config, const std::string& profile_id);
std::vector<ManualCard> LoadManualCards(const BackendConfig& config, const std::string& profile_id);
std::vector<RecentActionItem> LoadRecentActions(
    const BackendConfig& config,
    const std::string& profile_id,
    int limit
);
std::vector<RecentRunItem> LoadRecentRuns(
    const BackendConfig& config,
    const std::string& profile_id,
    int limit
);
ActionSnapshot LoadSnapshot(const BackendConfig& config, const std::string& run_id_or_path);
RunSnapshot LoadRunSnapshot(const BackendConfig& config, const std::string& run_id_or_path);
std::string LaunchAction(const BackendConfig& config, const std::string& action_id);

}  // namespace sg_preflight::native_shell
