#include "sgfx/cine/ramses_preview.h"

#include "ramses/client/Camera.h"
#include "ramses/client/RenderPass.h"
#include "ramses/client/Scene.h"
#include "ramses/client/SceneConfig.h"
#include "ramses/client/SceneMetadata.h"
#include "ramses/client/SceneObjectIterator.h"
#include "ramses/client/logic/LogicEngine.h"
#include "ramses/client/logic/LuaInterface.h"
#include "ramses/client/logic/LuaScript.h"
#include "ramses/client/logic/Property.h"
#include "ramses/client/ramses-client.h"
#include "ramses/client/ramses-utils.h"
#include "ramses/framework/RamsesFramework.h"
#include "ramses/framework/RamsesFrameworkConfig.h"
#include "ramses/framework/RamsesVersion.h"
#include "ramses/renderer/DisplayConfig.h"
#include "ramses/renderer/RamsesRenderer.h"
#include "ramses/renderer/RendererConfig.h"
#include "ramses/renderer/RendererSceneControl.h"

#include "ramses_render_support.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <initializer_list>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <thread>
#include <utility>

#if defined(_WIN32)
#define NOMINMAX
#include <Windows.h>
#endif

namespace sgfx::cine
{
namespace
{
namespace fs = std::filesystem;

class PreviewFailure final : public std::runtime_error
{
public:
    explicit PreviewFailure(std::string reason)
        : std::runtime_error(reason)
        , m_reason(std::move(reason))
    {
    }

