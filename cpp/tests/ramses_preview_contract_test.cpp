#include "sgfx/cine/ramses_preview.h"

#include <array>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

#if defined(_WIN32)
#define NOMINMAX
#include <Windows.h>
#include <winioctl.h>
#endif

namespace
{
namespace fs = std::filesystem;

class TemporaryDirectory
{
public:
    TemporaryDirectory()
    {
        const auto base = fs::temp_directory_path();
        for (unsigned attempt = 0u; attempt < 100u; ++attempt)
        {
            const auto seed = std::chrono::steady_clock::now().time_since_epoch().count();
            m_path = base / ("sgfx-ramses-preview-contract-" + std::to_string(seed) + "-" + std::to_string(attempt));
            std::error_code error;
            if (fs::create_directory(m_path, error))
                return;
        }
        throw std::runtime_error("could not create contract-test directory");
    }

    ~TemporaryDirectory()
    {
        std::error_code error;
        fs::remove_all(m_path, error);
    }

    const fs::path& path() const { return m_path; }

private:
    fs::path m_path;
};

bool expectRejected(const sgfx::cine::RamsesPreviewRequest& request, const std::string& reason)
{
    const auto result = sgfx::cine::render_ramses_preview(request);
    if (result.rendered || result.safe_reason != reason || !result.frames.empty())
    {
        std::cerr << "expected rejection " << reason << ", received " << result.safe_reason << "\n";
        return false;
    }
    return true;
}

bool createDirectoryLink(const fs::path& link, const fs::path& target)
{
    std::error_code error;
    fs::create_directory_symlink(target, link, error);
    if (!error)
        return true;
#if defined(_WIN32)
    error.clear();
    if (!fs::create_directory(link, error))
        return false;

    struct JunctionBuffer
    {
        ULONG tag;
        USHORT dataLength;
        USHORT reserved;
        USHORT substituteOffset;
        USHORT substituteLength;
        USHORT printOffset;
        USHORT printLength;
        WCHAR pathBuffer[1];
    };

    const std::wstring printName = fs::absolute(target).wstring();
    const std::wstring substituteName = L"\\??\\" + printName;
    alignas(void*) std::array<unsigned char, MAXIMUM_REPARSE_DATA_BUFFER_SIZE> storage{};
    auto* buffer = reinterpret_cast<JunctionBuffer*>(storage.data());
    buffer->tag = IO_REPARSE_TAG_MOUNT_POINT;
    buffer->substituteOffset = 0u;
    buffer->substituteLength = static_cast<USHORT>(substituteName.size() * sizeof(WCHAR));
    buffer->printOffset = static_cast<USHORT>(buffer->substituteLength + sizeof(WCHAR));
    buffer->printLength = static_cast<USHORT>(printName.size() * sizeof(WCHAR));
    std::memcpy(buffer->pathBuffer, substituteName.c_str(), buffer->substituteLength);
    std::memcpy(
        reinterpret_cast<unsigned char*>(buffer->pathBuffer) + buffer->printOffset,
        printName.c_str(),
        buffer->printLength);
    buffer->dataLength = static_cast<USHORT>(
        8u + buffer->substituteLength + sizeof(WCHAR) + buffer->printLength + sizeof(WCHAR));

    const HANDLE handle = CreateFileW(
        link.c_str(),
        GENERIC_WRITE,
        0u,
        nullptr,
        OPEN_EXISTING,
        FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS,
        nullptr);
    if (handle == INVALID_HANDLE_VALUE)
        return false;
    DWORD returned = 0u;
    const BOOL linked = DeviceIoControl(
        handle,
        FSCTL_SET_REPARSE_POINT,
        buffer,
        buffer->dataLength + 8u,
        nullptr,
        0u,
        &returned,
        nullptr);
    CloseHandle(handle);
    if (!linked)
        fs::remove(link, error);
    return linked != FALSE;
#else
    return false;
#endif
}
}

int main()
{
    try
    {
        TemporaryDirectory temporary;
        const auto scene = temporary.path() / "scene.ramses";
        const auto output = temporary.path() / "output";
        std::ofstream(scene, std::ios::binary) << "not-a-ramses-scene";
        fs::create_directory(output);

        sgfx::cine::RamsesPreviewRequest request;
        request.scene_path = temporary.path() / "missing.ramses";
        request.output_root = output;
        if (!expectRejected(request, "scene_unavailable"))
            return 1;

        request.scene_path = scene;
        request.output_root = temporary.path() / "parent-file" / "output";
        std::ofstream(temporary.path() / "parent-file") << "not-a-directory";
        if (!expectRejected(request, "output_unavailable"))
            return 1;

        request.output_root = output;
        request.width = 481u;
        if (!expectRejected(request, "request_out_of_bounds"))
            return 1;

        request.width = 480u;
        request.height = 271u;
        if (!expectRejected(request, "request_out_of_bounds"))
            return 1;

        request.height = 270u;
        request.frame_count = 25u;
        if (!expectRejected(request, "request_out_of_bounds"))
            return 1;

        request.frame_count = 24u;
        request.reduced_motion = true;
        if (!expectRejected(request, "request_out_of_bounds"))
            return 1;

        const auto linkedOutput = temporary.path() / "linked-output";
        if (!createDirectoryLink(linkedOutput, output))
        {
            std::cerr << "linked-output fixture unavailable\n";
            return 1;
        }
        request.output_root = linkedOutput;
        request.frame_count = 1u;
        if (!expectRejected(request, "output_linked"))
            return 1;

        if (!fs::is_empty(output))
        {
            std::cerr << "invalid requests wrote output\n";
            return 1;
        }

        std::cout << "Ramses preview contract OK\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "Ramses preview contract failed: " << error.what() << "\n";
        return 1;
    }
}
