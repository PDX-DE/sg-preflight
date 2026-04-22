#include "backend_bridge.hpp"

#include <windows.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <vector>

#include <nlohmann/json.hpp>

namespace sg_preflight::native_shell {
using json = nlohmann::json;

namespace {

struct ProcessResult {
    DWORD exit_code = 0;
    std::string output;
};

std::mutex g_trace_mutex;

std::string WideToUtf8(std::wstring_view text) {
    if (text.empty()) {
        return {};
    }
    const int length = WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    if (length <= 0) {
        return {};
    }
    std::string result(static_cast<size_t>(length), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), result.data(), length, nullptr, nullptr);
    return result;
}

std::filesystem::path NativeTracePath() {
    wchar_t buffer[32767];
    const DWORD length = GetEnvironmentVariableW(L"SG_PREFLIGHT_NATIVE_TRACE_FILE", buffer, static_cast<DWORD>(std::size(buffer)));
    if (length == 0 || length >= std::size(buffer)) {
        return {};
    }
    return std::filesystem::path(std::wstring(buffer, length));
}

void AppendNativeTraceLine(std::string_view line) {
    const std::filesystem::path trace_path = NativeTracePath();
    if (trace_path.empty()) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_trace_mutex);
    std::ofstream stream(trace_path, std::ios::app | std::ios::binary);
    if (!stream) {
        return;
    }
    stream << line << "\r\n";
}

std::wstring QuoteWindowsArg(const std::wstring& arg) {
    if (arg.empty()) {
        return L"\"\"";
    }
    if (arg.find_first_of(L" \t\"") == std::wstring::npos) {
        return arg;
    }

    std::wstring quoted = L"\"";
    size_t backslash_count = 0;
    for (wchar_t ch : arg) {
        if (ch == L'\\') {
            ++backslash_count;
            continue;
        }
        if (ch == L'"') {
            quoted.append(backslash_count * 2 + 1, L'\\');
            quoted.push_back(L'"');
            backslash_count = 0;
            continue;
        }
        if (backslash_count > 0) {
            quoted.append(backslash_count, L'\\');
            backslash_count = 0;
        }
        quoted.push_back(ch);
    }
    if (backslash_count > 0) {
        quoted.append(backslash_count * 2, L'\\');
    }
    quoted.push_back(L'"');
    return quoted;
}

std::wstring JoinCommandLine(const std::vector<std::wstring>& args) {
    std::wstring command_line;
    for (size_t index = 0; index < args.size(); ++index) {
        if (index > 0) {
            command_line.push_back(L' ');
        }
        command_line += QuoteWindowsArg(args[index]);
    }
    return command_line;
}

ProcessResult RunProcessCapture(const std::vector<std::wstring>& args, const std::wstring& working_directory) {
    SECURITY_ATTRIBUTES attributes{};
    attributes.nLength = sizeof(attributes);
    attributes.bInheritHandle = TRUE;

    HANDLE read_pipe = nullptr;
    HANDLE write_pipe = nullptr;
    if (!CreatePipe(&read_pipe, &write_pipe, &attributes, 0)) {
        throw std::runtime_error("Failed to create backend output pipe.");
    }
    SetHandleInformation(read_pipe, HANDLE_FLAG_INHERIT, 0);

    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput = write_pipe;
    startup.hStdError = write_pipe;
    startup.wShowWindow = SW_HIDE;

    PROCESS_INFORMATION process{};
    std::wstring command_line = JoinCommandLine(args);
    std::vector<wchar_t> mutable_command(command_line.begin(), command_line.end());
    mutable_command.push_back(L'\0');

    const std::wstring effective_working_directory = working_directory.empty()
        ? std::filesystem::current_path().wstring()
        : working_directory;
    const auto started_at = std::chrono::steady_clock::now();
    AppendNativeTraceLine(
        "START cwd=\"" + WideToUtf8(effective_working_directory) + "\" cmd=\"" + WideToUtf8(command_line) + "\""
    );

    const BOOL started = CreateProcessW(
        nullptr,
        mutable_command.data(),
        nullptr,
        nullptr,
        TRUE,
        CREATE_NO_WINDOW,
        nullptr,
        effective_working_directory.c_str(),
        &startup,
        &process
    );

    CloseHandle(write_pipe);
    write_pipe = nullptr;

    if (!started) {
        CloseHandle(read_pipe);
        AppendNativeTraceLine("FAILED cmd=\"" + WideToUtf8(command_line) + "\" reason=\"CreateProcessW\"");
        throw std::runtime_error("Failed to launch Python backend command.");
    }

    std::string output;
    char buffer[4096];
    DWORD bytes_read = 0;
    while (ReadFile(read_pipe, buffer, sizeof(buffer), &bytes_read, nullptr) && bytes_read > 0) {
        output.append(buffer, bytes_read);
    }

    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD exit_code = 0;
    GetExitCodeProcess(process.hProcess, &exit_code);
    const auto finished_at = std::chrono::steady_clock::now();
    const auto duration_ms = std::chrono::duration_cast<std::chrono::milliseconds>(finished_at - started_at).count();

    CloseHandle(read_pipe);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);

    std::string trace_line =
        "END exit_code=" + std::to_string(exit_code)
        + " duration_ms=" + std::to_string(duration_ms)
        + " output_bytes=" + std::to_string(output.size())
        + " cmd=\"" + WideToUtf8(command_line) + "\"";
    AppendNativeTraceLine(trace_line);
    if (exit_code != 0 && !output.empty()) {
        std::string sanitized = output;
        for (char& ch : sanitized) {
            if (ch == '\r' || ch == '\n') {
                ch = ' ';
            }
        }
        if (sanitized.size() > 1200U) {
            sanitized.resize(1200U);
            sanitized += "...";
        }
        AppendNativeTraceLine("ERROR_OUTPUT \"" + sanitized + "\"");
    }

    return ProcessResult{exit_code, output};
}

