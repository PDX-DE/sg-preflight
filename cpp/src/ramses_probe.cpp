#include "sgfx/cine/ramses_probe.h"

#include <ramses/client/RamsesClient.h>
#include <ramses/client/Scene.h>
#include <ramses/client/SceneConfig.h>
#include <ramses/client/SceneMetadata.h>
#include <ramses/client/SceneObject.h>
#include <ramses/client/SceneObjectIterator.h>
#include <ramses/client/logic/LogicEngine.h>
#include <ramses/client/logic/LogicEngineReport.h>
#include <ramses/client/logic/LogicNode.h>
#include <ramses/framework/EFeatureLevel.h>
#include <ramses/framework/RamsesFramework.h>
#include <ramses/framework/RamsesFrameworkConfig.h>
#include <ramses/framework/RamsesVersion.h>
#include <ramses/framework/ValidationReport.h>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <cctype>
#include <fstream>
#include <map>
#include <sstream>

namespace sgfx::cine
{
std::string ramses_link_probe_message()
{
    const auto version = ramses::GetRamsesVersion();

    ramses::RamsesFrameworkConfig config{ramses::EFeatureLevel_01};
    ramses::RamsesFramework framework{config};

    std::ostringstream out;
    out << "Ramses version: " << version.string << " ("
        << version.major << '.' << version.minor << '.' << version.patch << ")\n"
        << "Ramses feature level: " << static_cast<unsigned>(framework.getFeatureLevel()) << '\n'
        << "Ramses linked OK";
    return out.str();
}

RamsesProbeMetadata collect_ramses_probe_metadata()
{
    const auto version = ramses::GetRamsesVersion();

    ramses::RamsesFrameworkConfig config{ramses::EFeatureLevel_01};
    ramses::RamsesFramework framework{config};

    RamsesProbeMetadata metadata;
    metadata.version_string = version.string;
    metadata.version_major = version.major;
    metadata.version_minor = version.minor;
    metadata.version_patch = version.patch;
    metadata.feature_level = static_cast<std::uint32_t>(framework.getFeatureLevel());
    return metadata;
}

std::string frame_classification_code(FrameClassification classification)
{
    switch (classification)
    {
    case FrameClassification::Content:
        return "content";
    case FrameClassification::Black:
        return "black";
    case FrameClassification::Undetermined:
        break;
    }
    return "undetermined";
}

FrameClassification classify_frame_rgba8(const std::vector<std::uint8_t>& pixels, std::size_t width,
                                         std::size_t height)
{
    if (width == 0u || height == 0u || pixels.size() != width * height * 4u)
        return FrameClassification::Undetermined;

    for (std::size_t index = 0u; index < width * height; ++index)
    {
        const auto offset = index * 4u;
        if (pixels[offset + 0u] != 0u || pixels[offset + 1u] != 0u || pixels[offset + 2u] != 0u)
            return FrameClassification::Content;
    }
    return FrameClassification::Black;
}

std::string probe_finding_identity(const RamsesProbeFinding& finding)
{
    // Identity is name-free so duplicate or empty object names cannot collide.
    std::ostringstream identity;
    identity << finding.object_type << '#' << finding.object_id << '|' << finding.source_class << '|'
             << finding.severity << '|' << finding.message.size() << ':' << finding.message;
    return identity.str();
}

std::string ramses_object_type_name(ramses::ERamsesObjectType type)
{
    switch (type)
    {
    case ramses::ERamsesObjectType::Scene:
        return "Scene";
    case ramses::ERamsesObjectType::LogicEngine:
        return "LogicEngine";
    case ramses::ERamsesObjectType::Node:
        return "Node";
    case ramses::ERamsesObjectType::MeshNode:
        return "MeshNode";
    case ramses::ERamsesObjectType::PerspectiveCamera:
        return "PerspectiveCamera";
    case ramses::ERamsesObjectType::OrthographicCamera:
        return "OrthographicCamera";
    case ramses::ERamsesObjectType::Effect:
        return "Effect";
    case ramses::ERamsesObjectType::Appearance:
        return "Appearance";
    case ramses::ERamsesObjectType::Geometry:
        return "Geometry";
    case ramses::ERamsesObjectType::RenderGroup:
        return "RenderGroup";
    case ramses::ERamsesObjectType::RenderPass:
        return "RenderPass";
    case ramses::ERamsesObjectType::BlitPass:
        return "BlitPass";
    case ramses::ERamsesObjectType::RenderBuffer:
        return "RenderBuffer";
    case ramses::ERamsesObjectType::RenderTarget:
        return "RenderTarget";
    case ramses::ERamsesObjectType::DataObject:
        return "DataObject";
    case ramses::ERamsesObjectType::SceneReference:
        return "SceneReference";
    default:
        break;
    }
    return "type_" + std::to_string(static_cast<int>(type));
}

std::vector<RamsesProbeFinding> collect_validation_findings(const ramses::Scene& scene)
{
    ramses::ValidationReport report;
    scene.validate(report);

    std::vector<RamsesProbeFinding> findings;
    findings.reserve(report.getIssues().size());
    for (const auto& issue : report.getIssues())
    {
        RamsesProbeFinding finding;
        finding.severity = issue.type == ramses::EIssueType::Error ? "error" : "warning";
        finding.message = issue.message;
        finding.source_class = "scene";
        if (issue.object != nullptr)
        {
            finding.object_type = ramses_object_type_name(issue.object->getType());
            finding.object_name = std::string{issue.object->getName()};
            if (const auto* sceneObject = ramses::object_cast<const ramses::SceneObject*>(issue.object))
                finding.object_id = sceneObject->getSceneObjectId().getValue();
        }
        else
        {
            finding.object_type = "none";
        }
        findings.push_back(std::move(finding));
    }
    return findings;
}

std::vector<RamsesProbeInventoryEntry> collect_scene_inventory(const ramses::Scene& scene)
{
    constexpr std::array categories = {
        ramses::ERamsesObjectType::LogicEngine,      ramses::ERamsesObjectType::MeshNode,
        ramses::ERamsesObjectType::PerspectiveCamera, ramses::ERamsesObjectType::OrthographicCamera,
        ramses::ERamsesObjectType::Effect,           ramses::ERamsesObjectType::Appearance,
        ramses::ERamsesObjectType::Geometry,         ramses::ERamsesObjectType::RenderGroup,
        ramses::ERamsesObjectType::RenderPass,       ramses::ERamsesObjectType::BlitPass,
        ramses::ERamsesObjectType::RenderBuffer,     ramses::ERamsesObjectType::RenderTarget,
        ramses::ERamsesObjectType::DataObject,       ramses::ERamsesObjectType::SceneReference,
    };

    std::vector<RamsesProbeInventoryEntry> inventory;
    inventory.reserve(categories.size());
    for (const auto category : categories)
    {
        RamsesProbeInventoryEntry entry;
        entry.object_type = ramses_object_type_name(category);
        ramses::SceneObjectIterator iterator(scene, category);
        while (iterator.getNext() != nullptr)
            ++entry.count;
        inventory.push_back(std::move(entry));
    }
    return inventory;
}

RamsesLogicUpdateEvidence collect_logic_update_evidence(ramses::RamsesFramework& framework,
                                                        ramses::LogicEngine& engine)
{
    engine.enableUpdateReport(true);

    RamsesLogicUpdateEvidence evidence;
    evidence.engine_name = std::string{engine.getName()};
    evidence.update_succeeded = engine.update();
    if (!evidence.update_succeeded)
    {
        const auto issue = framework.getLastError();
        evidence.error_message = issue ? issue->message : "logic update failed without a framework error";
        return evidence;
    }

    // Report contents are undefined when update fails, so they are read only on success.
    const auto report = engine.getLastUpdateReport();
    for (const auto& [node, duration] : report.getNodesExecuted())
    {
        (void)duration;
        evidence.executed_nodes.emplace_back(node->getName());
    }
    for (const auto* node : report.getNodesSkippedExecution())
        evidence.skipped_nodes.emplace_back(node->getName());
    evidence.total_update_microseconds = report.getTotalUpdateExecutionTime().count();
    evidence.topology_sort_microseconds = report.getTopologySortExecutionTime().count();
    return evidence;
}

std::string probe_lifecycle_phase_code(ProbeLifecyclePhase phase)
{
    switch (phase)
    {
    case ProbeLifecyclePhase::Available:
        return "available";
    case ProbeLifecyclePhase::Ready:
        return "ready";
    case ProbeLifecyclePhase::Rendered:
        return "rendered";
    case ProbeLifecyclePhase::Readback:
        break;
    }
    return "readback";
}

RamsesLifecycleEvidence drive_probe_lifecycle(const std::function<bool(ProbeLifecyclePhase)>& phase_reached,
                                              const std::function<void()>& pump,
                                              std::chrono::milliseconds budget)
{
    RamsesLifecycleEvidence evidence;
    const auto start = std::chrono::steady_clock::now();
    const auto deadline = start + budget;
    const auto elapsed = [&start] {
        return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - start)
            .count();
    };

