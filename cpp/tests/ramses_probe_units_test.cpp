#include "sgfx/cine/ramses_probe.h"

#include "test_support.h"

#include <ramses/client/PerspectiveCamera.h>
#include <ramses/client/RamsesClient.h>
#include <ramses/client/RenderGroup.h>
#include <ramses/client/RenderPass.h>
#include <ramses/client/Scene.h>
#include <ramses/client/logic/LogicEngine.h>
#include <ramses/client/logic/LuaScript.h>
#include <ramses/client/logic/Property.h>
#include <ramses/framework/EFeatureLevel.h>
#include <ramses/framework/RamsesFramework.h>
#include <ramses/framework/RamsesFrameworkConfig.h>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <string>
#include <vector>

namespace
{
namespace fs = std::filesystem;

using sgfx_cine_tests::TemporaryDirectory;

bool expectMetadataFacts()
{
    const auto metadata = sgfx::cine::collect_ramses_probe_metadata();
    if (metadata.version_string.empty() || metadata.version_major != 28)
    {
        std::cerr << "unexpected Ramses version facts: '" << metadata.version_string << "' major "
                  << metadata.version_major << "\n";
        return false;
    }
    if (metadata.version_minor < 0 || metadata.version_patch < 0 || metadata.feature_level < 1u)
    {
        std::cerr << "unexpected Ramses minor/patch/feature-level facts\n";
        return false;
    }
    return true;
}

std::vector<std::uint8_t> solidFrame(std::size_t width, std::size_t height, std::uint8_t r, std::uint8_t g,
                                     std::uint8_t b, std::uint8_t a)
{
    std::vector<std::uint8_t> pixels(width * height * 4u);
    for (std::size_t index = 0u; index < width * height; ++index)
    {
        pixels[index * 4u + 0u] = r;
        pixels[index * 4u + 1u] = g;
        pixels[index * 4u + 2u] = b;
        pixels[index * 4u + 3u] = a;
    }
    return pixels;
}

bool expectClassification(const std::vector<std::uint8_t>& pixels, std::size_t width, std::size_t height,
                          sgfx::cine::FrameClassification expected, const char* label)
{
    const auto classification = sgfx::cine::classify_frame_rgba8(pixels, width, height);
    if (classification != expected)
    {
        std::cerr << "frame classification mismatch for " << label << "\n";
        return false;
    }
    return true;
}

bool expectFrameClassificationContract()
{
    const auto black = solidFrame(4u, 3u, 0u, 0u, 0u, 255u);
    if (!expectClassification(black, 4u, 3u, sgfx::cine::FrameClassification::Black, "opaque black"))
        return false;

    auto oneRedPixel = solidFrame(4u, 3u, 0u, 0u, 0u, 255u);
    oneRedPixel[0] = 1u;
    if (!expectClassification(oneRedPixel, 4u, 3u, sgfx::cine::FrameClassification::Content, "single lit pixel"))
        return false;

    const auto grey = solidFrame(2u, 2u, 128u, 128u, 128u, 0u);
    if (!expectClassification(grey, 2u, 2u, sgfx::cine::FrameClassification::Content, "transparent grey"))
        return false;

    if (!expectClassification({}, 4u, 3u, sgfx::cine::FrameClassification::Undetermined, "empty buffer"))
        return false;
    if (!expectClassification(black, 5u, 3u, sgfx::cine::FrameClassification::Undetermined, "size mismatch"))
        return false;
    if (!expectClassification(black, 0u, 0u, sgfx::cine::FrameClassification::Undetermined, "zero dimensions"))
        return false;

    const auto codes = {sgfx::cine::FrameClassification::Content, sgfx::cine::FrameClassification::Black,
                        sgfx::cine::FrameClassification::Undetermined};
    std::set<std::string> uniqueCodes;
    for (const auto code : codes)
    {
        const auto text = sgfx::cine::frame_classification_code(code);
        if (text.empty())
        {
            std::cerr << "empty frame classification code\n";
            return false;
        }
        uniqueCodes.insert(text);
    }
    if (uniqueCodes.size() != 3u || uniqueCodes.count("undetermined") != 1u)
    {
        std::cerr << "frame classification codes are not distinct stable strings\n";
        return false;
    }
    return true;
}

bool expectFindingIdentityContract()
{
    sgfx::cine::RamsesProbeFinding first;
    first.severity = "error";
    first.message = "mesh has no appearance";
    first.object_type = "MeshNode";
    first.object_id = 41u;
    first.object_name = "";
    first.source_class = "scene";

    sgfx::cine::RamsesProbeFinding second = first;
    second.object_id = 42u;

    sgfx::cine::RamsesProbeFinding duplicateName = first;
    duplicateName.object_id = 43u;
    duplicateName.object_name = "duplicate";
    sgfx::cine::RamsesProbeFinding duplicateNameOther = duplicateName;
    duplicateNameOther.object_id = 44u;

    const auto firstIdentity = sgfx::cine::probe_finding_identity(first);
    if (firstIdentity.empty() || firstIdentity != sgfx::cine::probe_finding_identity(first))
    {
        std::cerr << "finding identity is empty or unstable\n";
        return false;
    }
    if (firstIdentity == sgfx::cine::probe_finding_identity(second))
    {
        std::cerr << "distinct objects with empty names collide\n";
        return false;
    }
    if (sgfx::cine::probe_finding_identity(duplicateName) == sgfx::cine::probe_finding_identity(duplicateNameOther))
    {
        std::cerr << "distinct objects with duplicate names collide\n";
        return false;
    }

    sgfx::cine::RamsesProbeFinding otherMessage = first;
    otherMessage.message = "node is never rendered";
    if (firstIdentity == sgfx::cine::probe_finding_identity(otherMessage))
    {
        std::cerr << "distinct findings on one object collide\n";
        return false;
    }
    return true;
}

bool expectValidationAndInventoryContract()
{
    ramses::RamsesFrameworkConfig config{ramses::EFeatureLevel_01};
    ramses::RamsesFramework framework{config};
    auto* client = framework.createClient("sgfx-probe-units");
    if (client == nullptr)
    {
        std::cerr << "could not create Ramses client\n";
        return false;
    }
    auto* scene = client->createScene(ramses::sceneId_t{2026u}, "probe-units-scene");
    if (scene == nullptr)
    {
        std::cerr << "could not create synthetic scene\n";
        return false;
    }

    auto* camera = scene->createPerspectiveCamera("probe-camera");
    camera->setFrustum(19.0f, 480.0f / 270.0f, 0.1f, 100.0f);
    camera->setViewport(0, 0, 480u, 270u);
    auto* pass = scene->createRenderPass("probe-pass");
    pass->setCamera(*camera);
    auto* emptyGroup = scene->createRenderGroup("empty-group");
    pass->addRenderGroup(*emptyGroup);

    if (!scene->flush())
    {
        std::cerr << "synthetic scene must stay flushable\n";
        return false;
    }

    const auto findings = sgfx::cine::collect_validation_findings(*scene);
    if (findings.empty())
    {
        std::cerr << "synthetic scene with clear flags and no render target produced no validation findings\n";
        return false;
    }
    bool foundPassFinding = false;
    std::set<std::string> identities;
    for (const auto& finding : findings)
    {
        if (finding.severity != "error" && finding.severity != "warning")
        {
            std::cerr << "finding severity not preserved: '" << finding.severity << "'\n";
            return false;
        }
        if (finding.message.empty() || finding.object_type.empty() || finding.source_class != "scene")
        {
            std::cerr << "finding message/type/source class not preserved\n";
            return false;
        }
        identities.insert(sgfx::cine::probe_finding_identity(finding));
        if (finding.object_type == "RenderPass" && finding.object_id == pass->getSceneObjectId().getValue())
            foundPassFinding = true;
    }
    if (!foundPassFinding)
    {
        std::cerr << "render pass finding missing or lost object identity\n";
        return false;
    }
    if (identities.size() != findings.size())
    {
        std::cerr << "validation finding identities collide\n";
        return false;
    }

    scene->createMeshNode("duplicate-name");
    scene->createMeshNode("duplicate-name");
    scene->createMeshNode("");

    const auto inventory = sgfx::cine::collect_scene_inventory(*scene);
    if (inventory.empty())
    {
        std::cerr << "scene inventory is empty\n";
        return false;
    }
    std::set<std::string> categories;
    std::size_t meshNodes = 0u;
    std::size_t renderPasses = 0u;
    std::size_t perspectiveCameras = 0u;
    std::size_t orthographicCameras = 0u;
    bool sawOrthographicCategory = false;
    for (const auto& entry : inventory)
    {
        if (entry.object_type.empty())
        {
            std::cerr << "inventory entry with empty type name\n";
            return false;
        }
        categories.insert(entry.object_type);
        if (entry.object_type == "MeshNode")
            meshNodes = entry.count;
        if (entry.object_type == "RenderPass")
            renderPasses = entry.count;
        if (entry.object_type == "PerspectiveCamera")
            perspectiveCameras = entry.count;
        if (entry.object_type == "OrthographicCamera")
        {
            sawOrthographicCategory = true;
            orthographicCameras = entry.count;
        }
    }
    if (categories.size() != inventory.size())
    {
        std::cerr << "inventory categories are not unique\n";
        return false;
    }
    if (meshNodes != 3u || renderPasses != 1u || perspectiveCameras != 1u)
    {
        std::cerr << "inventory counts wrong: mesh " << meshNodes << " pass " << renderPasses << " camera "
                  << perspectiveCameras << "\n";
        return false;
    }
    if (!sawOrthographicCategory || orthographicCameras != 0u)
    {
        std::cerr << "empty categories must still be reported with zero counts\n";
        return false;
    }
    return true;
}

bool containsNode(const std::vector<std::string>& nodes, const std::string& name)
{
    return std::find(nodes.begin(), nodes.end(), name) != nodes.end();
}

bool expectLogicUpdateContract()
{
    ramses::RamsesFrameworkConfig config{ramses::EFeatureLevel_01};
    ramses::RamsesFramework framework{config};
    auto* client = framework.createClient("sgfx-probe-logic");
    auto* scene = client->createScene(ramses::sceneId_t{2027u}, "probe-logic-scene");
    auto* engine = scene->createLogicEngine("probe-logic");
    if (engine == nullptr)
    {
        std::cerr << "could not create logic engine\n";
        return false;
    }

    constexpr std::string_view forwardSource = R"(
        function interface(IN,OUT)
            IN.value = Type:Int32()
            OUT.value = Type:Int32()
        end
        function run(IN,OUT)
            OUT.value = IN.value
        end
    )";
    auto* forward = engine->createLuaScript(forwardSource, {}, "forward-script");
    if (forward == nullptr)
    {
        std::cerr << "could not create forward script\n";
        return false;
    }

