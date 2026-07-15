#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace sgfx::cine
{
std::string ramses_link_probe_message();

struct RamsesProbeMetadata
{
    std::string version_string;
    int version_major{0};
    int version_minor{0};
    int version_patch{0};
    std::uint32_t feature_level{0};
};

RamsesProbeMetadata collect_ramses_probe_metadata();

enum class FrameClassification
{
    Content,
    Black,
    Undetermined,
};

std::string frame_classification_code(FrameClassification classification);

FrameClassification classify_frame_rgba8(const std::vector<std::uint8_t>& pixels, std::size_t width,
                                         std::size_t height);

struct RamsesProbeFinding
{
    std::string severity;
    std::string message;
    std::string object_type;
    std::uint64_t object_id{0};
    std::string object_name;
    std::string source_class;
};

std::string probe_finding_identity(const RamsesProbeFinding& finding);
}