    constexpr std::array phases = {ProbeLifecyclePhase::Available, ProbeLifecyclePhase::Ready,
                                   ProbeLifecyclePhase::Rendered, ProbeLifecyclePhase::Readback};
    for (const auto phase : phases)
    {
        while (!phase_reached(phase))
        {
            if (std::chrono::steady_clock::now() >= deadline)
            {
                evidence.failure_phase = probe_lifecycle_phase_code(phase);
                evidence.elapsed_microseconds = elapsed();
                return evidence;
            }
            pump();
        }
        evidence.reached_phases.push_back(probe_lifecycle_phase_code(phase));
    }
    evidence.completed = true;
    evidence.elapsed_microseconds = elapsed();
    return evidence;
}

namespace
{
bool validIdentityToken(const std::string& value)
{
    if (value.empty() || value.size() > 64u || !std::isalnum(static_cast<unsigned char>(value.front())))
        return false;
    return std::all_of(value.begin(), value.end(), [](char character) {
        const auto unsignedCharacter = static_cast<unsigned char>(character);
        return std::isalnum(unsignedCharacter) != 0 || character == '_' || character == '-';
    });
}
}

RamsesProbeCliParse parse_probe_arguments(const std::vector<std::string>& arguments)
{
    RamsesProbeCliParse parse;

    const std::array<std::string, 6> knownOptions = {"--scene",       "--output-root", "--profile",
                                                     "--backend",     "--perspective", "--perspective-id"};
    std::map<std::string, std::string> values;
    for (std::size_t index = 0u; index < arguments.size(); index += 2u)
    {
        const auto& option = arguments[index];
        if (std::find(knownOptions.begin(), knownOptions.end(), option) == knownOptions.end())
        {
            parse.rejection = "unknown_option";
            return parse;
        }
        if (index + 1u >= arguments.size() || arguments[index + 1u].rfind("--", 0u) == 0u)
        {
            parse.rejection = "missing_value";
            return parse;
        }
        if (values.count(option) != 0u)
        {
            parse.rejection = "duplicate_option";
            return parse;
        }
        values[option] = arguments[index + 1u];
    }

    for (const auto& required : {"--scene", "--output-root", "--profile", "--backend"})
    {
        if (values.count(required) == 0u)
        {
            parse.rejection = "missing_required";
            return parse;
        }
    }
    if (values["--backend"] != "opengl")
    {
        parse.rejection = "unsupported_backend";
        return parse;
    }
    if (!validIdentityToken(values["--profile"]))
    {
        parse.rejection = "invalid_profile";
        return parse;
    }

    const std::filesystem::path scenePath{values["--scene"]};
    const std::filesystem::path outputRoot{values["--output-root"]};
    if (!scenePath.is_absolute() || !outputRoot.is_absolute())
    {
        parse.rejection = "relative_path";
        return parse;
    }

    const bool hasPerspective = values.count("--perspective") != 0u;
    const bool hasPerspectiveId = values.count("--perspective-id") != 0u;
    if (hasPerspective != hasPerspectiveId)
    {
        parse.rejection = "incomplete_perspective";
        return parse;
    }
    if (hasPerspective)
    {
        const std::filesystem::path perspectivePath{values["--perspective"]};
        if (!perspectivePath.is_absolute())
        {
            parse.rejection = "relative_path";
            return parse;
        }
        if (!validIdentityToken(values["--perspective-id"]))
        {
            parse.rejection = "invalid_perspective_id";
            return parse;
        }
        parse.request.perspective_path = perspectivePath;
        parse.request.perspective_id = values["--perspective-id"];
    }

    parse.request.profile = values["--profile"];
    parse.request.backend = values["--backend"];
    parse.request.scene_path = scenePath;
    parse.request.output_root = outputRoot;
    parse.accepted = true;
    return parse;
}

