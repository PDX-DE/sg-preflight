#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace sgfx::cine
{
struct RamsesPreviewRequest
{
    std::filesystem::path scene_path;
    std::filesystem::path output_root;
    std::uint32_t width{480};
    std::uint32_t height{270};
    std::uint32_t frame_count{24};
    bool reduced_motion{false};
};

struct RamsesPreviewResult
{
    bool rendered{false};
    std::string safe_reason;
    std::vector<std::filesystem::path> frames;
    std::string ramses_version;
    std::uint32_t feature_level{0};
};

RamsesPreviewResult render_ramses_preview(const RamsesPreviewRequest& request);
}