    const auto first = sgfx::cine::collect_logic_update_evidence(framework, *engine);
    if (!first.update_succeeded || !first.error_message.empty() ||
        !containsNode(first.executed_nodes, "forward-script") || first.total_update_microseconds < 0 ||
        first.topology_sort_microseconds < 0)
    {
        std::cerr << "first logic update must succeed, execute the script, and carry timing evidence\n";
        return false;
    }

    const auto second = sgfx::cine::collect_logic_update_evidence(framework, *engine);
    if (!second.update_succeeded || !containsNode(second.skipped_nodes, "forward-script") ||
        containsNode(second.executed_nodes, "forward-script"))
    {
        std::cerr << "unchanged inputs must be reported as skipped, not executed\n";
        return false;
    }

    if (!forward->getInputs()->getChild("value")->set<int32_t>(7))
    {
        std::cerr << "could not set script input\n";
        return false;
    }
    const auto third = sgfx::cine::collect_logic_update_evidence(framework, *engine);
    if (!third.update_succeeded || !containsNode(third.executed_nodes, "forward-script"))
    {
        std::cerr << "dirty input must re-execute the script\n";
        return false;
    }

    constexpr std::string_view failingSource = R"(
        function interface(IN,OUT)
        end
        function run(IN,OUT)
            error("probe runtime failure")
        end
    )";
    if (engine->createLuaScript(failingSource, {}, "failing-script") == nullptr)
    {
        std::cerr << "could not create failing script\n";
        return false;
    }
    const auto failed = sgfx::cine::collect_logic_update_evidence(framework, *engine);
    if (failed.update_succeeded || failed.error_message.empty())
    {
        std::cerr << "runtime failure must be reported with a nonempty error\n";
        return false;
    }

    auto* cycleEngine = scene->createLogicEngine("probe-cycle");
    auto* cycleA = cycleEngine->createLuaScript(forwardSource, {}, "cycle-a");
    auto* cycleB = cycleEngine->createLuaScript(forwardSource, {}, "cycle-b");
    if (cycleA == nullptr || cycleB == nullptr)
    {
        std::cerr << "could not create cycle scripts\n";
        return false;
    }
    if (!cycleEngine->link(*cycleA->getOutputs()->getChild("value"), *cycleB->getInputs()->getChild("value")))
    {
        std::cerr << "could not create forward link\n";
        return false;
    }
    bool cycleSurfaced = false;
    std::string cycleError;
    if (cycleEngine->link(*cycleB->getOutputs()->getChild("value"), *cycleA->getInputs()->getChild("value")))
    {
        const auto cycle = sgfx::cine::collect_logic_update_evidence(framework, *cycleEngine);
        cycleSurfaced = !cycle.update_succeeded;
        cycleError = cycle.error_message;
    }
    else
    {
        const auto issue = framework.getLastError();
        cycleSurfaced = true;
        cycleError = issue ? issue->message : "";
    }
    if (!cycleSurfaced || cycleError.empty())
    {
        std::cerr << "logic cycle must surface a classified failure with a nonempty error\n";
        return false;
    }
    return true;
}