std::string serialize_probe_report(const RamsesProbeNativeReport& report)
{
    nlohmann::json json;
    json["schemaVersion"] = 1;
    json["probeVersion"] = "0.1.0";
    json["profile"] = report.profile;
    json["backend"] = report.backend;
    json["scenePath"] = report.scene_path;
    if (report.metadata_collected)
    {
        json["metadata"] = {
            {"versionString", report.metadata.version_string},
            {"versionMajor", report.metadata.version_major},
            {"versionMinor", report.metadata.version_minor},
            {"versionPatch", report.metadata.version_patch},
            {"featureLevel", report.metadata.feature_level},
        };
    }
    else
    {
        json["metadata"] = nullptr;
    }
    json["phases"] = nlohmann::json::array();
    for (const auto& record : report.phases)
        json["phases"].push_back({{"phase", record.phase}, {"status", record.status}});
    if (report.failure_phase.empty())
        json["failure"] = nullptr;
    else
        json["failure"] = {{"phase", report.failure_phase}, {"reason", report.failure_reason}};
    json["findings"] = nlohmann::json::array();
    for (const auto& finding : report.findings)
    {
        json["findings"].push_back({
            {"severity", finding.severity},
            {"message", finding.message},
            {"objectType", finding.object_type},
            {"objectId", finding.object_id},
            {"objectName", finding.object_name},
            {"sourceClass", finding.source_class},
            {"identity", probe_finding_identity(finding)},
        });
    }
    json["inventory"] = nlohmann::json::array();
    for (const auto& entry : report.inventory)
        json["inventory"].push_back({{"objectType", entry.object_type}, {"count", entry.count}});
    json["logic"] = nlohmann::json::array();
    for (const auto& evidence : report.logic)
    {
        json["logic"].push_back({
            {"engine", evidence.engine_name},
            {"updateSucceeded", evidence.update_succeeded},
            {"errorMessage", evidence.error_message},
            {"executedNodes", evidence.executed_nodes},
            {"skippedNodes", evidence.skipped_nodes},
            {"totalUpdateMicroseconds", evidence.total_update_microseconds},
            {"topologySortMicroseconds", evidence.topology_sort_microseconds},
        });
    }
    json["lifecycle"] = nullptr;
    json["frame"] = nullptr;
    return json.dump();
}