std::vector<std::wstring> BuildBaseCommand(const BackendConfig& config) {
    std::vector<std::wstring> args = {
        config.python_executable.empty() ? L"python" : config.python_executable,
        L"-m",
        L"sg_preflight",
    };
    return args;
}

void AppendWorkspace(std::vector<std::wstring>& args, const BackendConfig& config) {
    if (config.workspace_root.empty()) {
        return;
    }
    args.push_back(L"--workspace");
    args.push_back(config.workspace_root);
}

json RunJsonCommand(const BackendConfig& config, std::vector<std::wstring> args) {
    std::vector<std::wstring> full_args = BuildBaseCommand(config);
    full_args.insert(full_args.end(), args.begin(), args.end());
    const ProcessResult result = RunProcessCapture(full_args, config.workspace_root);
    if (result.exit_code != 0) {
        throw std::runtime_error(result.output.empty() ? "Python backend command failed." : result.output);
    }
    try {
        return json::parse(result.output);
    } catch (const json::parse_error&) {
        throw std::runtime_error(result.output.empty() ? "Python backend returned no JSON." : result.output);
    }
}

std::string ValueString(const json& payload, std::string_view key) {
    const std::string name(key);
    return payload.contains(name) && payload.at(name).is_string()
        ? payload.at(name).get<std::string>()
        : std::string{};
}

int ValueInt(const json& payload, std::string_view key, int fallback = 0) {
    const std::string name(key);
    return payload.contains(name) && payload.at(name).is_number_integer()
        ? payload.at(name).get<int>()
        : fallback;
}

bool ValueBool(const json& payload, std::string_view key, bool fallback = false) {
    const std::string name(key);
    return payload.contains(name) && payload.at(name).is_boolean()
        ? payload.at(name).get<bool>()
        : fallback;
}

template <typename T>
std::vector<T> ParseArray(const json& payload) {
    if (!payload.is_array()) {
        return {};
    }
    return payload.get<std::vector<T>>();
}

}  // namespace

std::wstring ToWide(const std::string& text) {
    if (text.empty()) {
        return {};
    }
    const int length = MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, nullptr, 0);
    if (length <= 0) {
        return {};
    }
    std::vector<wchar_t> buffer(static_cast<size_t>(length), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, buffer.data(), length);
    return std::wstring(buffer.data());
}

std::string ToUtf8(const std::wstring& text) {
    if (text.empty()) {
        return {};
    }
    const int length = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), -1, nullptr, 0, nullptr, nullptr);
    if (length <= 0) {
        return {};
    }
    std::vector<char> buffer(static_cast<size_t>(length), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.c_str(), -1, buffer.data(), length, nullptr, nullptr);
    return std::string(buffer.data());
}

void AppendNativeTrace(std::string_view line) {
    AppendNativeTraceLine(line);
}