bool expectParseRejected(const std::vector<std::string>& arguments, const std::string& rejection)
{
    const auto parse = sgfx::cine::parse_probe_arguments(arguments);
    if (parse.accepted || parse.rejection != rejection)
    {
        std::cerr << "expected rejection " << rejection << ", received "
                  << (parse.accepted ? "accepted" : parse.rejection) << "\n";
        return false;
    }
    return true;
}

bool expectArgumentContract()
{
    const std::vector<std::string> valid{
        "--scene",       R"(C:\evidence\exported.ramses)", "--output-root", R"(C:\evidence\out)",
        "--profile",     "G45",                            "--backend",     "opengl",
    };
    const auto accepted = sgfx::cine::parse_probe_arguments(valid);
    if (!accepted.accepted || !accepted.rejection.empty() || accepted.request.profile != "G45" ||
        accepted.request.backend != "opengl" || accepted.request.scene_path.empty() ||
        accepted.request.output_root.empty() || !accepted.request.perspective_path.empty() ||
        !accepted.request.perspective_id.empty())
    {
        std::cerr << "valid argument set must be accepted with exact typed values\n";
        return false;
    }

    auto withPerspective = valid;
    withPerspective.insert(withPerspective.end(),
                           {"--perspective", R"(C:\evidence\perspective.json)", "--perspective-id", "P01"});
    const auto perspective = sgfx::cine::parse_probe_arguments(withPerspective);
    if (!perspective.accepted || perspective.request.perspective_id != "P01" ||
        perspective.request.perspective_path.empty())
    {
        std::cerr << "perspective pair must be accepted together\n";
        return false;
    }

    auto unknown = valid;
    unknown.push_back("--verbose");
    if (!expectParseRejected(unknown, "unknown_option"))
        return false;

    auto positional = valid;
    positional.push_back("stray");
    if (!expectParseRejected(positional, "unknown_option"))
        return false;

    auto duplicate = valid;
    duplicate.insert(duplicate.end(), {"--profile", "G45"});
    if (!expectParseRejected(duplicate, "duplicate_option"))
        return false;

    if (!expectParseRejected({"--scene", R"(C:\evidence\exported.ramses)", "--output-root", R"(C:\evidence\out)",
                              "--profile", "G45"},
                             "missing_required"))
        return false;

    auto danglingValue = valid;
    danglingValue.pop_back();
    if (!expectParseRejected(danglingValue, "missing_value"))
        return false;

    auto badBackend = valid;
    badBackend[7] = "vulkan";
    if (!expectParseRejected(badBackend, "unsupported_backend"))
        return false;

    auto badProfile = valid;
    badProfile[5] = "../G45";
    if (!expectParseRejected(badProfile, "invalid_profile"))
        return false;

    auto emptyProfile = valid;
    emptyProfile[5] = "";
    if (!expectParseRejected(emptyProfile, "invalid_profile"))
        return false;

    auto relativeOutput = valid;
    relativeOutput[3] = R"(..\out)";
    if (!expectParseRejected(relativeOutput, "relative_path"))
        return false;

    auto relativeScene = valid;
    relativeScene[1] = "exported.ramses";
    if (!expectParseRejected(relativeScene, "relative_path"))
        return false;

    auto lonePerspective = valid;
    lonePerspective.insert(lonePerspective.end(), {"--perspective", R"(C:\evidence\perspective.json)"});
    if (!expectParseRejected(lonePerspective, "incomplete_perspective"))
        return false;

    return true;
}

