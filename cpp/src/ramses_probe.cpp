#include "sgfx/cine/ramses_probe.h"

#include <ramses/framework/EFeatureLevel.h>
#include <ramses/framework/RamsesFramework.h>
#include <ramses/framework/RamsesFrameworkConfig.h>
#include <ramses/framework/RamsesVersion.h>

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
}
