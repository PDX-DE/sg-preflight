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
#include <ramses/client/logic/LuaInterface.h>
#include <ramses/client/logic/LuaScript.h>
#include <ramses/client/logic/Property.h>
#include <ramses/client/ramses-utils.h>
#include <ramses/framework/DataTypes.h>
#include <ramses/framework/EFeatureLevel.h>
#include <ramses/framework/RamsesFramework.h>
#include <ramses/framework/RamsesFrameworkConfig.h>
#include <ramses/framework/RamsesVersion.h>
#include <ramses/framework/ValidationReport.h>
#include <ramses/renderer/DisplayConfig.h>
#include <ramses/renderer/RendererConfig.h>

#include "ramses_render_support.h"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <fstream>
#include <initializer_list>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <thread>

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
    if (report.lifecycle_recorded)
    {
        json["lifecycle"] = {
            {"completed", report.lifecycle.completed},
            {"failurePhase", report.lifecycle.failure_phase},
            {"reachedPhases", report.lifecycle.reached_phases},
            {"elapsedMicroseconds", report.lifecycle.elapsed_microseconds},
        };
    }
    else
    {
        json["lifecycle"] = nullptr;
    }
    if (report.frame_recorded)
    {
        nlohmann::json frame;
        frame["outcome"] = report.frame_outcome;
        if (report.frame_classification.empty())
            frame["classification"] = nullptr;
        else
            frame["classification"] = report.frame_classification;
        if (report.frame_file.empty())
            frame["file"] = nullptr;
        else
            frame["file"] = report.frame_file;
        frame["drivenInputs"] = report.frame_driven_inputs;
        json["frame"] = frame;
    }
    else
    {
        json["frame"] = nullptr;
    }
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
constexpr std::array<const char*, 8> kProbePhases = {"arguments",  "metadata", "scene_load", "validation",
                                                     "inventory",  "logic",    "perspective", "frame"};
constexpr std::uint32_t kProbeFrameWidth = 480u;
constexpr std::uint32_t kProbeFrameHeight = 270u;

std::vector<ramses::LogicEngine*> collectProbeLogicEngines(ramses::Scene& scene)
{
    std::vector<ramses::LogicEngine*> engines;
    ramses::SceneObjectIterator iterator(scene, ramses::ERamsesObjectType::LogicEngine);
    while (auto* object = iterator.getNext())
    {
        if (auto* engine = object->as<ramses::LogicEngine>())
            engines.push_back(engine);
    }
    return engines;
}

ramses::Property* probeCameraCraneRoot(ramses::LogicNode& node)
{
    auto* inputs = node.getInputs();
    if (!inputs)
        return nullptr;
    if (inputs->hasChild("Interface_CameraCrane"))
        return inputs->getChild("Interface_CameraCrane");
    if (inputs->hasChild("CraneGimbal") && inputs->hasChild("Frustum") && inputs->hasChild("Viewport"))
        return inputs;
    return nullptr;
}

std::vector<ramses::Property*> collectProbeCraneRoots(const std::vector<ramses::LogicEngine*>& engines)
{
    // Drive interface AND script crane roots: real exports may keep the interface unlinked, with the
    // camera actually fed by a script's own crane inputs (proven by the accepted preview path on G50).
    std::vector<ramses::Property*> roots;
    for (auto* engine : engines)
    {
        for (auto* interfaceNode : engine->getCollection<ramses::LuaInterface>())
        {
            if (auto* root = probeCameraCraneRoot(*interfaceNode))
                roots.push_back(root);
        }
    }
    for (auto* engine : engines)
    {
        for (auto* script : engine->getCollection<ramses::LuaScript>())
        {
            if (auto* root = probeCameraCraneRoot(*script))
                roots.push_back(root);
        }
    }
    return roots;
}

template <typename T>
bool setProbeProperty(ramses::Property& root, std::initializer_list<std::string_view> path, T value)
{
    auto* property = &root;
    for (const auto segment : path)
    {
        if (!property->hasChild(segment))
            return false;
        property = property->getChild(segment);
    }
    return property && property->set<T>(value);
}

