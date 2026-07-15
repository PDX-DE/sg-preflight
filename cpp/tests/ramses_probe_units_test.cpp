#include "sgfx/cine/ramses_probe.h"

#include <ramses/client/PerspectiveCamera.h>
#include <ramses/client/RamsesClient.h>
#include <ramses/client/RenderGroup.h>
#include <ramses/client/RenderPass.h>
#include <ramses/client/Scene.h>
#include <ramses/framework/EFeatureLevel.h>
#include <ramses/framework/RamsesFramework.h>
#include <ramses/framework/RamsesFrameworkConfig.h>

#include <cstdint>
#include <iostream>
#include <set>
#include <string>
#include <vector>

namespace
{
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

    std::cout << "Ramses probe units OK\n";
    return 0;
}
