#include "sgfx/cine/ramses_probe.h"

#include <ramses/client/Scene.h>
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

#include <array>
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
}