void from_json(const json& payload, ProfileItem& item) {
    item.profile_id = ValueString(payload, "profile_id");
    item.label = ValueString(payload, "label");
    item.summary = ValueString(payload, "summary");
    item.recommended_action_id = ValueString(payload, "recommended_action_id");
}

void from_json(const json& payload, ActionItem& item) {
    item.action_id = ValueString(payload, "action_id");
    item.label = ValueString(payload, "label");
    item.description = ValueString(payload, "description");
    item.ready = ValueBool(payload, "ready", false);
    item.blocker_message = ValueString(payload, "blocker_message");
    item.command_preview = ValueString(payload, "command_preview");
}

void from_json(const json& payload, EvidenceItem& item) {
    item.path = ValueString(payload, "path");
    item.checker = ValueString(payload, "checker");
    item.message = ValueString(payload, "message");
    item.severity = ValueString(payload, "severity");
    item.source_kind = ValueString(payload, "source_kind");
    item.line = payload.contains("line") && payload.at("line").is_number_integer()
        ? payload.at("line").get<int>()
        : -1;
}

void from_json(const json& payload, ArtifactItem& item) {
    item.label = ValueString(payload, "label");
    item.path = ValueString(payload, "path");
}

void from_json(const json& payload, ManualEvidenceItem& item) {
    item.id = ValueString(payload, "id");
    item.kind = ValueString(payload, "kind");
    item.label = ValueString(payload, "label");
    item.path = ValueString(payload, "path");
    item.note = ValueString(payload, "note");
    item.source_path = ValueString(payload, "source_path");
    item.created_at_utc = ValueString(payload, "created_at_utc");
}

void from_json(const json& payload, CopyItem& item) {
    item.key = ValueString(payload, "key");
    item.label = ValueString(payload, "label");
    item.text = ValueString(payload, "text");
}

void from_json(const json& payload, BlockerItem& item) {
    item.key = ValueString(payload, "key");
    item.label = ValueString(payload, "label");
    item.state = ValueString(payload, "state");
    item.summary = ValueString(payload, "summary");
    if (payload.contains("blockers") && payload.at("blockers").is_array()) {
        item.blockers = payload.at("blockers").get<std::vector<std::string>>();
    }
}

void from_json(const json& payload, ManualCard& item) {
    item.key = ValueString(payload, "key");
    item.label = ValueString(payload, "label");
    item.state = ValueString(payload, "state");
    item.summary = ValueString(payload, "summary");
    item.note = ValueString(payload, "note");
}

void from_json(const json& payload, RecentActionItem& item) {
    item.run_id = ValueString(payload, "run_id");
    item.action_id = ValueString(payload, "action_id");
    item.title = ValueString(payload, "title");
    item.status = ValueString(payload, "status");
    item.profile_id = ValueString(payload, "profile_id");
    item.created_at_utc = ValueString(payload, "created_at_utc");
    item.progress_label = ValueString(payload, "progress_label");
    item.summary = ValueString(payload, "summary");
}

void from_json(const json& payload, RecentRunItem& item) {
    item.run_id = ValueString(payload, "run_id");
    item.profile_id = ValueString(payload, "profile_id");
    item.profile_label = ValueString(payload, "profile_label");
    item.title = ValueString(payload, "title");
    item.status = ValueString(payload, "status");
    item.created_at_utc = ValueString(payload, "created_at_utc");
    item.summary = ValueString(payload, "summary");
    item.html_report = ValueString(payload, "html_report");
}

void from_json(const json& payload, SnapshotLinks& item) {
    item.output_root = ValueString(payload, "output_root");
    item.html_report = ValueString(payload, "html_report");
    item.markdown_report = ValueString(payload, "markdown_report");
    item.json_report = ValueString(payload, "json_report");
}