bool applyProbePerspective(ramses::Property& root, const RamsesProbePerspective& perspective,
                           std::uint32_t width, std::uint32_t height)
{
    // Viewport targets the readback buffer; every other value comes from the authored perspective.
    bool ok = true;
    ok &= setProbeProperty<bool>(root, {"AutoAspect"}, perspective.aspect_from_resolution);
    ok &= setProbeProperty<float>(root, {"CraneGimbal", "Distance"}, perspective.distance);
    ok &= setProbeProperty<float>(root, {"CraneGimbal", "Pitch"}, perspective.pitch);
    ok &= setProbeProperty<float>(root, {"CraneGimbal", "Roll"}, perspective.roll);
    ok &= setProbeProperty<float>(root, {"CraneGimbal", "Yaw"}, perspective.yaw);
    ok &= setProbeProperty<float>(root, {"Frustum", "AspectRatio"}, perspective.aspect_ratio);
    ok &= setProbeProperty<float>(root, {"Frustum", "FarPlane"}, perspective.far_plane);
    ok &= setProbeProperty<float>(root, {"Frustum", "HorizontalFOV"}, perspective.horizontal_fov);
    ok &= setProbeProperty<float>(root, {"Frustum", "NearPlane"}, perspective.near_plane);
    ok &= setProbeProperty<float>(root, {"Scale"}, perspective.scale);
    ok &= setProbeProperty<ramses::vec2i>(root, {"ShiftXY"},
                                          ramses::vec2i{perspective.shift[0], perspective.shift[1]});
    ok &= setProbeProperty<ramses::vec3f>(
        root, {"Origin"},
        ramses::vec3f{perspective.origin[0], perspective.origin[1], perspective.origin[2]});
    ok &= setProbeProperty<std::int32_t>(root, {"Viewport", "Height"}, static_cast<std::int32_t>(height));
    ok &= setProbeProperty<std::int32_t>(root, {"Viewport", "OffsetX"}, 0);
    ok &= setProbeProperty<std::int32_t>(root, {"Viewport", "OffsetY"}, 0);
    ok &= setProbeProperty<std::int32_t>(root, {"Viewport", "Width"}, static_cast<std::int32_t>(width));
    return ok;
}

bool sceneHasCameraCraneContract(ramses::Scene& scene)
{
    const auto engines = collectProbeLogicEngines(scene);
    return !collectProbeCraneRoots(engines).empty();
}

struct ProbeFrameLaneResult
{
    std::string outcome{"renderer_unavailable"};
    std::string classification;
    std::string file;
    std::size_t driven{0};
    bool lifecycle_recorded{false};
    RamsesLifecycleEvidence lifecycle;
};

