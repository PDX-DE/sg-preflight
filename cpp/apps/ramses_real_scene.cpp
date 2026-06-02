#include "ramses/client/Camera.h"
#include "ramses/client/BlitPass.h"
#include "ramses/client/logic/CameraBinding.h"
#include "ramses/client/logic/LogicEngine.h"
#include "ramses/client/logic/LogicObject.h"
#include "ramses/client/logic/LuaInterface.h"
#include "ramses/client/logic/LuaScript.h"
#include "ramses/client/logic/NodeBinding.h"
#include "ramses/client/logic/Property.h"
#include "ramses/client/MeshNode.h"
#include "ramses/client/Node.h"
#include "ramses/client/OrthographicCamera.h"
#include "ramses/client/PerspectiveCamera.h"
#include "ramses/client/RamsesClient.h"
#include "ramses/client/RenderBuffer.h"
#include "ramses/client/RenderGroup.h"
#include "ramses/client/RenderPass.h"
#include "ramses/client/RenderTarget.h"
#include "ramses/client/Scene.h"
#include "ramses/client/SceneConfig.h"
#include "ramses/client/SceneMetadata.h"
#include "ramses/client/SceneObjectIterator.h"
#include "ramses/client/ramses-utils.h"
#include "ramses/framework/EFeatureLevel.h"
#include "ramses/framework/RamsesFramework.h"
#include "ramses/framework/RamsesFrameworkConfig.h"
#include "ramses/framework/RamsesFrameworkTypes.h"
#include "ramses/framework/RamsesVersion.h"
#include "ramses/framework/VersionInfo.h"
#include "ramses/renderer/DisplayConfig.h"
#include "ramses/renderer/IRendererEventHandler.h"
#include "ramses/renderer/IRendererSceneControlEventHandler.h"
#include "ramses/renderer/RamsesRenderer.h"
#include "ramses/renderer/RendererConfig.h"
#include "ramses/renderer/RendererSceneControl.h"

#include <SDL3/SDL.h>

#include <glm/gtc/quaternion.hpp>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <initializer_list>
#include <iostream>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace
{
constexpr float Pi = 3.14159265358979323846f;

struct Options
{
    uint32_t width = 0u;
    uint32_t height = 0u;
    uint32_t frames = 240u;
    bool readback = false;
    bool autoFrame = false;
    bool orbit = false;
    float zoom = 1.0f;
    std::string viewPreset = "three-quarter";
    std::string qaPerspectiveName;
    float qaPerspectiveDistance = 0.0f;
    float qaPerspectiveYaw = 0.0f;
    float qaPerspectivePitch = 0.0f;
    float qaPerspectiveRoll = 0.0f;
    float qaPerspectiveHorizontalFov = 0.0f;
    float qaPerspectiveAspectRatio = 0.0f;
    float qaPerspectiveNearPlane = 0.0f;
    float qaPerspectiveFarPlane = 0.0f;
    bool qaPerspectiveAspectFromResolution = true;
    float qaPerspectiveScale = 1.0f;
    ramses::vec3f qaPerspectiveOrigin{0.0f, 0.0f, 0.0f};
    ramses::vec2i qaPerspectiveShift{0, 0};
    int32_t qaPerspectiveViewportOffsetX = 0;
    int32_t qaPerspectiveViewportOffsetY = 0;
    uint32_t qaPerspectiveViewportWidth = 0u;
    uint32_t qaPerspectiveViewportHeight = 0u;
    std::string profileId;
    std::string screenshotPath;
    std::string sceneFile;
};

uint32_t parseUint(const char* value, const char* optionName)
{
    char* end = nullptr;
    const unsigned long parsed = std::strtoul(value, &end, 10);
    if (end == value || *end != '\0' || parsed == 0ul || parsed > UINT32_MAX)
        throw std::runtime_error(std::string("Invalid value for ") + optionName);
    return static_cast<uint32_t>(parsed);
}

float parseFloat(const char* value, const char* optionName)
{
    char* end = nullptr;
    const float parsed = std::strtof(value, &end);
    if (end == value || *end != '\0' || !std::isfinite(parsed) || parsed <= 0.0f)
        throw std::runtime_error(std::string("Invalid value for ") + optionName);
    return parsed;
}

float parseFiniteFloat(const char* value, const char* optionName)
{
    char* end = nullptr;
    const float parsed = std::strtof(value, &end);
    if (end == value || *end != '\0' || !std::isfinite(parsed))
        throw std::runtime_error(std::string("Invalid value for ") + optionName);
    return parsed;
}

bool parseBool(const char* value, const char* optionName)
{
    std::string normalized{value};
    std::transform(normalized.begin(), normalized.end(), normalized.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    if (normalized == "true" || normalized == "1" || normalized == "yes" || normalized == "on")
        return true;
    if (normalized == "false" || normalized == "0" || normalized == "no" || normalized == "off")
        return false;
    throw std::runtime_error(std::string("Invalid value for ") + optionName);
}

Options parseOptions(int argc, char** argv)
{
    Options options;
    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];
        auto requireValue = [&](const char* optionName) -> const char* {
            if (i + 1 >= argc)
                throw std::runtime_error(std::string("Missing value for ") + optionName);
            return argv[++i];
        };

        if (arg == "--width")
            options.width = parseUint(requireValue("--width"), "--width");
        else if (arg == "--height")
            options.height = parseUint(requireValue("--height"), "--height");
        else if (arg == "--frames")
            options.frames = parseUint(requireValue("--frames"), "--frames");
        else if (arg == "--readback")
            options.readback = true;
        else if (arg == "--auto-frame")
            options.autoFrame = true;
        else if (arg == "--no-auto-frame")
            options.autoFrame = false;
        else if (arg == "--orbit")
            options.orbit = true;
        else if (arg == "--no-orbit")
            options.orbit = false;
        else if (arg == "--zoom")
            options.zoom = parseFloat(requireValue("--zoom"), "--zoom");
        else if (arg == "--view-preset")
            options.viewPreset = requireValue("--view-preset");
        else if (arg == "--qa-perspective-name")
            options.qaPerspectiveName = requireValue("--qa-perspective-name");
        else if (arg == "--qa-perspective-distance")
            options.qaPerspectiveDistance = parseFloat(requireValue("--qa-perspective-distance"), "--qa-perspective-distance");
        else if (arg == "--qa-perspective-yaw")
            options.qaPerspectiveYaw = parseFiniteFloat(requireValue("--qa-perspective-yaw"), "--qa-perspective-yaw");
        else if (arg == "--qa-perspective-pitch")
            options.qaPerspectivePitch = parseFiniteFloat(requireValue("--qa-perspective-pitch"), "--qa-perspective-pitch");
        else if (arg == "--qa-perspective-roll")
            options.qaPerspectiveRoll = parseFiniteFloat(requireValue("--qa-perspective-roll"), "--qa-perspective-roll");
        else if (arg == "--qa-perspective-horizontal-fov")
            options.qaPerspectiveHorizontalFov =
                parseFloat(requireValue("--qa-perspective-horizontal-fov"), "--qa-perspective-horizontal-fov");
        else if (arg == "--qa-perspective-aspect-ratio")
            options.qaPerspectiveAspectRatio =
                parseFloat(requireValue("--qa-perspective-aspect-ratio"), "--qa-perspective-aspect-ratio");
        else if (arg == "--qa-perspective-near-plane")
            options.qaPerspectiveNearPlane = parseFloat(requireValue("--qa-perspective-near-plane"), "--qa-perspective-near-plane");
        else if (arg == "--qa-perspective-far-plane")
            options.qaPerspectiveFarPlane = parseFloat(requireValue("--qa-perspective-far-plane"), "--qa-perspective-far-plane");
        else if (arg == "--qa-perspective-aspect-from-resolution")
            options.qaPerspectiveAspectFromResolution =
                parseBool(requireValue("--qa-perspective-aspect-from-resolution"), "--qa-perspective-aspect-from-resolution");
        else if (arg == "--qa-perspective-scale")
            options.qaPerspectiveScale = parseFloat(requireValue("--qa-perspective-scale"), "--qa-perspective-scale");
        else if (arg == "--qa-perspective-origin-x")
            options.qaPerspectiveOrigin.x = parseFiniteFloat(requireValue("--qa-perspective-origin-x"), "--qa-perspective-origin-x");
        else if (arg == "--qa-perspective-origin-y")
            options.qaPerspectiveOrigin.y = parseFiniteFloat(requireValue("--qa-perspective-origin-y"), "--qa-perspective-origin-y");
        else if (arg == "--qa-perspective-origin-z")
            options.qaPerspectiveOrigin.z = parseFiniteFloat(requireValue("--qa-perspective-origin-z"), "--qa-perspective-origin-z");
        else if (arg == "--qa-perspective-shift-x")
            options.qaPerspectiveShift.x =
                static_cast<int32_t>(parseFiniteFloat(requireValue("--qa-perspective-shift-x"), "--qa-perspective-shift-x"));
        else if (arg == "--qa-perspective-shift-y")
            options.qaPerspectiveShift.y =
                static_cast<int32_t>(parseFiniteFloat(requireValue("--qa-perspective-shift-y"), "--qa-perspective-shift-y"));
        else if (arg == "--qa-perspective-viewport-offset-x")
            options.qaPerspectiveViewportOffsetX =
                static_cast<int32_t>(parseFiniteFloat(requireValue("--qa-perspective-viewport-offset-x"), "--qa-perspective-viewport-offset-x"));
        else if (arg == "--qa-perspective-viewport-offset-y")
            options.qaPerspectiveViewportOffsetY =
                static_cast<int32_t>(parseFiniteFloat(requireValue("--qa-perspective-viewport-offset-y"), "--qa-perspective-viewport-offset-y"));
        else if (arg == "--qa-perspective-viewport-width")
            options.qaPerspectiveViewportWidth =
                parseUint(requireValue("--qa-perspective-viewport-width"), "--qa-perspective-viewport-width");
        else if (arg == "--qa-perspective-viewport-height")
            options.qaPerspectiveViewportHeight =
                parseUint(requireValue("--qa-perspective-viewport-height"), "--qa-perspective-viewport-height");
        else if (arg == "--presentation-mode")
            throw std::runtime_error("--presentation-mode was removed; authored scene passes are always used");
        else if (arg == "--profile-id")
            options.profileId = requireValue("--profile-id");
        else if (arg == "--screenshot")
            options.screenshotPath = requireValue("--screenshot");
        else if (arg == "--scene-file")
            options.sceneFile = requireValue("--scene-file");
        else
            throw std::runtime_error("Unknown argument: " + arg);
    }

    if (options.sceneFile.empty())
        throw std::runtime_error("--scene-file is required");
    if (!std::filesystem::is_regular_file(options.sceneFile))
        throw std::runtime_error("Scene file does not exist: " + options.sceneFile);
    if (options.viewPreset != "three-quarter" && options.viewPreset != "front" && options.viewPreset != "rear" &&
        options.viewPreset != "left" && options.viewPreset != "right")
        throw std::runtime_error("Invalid --view-preset. Expected three-quarter, front, rear, left, or right");
    if (!options.qaPerspectiveName.empty())
    {
        if (options.qaPerspectiveDistance <= 0.0f || options.qaPerspectiveHorizontalFov <= 0.0f ||
            options.qaPerspectiveAspectRatio <= 0.0f || options.qaPerspectiveNearPlane <= 0.0f ||
            options.qaPerspectiveFarPlane <= options.qaPerspectiveNearPlane || options.qaPerspectiveScale <= 0.0f ||
            options.qaPerspectiveViewportWidth == 0u || options.qaPerspectiveViewportHeight == 0u)
        {
            throw std::runtime_error("Incomplete or invalid QA perspective parameters");
        }
    }

    return options;
}