void from_json(const json& payload, ActionSnapshot& item) {
    item.run_id = ValueString(payload, "run_id");
    item.action_id = ValueString(payload, "action_id");
    item.title = ValueString(payload, "title");
    item.status = ValueString(payload, "status");
    item.profile_id = ValueString(payload, "profile_id");
    item.progress_percent = ValueInt(payload, "progress_percent", 0);
    item.progress_label = ValueString(payload, "progress_label");
    item.progress_detail = ValueString(payload, "progress_detail");
    item.current_command = ValueString(payload, "current_command");
    item.child_run_id = ValueString(payload, "child_run_id");
    item.linked_run_id = ValueString(payload, "linked_run_id");
    item.workspace_root = ValueString(payload, "workspace_root");
    item.project_root = ValueString(payload, "project_root");
    item.output_root = ValueString(payload, "output_root");
    item.error_message = ValueString(payload, "error_message");
    item.exit_code = ValueInt(payload, "exit_code", 0);
    if (payload.contains("summary_lines") && payload.at("summary_lines").is_array()) {
        item.summary_lines = payload.at("summary_lines").get<std::vector<std::string>>();
    }
    if (payload.contains("top_paths") && payload.at("top_paths").is_array()) {
        item.top_paths = payload.at("top_paths").get<std::vector<EvidenceItem>>();
    }
    if (payload.contains("manual_followups") && payload.at("manual_followups").is_array()) {
        item.manual_followups = payload.at("manual_followups").get<std::vector<std::string>>();
    }
    if (payload.contains("artifacts") && payload.at("artifacts").is_array()) {
        item.artifacts = payload.at("artifacts").get<std::vector<ArtifactItem>>();
    }
    item.log_path = ValueString(payload, "log_path");
    item.log_tail = ValueString(payload, "log_tail");
    if (payload.contains("latest_run_links") && payload.at("latest_run_links").is_object()) {
        item.latest_run_links = payload.at("latest_run_links").get<SnapshotLinks>();
    }
    if (payload.contains("copy_items") && payload.at("copy_items").is_array()) {
        item.copy_items = payload.at("copy_items").get<std::vector<CopyItem>>();
    }
    item.summary_only = ValueBool(payload, "summary_only", true);
}

void from_json(const json& payload, RunSnapshot& item) {
    item.run_id = ValueString(payload, "run_id");
    item.profile_id = ValueString(payload, "profile_id");
    item.profile_label = ValueString(payload, "profile_label");
    item.status = ValueString(payload, "status");
    item.initializing = ValueBool(payload, "initializing", false);
    item.created_at_utc = ValueString(payload, "created_at_utc");
    item.workflow_stage_label = ValueString(payload, "workflow_stage_label");
    item.summary_title = ValueString(payload, "summary_title");
    item.current_command = ValueString(payload, "current_command");
    item.log_path = ValueString(payload, "log_path");
    item.log_tail = ValueString(payload, "log_tail");
    item.output_root = ValueString(payload, "output_root");
    item.project_root = ValueString(payload, "project_root");
    item.error_message = ValueString(payload, "error_message");
    item.exit_code = ValueInt(payload, "exit_code", 0);
    if (payload.contains("summary_lines") && payload.at("summary_lines").is_array()) {
        item.summary_lines = payload.at("summary_lines").get<std::vector<std::string>>();
    }
    if (payload.contains("grouped_lines") && payload.at("grouped_lines").is_array()) {
        item.grouped_lines = payload.at("grouped_lines").get<std::vector<std::string>>();
    }
    if (payload.contains("notes") && payload.at("notes").is_array()) {
        item.notes = payload.at("notes").get<std::vector<std::string>>();
    }
    if (payload.contains("packs") && payload.at("packs").is_array()) {
        item.packs = payload.at("packs").get<std::vector<std::string>>();
    }
    if (payload.contains("artifacts") && payload.at("artifacts").is_array()) {
        item.artifacts = payload.at("artifacts").get<std::vector<ArtifactItem>>();
    }
    if (payload.contains("source_files") && payload.at("source_files").is_array()) {
        item.source_files = payload.at("source_files").get<std::vector<ArtifactItem>>();
    }
    if (payload.contains("copy_items") && payload.at("copy_items").is_array()) {
        item.copy_items = payload.at("copy_items").get<std::vector<CopyItem>>();
    }
}

void from_json(const json& payload, EnvironmentDoctorItem& item) {
    item.key = ValueString(payload, "key");
    item.category = ValueString(payload, "category");
    item.label = ValueString(payload, "label");
    item.state = ValueString(payload, "state");
    item.summary = ValueString(payload, "summary");
    item.path = ValueString(payload, "path");
    item.next_action = ValueString(payload, "next_action");
}

void from_json(const json& payload, ReviewPriorityItem& item) {
    item.profile_id = ValueString(payload, "profile_id");
    item.filter_name = ValueString(payload, "filter_name");
    item.verdict = ValueString(payload, "verdict");
    item.priority_level = ValueString(payload, "priority_level");
    item.attention_category = ValueString(payload, "attention_category");
    item.priority_score = ValueInt(payload, "priority_score", 0);
    item.reason = ValueString(payload, "reason");
    item.recommendation = ValueString(payload, "recommendation");
    item.log_path = ValueString(payload, "log_path");
    if (payload.contains("signals") && payload.at("signals").is_array()) {
        item.signals = payload.at("signals").get<std::vector<std::string>>();
    }
    item.is_new_since_previous_run = ValueBool(payload, "is_new_since_previous_run", false);
}

