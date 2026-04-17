#include "backend_bridge.hpp"

#include <windows.h>

#include <filesystem>
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

    CloseHandle(read_pipe);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);

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
    item.created_at_utc = ValueString(payload, "created_at_utc");
    item.workflow_stage_label = ValueString(payload, "workflow_stage_label");
    item.summary_title = ValueString(payload, "summary_title");
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