const char* sceneStateName(ramses::RendererSceneState state)
{
    switch (state)
    {
    case ramses::RendererSceneState::Unavailable:
        return "Unavailable";
    case ramses::RendererSceneState::Available:
        return "Available";
    case ramses::RendererSceneState::Ready:
        return "Ready";
    case ramses::RendererSceneState::Rendered:
        return "Rendered";
    }
    return "Unknown";
}

std::string versionString(const ramses::VersionInfo& version)
{
    return std::to_string(version.major) + "." + std::to_string(version.minor) + "." + std::to_string(version.patch);
}

class SdlGuard
{
public:
    SdlGuard()
    {
        if (!SDL_Init(SDL_INIT_VIDEO))
            throw std::runtime_error(std::string("SDL_Init failed: ") + SDL_GetError());
    }

    ~SdlGuard()
    {
        SDL_Quit();
    }
};

class SdlWindow
{
public:
    SdlWindow(const char* title, uint32_t width, uint32_t height)
        : m_window(SDL_CreateWindow(title, static_cast<int>(width), static_cast<int>(height), SDL_WINDOW_RESIZABLE))
    {
        if (!m_window)
            throw std::runtime_error(std::string("SDL_CreateWindow failed: ") + SDL_GetError());
    }

    ~SdlWindow()
    {
        if (m_window)
            SDL_DestroyWindow(m_window);
    }

    SdlWindow(const SdlWindow&) = delete;
    SdlWindow& operator=(const SdlWindow&) = delete;

    SDL_Window* get() const
    {
        return m_window;
    }

private:
    SDL_Window* m_window = nullptr;
};

void* getWin32Hwnd(SDL_Window* window)
{
#if defined(_WIN32)
    SDL_PropertiesID properties = SDL_GetWindowProperties(window);
    void* hwnd = SDL_GetPointerProperty(properties, SDL_PROP_WINDOW_WIN32_HWND_POINTER, nullptr);
    if (!hwnd)
        throw std::runtime_error(std::string("SDL Win32 HWND lookup failed: ") + SDL_GetError());
    return hwnd;
#else
    (void)window;
    throw std::runtime_error("C-3 currently requires the SDL3 Win32 backend");
#endif
}

class RealSceneEventHandler : public ramses::RendererEventHandlerEmpty, public ramses::RendererSceneControlEventHandlerEmpty
{
public:
    RealSceneEventHandler(ramses::displayId_t displayId, ramses::sceneId_t sceneId, uint32_t width, uint32_t height, std::string screenshotPath)
        : m_displayId(displayId)
        , m_sceneId(sceneId)
        , m_width(width)
        , m_height(height)
        , m_screenshotPath(std::move(screenshotPath))
    {
    }

