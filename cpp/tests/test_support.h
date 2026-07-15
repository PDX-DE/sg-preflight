#pragma once

#include <chrono>
#include <filesystem>
#include <stdexcept>
#include <string>

namespace sgfx_cine_tests
{
class TemporaryDirectory
{
public:
    explicit TemporaryDirectory(const std::string& prefix = "sgfx-cine-test")
    {
        const auto base = std::filesystem::temp_directory_path();
        for (unsigned attempt = 0u; attempt < 100u; ++attempt)
        {
            const auto seed = std::chrono::steady_clock::now().time_since_epoch().count();
            m_path = base / (prefix + "-" + std::to_string(seed) + "-" + std::to_string(attempt));
            std::error_code error;
            if (std::filesystem::create_directory(m_path, error))
                return;
        }
        throw std::runtime_error("could not create test temp directory: " + prefix);
    }

    ~TemporaryDirectory()
    {
        std::error_code error;
        std::filesystem::remove_all(m_path, error);
    }

    TemporaryDirectory(const TemporaryDirectory&) = delete;
    TemporaryDirectory& operator=(const TemporaryDirectory&) = delete;

    const std::filesystem::path& path() const { return m_path; }

private:
    std::filesystem::path m_path;
};
}
