#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <nlohmann/json_fwd.hpp>

namespace sg_preflight::native_shell {

struct BackendConfig {
    std::wstring workspace_root;
    std::wstring python_executable = L"python";
    std::string initial_profile_id;
    std::string initial_action_id;
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

struct ManualEvidenceItem {
    std::string id;
    std::string kind;
    std::string label;
    std::string path;
    std::string note;
    std::string source_path;
    std::string created_at_utc;
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
    std::string workspace_root;
    std::string project_root;
    std::string output_root;
    std::string error_message;
    int exit_code = 0;
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

struct EnvironmentDoctorItem {
    std::string key;
    std::string category;
    std::string label;
    std::string state;
    std::string summary;
    std::string path;
    std::string next_action;
};

struct ReviewPriorityItem {
    std::string profile_id;
    std::string filter_name;
    std::string verdict;
    std::string priority_level;
    int priority_score = 0;
    std::string reason;
    std::string recommendation;
    std::string log_path;
    bool is_new_since_previous_run = false;
};

struct ReviewOwnerDecisionItem {
    std::string key;
    std::string title;
    std::string status;
    std::string owner;
    std::string date;
    std::string notes;
    bool pending = true;
};

struct ExternalFindingItem {
    std::string finding_id;
    std::string source;
    std::string reported_by;
    std::string type;
    std::string category;
    std::vector<std::string> scope;
    std::string finding;
    std::string owner;
    std::string status;
    std::string note;
    std::vector<std::string> related_investigation_surfaces;
};

struct ManualReviewProfileItem {
    std::string profile_id;
    std::string status;
    std::string summary;
    std::string note;
    std::string copy_review_note_text;
    std::string raco_scene_path;
    bool raco_scene_exists = false;
    std::string blender_workfile_path;
    bool blender_workfile_exists = false;
    std::string candidate_gallery_path;
    bool candidate_gallery_exists = false;
    std::string screenshot_triage_path;
    bool screenshot_triage_exists = false;
    std::string manual_review_record_path;
    bool manual_review_record_exists = false;
    std::string screenshot_evidence_slots_path;
    bool screenshot_evidence_slots_exists = false;
};

struct ReviewBoardState {
    std::string ticket_id;
    std::string title;
    std::vector<std::string> scope;
    std::string package_path;
    std::string package_zip_path;
    std::string generated_at;
    std::string review_owner_update_text;
    std::string morning_digest_text;
    std::string verification_status;
    std::string dod_overall_status;
    int visible_dod_progress_percent = 0;
    int smoke_completed = 0;
    int smoke_total = 0;
    int battery_total = 0;
    int exact_candidate_ready = 0;
    int proxy_candidate_ready = 0;
    int runtime_crash = 0;
    bool has_previous_run = false;
    int new_failures_count = 0;
    int resolved_failures_count = 0;
    int new_screenshot_diffs_count = 0;
    int unchanged_blockers_count = 0;
    std::string daily_delta_headline;
    std::vector<std::string> unresolved_families;
    std::vector<std::string> open_items;
    std::vector<ReviewPriorityItem> review_priority_items;
    std::vector<ReviewOwnerDecisionItem> decisions;
    std::vector<ExternalFindingItem> external_findings;
    std::vector<ManualReviewProfileItem> manual_review_profiles;
    std::vector<ArtifactItem> artifacts;
};

std::wstring ToWide(const std::string& text);
std::string ToUtf8(const std::wstring& text);
void AppendNativeTrace(std::string_view line);

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
std::vector<EnvironmentDoctorItem> LoadEnvironmentDoctor(const BackendConfig& config);
ReviewBoardState LoadReviewBoard(const BackendConfig& config, const std::string& ticket_id);
ReviewBoardState SetReviewDecision(
    const BackendConfig& config,
    const std::string& ticket_id,
    const std::string& decision_key,
    const std::string& status,
    const std::string& owner = {},
    const std::string& note = {},
    const std::string& date = {},
    const std::string& title = {}
);
ManualEvidenceItem AttachManualEvidence(
    const BackendConfig& config,
    const std::string& run_id_or_path,
    const std::string& kind,
    const std::string& label,
    const std::wstring& source_path,
    const std::wstring& note_text
);
ActionSnapshot LoadSnapshot(const BackendConfig& config, const std::string& run_id_or_path);
RunSnapshot LoadRunSnapshot(const BackendConfig& config, const std::string& run_id_or_path);
std::string LaunchAction(const BackendConfig& config, const std::string& action_id);

}  // namespace sg_preflight::native_shell