    void displayCreated(ramses::displayId_t displayId, ramses::ERendererEventResult result) override
    {
        if (displayId != m_displayId)
            return;

        m_displayCreated = result == ramses::ERendererEventResult::Ok;
        m_displayCreateFailed = result == ramses::ERendererEventResult::Failed;
        std::cout << "Ramses displayCreated result: " << (m_displayCreated ? "Ok" : "Failed") << "\n";
    }

    void sceneStateChanged(ramses::sceneId_t sceneId, ramses::RendererSceneState state) override
    {
        if (sceneId != m_sceneId)
            return;

        m_sceneState = state;
        std::cout << "Ramses scene state: " << sceneStateName(state) << "\n";
    }

    void framebufferPixelsRead(const uint8_t* pixelData,
                               const uint32_t pixelDataSize,
                               ramses::displayId_t displayId,
                               ramses::displayBufferId_t,
                               ramses::ERendererEventResult result) override
    {
        if (displayId != m_displayId)
            return;

        m_pixelsRead = true;
        m_pixelsReadOk = result == ramses::ERendererEventResult::Ok && pixelData && pixelDataSize == m_width * m_height * 4u;
        if (!m_pixelsReadOk)
        {
            std::cout << "C-3 readPixels: Failed\n";
            return;
        }

        std::vector<uint8_t> pixels(pixelData, pixelData + pixelDataSize);
        uint32_t x = 0u;
        uint32_t y = 0u;
        for (size_t i = 0; i + 3u < pixels.size(); i += 4u)
        {
            const uint32_t brightness = static_cast<uint32_t>(pixels[i]) + static_cast<uint32_t>(pixels[i + 1u]) + static_cast<uint32_t>(pixels[i + 2u]);
            if (brightness > 80u)
            {
                ++m_brightPixels;
                m_minBrightX = std::min(m_minBrightX, x);
                m_minBrightY = std::min(m_minBrightY, y);
                m_maxBrightX = std::max(m_maxBrightX, x);
                m_maxBrightY = std::max(m_maxBrightY, y);
            }

            ++x;
            if (x == m_width)
            {
                x = 0u;
                ++y;
            }
        }

        if (!m_screenshotPath.empty())
            m_screenshotSaved = ramses::RamsesUtils::SaveImageBufferToPng(m_screenshotPath, pixels, m_width, m_height, true);

        std::cout << "C-3 readPixels bright pixels: " << m_brightPixels << "\n";
        if (m_brightPixels > 0u)
            std::cout << "C-3 readPixels bright bounds x/y: " << m_minBrightX << "-" << m_maxBrightX << "/" << m_minBrightY << "-" << m_maxBrightY << "\n";
        if (!m_screenshotPath.empty())
            std::cout << "C-3 screenshot saved: " << (m_screenshotSaved ? m_screenshotPath : "failed") << "\n";
    }

    void renderThreadLoopTimings(ramses::displayId_t displayId,
                                 std::chrono::microseconds maximumLoopTime,
                                 std::chrono::microseconds averageLoopTime) override
    {
        if (displayId == m_displayId)
            std::cout << "Ramses loop timing us max/avg: " << maximumLoopTime.count() << "/" << averageLoopTime.count() << "\n";
    }

    bool displayCreated() const
    {
        return m_displayCreated;
    }

    bool displayCreateFailed() const
    {
        return m_displayCreateFailed;
    }

    bool sceneRendered() const
    {
        return m_sceneState == ramses::RendererSceneState::Rendered;
    }

    bool pixelsRead() const
    {
        return m_pixelsRead;
    }

    bool pixelsReadOk() const
    {
        return m_pixelsReadOk;
    }

    uint64_t brightPixels() const
    {
        return m_brightPixels;
    }

private:
    ramses::displayId_t m_displayId;
    ramses::sceneId_t m_sceneId;
    uint32_t m_width;
    uint32_t m_height;
    std::string m_screenshotPath;
    bool m_displayCreated = false;
    bool m_displayCreateFailed = false;
    ramses::RendererSceneState m_sceneState = ramses::RendererSceneState::Unavailable;
    bool m_pixelsRead = false;
    bool m_pixelsReadOk = false;
    bool m_screenshotSaved = false;
    uint64_t m_brightPixels = 0u;
    uint32_t m_minBrightX = UINT32_MAX;
    uint32_t m_minBrightY = UINT32_MAX;
    uint32_t m_maxBrightX = 0u;
    uint32_t m_maxBrightY = 0u;
};

bool pumpSdlEvents()
{
    SDL_Event event;
    while (SDL_PollEvent(&event))
    {
        if (event.type == SDL_EVENT_QUIT)
            return false;
        if (event.type == SDL_EVENT_WINDOW_CLOSE_REQUESTED)
            return false;
        if (event.type == SDL_EVENT_KEY_DOWN && event.key.key == SDLK_ESCAPE)
            return false;
    }
    return true;
}

void pumpRamsesEvents(ramses::RamsesRenderer& renderer, ramses::RendererSceneControl& sceneControl, RealSceneEventHandler& handler)
{
    renderer.dispatchEvents(handler);
    sceneControl.dispatchEvents(handler);
    renderer.flush();
    sceneControl.flush();
}

template <typename Predicate, typename Tick>
bool pumpUntil(ramses::RamsesRenderer& renderer,
               ramses::RendererSceneControl& sceneControl,
               RealSceneEventHandler& handler,
               Predicate predicate,
               Tick tick,
               std::chrono::milliseconds timeout)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (!predicate())
    {
        if (!pumpSdlEvents())
            return false;

        tick();
        renderer.doOneLoop();
        pumpRamsesEvents(renderer, sceneControl, handler);

        if (handler.displayCreateFailed() || std::chrono::steady_clock::now() >= deadline)
            return false;

        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    return true;
}

size_t countObjects(const ramses::Scene& scene, ramses::ERamsesObjectType objectType)
{
    size_t count = 0u;
    ramses::SceneObjectIterator iterator(scene, objectType);
    while (iterator.getNext())
        ++count;
    return count;
}