void from_json(const json& payload, ReviewOwnerDecisionItem& item) {
    item.key = ValueString(payload, "key");
    item.title = ValueString(payload, "title");
    item.status = ValueString(payload, "status");
    item.owner = ValueString(payload, "owner");
    item.date = ValueString(payload, "date");
    item.notes = ValueString(payload, "notes");
    item.pending = ValueBool(payload, "pending", true);
}

void from_json(const json& payload, ExternalFindingItem& item) {
    item.finding_id = ValueString(payload, "finding_id");
    item.source = ValueString(payload, "source");
    item.reported_by = ValueString(payload, "reported_by");
    item.type = ValueString(payload, "type");
    item.category = ValueString(payload, "category");
    if (payload.contains("scope") && payload.at("scope").is_array()) {
        item.scope = payload.at("scope").get<std::vector<std::string>>();
    }
    item.finding = ValueString(payload, "finding");
    item.owner = ValueString(payload, "owner");
    item.status = ValueString(payload, "status");
    item.note = ValueString(payload, "note");
    if (payload.contains("related_investigation_surfaces") && payload.at("related_investigation_surfaces").is_array()) {
        item.related_investigation_surfaces = payload.at("related_investigation_surfaces").get<std::vector<std::string>>();
    }
}

void from_json(const json& payload, ManualReviewProfileItem& item) {
    item.profile_id = ValueString(payload, "profile_id");
    item.status = ValueString(payload, "status");
    item.summary = ValueString(payload, "summary");
    item.note = ValueString(payload, "note");
    item.copy_review_note_text = ValueString(payload, "copy_review_note_text");
    if (payload.contains("raco_scene") && payload.at("raco_scene").is_object()) {
        item.raco_scene_path = ValueString(payload.at("raco_scene"), "absolute_path");
        item.raco_scene_exists = ValueBool(payload.at("raco_scene"), "exists", false);
    }
    if (payload.contains("blender_workfile") && payload.at("blender_workfile").is_object()) {
        item.blender_workfile_path = ValueString(payload.at("blender_workfile"), "absolute_path");
        item.blender_workfile_exists = ValueBool(payload.at("blender_workfile"), "exists", false);
    }
    if (payload.contains("candidate_gallery") && payload.at("candidate_gallery").is_object()) {
        item.candidate_gallery_path = ValueString(payload.at("candidate_gallery"), "absolute_path");
        item.candidate_gallery_exists = ValueBool(payload.at("candidate_gallery"), "exists", false);
    }
    if (payload.contains("screenshot_triage") && payload.at("screenshot_triage").is_object()) {
        item.screenshot_triage_path = ValueString(payload.at("screenshot_triage"), "absolute_path");
        item.screenshot_triage_exists = ValueBool(payload.at("screenshot_triage"), "exists", false);
    }
    if (payload.contains("manual_review_record") && payload.at("manual_review_record").is_object()) {
        item.manual_review_record_path = ValueString(payload.at("manual_review_record"), "absolute_path");
        item.manual_review_record_exists = ValueBool(payload.at("manual_review_record"), "exists", false);
    }
    if (payload.contains("screenshot_evidence_slots") && payload.at("screenshot_evidence_slots").is_object()) {
        item.screenshot_evidence_slots_path = ValueString(payload.at("screenshot_evidence_slots"), "absolute_path");
        item.screenshot_evidence_slots_exists = ValueBool(payload.at("screenshot_evidence_slots"), "exists", false);
    }
}