bool expectLifecycleContract()
{
    using sgfx::cine::ProbeLifecyclePhase;

    const auto phases = {ProbeLifecyclePhase::Available, ProbeLifecyclePhase::Ready,
                         ProbeLifecyclePhase::Rendered, ProbeLifecyclePhase::Readback};
    std::set<std::string> codes;
    for (const auto phase : phases)
        codes.insert(sgfx::cine::probe_lifecycle_phase_code(phase));
    if (codes.size() != 4u || codes.count("available") != 1u || codes.count("ready") != 1u ||
        codes.count("rendered") != 1u || codes.count("readback") != 1u)
    {
        std::cerr << "lifecycle phase codes are not the four stable strings\n";
        return false;
    }

    unsigned pumps = 0u;
    const auto success = sgfx::cine::drive_probe_lifecycle(
        [&](ProbeLifecyclePhase phase) { return pumps >= static_cast<unsigned>(phase) + 1u; },
        [&] { ++pumps; }, std::chrono::milliseconds{1000});
    if (!success.completed || !success.failure_phase.empty() || success.elapsed_microseconds < 0)
    {
        std::cerr << "successful lifecycle must complete with timing evidence\n";
        return false;
    }
    const std::vector<std::string> expectedOrder{"available", "ready", "rendered", "readback"};
    if (success.reached_phases != expectedOrder)
    {
        std::cerr << "successful lifecycle must record all four phases in order\n";
        return false;
    }

    for (int blockedPhase = 0; blockedPhase < 4; ++blockedPhase)
    {
        const auto blocked = sgfx::cine::drive_probe_lifecycle(
            [&](ProbeLifecyclePhase phase) { return static_cast<int>(phase) < blockedPhase; }, [] {},
            std::chrono::milliseconds{30});
        const auto expectedCode = sgfx::cine::probe_lifecycle_phase_code(
            static_cast<ProbeLifecyclePhase>(blockedPhase));
        if (blocked.completed || blocked.failure_phase != expectedCode ||
            blocked.reached_phases.size() != static_cast<std::size_t>(blockedPhase) ||
            blocked.elapsed_microseconds < 0)
        {
            std::cerr << "missing " << expectedCode << " event must terminate bounded with that failure phase\n";
            return false;
        }
    }
    return true;
}

const std::set<std::string> kReportTopLevelKeys = {
    "schemaVersion", "probeVersion", "profile",   "backend", "scenePath", "metadata", "phases",
    "failure",       "findings",     "inventory", "logic",   "lifecycle", "frame"};

bool expectReportSerializationContract()
{
    sgfx::cine::RamsesProbeNativeReport report;
    report.profile = "G45";
    report.backend = "opengl";
    report.scene_path = R"(C:\evidence\exported.ramses)";
    report.metadata_collected = true;
    report.metadata.version_string = "28.16.0";
    report.metadata.version_major = 28;
    report.metadata.version_minor = 16;
    report.metadata.version_patch = 0;
    report.metadata.feature_level = 1u;
    for (const auto* phase : {"arguments", "metadata", "scene_load", "validation", "inventory", "logic"})
        report.phases.push_back({phase, "completed"});
    sgfx::cine::RamsesProbeFinding finding;
    finding.severity = "warning";
    finding.message = "renderpass has clear flags enabled";
    finding.object_type = "RenderPass";
    finding.object_id = 2u;
    finding.object_name = "probe-pass";
    finding.source_class = "scene";
    report.findings.push_back(finding);
    report.inventory.push_back({"RenderPass", 1u});
    sgfx::cine::RamsesLogicUpdateEvidence logic;
    logic.engine_name = "probe-logic";
    logic.update_succeeded = true;
    logic.executed_nodes = {"forward-script"};
    logic.total_update_microseconds = 5;
    logic.topology_sort_microseconds = 1;
    report.logic.push_back(logic);

    const auto serialized = sgfx::cine::serialize_probe_report(report);
    const auto parsed = nlohmann::json::parse(serialized, nullptr, false);
    if (parsed.is_discarded() || !parsed.is_object())
    {
        std::cerr << "serialized report is not valid JSON\n";
        return false;
    }
    std::set<std::string> keys;
    for (const auto& item : parsed.items())
        keys.insert(item.key());
    if (keys != kReportTopLevelKeys)
    {
        std::cerr << "report top-level key set is not exact\n";
        return false;
    }
    if (parsed["schemaVersion"] != 1 || parsed["probeVersion"] != "0.1.0" || !parsed["failure"].is_null() ||
        !parsed["lifecycle"].is_null() || !parsed["frame"].is_null())
    {
        std::cerr << "report version/reserved fields wrong\n";
        return false;
    }
    if (parsed["metadata"]["versionMajor"] != 28 || parsed["phases"][0]["phase"] != "arguments" ||
        parsed["phases"][5]["status"] != "completed")
    {
        std::cerr << "report metadata/phase records wrong\n";
        return false;
    }
    const auto& findingJson = parsed["findings"][0];
    if (findingJson["severity"] != "warning" || findingJson["objectType"] != "RenderPass" ||
        findingJson["objectId"] != 2 || findingJson["sourceClass"] != "scene" ||
        findingJson["identity"] != sgfx::cine::probe_finding_identity(finding))
    {
        std::cerr << "report finding record wrong\n";
        return false;
    }
    if (parsed["logic"][0]["engine"] != "probe-logic" || parsed["logic"][0]["updateSucceeded"] != true ||
        parsed["inventory"][0]["count"] != 1)
    {
        std::cerr << "report logic/inventory records wrong\n";
        return false;
    }

    sgfx::cine::RamsesProbeNativeReport withLane = report;
    withLane.frame_recorded = true;
    withLane.frame_outcome = "readback_complete";
    withLane.frame_classification = "black";
    withLane.frame_file = "first-frame.png";
    withLane.frame_driven_inputs = 1u;
    withLane.lifecycle_recorded = true;
    withLane.lifecycle.completed = true;
    withLane.lifecycle.reached_phases = {"available", "ready", "rendered", "readback"};
    withLane.lifecycle.elapsed_microseconds = 1234;
    const auto laneParsed = nlohmann::json::parse(sgfx::cine::serialize_probe_report(withLane));
    if (laneParsed["frame"]["outcome"] != "readback_complete" ||
        laneParsed["frame"]["classification"] != "black" || laneParsed["frame"]["file"] != "first-frame.png" ||
        laneParsed["frame"]["drivenInputs"] != 1 || laneParsed["lifecycle"]["completed"] != true ||
        laneParsed["lifecycle"]["reachedPhases"].size() != 4u ||
        laneParsed["lifecycle"]["elapsedMicroseconds"] != 1234)
    {
        std::cerr << "recorded frame/lifecycle report shape wrong\n";
        return false;
    }

    sgfx::cine::RamsesProbeNativeReport failed;
    failed.profile = "G45";
    failed.backend = "opengl";
    failed.scene_path = R"(C:\evidence\missing.ramses)";
    failed.failure_phase = "scene_load";
    failed.failure_reason = "scene_unavailable";
    const auto failedParsed = nlohmann::json::parse(sgfx::cine::serialize_probe_report(failed));
    if (!failedParsed["metadata"].is_null() || failedParsed["failure"]["phase"] != "scene_load" ||
        failedParsed["failure"]["reason"] != "scene_unavailable")
    {
        std::cerr << "failure report shape wrong\n";
        return false;
    }
    return true;
}