std::vector<ramses::Camera*> collectCameras(ramses::Scene& scene)
{
    std::vector<ramses::Camera*> cameras;
    ramses::SceneObjectIterator iterator(scene, ramses::ERamsesObjectType::Camera);
    while (auto* object = iterator.getNext())
    {
        if (auto* camera = object->as<ramses::Camera>())
            cameras.push_back(camera);
    }
    return cameras;
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

size_t countLogicObjects(const std::vector<ramses::LogicEngine*>& engines)
{
    size_t count = 0u;
    for (const auto* engine : engines)
        count += engine->getCollection<ramses::LogicObject>().size();
    return count;
}

bool updateLogicEngines(const std::vector<ramses::LogicEngine*>& engines)
{
    bool ok = true;
    for (auto* engine : engines)
        ok = engine->update() && ok;
    return ok;
}

bool isFinite(const ramses::vec3f& value)
{
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

float length(const ramses::vec3f& value)
{
    return std::sqrt(value.x * value.x + value.y * value.y + value.z * value.z);
}

struct SceneBounds
{
    bool valid = false;
    ramses::vec3f min{0.0f, 0.0f, 0.0f};
    ramses::vec3f max{0.0f, 0.0f, 0.0f};
    ramses::vec3f center{0.0f, 0.0f, 0.0f};
    float radius = 5.0f;
    size_t sampleCount = 0u;
};

SceneBounds estimateSceneBoundsFromMeshNodes(ramses::Scene& scene)
{
    SceneBounds bounds;
    bounds.min = {std::numeric_limits<float>::max(), std::numeric_limits<float>::max(), std::numeric_limits<float>::max()};
    bounds.max = {-std::numeric_limits<float>::max(), -std::numeric_limits<float>::max(), -std::numeric_limits<float>::max()};

    ramses::SceneObjectIterator iterator(scene, ramses::ERamsesObjectType::MeshNode);
    while (auto* object = iterator.getNext())
    {
        auto* mesh = object->as<ramses::MeshNode>();
        if (!mesh)
            continue;

        ramses::matrix44f modelMatrix{1.0f};
        if (!mesh->getModelMatrix(modelMatrix))
            continue;

        const ramses::vec3f point{modelMatrix[3].x, modelMatrix[3].y, modelMatrix[3].z};
        if (!isFinite(point))
            continue;

        bounds.min.x = std::min(bounds.min.x, point.x);
        bounds.min.y = std::min(bounds.min.y, point.y);
        bounds.min.z = std::min(bounds.min.z, point.z);
        bounds.max.x = std::max(bounds.max.x, point.x);
        bounds.max.y = std::max(bounds.max.y, point.y);
        bounds.max.z = std::max(bounds.max.z, point.z);
        ++bounds.sampleCount;
    }

    if (bounds.sampleCount == 0u)
        return bounds;

    bounds.valid = true;
    bounds.center = (bounds.min + bounds.max) * 0.5f;
    const ramses::vec3f extents = bounds.max - bounds.min;
    bounds.radius = std::max(1.0f, length(extents) * 0.5f);
    return bounds;
}

struct CameraRig
{
    ramses::vec3f center{0.0f, 0.0f, 0.0f};
    ramses::vec3f target{0.0f, 0.8f, 0.0f};
    float radius = 5.0f;
    float distance = 12.0f;
    float fov = 32.0f;
    float nearPlane = 0.05f;
    float farPlane = 100.0f;
};

CameraRig makeCameraRig(const SceneBounds& bounds, uint32_t width, uint32_t height, float zoom)
{
    const float safeZoom = std::max(0.2f, zoom);
    CameraRig rig;
    rig.center = bounds.valid ? bounds.center : ramses::vec3f{0.0f, 0.8f, 0.0f};
    if (bounds.valid)
    {
        const float height = std::max(0.1f, bounds.max.y - bounds.min.y);
        rig.target = {bounds.center.x, bounds.min.y + height * 0.35f, bounds.center.z};
    }
    else
    {
        rig.target = rig.center;
    }
    rig.radius = bounds.valid ? bounds.radius : 5.0f;
    rig.radius = std::max(1.0f, rig.radius * 1.05f);
    const float aspect = static_cast<float>(width) / static_cast<float>(height);
    const float verticalFovRadians = rig.fov * Pi / 180.0f;
    const float horizontalFovRadians = 2.0f * std::atan(std::tan(verticalFovRadians * 0.5f) * aspect);
    const float limitingFov = std::min(verticalFovRadians, horizontalFovRadians);
    rig.distance = (rig.radius / std::tan(limitingFov * 0.5f)) / safeZoom;
    rig.distance = std::max(rig.distance, rig.radius * 2.2f);
    rig.nearPlane = std::max(0.01f, rig.distance - rig.radius * 3.5f);
    rig.farPlane = rig.distance + rig.radius * 4.0f;
    return rig;
}

void pointCameraAt(ramses::Camera& camera, const ramses::vec3f& cameraPosition, const ramses::vec3f& target)
{
    const ramses::vec3f direction = glm::normalize(target - cameraPosition);
    camera.setTranslation(cameraPosition);
    camera.setRotation(glm::quatLookAtRH(direction, ramses::vec3f{0.0f, 1.0f, 0.0f}));
}

float viewPresetYawDeltaDegrees(const std::string& viewPreset)
{
    if (viewPreset == "front")
        return 0.0f;
    if (viewPreset == "rear")
        return 180.0f;
    if (viewPreset == "left")
        return -90.0f;
    if (viewPreset == "right")
        return 90.0f;
    return 35.0f;
}

void driveAuthoredCameras(const std::vector<ramses::Camera*>& cameras,
                          const CameraRig& rig,
                          uint32_t frame,
                          bool orbit,
                          const Options& options)
{
    ramses::vec3f target = rig.target;
    ramses::vec3f cameraPosition;
    const bool useQaPerspective = !options.qaPerspectiveName.empty();

    if (useQaPerspective)
    {
        const float yawDegrees = options.qaPerspectiveYaw + (orbit ? static_cast<float>(frame) * 0.35f : 0.0f);
        const float pitchRadians = options.qaPerspectivePitch * Pi / 180.0f;
        const float yawRadians = yawDegrees * Pi / 180.0f;
        const float distance = options.qaPerspectiveDistance / std::max(0.2f, options.zoom);
        target = rig.target + options.qaPerspectiveOrigin;
        const float groundDistance = distance * std::cos(pitchRadians);
        cameraPosition = {
            target.x + groundDistance * std::sin(yawRadians),
            target.y + distance * std::sin(pitchRadians),
            target.z + groundDistance * std::cos(yawRadians)};
    }
    else
    {
        const float yawDegrees = (orbit ? static_cast<float>(frame) * 0.35f : 0.0f) + viewPresetYawDeltaDegrees(options.viewPreset);
        const float yawRadians = yawDegrees * Pi / 180.0f;
        const float elevation = std::max(1.1f, rig.radius * 0.16f);
        cameraPosition = {
            rig.center.x + rig.distance * std::sin(yawRadians),
            rig.target.y + elevation,
            rig.center.z + rig.distance * std::cos(yawRadians)};
    }

    for (auto* camera : cameras)
    {
        if (camera)
        {
            pointCameraAt(*camera, cameraPosition, target);
        }
    }
}

std::string objectName(const ramses::RamsesObject* object)
{
    if (!object)
        return "<none>";
    const std::string name{object->getName()};
    return name.empty() ? "<unnamed>" : name;
}

struct CameraUse
{
    ramses::Camera* camera = nullptr;
    size_t uses = 0u;
    uint64_t viewportArea = 0u;
    bool perspective = false;
};

struct AuthoredRenderSetup
{
    ramses::RenderPass* finalFramebufferPass = nullptr;
    ramses::Camera* finalFramebufferCamera = nullptr;
    ramses::Camera* heroCamera = nullptr;
    ramses::Camera* primaryOffscreenCamera = nullptr;
    size_t totalPasses = 0u;
    size_t enabledPasses = 0u;
    size_t framebufferPasses = 0u;
    size_t enabledFramebufferPasses = 0u;
    size_t framebufferPassesWithCamera = 0u;
    size_t offscreenPassesWithCamera = 0u;
    size_t disabledPasses = 0u;
    size_t missingCameraPasses = 0u;
    size_t heroCameraUses = 0u;
    size_t primaryOffscreenCameraUses = 0u;
    int32_t finalRenderOrder = std::numeric_limits<int32_t>::min();
    uint32_t preferredWidth = 0u;
    uint32_t preferredHeight = 0u;
};

void addCameraUse(std::vector<CameraUse>& uses, ramses::Camera* camera)
{
    if (!camera)
        return;

    auto existing = std::find_if(uses.begin(), uses.end(), [&](const CameraUse& use) { return use.camera == camera; });
    if (existing != uses.end())
    {
        ++existing->uses;
        return;
    }

    uses.push_back({camera,
                    1u,
                    static_cast<uint64_t>(camera->getViewportWidth()) * static_cast<uint64_t>(camera->getViewportHeight()),
                    camera->as<ramses::PerspectiveCamera>() != nullptr});
}

bool isBetterCameraUse(const CameraUse& candidate, const CameraUse& current)
{
    const bool candidateScene = objectName(candidate.camera) == "Camera_Scene";
    const bool currentScene = objectName(current.camera) == "Camera_Scene";
    if (candidateScene != currentScene)
        return candidateScene;
    if (candidate.uses != current.uses)
        return candidate.uses > current.uses;
    if (candidate.perspective != current.perspective)
        return candidate.perspective;
    if (candidate.viewportArea != current.viewportArea)
        return candidate.viewportArea > current.viewportArea;
    return objectName(candidate.camera) < objectName(current.camera);
}

AuthoredRenderSetup inspectAuthoredRenderSetup(ramses::Scene& scene)
{
    AuthoredRenderSetup setup;
    std::vector<CameraUse> cameraUses;
    bool finalCandidateEnabled = false;

    ramses::SceneObjectIterator iterator(scene, ramses::ERamsesObjectType::RenderPass);
    while (auto* object = iterator.getNext())
    {
        auto* renderPass = object->as<ramses::RenderPass>();
        if (!renderPass)
            continue;

        ++setup.totalPasses;
        if (!renderPass->isEnabled())
            ++setup.disabledPasses;
        else
            ++setup.enabledPasses;

        auto* camera = renderPass->getCamera();
        if (!camera)
            ++setup.missingCameraPasses;

        if (!renderPass->getRenderTarget())
        {
            ++setup.framebufferPasses;
            if (renderPass->isEnabled())
                ++setup.enabledFramebufferPasses;
            if (camera)
                ++setup.framebufferPassesWithCamera;

            const bool candidateEnabled = renderPass->isEnabled();
            const bool betterCandidate =
                camera &&
                (!setup.finalFramebufferPass ||
                 (candidateEnabled && !finalCandidateEnabled) ||
                 (candidateEnabled == finalCandidateEnabled && renderPass->getRenderOrder() >= setup.finalRenderOrder));

            if (betterCandidate)
            {
                setup.finalFramebufferPass = renderPass;
                setup.finalFramebufferCamera = camera;
                setup.finalRenderOrder = renderPass->getRenderOrder();
                finalCandidateEnabled = candidateEnabled;
            }
        }
        else if (renderPass->isEnabled() && camera)
        {
            ++setup.offscreenPassesWithCamera;
            addCameraUse(cameraUses, camera);
        }
    }

    if (setup.finalFramebufferCamera)
    {
        setup.preferredWidth = setup.finalFramebufferCamera->getViewportWidth();
        setup.preferredHeight = setup.finalFramebufferCamera->getViewportHeight();
    }

    CameraUse bestOffscreenCamera;
    bool hasOffscreenCamera = false;
    if (!cameraUses.empty())
    {
        bestOffscreenCamera = cameraUses.front();
        hasOffscreenCamera = true;
        for (const auto& use : cameraUses)
        {
            if (isBetterCameraUse(use, bestOffscreenCamera))
                bestOffscreenCamera = use;
        }
    }

    if (hasOffscreenCamera)
    {
        setup.primaryOffscreenCamera = bestOffscreenCamera.camera;
        setup.primaryOffscreenCameraUses = bestOffscreenCamera.uses;
        setup.heroCamera = bestOffscreenCamera.camera;
        setup.heroCameraUses = bestOffscreenCamera.uses;
    }
    else if (setup.finalFramebufferCamera)
    {
        setup.heroCamera = setup.finalFramebufferCamera;
        setup.heroCameraUses = 1u;
    }

    return setup;
}

ramses::Camera* findCameraByName(const std::vector<ramses::Camera*>& cameras, const char* name)
{
    const auto found = std::find_if(cameras.begin(), cameras.end(), [&](const ramses::Camera* camera) {
        return camera && std::string(camera->getName()) == name;
    });
    return found == cameras.end() ? nullptr : *found;
}

void addUniqueCamera(std::vector<ramses::Camera*>& cameras, ramses::Camera* camera)
{
    if (!camera)
        return;
    if (std::find(cameras.begin(), cameras.end(), camera) == cameras.end())
        cameras.push_back(camera);
}

std::vector<ramses::Camera*> selectAuthoredViewCameras(const std::vector<ramses::Camera*>& cameras,
                                                       const AuthoredRenderSetup& setup)
{
    std::vector<ramses::Camera*> drivenCameras;
    addUniqueCamera(drivenCameras, findCameraByName(cameras, "Camera_Scene"));
    addUniqueCamera(drivenCameras, findCameraByName(cameras, "Camera_Scene_Wheels"));
    if (drivenCameras.empty())
        addUniqueCamera(drivenCameras, setup.primaryOffscreenCamera);
    if (drivenCameras.empty() && setup.heroCamera != setup.finalFramebufferCamera)
        addUniqueCamera(drivenCameras, setup.heroCamera);
    return drivenCameras;
}

std::string cameraListName(const std::vector<ramses::Camera*>& cameras)
{
    if (cameras.empty())
        return "<none>";

    std::string names;
    for (auto* camera : cameras)
    {
        if (!names.empty())
            names += "+";
        names += objectName(camera);
    }
    return names;
}

std::string lowerCopy(std::string value)
{
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

bool isViewControlName(std::string_view name)
{
    const std::string lower = lowerCopy(std::string{name});
    return lower.find("camera") != std::string::npos ||
           lower.find("crane") != std::string::npos ||
           lower.find("gimbal") != std::string::npos ||
           lower.find("scene") != std::string::npos ||
           lower.find("wheel") != std::string::npos ||
           lower.find("view") != std::string::npos ||
           lower.find("perspective") != std::string::npos ||
           lower.find("cid") != std::string::npos ||
           lower.find("phud") != std::string::npos ||
           lower.find("hud") != std::string::npos;
}

std::string propertyPathText(std::initializer_list<std::string_view> path)
{
    std::string text;
    for (std::string_view segment : path)
    {
        if (!text.empty())
            text += ".";
        text += segment;
    }
    return text;
}

ramses::Property* findPropertyPath(ramses::Property* root, std::initializer_list<std::string_view> path)
{
    auto* current = root;
    for (std::string_view segment : path)
    {
        if (!current)
            return nullptr;
        current = current->getChild(segment);
    }
    return current;
}

template <typename T>
bool setCameraCraneProperty(ramses::Property& root,
                            std::initializer_list<std::string_view> path,
                            T value,
                            std::string_view targetName,
                            bool logFailures)
{
    auto* property = findPropertyPath(&root, path);
    if (!property)
    {
        if (logFailures)
            std::cout << "Real viewer QA perspective logic missing property: " << targetName << "/"
                      << propertyPathText(path) << "\n";
        return false;
    }

    if (!property->set<T>(value))
    {
        if (logFailures)
            std::cout << "Real viewer QA perspective logic set failed: " << targetName << "/"
                      << propertyPathText(path) << "\n";
        return false;
    }

    return true;
}

bool driveCameraCraneRoot(ramses::Property& root,
                          uint32_t frame,
                          bool orbit,
                          const Options& options,
                          std::string_view targetName,
                          bool logFailures)
{
    const float yaw = options.qaPerspectiveYaw + (orbit ? static_cast<float>(frame) * 0.35f : 0.0f);
    bool ok = true;
    ok &= setCameraCraneProperty<bool>(root, {"AutoAspect"}, options.qaPerspectiveAspectFromResolution, targetName, logFailures);
    ok &= setCameraCraneProperty<float>(root, {"CraneGimbal", "Distance"},
                                        options.qaPerspectiveDistance / std::max(0.2f, options.zoom),
                                        targetName,
                                        logFailures);
    ok &= setCameraCraneProperty<float>(root, {"CraneGimbal", "Pitch"}, options.qaPerspectivePitch, targetName, logFailures);
    ok &= setCameraCraneProperty<float>(root, {"CraneGimbal", "Roll"}, options.qaPerspectiveRoll, targetName, logFailures);
    ok &= setCameraCraneProperty<float>(root, {"CraneGimbal", "Yaw"}, yaw, targetName, logFailures);
    ok &= setCameraCraneProperty<float>(root, {"Frustum", "AspectRatio"}, options.qaPerspectiveAspectRatio, targetName, logFailures);
    ok &= setCameraCraneProperty<float>(root, {"Frustum", "FarPlane"}, options.qaPerspectiveFarPlane, targetName, logFailures);
    ok &= setCameraCraneProperty<float>(root, {"Frustum", "HorizontalFOV"}, options.qaPerspectiveHorizontalFov, targetName, logFailures);
    ok &= setCameraCraneProperty<float>(root, {"Frustum", "NearPlane"}, options.qaPerspectiveNearPlane, targetName, logFailures);
    ok &= setCameraCraneProperty<float>(root, {"Scale"}, options.qaPerspectiveScale, targetName, logFailures);
    ok &= setCameraCraneProperty<ramses::vec2i>(root, {"ShiftXY"}, options.qaPerspectiveShift, targetName, logFailures);
    ok &= setCameraCraneProperty<ramses::vec3f>(root, {"Origin"}, options.qaPerspectiveOrigin, targetName, logFailures);
    ok &= setCameraCraneProperty<int32_t>(root, {"Viewport", "Height"},
                                          static_cast<int32_t>(options.qaPerspectiveViewportHeight),
                                          targetName,
                                          logFailures);
    ok &= setCameraCraneProperty<int32_t>(root, {"Viewport", "OffsetX"},
                                          options.qaPerspectiveViewportOffsetX,
                                          targetName,
                                          logFailures);
    ok &= setCameraCraneProperty<int32_t>(root, {"Viewport", "OffsetY"},
                                          options.qaPerspectiveViewportOffsetY,
                                          targetName,
                                          logFailures);
    ok &= setCameraCraneProperty<int32_t>(root, {"Viewport", "Width"},
                                          static_cast<int32_t>(options.qaPerspectiveViewportWidth),
                                          targetName,
                                          logFailures);
    return ok;
}

ramses::Property* findCameraCraneRoot(ramses::LogicNode& node)
{
    auto* inputs = node.getInputs();
    if (!inputs)
        return nullptr;

    if (auto* interfaceInput = inputs->getChild("Interface_CameraCrane"))
        return interfaceInput;
    if (inputs->hasChild("CraneGimbal") && inputs->hasChild("Frustum") && inputs->hasChild("Viewport"))
        return inputs;
    return nullptr;
}

size_t driveQaPerspectiveLogic(const std::vector<ramses::LogicEngine*>& engines,
                               uint32_t frame,
                               bool orbit,
                               const Options& options,
                               bool logTargets)
{
    size_t candidates = 0u;
    size_t driven = 0u;

    auto tryNode = [&](ramses::LogicNode& node, std::string_view kind) {
        auto* cameraCraneRoot = findCameraCraneRoot(node);
        if (!cameraCraneRoot)
            return;

        ++candidates;
        const std::string targetName = std::string(kind) + " " + objectName(&node);
        if (logTargets)
            std::cout << "Real viewer QA perspective logic target: " << targetName << "\n";
        if (driveCameraCraneRoot(*cameraCraneRoot, frame, orbit, options, targetName, logTargets))
            ++driven;
    };

    for (auto* engine : engines)
    {
        for (auto* luaInterface : engine->getCollection<ramses::LuaInterface>())
            tryNode(*luaInterface, "LuaInterface");
    }

    if (driven == 0u)
    {
        for (auto* engine : engines)
        {
            for (auto* luaScript : engine->getCollection<ramses::LuaScript>())
                tryNode(*luaScript, "LuaScript");
        }
    }

    if (logTargets)
        std::cout << "Real viewer QA perspective logic camera-crane driven/candidates: " << driven << "/" << candidates << "\n";
    return driven;
}

void logViewControlBindings(const std::vector<ramses::LogicEngine*>& engines)
{
    size_t nodeBindingCount = 0u;
    size_t cameraBindingCount = 0u;
    size_t printedNodeBindings = 0u;
    size_t printedCameraBindings = 0u;

    for (const auto* engine : engines)
    {
        const auto nodeBindings = engine->getCollection<ramses::NodeBinding>();
        nodeBindingCount += nodeBindings.size();
        for (const auto* binding : nodeBindings)
        {
            const std::string bindingName = objectName(binding);
            const ramses::Node& node = binding->getRamsesNode();
            const std::string nodeName = objectName(&node);
            if (printedNodeBindings < 48u && (isViewControlName(bindingName) || isViewControlName(nodeName)))
            {
                std::cout << "Real viewer logic node binding: " << bindingName << " -> " << nodeName << "\n";
                ++printedNodeBindings;
            }
        }

        const auto cameraBindings = engine->getCollection<ramses::CameraBinding>();
        cameraBindingCount += cameraBindings.size();
        for (const auto* binding : cameraBindings)
        {
            const std::string bindingName = objectName(binding);
            const ramses::Camera& camera = binding->getRamsesCamera();
            const std::string cameraName = objectName(&camera);
            if (printedCameraBindings < 48u && (isViewControlName(bindingName) || isViewControlName(cameraName)))
            {
                std::cout << "Real viewer logic camera binding: " << bindingName << " -> " << cameraName << "\n";
                ++printedCameraBindings;
            }
        }
    }

    std::cout << "Real viewer logic binding counts node/camera/view-node/view-camera-printed: "
              << nodeBindingCount << "/" << cameraBindingCount << "/"
              << printedNodeBindings << "/" << printedCameraBindings << "\n";
}

void logAuthoredRenderPasses(ramses::Scene& scene)
{
    ramses::SceneObjectIterator iterator(scene, ramses::ERamsesObjectType::RenderPass);
    while (auto* object = iterator.getNext())
    {
        auto* renderPass = object->as<ramses::RenderPass>();
        if (!renderPass)
            continue;

        auto* camera = renderPass->getCamera();
        std::cout << "Real viewer render pass order/enabled/target/camera/viewport/name: "
                  << renderPass->getRenderOrder() << "/"
                  << (renderPass->isEnabled() ? "on" : "off") << "/"
                  << objectName(renderPass->getRenderTarget()) << "/"
                  << objectName(camera) << "/";
        if (camera)
            std::cout << camera->getViewportWidth() << "x" << camera->getViewportHeight();
        else
            std::cout << "0x0";
        std::cout << "/" << objectName(renderPass) << "\n";
    }
}

struct DisplayDimensions
{
    uint32_t width = 1280u;
    uint32_t height = 720u;
    bool fromScene = false;
};

DisplayDimensions chooseDisplayDimensions(const Options& options, const AuthoredRenderSetup& setup)
{
    DisplayDimensions dimensions;
    if (setup.preferredWidth > 0u && setup.preferredHeight > 0u)
    {
        dimensions.width = setup.preferredWidth;
        dimensions.height = setup.preferredHeight;
        dimensions.fromScene = true;
    }

    if (options.width > 0u)
    {
        dimensions.width = options.width;
        dimensions.fromScene = false;
    }
    if (options.height > 0u)
    {
        dimensions.height = options.height;
        dimensions.fromScene = false;
    }
    return dimensions;
}
}

int main(int argc, char** argv)
{
    try
    {
        const Options options = parseOptions(argc, argv);
        const auto linkedVersion = ramses::GetRamsesVersion();
        const std::optional<ramses::SceneMetadata> metadata = ramses::RamsesClient::GetMetadataFromFile(options.sceneFile);
        if (!metadata)
            throw std::runtime_error("Could not read Ramses metadata from scene file");

        SdlGuard sdl;

        std::cout << "C-3 linked Ramses version: " << linkedVersion.string << "\n";
        if (!options.profileId.empty())
            std::cout << "Real viewer profile id: " << options.profileId << "\n";
        std::cout << "C-3 scene file: " << options.sceneFile << "\n";
        std::cout << "C-3 scene metadata Ramses version: " << versionString(metadata->ramsesVersion) << "\n";
        std::cout << "C-3 scene metadata exporter version: " << versionString(metadata->exporterVersion) << "\n";
        std::cout << "C-3 scene metadata feature level: " << static_cast<unsigned>(metadata->featureLevel) << "\n";
        std::cout << "Real viewer presentation mode: authored-passes\n";
        std::cout << "Real viewer auto-frame/orbit/zoom: " << (options.autoFrame ? "on" : "off") << "/"
                  << (options.orbit ? "on" : "off") << "/" << options.zoom << "\n";
        std::cout << "Real viewer view preset: " << options.viewPreset << "\n";
        if (!options.qaPerspectiveName.empty())
        {
            std::cout << "Real viewer QA perspective: " << options.qaPerspectiveName
                      << " distance/yaw/pitch/hfov/aspect/near/far "
                      << options.qaPerspectiveDistance << "/"
                      << options.qaPerspectiveYaw << "/"
                      << options.qaPerspectivePitch << "/"
                      << options.qaPerspectiveHorizontalFov << "/"
                      << options.qaPerspectiveAspectRatio << "/"
                      << options.qaPerspectiveNearPlane << "/"
                      << options.qaPerspectiveFarPlane << "\n";
            std::cout << "Real viewer QA perspective origin/shift/viewport: "
                      << options.qaPerspectiveOrigin.x << "," << options.qaPerspectiveOrigin.y << "," << options.qaPerspectiveOrigin.z << "/"
                      << options.qaPerspectiveShift.x << "," << options.qaPerspectiveShift.y << "/"
                      << options.qaPerspectiveViewportWidth << "x" << options.qaPerspectiveViewportHeight << "@"
                      << options.qaPerspectiveViewportOffsetX << "," << options.qaPerspectiveViewportOffsetY
                      << " scale/autoAspect " << options.qaPerspectiveScale << "/"
                      << (options.qaPerspectiveAspectFromResolution ? "true" : "false") << "\n";
        }

        ramses::RamsesFrameworkConfig frameworkConfig{metadata->featureLevel};
        frameworkConfig.setRequestedRamsesShellType(ramses::ERamsesShellType::Console);
        frameworkConfig.setPeriodicLogInterval(std::chrono::seconds(1));
        ramses::RamsesFramework framework(frameworkConfig);
        auto& client = *framework.createClient("sgfx-cine-c3-client");

        ramses::RendererConfig rendererConfig;
        rendererConfig.setRenderThreadLoopTimingReportingPeriod(std::chrono::milliseconds(500));
        auto& renderer = *framework.createRenderer(rendererConfig);
        auto& sceneControl = *renderer.getSceneControlAPI();

        framework.connect();

        ramses::SceneConfig sceneConfig{ramses::sceneId_t{65u}, ramses::EScenePublicationMode::LocalOnly, ramses::ERenderBackendCompatibility::OpenGL};
        auto* scene = client.loadSceneFromFile(options.sceneFile, sceneConfig);
        if (!scene)
        {
            if (auto issue = framework.getLastError())
                std::cerr << "Ramses last error: " << issue->message << "\n";
            throw std::runtime_error("loadSceneFromFile returned null");
        }

        const ramses::sceneId_t sceneId = scene->getSceneId();
        std::cout << "C-3 loaded scene id: " << sceneId.getValue() << "\n";
        std::cout << "C-3 object counts nodes/meshes/cameras/renderPasses/renderGroups: "
                  << countObjects(*scene, ramses::ERamsesObjectType::Node) << "/"
                  << countObjects(*scene, ramses::ERamsesObjectType::MeshNode) << "/"
                  << countObjects(*scene, ramses::ERamsesObjectType::Camera) << "/"
                  << countObjects(*scene, ramses::ERamsesObjectType::RenderPass) << "/"
                  << countObjects(*scene, ramses::ERamsesObjectType::RenderGroup) << "\n";
        std::cout << "Real viewer object counts logicEngines/blitPasses/renderBuffers/renderTargets: "
                  << countObjects(*scene, ramses::ERamsesObjectType::LogicEngine) << "/"
                  << countObjects(*scene, ramses::ERamsesObjectType::BlitPass) << "/"
                  << countObjects(*scene, ramses::ERamsesObjectType::RenderBuffer) << "/"
                  << countObjects(*scene, ramses::ERamsesObjectType::RenderTarget) << "\n";

        auto cameras = collectCameras(*scene);
        auto logicEngines = collectLogicEngines(*scene);
        const AuthoredRenderSetup renderSetup = inspectAuthoredRenderSetup(*scene);
        const std::vector<ramses::Camera*> viewControlCameras = selectAuthoredViewCameras(cameras, renderSetup);
        const bool viewControlEnabled = options.autoFrame || !options.qaPerspectiveName.empty();
        const DisplayDimensions displayDimensions = chooseDisplayDimensions(options, renderSetup);
        const SceneBounds sceneBounds = estimateSceneBoundsFromMeshNodes(*scene);
        const CameraRig cameraRig = makeCameraRig(sceneBounds, displayDimensions.width, displayDimensions.height, options.zoom);

        std::cout << "C-3 cameras: " << cameras.size() << "\n";
        std::cout << "Real viewer logic engines/logic objects: " << logicEngines.size() << "/" << countLogicObjects(logicEngines) << "\n";
        std::cout << "Real viewer authored render passes total/enabled/framebuffer/enabledFramebuffer/withFramebufferCamera/offscreenWithCamera/disabled/missingCamera: "
                  << renderSetup.totalPasses << "/"
                  << renderSetup.enabledPasses << "/"
                  << renderSetup.framebufferPasses << "/"
                  << renderSetup.enabledFramebufferPasses << "/"
                  << renderSetup.framebufferPassesWithCamera << "/"
                  << renderSetup.offscreenPassesWithCamera << "/"
                  << renderSetup.disabledPasses << "/"
                  << renderSetup.missingCameraPasses << "\n";
        std::cout << "Real viewer final framebuffer pass/camera/order/viewport: "
                  << objectName(renderSetup.finalFramebufferPass) << "/"
                  << objectName(renderSetup.finalFramebufferCamera) << "/"
                  << renderSetup.finalRenderOrder << "/"
                  << renderSetup.preferredWidth << "x" << renderSetup.preferredHeight << "\n";
        std::cout << "Real viewer authored hero camera/uses: " << objectName(renderSetup.heroCamera) << "/" << renderSetup.heroCameraUses << "\n";
        std::cout << "Real viewer primary offscreen camera/uses: "
                  << objectName(renderSetup.primaryOffscreenCamera) << "/" << renderSetup.primaryOffscreenCameraUses << "\n";
        std::cout << "Real viewer authored view-control cameras: " << cameraListName(viewControlCameras) << "\n";
        std::cout << "Real viewer authored view-control target: "
                  << cameraRig.target.x << "," << cameraRig.target.y << "," << cameraRig.target.z << "\n";
        logViewControlBindings(logicEngines);
        logAuthoredRenderPasses(*scene);
        std::cout << "Real viewer estimated bounds samples/min/max/center/radius: "
                  << sceneBounds.sampleCount << "/"
                  << sceneBounds.min.x << "," << sceneBounds.min.y << "," << sceneBounds.min.z << "/"
                  << sceneBounds.max.x << "," << sceneBounds.max.y << "," << sceneBounds.max.z << "/"
                  << sceneBounds.center.x << "," << sceneBounds.center.y << "," << sceneBounds.center.z << "/"
                  << sceneBounds.radius << "\n";
        std::cout << "Real viewer camera distance/near/far/fov: "
                  << cameraRig.distance << "/" << cameraRig.nearPlane << "/" << cameraRig.farPlane << "/" << cameraRig.fov << "\n";

        if (!renderSetup.finalFramebufferPass || !renderSetup.finalFramebufferCamera)
            throw std::runtime_error("Scene has no authored framebuffer render pass with a camera");
        if (viewControlEnabled && viewControlCameras.empty())
            throw std::runtime_error("Auto-frame requested but no authored view-control cameras were found");

        SdlWindow window("SGFX Cine Real Ramses Scene", displayDimensions.width, displayDimensions.height);
        void* hwnd = getWin32Hwnd(window.get());
        std::cout << "C-3 SDL3 window created: " << displayDimensions.width << "x" << displayDimensions.height
                  << (displayDimensions.fromScene ? " (scene framebuffer pass)" : " (explicit/fallback)") << "\n";
        std::cout << "C-3 SDL3 Win32 HWND: " << hwnd << "\n";

        ramses::DisplayConfig displayConfig;
        displayConfig.setWindowType(ramses::EWindowType::Windows);
        displayConfig.setWindowsWindowHandle(hwnd);
        displayConfig.setWindowRectangle(0, 0, displayDimensions.width, displayDimensions.height);
        displayConfig.setWindowTitle("SGFX Cine Real Ramses Scene");

        const ramses::displayId_t display = renderer.createDisplay(displayConfig);
        if (!display.isValid())
            throw std::runtime_error("Ramses createDisplay returned an invalid display id");
        renderer.setSkippingOfUnmodifiedBuffers(false);
        const ramses::displayBufferId_t displayFramebuffer = renderer.getDisplayFramebuffer(display);
        renderer.setDisplayBufferClearColor(display, displayFramebuffer, ramses::vec4f{0.02f, 0.03f, 0.05f, 1.0f});
        renderer.flush();

        RealSceneEventHandler handler(display, sceneId, displayDimensions.width, displayDimensions.height, options.screenshotPath);
        if (!pumpUntil(renderer, sceneControl, handler, [&] { return handler.displayCreated(); }, [] {}, std::chrono::seconds(5)))
            throw std::runtime_error("Timed out waiting for Ramses display creation");

        bool qaLogicLogged = false;
        auto updateLogicAndViewControl = [&](uint32_t frame, bool orbit, const char* context) {
            bool qaPerspectiveLogicDriven = false;
            if (!options.qaPerspectiveName.empty())
            {
                qaPerspectiveLogicDriven =
                    driveQaPerspectiveLogic(logicEngines, frame, orbit, options, !qaLogicLogged) > 0u;
                qaLogicLogged = true;
            }

            if (!updateLogicEngines(logicEngines))
                throw std::runtime_error(std::string("LogicEngine update failed ") + context);
            if (viewControlEnabled && !qaPerspectiveLogicDriven)
                driveAuthoredCameras(viewControlCameras, cameraRig, frame, orbit, options);
        };

        updateLogicAndViewControl(0u, false, "before scene publish");
        scene->publish(ramses::EScenePublicationMode::LocalOnly);
        scene->flush();

        if (!sceneControl.setSceneMapping(sceneId, display))
            throw std::runtime_error("Ramses setSceneMapping failed");
        if (!sceneControl.setSceneDisplayBufferAssignment(sceneId, displayFramebuffer, 0))
            throw std::runtime_error("Ramses setSceneDisplayBufferAssignment failed");
        if (!sceneControl.setSceneState(sceneId, ramses::RendererSceneState::Rendered))
            throw std::runtime_error("Ramses setSceneState(Rendered) failed");
        sceneControl.flush();

        if (!pumpUntil(renderer, sceneControl, handler, [&] { return handler.sceneRendered(); }, [&] {
                updateLogicAndViewControl(0u, false, "while waiting for Rendered");
                scene->flush();
            }, std::chrono::seconds(10)))
            throw std::runtime_error("Timed out waiting for Ramses scene to reach Rendered");

        uint32_t renderedFrames = 0u;
        while (renderedFrames < options.frames)
        {
            if (!pumpSdlEvents())
                break;

            updateLogicAndViewControl(renderedFrames, options.orbit, "during render loop");
            scene->flush();

            renderer.doOneLoop();
            pumpRamsesEvents(renderer, sceneControl, handler);
            ++renderedFrames;
        }

        if (options.readback)
        {
            renderer.readPixels(display, displayFramebuffer, 0u, 0u, displayDimensions.width, displayDimensions.height);
            renderer.flush();
            if (!pumpUntil(renderer, sceneControl, handler, [&] { return handler.pixelsRead(); }, [&] {
                    updateLogicAndViewControl(renderedFrames, options.orbit, "while waiting for readback");
                    scene->flush();
                }, std::chrono::seconds(5)))
                throw std::runtime_error("Timed out waiting for Ramses framebuffer readback");
            if (!handler.pixelsReadOk() || handler.brightPixels() == 0u)
                throw std::runtime_error("Ramses framebuffer readback did not contain visible scene pixels");
        }

        renderer.logRendererInfo();
        renderer.flush();
        renderer.doOneLoop();
        pumpRamsesEvents(renderer, sceneControl, handler);

        std::cout << "C-3 frames rendered: " << renderedFrames << "\n";
        std::cout << "C-3 real Ramses scene load/render OK\n";
        return 0;
    }
    catch (const std::exception& ex)
    {
        std::cerr << "C-3 real Ramses scene failed: " << ex.what() << "\n";
        return 1;
    }
}