    const std::string& reason() const { return m_reason; }

private:
    std::string m_reason;
};

bool isLinked(const fs::path& path)
{
    std::error_code error;
    const auto status = fs::symlink_status(path, error);
    if (error || fs::is_symlink(status))
        return true;
#if defined(_WIN32)
    const auto attributes = GetFileAttributesW(path.c_str());
    return attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0u;
#else
    return false;
#endif
}

void validateRequest(const RamsesPreviewRequest& request)
{
    if (request.width == 0u || request.width > 960u ||
        request.height == 0u || request.height > 540u ||
        request.frame_count == 0u || request.frame_count > 48u ||
        (request.reduced_motion && request.frame_count != 1u))
    {
        throw PreviewFailure("request_out_of_bounds");
    }

    std::error_code error;
    if (!fs::is_regular_file(request.scene_path, error) || error)
        throw PreviewFailure("scene_unavailable");
    if (isLinked(request.scene_path))
        throw PreviewFailure("scene_linked");

    error.clear();
    if (!fs::is_directory(request.output_root, error) || error)
        throw PreviewFailure("output_unavailable");
    if (isLinked(request.output_root))
        throw PreviewFailure("output_linked");

    error.clear();
    if (!fs::is_empty(request.output_root, error) || error)
        throw PreviewFailure("output_not_empty");
}

template <typename Predicate, typename Tick>
void waitFor(
    ramses::RamsesRenderer& renderer,
    ramses::RendererSceneControl& sceneControl,
    render_support::RenderEventHandler& handler,
    Predicate predicate,
    Tick tick,
    std::chrono::steady_clock::time_point deadline)
{
    while (!predicate())
    {
        if (handler.failed() || std::chrono::steady_clock::now() >= deadline)
            throw PreviewFailure("lifecycle_timeout");
        tick();
        render_support::pumpRamses(renderer, sceneControl, handler);
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
}

std::vector<ramses::LogicEngine*> collectLogicEngines(ramses::Scene& scene)
{
    std::vector<ramses::LogicEngine*> engines;
    ramses::SceneObjectIterator iterator(scene, ramses::ERamsesObjectType::LogicEngine);
    while (auto* object = iterator.getNext())
    {
        if (auto* engine = object->as<ramses::LogicEngine>())
            engines.push_back(engine);
    }
    return engines;
}

ramses::Property* cameraCraneRoot(ramses::LogicNode& node)
{
    auto* inputs = node.getInputs();
    if (!inputs)
        return nullptr;
    if (inputs->hasChild("Interface_CameraCrane"))
        return inputs->getChild("Interface_CameraCrane");
    if (inputs->hasChild("CraneGimbal"))
        return inputs;
    return nullptr;
}

std::vector<ramses::Property*> collectCameraCraneInputs(const std::vector<ramses::LogicEngine*>& engines)
{
    std::vector<ramses::Property*> inputs;
    for (auto* engine : engines)
    {
        for (auto* interfaceNode : engine->getCollection<ramses::LuaInterface>())
        {
            if (auto* input = cameraCraneRoot(*interfaceNode))
                inputs.push_back(input);
        }
    }
    for (auto* engine : engines)
    {
        for (auto* script : engine->getCollection<ramses::LuaScript>())
        {
            if (auto* input = cameraCraneRoot(*script))
                inputs.push_back(input);
        }
    }
    return inputs;
}

template <typename T>
bool setProperty(ramses::Property& root, std::initializer_list<std::string_view> path, T value)
{
    auto* property = &root;
    for (const auto segment : path)
    {
        if (!property->hasChild(segment))
            return false;
        property = property->getChild(segment);
    }
    return property && property->set<T>(value);
}

std::vector<ramses::Property*> configureAuthoredCamera(
    const std::vector<ramses::Property*>& inputs,
    std::uint32_t width,
    std::uint32_t height)
{
    std::vector<ramses::Property*> configuredInputs;
    const auto aspect = static_cast<float>(width) / static_cast<float>(height);
    for (auto* input : inputs)
    {
        // Current exports expose AutoAspect; older exports use the prototype spelling.
        const bool aspectConfigured = input &&
            (setProperty<bool>(*input, {"AutoAspect"}, true) ||
             setProperty<bool>(*input, {"AspectFromResolution_isEnabled"}, true));
        const bool configured = aspectConfigured &&
            setProperty<float>(*input, {"CraneGimbal", "Distance"}, 12.0f) &&
            setProperty<float>(*input, {"CraneGimbal", "Pitch"}, 4.0f) &&
            setProperty<float>(*input, {"CraneGimbal", "Roll"}, 0.0f) &&
            setProperty<float>(*input, {"Frustum", "AspectRatio"}, aspect) &&
            setProperty<float>(*input, {"Frustum", "FarPlane"}, 100.0f) &&
            setProperty<float>(*input, {"Frustum", "HorizontalFOV"}, 43.0f) &&
            setProperty<float>(*input, {"Frustum", "NearPlane"}, 0.5f) &&
            setProperty<float>(*input, {"Scale"}, 1.0f) &&
            setProperty<ramses::vec2i>(*input, {"ShiftXY"}, ramses::vec2i{0, 0}) &&
            setProperty<ramses::vec3f>(*input, {"Origin"}, ramses::vec3f{0.0f, -0.123f, 0.0f}) &&
            setProperty<std::int32_t>(*input, {"Viewport", "Height"}, static_cast<std::int32_t>(height)) &&
            setProperty<std::int32_t>(*input, {"Viewport", "OffsetX"}, 0) &&
            setProperty<std::int32_t>(*input, {"Viewport", "OffsetY"}, 0) &&
            setProperty<std::int32_t>(*input, {"Viewport", "Width"}, static_cast<std::int32_t>(width));
        if (configured)
            configuredInputs.push_back(input);
    }
    if (configuredInputs.empty())
        throw PreviewFailure("authored_camera_unavailable");
    return configuredInputs;
}

void setAuthoredYaw(const std::vector<ramses::Property*>& inputs, float yaw)
{
    for (auto* input : inputs)
    {
        if (!input || !setProperty<float>(*input, {"CraneGimbal", "Yaw"}, yaw))
            throw PreviewFailure("authored_camera_unavailable");
    }
}

void updateLogic(const std::vector<ramses::LogicEngine*>& engines)
{
    for (auto* engine : engines)
    {
        if (!engine->update())
            throw PreviewFailure("logic_update_failed");
    }
}

bool hasVisiblePixels(const std::vector<std::uint8_t>& pixels)
{
    for (std::size_t index = 0u; index + 3u < pixels.size(); index += 4u)
    {
        const auto brightness = static_cast<unsigned>(pixels[index]) +
                                static_cast<unsigned>(pixels[index + 1u]) +
                                static_cast<unsigned>(pixels[index + 2u]);
        if (brightness > 80u)
            return true;
    }
    return false;
}

bool hasAuthoredFramebufferPass(ramses::Scene& scene)
{
    ramses::SceneObjectIterator iterator(scene, ramses::ERamsesObjectType::RenderPass);
    while (auto* object = iterator.getNext())
    {
        auto* pass = object->as<ramses::RenderPass>();
        if (pass && pass->isEnabled() && !pass->getRenderTarget() && pass->getCamera())
            return true;
    }
    return false;
}

std::string frameName(std::uint32_t index)
{
    std::ostringstream stream;
    stream << "frame-" << std::setw(3) << std::setfill('0') << index << ".png";
    return stream.str();
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

RamsesPreviewResult render_ramses_preview(const RamsesPreviewRequest& request)
{
    RamsesPreviewResult result;
    std::vector<fs::path> createdFrames;
    try
    {
        validateRequest(request);
        const auto metadata = ramses::RamsesClient::GetMetadataFromFile(request.scene_path.string());
        if (!metadata)
            throw PreviewFailure("scene_incompatible");

        const auto linkedVersion = ramses::GetRamsesVersion();
        result.ramses_version = linkedVersion.string;
        result.feature_level = static_cast<std::uint32_t>(metadata->featureLevel);

        render_support::SdlGuard sdl;
        if (!sdl.initialized())
            throw PreviewFailure("renderer_unavailable");
        render_support::HiddenWindow window(request.width, request.height);
        if (!window.valid())
            throw PreviewFailure("renderer_unavailable");

        ramses::RamsesFrameworkConfig frameworkConfig{metadata->featureLevel};
        frameworkConfig.setRequestedRamsesShellType(ramses::ERamsesShellType::None);
        frameworkConfig.setLogLevel(ramses::ELogLevel::Off);
        frameworkConfig.setLogLevelConsole(ramses::ELogLevel::Off);
        ramses::RamsesFramework framework(frameworkConfig);
        auto* client = framework.createClient("sgfx-ramses-preview-client");
        ramses::RendererConfig rendererConfig;
        auto* renderer = framework.createRenderer(rendererConfig);
        if (!client || !renderer || !framework.connect())
            throw PreviewFailure("renderer_unavailable");
        auto* sceneControl = renderer->getSceneControlAPI();
        if (!sceneControl)
            throw PreviewFailure("renderer_unavailable");

        ramses::SceneConfig sceneConfig{
            ramses::sceneId_t{9701u},
            ramses::EScenePublicationMode::LocalOnly,
            ramses::ERenderBackendCompatibility::OpenGL};
        auto* scene = client->loadSceneFromFile(request.scene_path.string(), sceneConfig);
        if (!scene || !hasAuthoredFramebufferPass(*scene))
            throw PreviewFailure("scene_incompatible");

        const auto logicEngines = collectLogicEngines(*scene);
        const auto cameraCandidates = collectCameraCraneInputs(logicEngines);
        const auto cameraInputs = configureAuthoredCamera(cameraCandidates, request.width, request.height);

        ramses::DisplayConfig displayConfig;
        displayConfig.setWindowType(ramses::EWindowType::Windows);
        void* nativeHandle = window.nativeHandle();
        if (!nativeHandle)
            throw PreviewFailure("renderer_unavailable");
        displayConfig.setWindowsWindowHandle(nativeHandle);
        displayConfig.setWindowRectangle(0, 0, request.width, request.height);
        displayConfig.setWindowTitle("SGFX Ramses Preview");
        const auto display = renderer->createDisplay(displayConfig);
        if (!display.isValid())
            throw PreviewFailure("renderer_unavailable");
        renderer->setSkippingOfUnmodifiedBuffers(false);
        renderer->flush();

        const auto sceneId = scene->getSceneId();
        render_support::RenderEventHandler handler(display, sceneId, request.width, request.height);
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(25);
        waitFor(*renderer, *sceneControl, handler, [&] { return handler.displayReady(); }, [] {}, deadline);

        const auto offscreen = renderer->createOffscreenBuffer(display, request.width, request.height);
        if (!offscreen.isValid())
            throw PreviewFailure("renderer_unavailable");
        handler.setBuffer(offscreen);
        // Fully transparent clear: the readback keeps its alpha channel through the PNG, so the
        // shell composites the car itself instead of a rendered backdrop slab.
        renderer->setDisplayBufferClearColor(display, offscreen, ramses::vec4f{0.0f, 0.0f, 0.0f, 0.0f});
        renderer->flush();
        waitFor(*renderer, *sceneControl, handler, [&] { return handler.bufferReady(); }, [] {}, deadline);

        setAuthoredYaw(cameraInputs, -45.0f);
        updateLogic(logicEngines);
        if (!scene->publish(ramses::EScenePublicationMode::LocalOnly))
            throw PreviewFailure("lifecycle_rejected");
        scene->flush();
        waitFor(*renderer, *sceneControl, handler, [&] { return handler.sceneAvailable(); }, [&] { scene->flush(); }, deadline);

        if (!sceneControl->setSceneMapping(sceneId, display) ||
            !sceneControl->setSceneDisplayBufferAssignment(sceneId, offscreen, 0) ||
            !sceneControl->setSceneState(sceneId, ramses::RendererSceneState::Ready))
        {
            throw PreviewFailure("lifecycle_rejected");
        }
        sceneControl->flush();
        waitFor(*renderer, *sceneControl, handler, [&] { return handler.sceneReady(); }, [&] { scene->flush(); }, deadline);

        if (!sceneControl->setSceneState(sceneId, ramses::RendererSceneState::Rendered))
            throw PreviewFailure("lifecycle_rejected");
        sceneControl->flush();
        waitFor(*renderer, *sceneControl, handler, [&] { return handler.sceneRendered(); }, [&] { scene->flush(); }, deadline);

        for (std::uint32_t index = 0u; index < request.frame_count; ++index)
        {
            const float yaw = request.reduced_motion
                ? -45.0f
                : -45.0f + static_cast<float>(index) * 360.0f / static_cast<float>(request.frame_count);
            setAuthoredYaw(cameraInputs, yaw);
            updateLogic(logicEngines);
            scene->flush();
            for (std::uint32_t settle = 0u; settle < 3u; ++settle)
                pumpRamses(*renderer, *sceneControl, handler);

            handler.resetPixels();
            renderer->readPixels(display, offscreen, 0u, 0u, request.width, request.height);
            renderer->flush();
            waitFor(*renderer, *sceneControl, handler, [&] { return handler.pixelsReceived(); }, [&] { scene->flush(); }, deadline);
            if (!hasVisiblePixels(handler.pixels()))
                throw PreviewFailure("readback_failed");

            const auto frame = request.output_root / frameName(index);
            auto pixels = handler.pixels();
            createdFrames.push_back(frame);
            if (!ramses::RamsesUtils::SaveImageBufferToPng(frame.string(), pixels, request.width, request.height, true))
                throw PreviewFailure("frame_write_failed");
        }

        sceneControl->setSceneState(sceneId, ramses::RendererSceneState::Unavailable);
        sceneControl->flush();
        scene->unpublish();
        renderer->destroyOffscreenBuffer(display, offscreen);
        renderer->destroyDisplay(display);
        renderer->flush();
        framework.disconnect();

        result.rendered = true;
        result.frames = createdFrames;
        return result;
    }
    catch (const PreviewFailure& failure)
    {
        removeFrames(createdFrames);
        result.safe_reason = failure.reason();
        return result;
    }
    catch (...)
    {
        removeFrames(createdFrames);
        result.safe_reason = "render_failed";
        return result;
    }
}
}