bool expectReportWriterContract()
{
    TemporaryDirectory root;
    const std::string payload = R"({"schemaVersion":1})";
    const auto written = sgfx::cine::write_probe_report_atomically(root.path(), payload);
    if (!written.written || !written.rejection.empty() ||
        written.report_path != root.path() / "ramses-probe-native.json" || !fs::exists(written.report_path))
    {
        std::cerr << "atomic write must create exactly ramses-probe-native.json\n";
        return false;
    }
    std::ifstream stream(written.report_path, std::ios::binary);
    std::string content((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    if (content != payload || fs::exists(written.report_path.string() + ".tmp"))
    {
        std::cerr << "written content must match and leave no temp file\n";
        return false;
    }

    const auto duplicate = sgfx::cine::write_probe_report_atomically(root.path(), payload);
    if (duplicate.written || duplicate.rejection != "report_exists")
    {
        std::cerr << "existing report must be rejected, not replaced\n";
        return false;
    }

    TemporaryDirectory oversizeRoot;
    const std::string oversize(2u * 1024u * 1024u + 1u, 'x');
    const auto tooLarge = sgfx::cine::write_probe_report_atomically(oversizeRoot.path(), oversize);
    if (tooLarge.written || tooLarge.rejection != "report_too_large" ||
        fs::exists(oversizeRoot.path() / "ramses-probe-native.json"))
    {
        std::cerr << "oversize report must be rejected without writing\n";
        return false;
    }

    const auto missingRoot =
        sgfx::cine::write_probe_report_atomically(root.path() / "does-not-exist", payload);
    if (missingRoot.written || missingRoot.rejection != "output_unavailable")
    {
        std::cerr << "missing output root must be rejected\n";
        return false;
    }
    return true;
}

std::string validPerspectiveJson()
{
    return R"({
        "CID_CARHUB_ALL_GOOD": {
            "AspectFromResolution_isEnabled": true,
            "CraneGimbal": {"Distance": 12.5, "Yaw": -45.0, "Pitch": 4.0, "Roll": 0.0},
            "Frustum": {"HorizontalFOV": 43.0, "AspectRatio": 1.7777, "NearPlane": 0.5, "FarPlane": 100.0},
            "Viewport": {"OffsetX": 0, "OffsetY": 0, "Width": 480, "Height": 270},
            "Origin": [0.0, -0.123, 0.0],
            "ShiftXY": [0, 0],
            "Scale": 1.0
        }
    })";
}

bool writeTextFile(const fs::path& path, const std::string& text)
{
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    stream << text;
    return stream.good();
}

bool expectPerspectiveRejected(const fs::path& file, const std::string& id, const std::string& rejection)
{
    const auto parse = sgfx::cine::parse_probe_perspective(file, id);
    if (parse.accepted || parse.rejection != rejection)
    {
        std::cerr << "expected perspective rejection " << rejection << ", received "
                  << (parse.accepted ? "accepted" : parse.rejection) << "\n";
        return false;
    }
    return true;
}

