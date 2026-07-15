#include "sgfx/cine/ramses_probe.h"

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
}

int main()
{
    if (!expectMetadataFacts())
        return 1;
    if (!expectFrameClassificationContract())
        return 1;
    if (!expectFindingIdentityContract())
        return 1;

    std::cout << "Ramses probe units OK\n";
    return 0;
}