ProbeFrameLaneResult runProbeFrameLane(const std::filesystem::path& scenePath,
                                       const RamsesProbePerspective& perspective,
                                       const std::filesystem::path& outputRoot)
{
    ProbeFrameLaneResult result;
    const auto metadata = ramses::RamsesClient::GetMetadataFromFile(scenePath.string());
    if (!metadata)
    {
        result.outcome = "scene_incompatible";
        return result;
    }

    render_support::SdlGuard sdl;
    if (!sdl.initialized())
        return result;
    render_support::HiddenWindow window(kProbeFrameWidth, kProbeFrameHeight);
    if (!window.valid())
        return result;
    void* nativeHandle = window.nativeHandle();
    if (!nativeHandle)
        return result;

    ramses::RamsesFrameworkConfig frameworkConfig{metadata->featureLevel};
    frameworkConfig.setRequestedRamsesShellType(ramses::ERamsesShellType::None);
    frameworkConfig.setLogLevel(ramses::ELogLevel::Off);
    frameworkConfig.setLogLevelConsole(ramses::ELogLevel::Off);
    ramses::RamsesFramework framework{frameworkConfig};
    auto* client = framework.createClient("sgfx-ramses-probe-frame");
    ramses::RendererConfig rendererConfig;
    auto* renderer = framework.createRenderer(rendererConfig);
    if (!client || !renderer || !framework.connect())
        return result;
    auto* sceneControl = renderer->getSceneControlAPI();
    if (!sceneControl)
        return result;

    ramses::SceneConfig sceneConfig{ramses::sceneId_t{9703u}, ramses::EScenePublicationMode::LocalOnly,
                                    ramses::ERenderBackendCompatibility::OpenGL};
    auto* scene = client->loadSceneFromFile(scenePath.string(), sceneConfig);
    if (!scene)
    {
        result.outcome = "scene_incompatible";
        return result;
    }

    const auto engines = collectProbeLogicEngines(*scene);
    const auto craneRoots = collectProbeCraneRoots(engines);
    if (craneRoots.empty())
    {
        result.outcome = "missing_contract";
        return result;
    }
    for (auto* root : craneRoots)
    {
        if (applyProbePerspective(*root, perspective, kProbeFrameWidth, kProbeFrameHeight))
            ++result.driven;
    }
    if (result.driven == 0u)
    {
        result.outcome = "missing_contract";
        return result;
    }
    for (auto* engine : engines)
    {
        if (!engine->update())
        {
            result.outcome = "logic_update_failed";
            return result;
        }
    }

    ramses::DisplayConfig displayConfig;
    displayConfig.setWindowType(ramses::EWindowType::Windows);
    displayConfig.setWindowsWindowHandle(nativeHandle);
    displayConfig.setWindowRectangle(0, 0, kProbeFrameWidth, kProbeFrameHeight);
    displayConfig.setWindowTitle("SGFX Ramses Probe");
    const auto display = renderer->createDisplay(displayConfig);
    if (!display.isValid())
        return result;
    renderer->setSkippingOfUnmodifiedBuffers(false);
    renderer->flush();

    const auto sceneId = scene->getSceneId();
    render_support::RenderEventHandler handler(display, sceneId, kProbeFrameWidth, kProbeFrameHeight);

    const auto setupDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(30);
    const auto waitUntil = [&](auto&& predicate) {
        while (!predicate())
        {
            if (handler.failed() || std::chrono::steady_clock::now() >= setupDeadline)
                return false;
            render_support::pumpRamses(*renderer, *sceneControl, handler);
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        return true;
    };

    if (!waitUntil([&] { return handler.displayReady(); }))
        return result;
    const auto offscreen = renderer->createOffscreenBuffer(display, kProbeFrameWidth, kProbeFrameHeight);
    if (!offscreen.isValid())
        return result;
    handler.setBuffer(offscreen);
    renderer->setDisplayBufferClearColor(display, offscreen, ramses::vec4f{0.0f, 0.0f, 0.0f, 1.0f});
    renderer->flush();
    if (!waitUntil([&] { return handler.bufferReady(); }))
        return result;

    if (!scene->publish(ramses::EScenePublicationMode::LocalOnly))
    {
        result.outcome = "lifecycle_rejected";
        return result;
    }
    scene->flush();

    bool mappingRequested = false;
    bool renderRequested = false;
    bool readRequested = false;
    bool transitionRejected = false;
    const auto phaseReached = [&](ProbeLifecyclePhase phase) {
        switch (phase)
        {
        case ProbeLifecyclePhase::Available:
            return handler.sceneAvailable() || handler.sceneReady() || handler.sceneRendered();
        case ProbeLifecyclePhase::Ready:
            if (!mappingRequested)
            {
                mappingRequested = true;
                if (!sceneControl->setSceneMapping(sceneId, display) ||
                    !sceneControl->setSceneDisplayBufferAssignment(sceneId, offscreen, 0) ||
                    !sceneControl->setSceneState(sceneId, ramses::RendererSceneState::Ready))
                    transitionRejected = true;
                sceneControl->flush();
            }
            return handler.sceneReady() || handler.sceneRendered();
        case ProbeLifecyclePhase::Rendered:
            if (!renderRequested)
            {
                renderRequested = true;
                if (!sceneControl->setSceneState(sceneId, ramses::RendererSceneState::Rendered))
                    transitionRejected = true;
                sceneControl->flush();
            }
            return handler.sceneRendered();
        case ProbeLifecyclePhase::Readback:
            if (!readRequested)
            {
                readRequested = true;
                for (unsigned settle = 0u; settle < 3u; ++settle)
                    render_support::pumpRamses(*renderer, *sceneControl, handler);
                handler.resetPixels();
                renderer->readPixels(display, offscreen, 0u, 0u, kProbeFrameWidth, kProbeFrameHeight);
                renderer->flush();
            }
            return handler.pixelsReceived();
        }
        return false;
    };
    const auto pump = [&] {
        if (handler.failed() || transitionRejected)
            throw std::runtime_error("render_event_failed");
        render_support::pumpRamses(*renderer, *sceneControl, handler);
        scene->flush();
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    };

    try
    {
        result.lifecycle = drive_probe_lifecycle(phaseReached, pump, std::chrono::milliseconds{30000});
        result.lifecycle_recorded = true;
    }
    catch (const std::runtime_error&)
    {
        result.outcome = transitionRejected ? "lifecycle_rejected" : "renderer_unavailable";
        return result;
    }
    if (!result.lifecycle.completed)
    {
        result.outcome = "lifecycle_timeout";
        return result;
    }
    // pixelsReceived also fires for a failed read; only nonempty pixels prove a usable readback.
    if (handler.failed() || handler.pixels().empty())
    {
        result.outcome = "readback_failed";
        return result;
    }

    result.classification = frame_classification_code(
        classify_frame_rgba8(handler.pixels(), kProbeFrameWidth, kProbeFrameHeight));

    const auto framePath = outputRoot / "first-frame.png";
    auto pixels = handler.pixels();
    if (!ramses::RamsesUtils::SaveImageBufferToPng(framePath.string(), pixels, kProbeFrameWidth,
                                                   kProbeFrameHeight, true))
    {
        result.outcome = "frame_write_failed";
        return result;
    }
    std::error_code sizeError;
    const auto frameSize = std::filesystem::file_size(framePath, sizeError);
    if (sizeError || frameSize > 1024u * 1024u)
    {
        std::filesystem::remove(framePath, sizeError);
        result.outcome = "frame_too_large";
        return result;
    }
    result.file = "first-frame.png";

    sceneControl->setSceneState(sceneId, ramses::RendererSceneState::Unavailable);
    sceneControl->flush();
    scene->unpublish();
    renderer->destroyOffscreenBuffer(display, offscreen);
    renderer->destroyDisplay(display);
    renderer->flush();
    framework.disconnect();

    result.outcome = "readback_complete";
    return result;
}
}