bool expectPerspectiveContract()
{
    TemporaryDirectory root;
    const auto validFile = root.path() / "perspectives_probe.json";
    if (!writeTextFile(validFile, validPerspectiveJson()))
    {
        std::cerr << "could not write perspective fixture\n";
        return false;
    }

    const auto parsed = sgfx::cine::parse_probe_perspective(validFile, "CID_CARHUB_ALL_GOOD");
    if (!parsed.accepted || !parsed.rejection.empty() || parsed.perspective.id != "CID_CARHUB_ALL_GOOD" ||
        !parsed.perspective.aspect_from_resolution || parsed.perspective.distance != 12.5f ||
        parsed.perspective.yaw != -45.0f || parsed.perspective.horizontal_fov != 43.0f ||
        parsed.perspective.near_plane != 0.5f || parsed.perspective.far_plane != 100.0f ||
        parsed.perspective.scale != 1.0f || parsed.perspective.origin[1] != -0.123f ||
        parsed.perspective.viewport_width != 480u || parsed.perspective.viewport_height != 270u)
    {
        std::cerr << "valid perspective must parse with exact typed values\n";
        return false;
    }

    if (!expectPerspectiveRejected(root.path() / "absent.json", "CID_CARHUB_ALL_GOOD",
                                   "perspective_unreadable"))
        return false;

    const auto malformedFile = root.path() / "malformed.json";
    if (!writeTextFile(malformedFile, "{ not json"))
        return false;
    if (!expectPerspectiveRejected(malformedFile, "CID_CARHUB_ALL_GOOD", "perspective_malformed"))
        return false;

    if (!expectPerspectiveRejected(validFile, "CID_DOES_NOT_EXIST", "perspective_id_missing"))
        return false;

    auto missingField = validPerspectiveJson();
    const auto craneAt = missingField.find("\"Distance\"");
    missingField.replace(craneAt, 10u, "\"Renamed\"");
    const auto missingFieldFile = root.path() / "missing-field.json";
    if (!writeTextFile(missingFieldFile, missingField))
        return false;
    if (!expectPerspectiveRejected(missingFieldFile, "CID_CARHUB_ALL_GOOD", "perspective_malformed"))
        return false;

    auto badBounds = validPerspectiveJson();
    const auto farAt = badBounds.find("\"FarPlane\": 100.0");
    badBounds.replace(farAt, std::string("\"FarPlane\": 100.0").size(), "\"FarPlane\": 0.1");
    const auto badBoundsFile = root.path() / "bad-bounds.json";
    if (!writeTextFile(badBoundsFile, badBounds))
        return false;
    if (!expectPerspectiveRejected(badBoundsFile, "CID_CARHUB_ALL_GOOD", "perspective_values_invalid"))
        return false;

    const auto oversizedFile = root.path() / "oversized.json";
    {
        std::ofstream stream(oversizedFile, std::ios::binary | std::ios::trunc);
        const std::string filler(64u * 1024u, 'x');
        for (int block = 0; block < 20; ++block)
            stream << filler;  // ~1.25 MiB, above the 1 MiB perspective cap
    }
    if (!expectPerspectiveRejected(oversizedFile, "CID_CARHUB_ALL_GOOD", "perspective_too_large"))
        return false;

    return true;
}

bool expectExecuteProbeContract()
{
    TemporaryDirectory sceneDir;
    const auto scenePath = sceneDir.path() / "synthetic.ramses";
    {
        ramses::RamsesFrameworkConfig config{ramses::EFeatureLevel_01};
        ramses::RamsesFramework framework{config};
        auto* client = framework.createClient("sgfx-probe-save");
        auto* scene = client->createScene(ramses::sceneId_t{2028u}, "probe-save-scene");
        auto* camera = scene->createPerspectiveCamera("probe-camera");
        camera->setFrustum(19.0f, 480.0f / 270.0f, 0.1f, 100.0f);
        camera->setViewport(0, 0, 480u, 270u);
        auto* pass = scene->createRenderPass("probe-pass");
        pass->setCamera(*camera);
        auto* group = scene->createRenderGroup("probe-group");
        pass->addRenderGroup(*group);
        auto* engine = scene->createLogicEngine("probe-logic");
        constexpr std::string_view forwardSource = R"(
            function interface(IN,OUT)
                IN.value = Type:Int32()
                OUT.value = Type:Int32()
            end
            function run(IN,OUT)
                OUT.value = IN.value
            end
        )";
        if (engine->createLuaScript(forwardSource, {}, "forward-script") == nullptr || !scene->flush() ||
            !scene->saveToFile(scenePath.string()))
        {
            std::cerr << "could not save the synthetic probe scene\n";
            return false;
        }
    }

    TemporaryDirectory outputRoot;
    sgfx::cine::RamsesProbeCliRequest request;
    request.profile = "G45";
    request.backend = "opengl";
    request.scene_path = scenePath;
    request.output_root = outputRoot.path();

    const auto outcome = sgfx::cine::execute_probe_request(request);
    if (outcome.exit_code != sgfx::cine::kProbeExitOk || outcome.classification != "completed" ||
        !fs::exists(outcome.report_path))
    {
        std::cerr << "probe execution against the synthetic scene must complete: " << outcome.classification
                  << " exit " << outcome.exit_code << "\n";
        return false;
    }
    std::ifstream stream(outcome.report_path, std::ios::binary);
    const auto report = nlohmann::json::parse(std::string((std::istreambuf_iterator<char>(stream)),
                                                          std::istreambuf_iterator<char>()));
    bool renderPassFinding = false;
    for (const auto& finding : report["findings"])
        if (finding["objectType"] == "RenderPass")
            renderPassFinding = true;
    std::size_t renderPassCount = 0u;
    std::size_t logicEngineCount = 0u;
    for (const auto& entry : report["inventory"])
    {
        if (entry["objectType"] == "RenderPass")
            renderPassCount = entry["count"].get<std::size_t>();
        if (entry["objectType"] == "LogicEngine")
            logicEngineCount = entry["count"].get<std::size_t>();
    }
    bool forwardExecuted = false;
    for (const auto& node : report["logic"][0]["executedNodes"])
        if (node == "forward-script")
            forwardExecuted = true;
    if (!report["failure"].is_null() || report["metadata"]["versionMajor"] != 28 || !renderPassFinding ||
        renderPassCount != 1u || logicEngineCount != 1u || report["logic"][0]["engine"] != "probe-logic" ||
        report["logic"][0]["updateSucceeded"] != true || !forwardExecuted)
    {
        std::cerr << "probe report content wrong for the synthetic scene\n";
        return false;
    }
    if (report["phases"].size() != 8u)
    {
        std::cerr << "report must carry exactly eight ordered phases\n";
        return false;
    }
    for (std::size_t index = 0u; index < 6u; ++index)
        if (report["phases"][index]["status"] != "completed")
        {
            std::cerr << "headless phases must be completed on success\n";
            return false;
        }
    if (report["phases"][6]["phase"] != "perspective" || report["phases"][6]["status"] != "not_requested" ||
        report["phases"][7]["phase"] != "frame" || report["phases"][7]["status"] != "not_requested")
    {
        std::cerr << "unrequested frame lane must be reported as not_requested\n";
        return false;
    }

    TemporaryDirectory missingOutputRoot;
    sgfx::cine::RamsesProbeCliRequest missingScene = request;
    missingScene.scene_path = sceneDir.path() / "missing.ramses";
    missingScene.output_root = missingOutputRoot.path();
    const auto failedOutcome = sgfx::cine::execute_probe_request(missingScene);
    if (failedOutcome.exit_code != sgfx::cine::kProbeExitData ||
        failedOutcome.classification != "scene_unavailable" || !fs::exists(failedOutcome.report_path))
    {
        std::cerr << "missing scene must produce a truthful classified failure report\n";
        return false;
    }
    std::ifstream failedStream(failedOutcome.report_path, std::ios::binary);
    const auto failedReport = nlohmann::json::parse(std::string(
        (std::istreambuf_iterator<char>(failedStream)), std::istreambuf_iterator<char>()));
    bool sceneLoadFailed = false;
    bool validationNotRun = false;
    for (const auto& phase : failedReport["phases"])
    {
        if (phase["phase"] == "scene_load" && phase["status"] == "failed")
            sceneLoadFailed = true;
        if (phase["phase"] == "validation" && phase["status"] == "not_run")
            validationNotRun = true;
    }
    if (failedReport["failure"]["phase"] != "scene_load" ||
        failedReport["failure"]["reason"] != "scene_unavailable" || !sceneLoadFailed || !validationNotRun ||
        !failedReport["findings"].empty() || !failedReport["logic"].empty())
    {
        std::cerr << "classified failure report shape wrong\n";
        return false;
    }

    TemporaryDirectory perspectiveDir;
    const auto perspectiveFile = perspectiveDir.path() / "perspectives_probe.json";
    if (!writeTextFile(perspectiveFile, validPerspectiveJson()))
        return false;
    TemporaryDirectory missingContractRoot;
    sgfx::cine::RamsesProbeCliRequest contractRequest = request;
    contractRequest.output_root = missingContractRoot.path();
    contractRequest.perspective_path = perspectiveFile;
    contractRequest.perspective_id = "CID_CARHUB_ALL_GOOD";
    const auto contractOutcome = sgfx::cine::execute_probe_request(contractRequest);
    if (contractOutcome.exit_code != sgfx::cine::kProbeExitOk ||
        contractOutcome.classification != "completed" || !fs::exists(contractOutcome.report_path))
    {
        std::cerr << "missing camera-crane contract must be an explicit result, not a failure: "
                  << contractOutcome.classification << " exit " << contractOutcome.exit_code << "\n";
        return false;
    }
    std::ifstream contractStream(contractOutcome.report_path, std::ios::binary);
    const auto contractReport = nlohmann::json::parse(std::string(
        (std::istreambuf_iterator<char>(contractStream)), std::istreambuf_iterator<char>()));
    if (contractReport["frame"]["outcome"] != "missing_contract" ||
        !contractReport["frame"]["classification"].is_null() || !contractReport["frame"]["file"].is_null() ||
        !contractReport["lifecycle"].is_null() ||
        contractReport["phases"][6]["status"] != "completed" ||
        contractReport["phases"][7]["status"] != "completed" || !contractReport["failure"].is_null())
    {
        std::cerr << "missing-contract report shape wrong\n";
        return false;
    }
    return true;
}