RamsesProbeWriteResult write_probe_report_atomically(const std::filesystem::path& output_root,
                                                     const std::string& report_json)
{
    RamsesProbeWriteResult result;
    std::error_code error;
    if (!std::filesystem::is_directory(output_root, error) || error)
    {
        result.rejection = "output_unavailable";
        return result;
    }
    if (report_json.size() > 2u * 1024u * 1024u)
    {
        result.rejection = "report_too_large";
        return result;
    }
    const auto target = output_root / "ramses-probe-native.json";
    if (std::filesystem::exists(target, error) || error)
    {
        result.rejection = "report_exists";
        return result;
    }
    const auto temporary = output_root / "ramses-probe-native.json.tmp";
    {
        std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
        stream.write(report_json.data(), static_cast<std::streamsize>(report_json.size()));
        stream.flush();
        if (!stream.good())
        {
            stream.close();
            std::filesystem::remove(temporary, error);
            result.rejection = "report_write_failed";
            return result;
        }
    }
    std::filesystem::rename(temporary, target, error);
    if (error)
    {
        std::filesystem::remove(temporary, error);
        result.rejection = "report_write_failed";
        return result;
    }
    result.written = true;
    result.report_path = target;
    return result;
}

namespace
{
constexpr std::array<const char*, 6> kProbePhases = {"arguments", "metadata",  "scene_load",
                                                     "validation", "inventory", "logic"};
}