RamsesProbeRunOutcome execute_probe_request(const RamsesProbeCliRequest& request)
{
    RamsesProbeRunOutcome outcome;
    RamsesProbeNativeReport report;
    report.profile = request.profile;
    report.backend = request.backend;
    report.scene_path = request.scene_path.string();

    const bool laneRequested = !request.perspective_path.empty();
    bool laneReady = false;
    RamsesProbePerspective perspective;

    std::size_t completed = 1u;
    bool failed = false;
    const auto fail = [&report, &failed](const char* phase, const std::string& reason) {
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
                if (client == nullptr)
                {
                    fail("scene_load", "framework_unavailable");
                }
                else if (scene == nullptr)
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
                    for (auto* engine : collectProbeLogicEngines(*scene))
                        report.logic.push_back(collect_logic_update_evidence(framework, *engine));
                    ++completed;
                    if (laneRequested)
                    {
                        const auto perspectiveParse =
                            parse_probe_perspective(request.perspective_path, request.perspective_id);
                        if (!perspectiveParse.accepted)
                        {
                            fail("perspective", perspectiveParse.rejection);
                        }
                        else
                        {
                            ++completed;
                            perspective = perspectiveParse.perspective;
                            if (!sceneHasCameraCraneContract(*scene))
                            {
                                report.frame_recorded = true;
                                report.frame_outcome = "missing_contract";
                                ++completed;
                            }
                            else
                            {
                                laneReady = true;
                            }
                        }
                    }
                }
            }
        }
    }
    catch (...)
    {
        if (report.failure_phase.empty())
            fail(completed < kProbePhases.size() ? kProbePhases[completed] : "frame",
                 "unexpected_exception");
    }

    if (laneReady && !failed)
    {
        // The validation framework above is destroyed before the render framework starts.
        try
        {
            const auto lane = runProbeFrameLane(request.scene_path, perspective, request.output_root);
            report.frame_recorded = true;
            report.frame_outcome = lane.outcome;
            report.frame_classification = lane.classification;
            report.frame_file = lane.file;
            report.frame_driven_inputs = lane.driven;
            if (lane.lifecycle_recorded)
            {
                report.lifecycle_recorded = true;
                report.lifecycle = lane.lifecycle;
            }
            if (lane.outcome == "readback_complete" || lane.outcome == "missing_contract")
                ++completed;
            else
                fail("frame", lane.outcome);
        }
        catch (...)
        {
            fail("frame", "unexpected_exception");
        }
    }

    for (std::size_t index = 0u; index < kProbePhases.size(); ++index)
    {
        std::string status = "not_run";
        if (!laneRequested && index >= 6u)
            status = "not_requested";
        else if (index < completed)
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

namespace
{
const nlohmann::json* jsonField(const nlohmann::json& object, const char* key)
{
    const auto found = object.find(key);
    return found == object.end() ? nullptr : &*found;
}

bool readNumberField(const nlohmann::json& object, const char* key, float& target)
{
    const auto* field = jsonField(object, key);
    if (field == nullptr || !field->is_number())
        return false;
    target = static_cast<float>(field->get<double>());
    return true;
}

bool readRoundedField(const nlohmann::json& object, const char* key, std::int32_t& target)
{
    const auto* field = jsonField(object, key);
    if (field == nullptr || !field->is_number())
        return false;
    target = static_cast<std::int32_t>(std::lround(field->get<double>()));
    return true;
}
}

RamsesProbePerspectiveParse parse_probe_perspective(const std::filesystem::path& file,
                                                    const std::string& perspective_id)
{
    RamsesProbePerspectiveParse parse;

    std::ifstream stream(file, std::ios::binary);
    if (!stream.good())
    {
        parse.rejection = "perspective_unreadable";
        return parse;
    }
    const std::string text((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());

    const auto root = nlohmann::json::parse(text, nullptr, false);
    if (root.is_discarded() || !root.is_object())
    {
        parse.rejection = "perspective_malformed";
        return parse;
    }
    const auto* view = jsonField(root, perspective_id.c_str());
    if (view == nullptr)
    {
        parse.rejection = "perspective_id_missing";
        return parse;
    }

    const auto malformed = [&parse] {
        parse.rejection = "perspective_malformed";
        return parse;
    };
    if (!view->is_object())
        return malformed();
    const auto* aspect = jsonField(*view, "AspectFromResolution_isEnabled");
    const auto* crane = jsonField(*view, "CraneGimbal");
    const auto* frustum = jsonField(*view, "Frustum");
    const auto* viewport = jsonField(*view, "Viewport");
    const auto* origin = jsonField(*view, "Origin");
    const auto* shift = jsonField(*view, "ShiftXY");
    if (aspect == nullptr || !aspect->is_boolean() || crane == nullptr || !crane->is_object() ||
        frustum == nullptr || !frustum->is_object() || viewport == nullptr || !viewport->is_object() ||
        origin == nullptr || !origin->is_array() || origin->size() != 3u || shift == nullptr ||
        !shift->is_array() || shift->size() != 2u)
    {
        return malformed();
    }
    for (const auto& element : *origin)
        if (!element.is_number())
            return malformed();
    for (const auto& element : *shift)
        if (!element.is_number())
            return malformed();

    RamsesProbePerspective perspective;
    perspective.id = perspective_id;
    perspective.aspect_from_resolution = aspect->get<bool>();
    std::int32_t viewportWidth = 0;
    std::int32_t viewportHeight = 0;
    if (!readNumberField(*crane, "Distance", perspective.distance) ||
        !readNumberField(*crane, "Yaw", perspective.yaw) ||
        !readNumberField(*crane, "Pitch", perspective.pitch) ||
        !readNumberField(*crane, "Roll", perspective.roll) ||
        !readNumberField(*frustum, "HorizontalFOV", perspective.horizontal_fov) ||
        !readNumberField(*frustum, "AspectRatio", perspective.aspect_ratio) ||
        !readNumberField(*frustum, "NearPlane", perspective.near_plane) ||
        !readNumberField(*frustum, "FarPlane", perspective.far_plane) ||
        !readNumberField(*view, "Scale", perspective.scale) ||
        !readRoundedField(*viewport, "OffsetX", perspective.viewport_offset_x) ||
        !readRoundedField(*viewport, "OffsetY", perspective.viewport_offset_y) ||
        !readRoundedField(*viewport, "Width", viewportWidth) ||
        !readRoundedField(*viewport, "Height", viewportHeight))
    {
        return malformed();
    }
    for (std::size_t index = 0u; index < 3u; ++index)
        perspective.origin[index] = static_cast<float>((*origin)[index].get<double>());
    for (std::size_t index = 0u; index < 2u; ++index)
        perspective.shift[index] = static_cast<std::int32_t>(std::lround((*shift)[index].get<double>()));

    if (perspective.distance <= 0.0f || perspective.horizontal_fov <= 0.0f ||
        perspective.aspect_ratio <= 0.0f || perspective.near_plane <= 0.0f ||
        perspective.far_plane <= perspective.near_plane || perspective.scale <= 0.0f ||
        viewportWidth <= 0 || viewportHeight <= 0)
    {
        parse.rejection = "perspective_values_invalid";
        return parse;
    }
    perspective.viewport_width = static_cast<std::uint32_t>(viewportWidth);
    perspective.viewport_height = static_cast<std::uint32_t>(viewportHeight);

    parse.perspective = perspective;
    parse.accepted = true;
    return parse;
}
}
