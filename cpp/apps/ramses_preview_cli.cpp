#include "sgfx/cine/ramses_preview.h"

#include <nlohmann/json.hpp>

#include <charconv>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <unordered_set>

namespace
{
namespace fs = std::filesystem;

std::uint32_t parseUnsigned(std::string_view value)
{
    std::uint32_t parsed = 0u;
    const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size() || parsed == 0u)
        throw std::runtime_error("invalid_arguments");
    return parsed;
}

sgfx::cine::RamsesPreviewRequest parseRequest(int argc, char** argv)
{
    sgfx::cine::RamsesPreviewRequest request;
    std::unordered_set<std::string> seen;
    for (int index = 1; index < argc; ++index)
    {
        const std::string option = argv[index];
        if (!seen.insert(option).second)
            throw std::runtime_error("invalid_arguments");
        if (option == "--reduced-motion")
        {
            request.reduced_motion = true;
            continue;
        }
        if (option != "--scene" && option != "--output-root" && option != "--width" &&
            option != "--height" && option != "--frames")
        {
            throw std::runtime_error("invalid_arguments");
        }
        if (++index >= argc)
            throw std::runtime_error("invalid_arguments");
        const std::string value = argv[index];
        if (option == "--scene")
            request.scene_path = value;
        else if (option == "--output-root")
            request.output_root = value;
        else if (option == "--width")
            request.width = parseUnsigned(value);
        else if (option == "--height")
            request.height = parseUnsigned(value);
        else if (option == "--frames")
            request.frame_count = parseUnsigned(value);
    }
    if (!seen.count("--scene") || !seen.count("--output-root") || !seen.count("--width") ||
        !seen.count("--height") || !seen.count("--frames"))
    {
        throw std::runtime_error("invalid_arguments");
    }
    return request;
}

void removeFrames(const std::vector<fs::path>& frames)
{
    for (const auto& frame : frames)
    {
        std::error_code error;
        fs::remove(frame, error);
    }
}
}

int main(int argc, char** argv)
{
    std::vector<fs::path> renderedFrames;
    try
    {
        const auto request = parseRequest(argc, argv);
        const auto result = sgfx::cine::render_ramses_preview(request);
        if (!result.rendered)
        {
            std::cerr << result.safe_reason << "\n";
            return 1;
        }
        renderedFrames = result.frames;

        nlohmann::json manifest{
            {"schema_version", 1},
            {"state", "rendered"},
            {"frame_count", result.frames.size()},
            {"width", request.width},
            {"height", request.height},
            {"frames", nlohmann::json::array()},
            {"ramses_version", result.ramses_version},
            {"feature_level", result.feature_level},
        };
        for (const auto& frame : result.frames)
            manifest["frames"].push_back(frame.filename().string());

        const auto temporary = request.output_root / "preview-manifest.json.tmp";
        const auto destination = request.output_root / "preview-manifest.json";
        try
        {
            std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
            if (!stream)
                throw std::runtime_error("manifest_write_failed");
            stream << manifest.dump(2) << '\n';
            stream.close();
            if (!stream)
                throw std::runtime_error("manifest_write_failed");
            fs::rename(temporary, destination);
        }
        catch (...)
        {
            std::error_code error;
            fs::remove(temporary, error);
            removeFrames(result.frames);
            throw std::runtime_error("manifest_write_failed");
        }
        std::cout << manifest.dump() << "\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        removeFrames(renderedFrames);
        const std::string reason = error.what();
        std::cerr << (reason == "invalid_arguments" || reason == "manifest_write_failed" ? reason : "render_failed") << "\n";
        return 2;
    }
    catch (...)
    {
        removeFrames(renderedFrames);
        std::cerr << "render_failed\n";
        return 2;
    }
}