bool expectRenderedFrameContract()
{
    TemporaryDirectory sceneDir;
    const auto scenePath = sceneDir.path() / "crane.ramses";
    {
        ramses::RamsesFrameworkConfig config{ramses::EFeatureLevel_01};
        ramses::RamsesFramework framework{config};
        auto* client = framework.createClient("sgfx-probe-crane-save");
        auto* scene = client->createScene(ramses::sceneId_t{2029u}, "probe-crane-scene");
        auto* camera = scene->createPerspectiveCamera("probe-camera");
        camera->setFrustum(19.0f, 480.0f / 270.0f, 0.1f, 100.0f);
        camera->setViewport(0, 0, 480u, 270u);
        auto* pass = scene->createRenderPass("probe-pass");
        pass->setCamera(*camera);
        auto* group = scene->createRenderGroup("probe-group");
        pass->addRenderGroup(*group);
        auto* engine = scene->createLogicEngine("probe-crane-logic");
        constexpr std::string_view craneInterfaceSource = R"(
            function interface(inout)
                inout.AutoAspect = Type:Bool()
                inout.Scale = Type:Float()
                inout.Origin = Type:Vec3f()
                inout.ShiftXY = Type:Vec2i()
                inout.CraneGimbal = {
                    Distance = Type:Float(),
                    Yaw = Type:Float(),
                    Pitch = Type:Float(),
                    Roll = Type:Float()
                }
                inout.Frustum = {
                    HorizontalFOV = Type:Float(),
                    AspectRatio = Type:Float(),
                    NearPlane = Type:Float(),
                    FarPlane = Type:Float()
                }
                inout.Viewport = {
                    OffsetX = Type:Int32(),
                    OffsetY = Type:Int32(),
                    Width = Type:Int32(),
                    Height = Type:Int32()
                }
            end
        )";
        if (engine->createLuaInterface(craneInterfaceSource, "Interface_CameraCrane") == nullptr ||
            !scene->flush() || !scene->saveToFile(scenePath.string()))
        {
            std::cerr << "could not save the camera-crane probe scene\n";
            return false;
        }
    }

    TemporaryDirectory perspectiveDir;
    const auto perspectiveFile = perspectiveDir.path() / "perspectives_probe.json";
    if (!writeTextFile(perspectiveFile, validPerspectiveJson()))
        return false;

    TemporaryDirectory outputRoot;
    sgfx::cine::RamsesProbeCliRequest request;
    request.profile = "G45";
    request.backend = "opengl";
    request.scene_path = scenePath;
    request.output_root = outputRoot.path();
    request.perspective_path = perspectiveFile;
    request.perspective_id = "CID_CARHUB_ALL_GOOD";

    const auto outcome = sgfx::cine::execute_probe_request(request);
    if (outcome.exit_code != sgfx::cine::kProbeExitOk || outcome.classification != "completed")
    {
        std::cerr << "rendered frame lane must complete: " << outcome.classification << " exit "
                  << outcome.exit_code << "\n";
        return false;
    }
    std::ifstream stream(outcome.report_path, std::ios::binary);
    const auto report = nlohmann::json::parse(std::string((std::istreambuf_iterator<char>(stream)),
                                                          std::istreambuf_iterator<char>()));
    if (report["frame"]["outcome"] != "readback_complete" || report["frame"]["classification"] != "black" ||
        report["frame"]["file"] != "first-frame.png" || report["frame"]["drivenInputs"].get<int>() < 1 ||
        report["lifecycle"]["completed"] != true || report["lifecycle"]["reachedPhases"].size() != 4u ||
        report["lifecycle"]["elapsedMicroseconds"].get<std::int64_t>() < 0)
    {
        std::cerr << "rendered frame report shape wrong\n";
        return false;
    }
    for (const auto& phase : report["phases"])
        if (phase["status"] != "completed")
        {
            std::cerr << "all eight phases must complete on a rendered run\n";
            return false;
        }
    const auto framePath = outputRoot.path() / "first-frame.png";
    std::error_code sizeError;
    const auto frameSize = fs::file_size(framePath, sizeError);
    if (sizeError || frameSize == 0u || frameSize > 1024u * 1024u)
    {
        std::cerr << "first-frame.png missing or out of bounds\n";
        return false;
    }
    return true;
}