void from_json(const json& payload, ReviewBoardState& item) {
    item.ticket_id = ValueString(payload, "ticket_id");
    item.title = ValueString(payload, "title");
    item.package_path = ValueString(payload, "package_path");
    item.package_zip_path = ValueString(payload, "package_zip_path");
    item.generated_at = ValueString(payload, "generated_at");
    item.review_owner_update_text = ValueString(payload, "review_owner_update_text");
    item.morning_digest_text = ValueString(payload, "morning_digest_text");
    item.visible_dod_progress_percent = ValueInt(payload, "visible_dod_progress_percent", 0);
    if (payload.contains("scope") && payload.at("scope").is_array()) {
        item.scope = payload.at("scope").get<std::vector<std::string>>();
    }
    if (payload.contains("package_verification") && payload.at("package_verification").is_object()) {
        item.verification_status = ValueString(payload.at("package_verification"), "status");
    }
    if (payload.contains("dod_status_summary") && payload.at("dod_status_summary").is_object()) {
        item.dod_overall_status = ValueString(payload.at("dod_status_summary"), "overall_status");
    }
    if (payload.contains("daily_snapshot_summary") && payload.at("daily_snapshot_summary").is_object()) {
        const json& summary = payload.at("daily_snapshot_summary");
        item.smoke_completed = ValueInt(summary, "smoke_completed", 0);
        item.smoke_total = ValueInt(summary, "smoke_total", 0);
    }
    if (payload.contains("screenshot_battery_counts") && payload.at("screenshot_battery_counts").is_object()) {
        const json& counts = payload.at("screenshot_battery_counts");
        item.battery_total = ValueInt(counts, "total", 0);
        item.exact_candidate_ready = ValueInt(counts, "exact_candidate_ready", 0);
        item.proxy_candidate_ready = ValueInt(counts, "proxy_candidate_ready", 0);
        item.runtime_crash = ValueInt(counts, "runtime_crash", 0);
    }
    if (payload.contains("daily_delta_summary") && payload.at("daily_delta_summary").is_object()) {
        const json& delta = payload.at("daily_delta_summary");
        item.has_previous_run = ValueBool(delta, "has_previous_run", false);
        item.new_failures_count = ValueInt(delta, "new_failures_count", 0);
        item.resolved_failures_count = ValueInt(delta, "resolved_failures_count", 0);
        item.new_screenshot_diffs_count = ValueInt(delta, "new_screenshot_diffs_count", 0);
        item.unchanged_blockers_count = ValueInt(delta, "unchanged_blockers_count", 0);
        item.daily_delta_headline = ValueString(delta, "headline");
        if (delta.contains("new_failure_preview") && delta.at("new_failure_preview").is_array()) {
            item.new_failures = delta.at("new_failure_preview").get<std::vector<std::string>>();
        }
        if (delta.contains("resolved_failure_preview") && delta.at("resolved_failure_preview").is_array()) {
            item.resolved_failures = delta.at("resolved_failure_preview").get<std::vector<std::string>>();
        }
        if (delta.contains("new_screenshot_diff_preview") && delta.at("new_screenshot_diff_preview").is_array()) {
            item.new_screenshot_diffs = delta.at("new_screenshot_diff_preview").get<std::vector<std::string>>();
        }
        if (delta.contains("unchanged_blocker_preview") && delta.at("unchanged_blocker_preview").is_array()) {
            item.unchanged_blockers = delta.at("unchanged_blocker_preview").get<std::vector<std::string>>();
        }
        if (delta.contains("review_first_preview") && delta.at("review_first_preview").is_array()) {
            item.review_first_preview = delta.at("review_first_preview").get<std::vector<std::string>>();
        }
    }
    item.operator_next_step = ValueString(payload, "operator_next_step");
    if (payload.contains("unresolved_families") && payload.at("unresolved_families").is_array()) {
        item.unresolved_families = payload.at("unresolved_families").get<std::vector<std::string>>();
    }
    if (payload.contains("open_items") && payload.at("open_items").is_array()) {
        item.open_items = payload.at("open_items").get<std::vector<std::string>>();
    }
    if (payload.contains("top_review_priority_items") && payload.at("top_review_priority_items").is_array()) {
        item.review_priority_items = payload.at("top_review_priority_items").get<std::vector<ReviewPriorityItem>>();
    }
    if (payload.contains("review_owner_decisions") && payload.at("review_owner_decisions").is_object()) {
        const json& decisions = payload.at("review_owner_decisions");
        if (decisions.contains("status_options") && decisions.at("status_options").is_array()) {
            item.decision_status_options = decisions.at("status_options").get<std::vector<std::string>>();
        }
        if (decisions.contains("sections") && decisions.at("sections").is_array()) {
            item.decisions = decisions.at("sections").get<std::vector<ReviewOwnerDecisionItem>>();
        }
    }
    if (payload.contains("external_findings") && payload.at("external_findings").is_object()) {
        const json& findings = payload.at("external_findings");
        if (findings.contains("items") && findings.at("items").is_array()) {
            item.external_findings = findings.at("items").get<std::vector<ExternalFindingItem>>();
        }
    }
    if (payload.contains("manual_review_profiles") && payload.at("manual_review_profiles").is_array()) {
        item.manual_review_profiles = payload.at("manual_review_profiles").get<std::vector<ManualReviewProfileItem>>();
    }
    if (payload.contains("artifact_references") && payload.at("artifact_references").is_object()) {
        for (const auto& [_, value] : payload.at("artifact_references").items()) {
            ArtifactItem artifact;
            artifact.label = ValueString(value, "label");
            artifact.path = ValueString(value, "absolute_path");
            if (!artifact.path.empty()) {
                item.artifacts.push_back(artifact);
            }
        }
    }
}