RamsesProbeRunOutcome execute_probe_request(const RamsesProbeCliRequest& request)
{
    RamsesProbeRunOutcome outcome;
    RamsesProbeNativeReport report;
    report.profile = request.profile;
    report.backend = request.backend;
    report.scene_path = request.scene_path.string();

    std::size_t completed = 1u;
    bool failed = false;
    const auto fail = [&report, &failed](const char* phase, const char* reason) {
        report.failure_phase = phase;
        report.failure_reason = reason;
        failed = true;
    };

    try
    {
        report.metadata = collect_ramses_probe_metadata();
        report.metadata_collected = true;
        ++completed;

        std::error_code error;
        if (!std::filesystem::is_regular_file(request.scene_path, error) || error)
        {
            fail("scene_load", "scene_unavailable");
        }
        else
        {
            const auto sceneMetadata = ramses::RamsesClient::GetMetadataFromFile(request.scene_path.string());
            if (!sceneMetadata)
            {
                fail("scene_load", "scene_incompatible");
            }
            else
            {
                ramses::RamsesFrameworkConfig frameworkConfig{sceneMetadata->featureLevel};
                frameworkConfig.setRequestedRamsesShellType(ramses::ERamsesShellType::None);
                frameworkConfig.setLogLevel(ramses::ELogLevel::Off);
                frameworkConfig.setLogLevelConsole(ramses::ELogLevel::Off);
                ramses::RamsesFramework framework{frameworkConfig};
                auto* client = framework.createClient("sgfx-ramses-probe");
                ramses::SceneConfig sceneConfig{ramses::sceneId_t{9702u},
                                                ramses::EScenePublicationMode::LocalOnly,
                                                ramses::ERenderBackendCompatibility::OpenGL};
                auto* scene =
                    client ? client->loadSceneFromFile(request.scene_path.string(), sceneConfig) : nullptr;
                if (scene == nullptr)
                {
                    fail("scene_load", "scene_incompatible");
                }
                else
                {
                    ++completed;
                    report.findings = collect_validation_findings(*scene);
                    ++completed;
                    report.inventory = collect_scene_inventory(*scene);
                    ++completed;
                    ramses::SceneObjectIterator iterator(*scene, ramses::ERamsesObjectType::LogicEngine);
                    while (auto* object = iterator.getNext())
                    {
                        if (auto* engine = object->as<ramses::LogicEngine>())
                            report.logic.push_back(collect_logic_update_evidence(framework, *engine));
                    }
                    ++completed;
                }
            }
        }
    }
    catch (...)
    {
        if (report.failure_phase.empty())
            fail(completed < kProbePhases.size() ? kProbePhases[completed] : "logic", "unexpected_exception");
    }

    for (std::size_t index = 0u; index < kProbePhases.size(); ++index)
    {
        std::string status = "not_run";
        if (index < completed)
            status = "completed";
        else if (failed && index == completed)
            status = "failed";
        report.phases.push_back({kProbePhases[index], status});
    }

    const auto written = write_probe_report_atomically(request.output_root, serialize_probe_report(report));
    if (!written.written)
    {
        outcome.exit_code = kProbeExitIo;
        outcome.classification = written.rejection;
        return outcome;
    }
    outcome.report_path = written.report_path;
    if (failed)
    {
        outcome.exit_code = kProbeExitData;
        outcome.classification = report.failure_reason;
        return outcome;
    }
    outcome.exit_code = kProbeExitOk;
    outcome.classification = "completed";
    return outcome;
}
}