bool expectLegacyAspectCraneIsDriven()
{
    TemporaryDirectory sceneDir;
    const auto scenePath = sceneDir.path() / "legacy-crane.ramses";
    {
        ramses::RamsesFrameworkConfig config{ramses::EFeatureLevel_01};
        ramses::RamsesFramework framework{config};
        auto* client = framework.createClient("sgfx-probe-legacy-crane-save");
        auto* scene = client->createScene(ramses::sceneId_t{2031u}, "probe-legacy-crane-scene");
        auto* camera = scene->createPerspectiveCamera("probe-camera");
        camera->setFrustum(19.0f, 480.0f / 270.0f, 0.1f, 100.0f);
        camera->setViewport(0, 0, 480u, 270u);
        auto* pass = scene->createRenderPass("probe-pass");
        pass->setCamera(*camera);
        auto* group = scene->createRenderGroup("probe-group");
        pass->addRenderGroup(*group);
        auto* engine = scene->createLogicEngine("probe-legacy-crane-logic");
        // The crane exposes the legacy prototype spelling AspectFromResolution_isEnabled instead of
        // the modern AutoAspect; the probe must still drive it (real IDCevo exports vary here).
        constexpr std::string_view craneInterfaceSource = R"(
            function interface(inout)
                inout.AspectFromResolution_isEnabled = Type:Bool()
                inout.Scale = Type:Float()
                inout.Origin = Type:Vec3f()
                inout.ShiftXY = Type:Vec2i()
                inout.CraneGimbal = {
                    Distance = Type:Float(),
                    Yaw = Type:Float(),
                    Pitch = Type:Float(),
                    Roll = Type:Float()
                }
                inout.Frustum = {
                    HorizontalFOV = Type:Float(),
                    AspectRatio = Type:Float(),
                    NearPlane = Type:Float(),
                    FarPlane = Type:Float()
                }
                inout.Viewport = {
                    OffsetX = Type:Int32(),
                    OffsetY = Type:Int32(),
                    Width = Type:Int32(),
                    Height = Type:Int32()
                }
            end
        )";
        if (engine->createLuaInterface(craneInterfaceSource, "Interface_CameraCrane") == nullptr ||
            !scene->flush() || !scene->saveToFile(scenePath.string()))
        {
            std::cerr << "could not save the legacy-spelling camera-crane probe scene\n";
            return false;
        }
    }

    TemporaryDirectory perspectiveDir;
    const auto perspectiveFile = perspectiveDir.path() / "perspectives_probe.json";
    if (!writeTextFile(perspectiveFile, validPerspectiveJson()))
        return false;

    TemporaryDirectory outputRoot;
    sgfx::cine::RamsesProbeCliRequest request;
    request.profile = "G45";
    request.backend = "opengl";
    request.scene_path = scenePath;
    request.output_root = outputRoot.path();
    request.perspective_path = perspectiveFile;
    request.perspective_id = "CID_CARHUB_ALL_GOOD";

    const auto outcome = sgfx::cine::execute_probe_request(request);
    std::ifstream stream(outcome.report_path, std::ios::binary);
    const auto report = nlohmann::json::parse(std::string((std::istreambuf_iterator<char>(stream)),
                                                          std::istreambuf_iterator<char>()));
    // The legacy crane root must be driven (real render outcome + at least one driven input),
    // not silently reported as missing_contract with no frame.
    if (report["frame"]["outcome"] != "readback_complete" ||
        report["frame"]["drivenInputs"].get<int>() < 1)
    {
        std::cerr << "legacy AspectFromResolution crane was not driven: "
                  << report["frame"]["outcome"] << "\n";
        return false;
    }
    return true;
}
}

int main()
{
    if (!expectMetadataFacts())
        return 1;
    if (!expectFrameClassificationContract())
        return 1;
    if (!expectFindingIdentityContract())
        return 1;
    if (!expectValidationAndInventoryContract())
        return 1;
    if (!expectLogicUpdateContract())
        return 1;
    if (!expectLifecycleContract())
        return 1;
    if (!expectArgumentContract())
        return 1;
    if (!expectReportSerializationContract())
        return 1;
    if (!expectReportWriterContract())
        return 1;
    if (!expectPerspectiveContract())
        return 1;
    if (!expectExecuteProbeContract())
        return 1;
    if (!expectRenderedFrameContract())
        return 1;
    if (!expectLegacyAspectCraneIsDriven())
        return 1;

    std::cout << "Ramses probe units OK\n";
    return 0;
}