std::vector<ProfileItem> LoadProfiles(const BackendConfig& config) {
    std::vector<std::wstring> args = {L"desktop-state", L"profiles", L"--json"};
    AppendWorkspace(args, config);
    return ParseArray<ProfileItem>(RunJsonCommand(config, args));
}

std::vector<ActionItem> LoadActions(const BackendConfig& config, const std::string& profile_id) {
    std::vector<std::wstring> args = {
        L"desktop-state",
        L"actions",
        ToWide(profile_id),
        L"--json",
    };
    AppendWorkspace(args, config);
    return ParseArray<ActionItem>(RunJsonCommand(config, args));
}

std::vector<BlockerItem> LoadBlockers(const BackendConfig& config, const std::string& profile_id) {
    std::vector<std::wstring> args = {
        L"desktop-state",
        L"blockers",
        ToWide(profile_id),
        L"--json",
    };
    AppendWorkspace(args, config);
    return ParseArray<BlockerItem>(RunJsonCommand(config, args));
}

std::vector<ManualCard> LoadManualCards(const BackendConfig& config, const std::string& profile_id) {
    std::vector<std::wstring> args = {
        L"desktop-state",
        L"manual",
        ToWide(profile_id),
        L"--json",
    };
    AppendWorkspace(args, config);
    return ParseArray<ManualCard>(RunJsonCommand(config, args));
}

std::vector<RecentActionItem> LoadRecentActions(
    const BackendConfig& config,
    const std::string& profile_id,
    int limit
) {
    std::vector<std::wstring> args = {
        L"desktop-state",
        L"recent-actions",
        L"--json",
        L"--limit",
        std::to_wstring(limit),
    };
    if (!profile_id.empty()) {
        args.push_back(L"--profile-id");
        args.push_back(ToWide(profile_id));
    }
    AppendWorkspace(args, config);
    return ParseArray<RecentActionItem>(RunJsonCommand(config, args));
}

std::vector<RecentRunItem> LoadRecentRuns(
    const BackendConfig& config,
    const std::string& profile_id,
    int limit
) {
    std::vector<std::wstring> args = {
        L"desktop-state",
        L"recent-runs",
        L"--json",
        L"--limit",
        std::to_wstring(limit),
    };
    if (!profile_id.empty()) {
        args.push_back(L"--profile-id");
        args.push_back(ToWide(profile_id));
    }
    AppendWorkspace(args, config);
    return ParseArray<RecentRunItem>(RunJsonCommand(config, args));
}

std::vector<EnvironmentDoctorItem> LoadEnvironmentDoctor(const BackendConfig& config) {
    std::vector<std::wstring> args = {
        L"desktop-state",
        L"environment",
        L"--json",
    };
    AppendWorkspace(args, config);
    return ParseArray<EnvironmentDoctorItem>(RunJsonCommand(config, args));
}

ReviewBoardState LoadReviewBoard(const BackendConfig& config, const std::string& ticket_id) {
    std::vector<std::wstring> args = {
        L"desktop-state",
        L"review-board",
        L"--json",
    };
    if (!ticket_id.empty()) {
        args.push_back(L"--ticket-id");
        args.push_back(ToWide(ticket_id));
    }
    AppendWorkspace(args, config);
    return RunJsonCommand(config, args).get<ReviewBoardState>();
}

