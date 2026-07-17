#include "sgfx/cine/ramses_preview.h"

#include "test_support.h"

#include <ramses/client/PerspectiveCamera.h>
#include <ramses/client/RamsesClient.h>
#include <ramses/client/RenderGroup.h>
#include <ramses/client/RenderPass.h>
#include <ramses/client/Scene.h>
#include <ramses/client/logic/LogicEngine.h>
#include <ramses/framework/EFeatureLevel.h>
#include <ramses/framework/RamsesFramework.h>
#include <ramses/framework/RamsesFrameworkConfig.h>

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

using sgfx_cine_tests::TemporaryDirectory;

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

constexpr std::string_view kAutoAspectInterfaceSource = R"(
    function interface(inout)
        inout.AutoAspect = Type:Bool()
        inout.Scale = Type:Float()
        inout.Origin = Type:Vec3f()
        inout.ShiftXY = Type:Vec2i()
        inout.CraneGimbal = {
            Distance = Type:Float(), Yaw = Type:Float(), Pitch = Type:Float(), Roll = Type:Float()
        }
        inout.Frustum = {
            HorizontalFOV = Type:Float(), AspectRatio = Type:Float(),
            NearPlane = Type:Float(), FarPlane = Type:Float()
        }
        inout.Viewport = {
            OffsetX = Type:Int32(), OffsetY = Type:Int32(), Width = Type:Int32(), Height = Type:Int32()
        }
    end
)";

constexpr std::string_view kLegacyAspectInterfaceSource = R"(
    function interface(inout)
        inout.AspectFromResolution_isEnabled = Type:Bool()
        inout.Scale = Type:Float()
        inout.Origin = Type:Vec3f()
        inout.ShiftXY = Type:Vec2i()
        inout.CraneGimbal = {
            Distance = Type:Float(), Yaw = Type:Float(), Pitch = Type:Float(), Roll = Type:Float()
        }
        inout.Frustum = {
            HorizontalFOV = Type:Float(), AspectRatio = Type:Float(),
            NearPlane = Type:Float(), FarPlane = Type:Float()
        }
        inout.Viewport = {
            OffsetX = Type:Int32(), OffsetY = Type:Int32(), Width = Type:Int32(), Height = Type:Int32()
        }
    end
)";

bool expectAuthoredGenerationReachesReadback(const fs::path& sceneDir, const fs::path& outputDir,
                                             std::string_view interfaceSource, const char* label)
{
    const auto scenePath = sceneDir / (std::string(label) + ".ramses");
    {
        ramses::RamsesFrameworkConfig config{ramses::EFeatureLevel_01};
        ramses::RamsesFramework framework{config};
        auto* client = framework.createClient("sgfx-preview-contract-save");
        auto* scene = client->createScene(ramses::sceneId_t{2030u}, "preview-crane-scene");
        auto* camera = scene->createPerspectiveCamera("preview-camera");
        camera->setFrustum(19.0f, 480.0f / 270.0f, 0.1f, 100.0f);
        camera->setViewport(0, 0, 480u, 270u);
        auto* pass = scene->createRenderPass("preview-pass");
        pass->setCamera(*camera);
        auto* group = scene->createRenderGroup("preview-group");
        pass->addRenderGroup(*group);
        auto* engine = scene->createLogicEngine("preview-crane-logic");
        if (engine->createLuaInterface(interfaceSource, "Interface_CameraCrane") == nullptr ||
            !scene->flush() || !scene->saveToFile(scenePath.string()))
        {
            std::cerr << label << ": could not save the synthetic camera-crane scene\n";
            return false;
        }
    }

    sgfx::cine::RamsesPreviewRequest request;
    request.scene_path = scenePath;
    request.output_root = outputDir;
    request.width = 480u;
    request.height = 270u;
    request.frame_count = 1u;
    request.reduced_motion = true;
    const auto result = sgfx::cine::render_ramses_preview(request);
    if (result.rendered || result.safe_reason != "readback_failed")
    {
        std::cerr << label << ": expected readback_failed after camera configuration, received "
                  << (result.rendered ? std::string("rendered") : result.safe_reason) << "\n";
        return false;
    }
    return true;
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
        request.width = 961u;
        if (!expectRejected(request, "request_out_of_bounds"))
            return 1;

        request.width = 480u;
        request.height = 541u;
        if (!expectRejected(request, "request_out_of_bounds"))
            return 1;

        request.height = 270u;
        request.frame_count = 49u;
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

        const auto autoAspectOutput = temporary.path() / "auto-aspect-output";
        const auto legacyOutput = temporary.path() / "legacy-aspect-output";
        std::error_code generationError;
        if (!fs::create_directory(autoAspectOutput, generationError) ||
            !fs::create_directory(legacyOutput, generationError))
        {
            std::cerr << "could not create generation output roots\n";
            return 1;
        }
        if (!expectAuthoredGenerationReachesReadback(temporary.path(), autoAspectOutput,
                                                     kAutoAspectInterfaceSource, "auto-aspect-generation"))
            return 1;
        if (!expectAuthoredGenerationReachesReadback(temporary.path(), legacyOutput,
                                                     kLegacyAspectInterfaceSource, "legacy-aspect-generation"))
            return 1;

        std::cout << "Ramses preview contract OK\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "Ramses preview contract failed: " << error.what() << "\n";
        return 1;
    }
}