ReviewBoardState SetReviewDecision(
    const BackendConfig& config,
    const std::string& ticket_id,
    const std::string& decision_key,
    const std::string& status,
    const std::string& owner,
    const std::string& note,
    const std::string& date,
    const std::string& title
) {
    std::vector<std::wstring> args = {
        L"review-decisions",
        L"set",
        ToWide(ticket_id),
        ToWide(decision_key),
        L"--status",
        ToWide(status),
        L"--json",
    };
    if (!owner.empty()) {
        args.push_back(L"--owner");
        args.push_back(ToWide(owner));
    }
    if (!note.empty()) {
        args.push_back(L"--note");
        args.push_back(ToWide(note));
    }
    if (!date.empty()) {
        args.push_back(L"--date");
        args.push_back(ToWide(date));
    }
    if (!title.empty()) {
        args.push_back(L"--title");
        args.push_back(ToWide(title));
    }
    AppendWorkspace(args, config);
    (void)RunJsonCommand(config, args);
    return LoadReviewBoard(config, ticket_id);
}

ReviewBoardState AddExternalFinding(
    const BackendConfig& config,
    const std::string& ticket_id,
    const std::string& source,
    const std::string& reported_by,
    const std::string& category,
    const std::vector<std::string>& scope,
    const std::string& finding,
    const std::string& owner,
    const std::string& status,
    const std::string& note,
    const std::string& finding_type,
    const std::vector<std::string>& related_investigation_surfaces
) {
    std::vector<std::wstring> args = {
        L"external-findings",
        L"add",
        ToWide(ticket_id),
        L"--source",
        ToWide(source),
        L"--reported-by",
        ToWide(reported_by),
        L"--category",
        ToWide(category),
        L"--finding",
        ToWide(finding),
        L"--json",
    };
    for (const auto& scope_item : scope) {
        if (scope_item.empty()) {
            continue;
        }
        args.push_back(L"--scope");
        args.push_back(ToWide(scope_item));
    }
    if (!owner.empty()) {
        args.push_back(L"--owner");
        args.push_back(ToWide(owner));
    }
    if (!status.empty()) {
        args.push_back(L"--status");
        args.push_back(ToWide(status));
    }
    if (!note.empty()) {
        args.push_back(L"--note");
        args.push_back(ToWide(note));
    }
    if (!finding_type.empty()) {
        args.push_back(L"--type");
        args.push_back(ToWide(finding_type));
    }
    for (const auto& surface : related_investigation_surfaces) {
        if (surface.empty()) {
            continue;
        }
        args.push_back(L"--related-surface");
        args.push_back(ToWide(surface));
    }
    AppendWorkspace(args, config);
    (void)RunJsonCommand(config, args);
    return LoadReviewBoard(config, ticket_id);
}

ManualEvidenceItem AttachManualEvidence(
    const BackendConfig& config,
    const std::string& run_id_or_path,
    const std::string& kind,
    const std::string& label,
    const std::wstring& source_path,
    const std::wstring& note_text
) {
    std::vector<std::wstring> args = {
        L"desktop-state",
        L"attach-manual-evidence",
        ToWide(run_id_or_path),
        L"--kind",
        ToWide(kind),
        L"--json",
    };
    if (!label.empty()) {
        args.push_back(L"--label");
        args.push_back(ToWide(label));
    }
    if (!source_path.empty()) {
        args.push_back(L"--source");
        args.push_back(source_path);
    }
    if (!note_text.empty()) {
        args.push_back(L"--note");
        args.push_back(note_text);
    }
    AppendWorkspace(args, config);
    return RunJsonCommand(config, args).get<ManualEvidenceItem>();
}

ActionSnapshot LoadSnapshot(const BackendConfig& config, const std::string& run_id_or_path) {
    std::vector<std::wstring> args = {
        L"desktop-state",
        L"snapshot",
        ToWide(run_id_or_path),
        L"--json",
    };
    AppendWorkspace(args, config);
    return RunJsonCommand(config, args).get<ActionSnapshot>();
}

RunSnapshot LoadRunSnapshot(const BackendConfig& config, const std::string& run_id_or_path) {
    std::vector<std::wstring> args = {
        L"desktop-state",
        L"run-snapshot",
        ToWide(run_id_or_path),
        L"--json",
    };
    AppendWorkspace(args, config);
    return RunJsonCommand(config, args).get<RunSnapshot>();
}

std::string LaunchAction(const BackendConfig& config, const std::string& action_id) {
    std::vector<std::wstring> args = {
        L"launch-action",
        ToWide(action_id),
        L"--json",
    };
    AppendWorkspace(args, config);
    const json payload = RunJsonCommand(config, args);
    const std::string run_id = ValueString(payload, "run_id");
    if (run_id.empty()) {
        throw std::runtime_error("launch-action did not return a run_id.");
    }
    return run_id;
}

}  // namespace sg_preflight::native_shell
