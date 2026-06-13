#include "ramses/client/Camera.h"
#include "ramses/client/MeshNode.h"
#include "ramses/client/PerspectiveCamera.h"
#include "ramses/client/RenderPass.h"
#include "ramses/client/RenderTarget.h"
#include "ramses/client/Scene.h"
#include "ramses/client/SceneConfig.h"
#include "ramses/client/SceneMetadata.h"
#include "ramses/client/SceneObjectIterator.h"
#include "ramses/client/logic/LogicEngine.h"
#include "ramses/client/logic/LogicObject.h"
#include "ramses/client/ramses-client.h"
#include "ramses/framework/RamsesFramework.h"
#include "ramses/framework/RamsesFrameworkConfig.h"
#include "ramses/framework/RamsesVersion.h"
#include "ramses/framework/VersionInfo.h"
#include "ramses/renderer/DisplayConfig.h"
#include "ramses/renderer/IRendererEventHandler.h"
#include "ramses/renderer/IRendererSceneControlEventHandler.h"
#include "ramses/renderer/RamsesRenderer.h"
#include "ramses/renderer/RendererConfig.h"
#include "ramses/renderer/RendererSceneControl.h"

#include <SDL3/SDL.h>
#include <SDL3/SDL_opengl.h>

#include <glm/gtc/quaternion.hpp>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <limits>
#include <cmath>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace
{
constexpr float Pi = 3.14159265358979323846f;

struct Options
{
    uint32_t width = 1280u;
    uint32_t height = 720u;
    uint32_t producerWidth = 0u;
    uint32_t producerHeight = 0u;
    uint32_t frames = 120u;
    bool autoFrame = true;
    bool orbit = false;
    float zoom = 1.0f;
    std::string viewPreset = "three-quarter";
    std::string profileId = "G65";
    std::string sceneFile;
    std::string screenshotPath = "sgfx-ramses-shell-fusion-phase1.bmp";
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

Options parseOptions(int argc, char** argv)
{
    Options options;
    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];
        auto takeValue = [&](const char* name) -> const char* {
            if (i + 1 >= argc)
                throw std::runtime_error(std::string("Missing value for ") + name);
            return argv[++i];
        };

        if (arg == "--width")
            options.width = parseUint(takeValue("--width"), "--width");
        else if (arg == "--height")
            options.height = parseUint(takeValue("--height"), "--height");
        else if (arg == "--producer-width")
            options.producerWidth = parseUint(takeValue("--producer-width"), "--producer-width");
        else if (arg == "--producer-height")
            options.producerHeight = parseUint(takeValue("--producer-height"), "--producer-height");
        else if (arg == "--frames")
            options.frames = parseUint(takeValue("--frames"), "--frames");
        else if (arg == "--auto-frame")
            options.autoFrame = true;
        else if (arg == "--no-auto-frame")
            options.autoFrame = false;
        else if (arg == "--orbit")
            options.orbit = true;
        else if (arg == "--no-orbit")
            options.orbit = false;
        else if (arg == "--zoom")
            options.zoom = parseFloat(takeValue("--zoom"), "--zoom");
        else if (arg == "--view-preset")
            options.viewPreset = takeValue("--view-preset");
        else if (arg == "--profile-id")
            options.profileId = takeValue("--profile-id");
        else if (arg == "--scene-file")
            options.sceneFile = takeValue("--scene-file");
        else if (arg == "--screenshot")
            options.screenshotPath = takeValue("--screenshot");
        else
            throw std::runtime_error("Unknown argument: " + arg);
    }

    if (options.sceneFile.empty())
        throw std::runtime_error("--scene-file is required");
    if (!std::filesystem::is_regular_file(options.sceneFile))
        throw std::runtime_error("Scene file does not exist: " + options.sceneFile);
    return options;
}

const char* sceneStateName(ramses::RendererSceneState state)
{
    switch (state)
    {
    case ramses::RendererSceneState::Unavailable: return "Unavailable";
    case ramses::RendererSceneState::Available: return "Available";
    case ramses::RendererSceneState::Ready: return "Ready";
    case ramses::RendererSceneState::Rendered: return "Rendered";
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

class SdlPlainWindow
{
public:
    SdlPlainWindow(const char* title, uint32_t width, uint32_t height, SDL_WindowFlags flags)
        : m_window(SDL_CreateWindow(title, static_cast<int>(width), static_cast<int>(height), flags))
    {
        if (!m_window)
            throw std::runtime_error(std::string("SDL_CreateWindow failed: ") + SDL_GetError());
    }

    ~SdlPlainWindow()
    {
        if (m_window)
            SDL_DestroyWindow(m_window);
    }

    SDL_Window* get() const
    {
        return m_window;
    }

private:
    SDL_Window* m_window = nullptr;
};

class SdlGlWindow
{
public:
    SdlGlWindow(const char* title, uint32_t width, uint32_t height)
        : m_width(width)
        , m_height(height)
    {
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 3);
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE);
        SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);

        m_window = SDL_CreateWindow(title, static_cast<int>(width), static_cast<int>(height), SDL_WINDOW_OPENGL);
        if (!m_window)
            throw std::runtime_error(std::string("SDL_CreateWindow(GL) failed: ") + SDL_GetError());

        m_context = SDL_GL_CreateContext(m_window);
        if (!m_context)
            throw std::runtime_error(std::string("SDL_GL_CreateContext failed: ") + SDL_GetError());
        makeCurrent();
        SDL_GL_SetSwapInterval(0);
    }

    ~SdlGlWindow()
    {
        if (m_context)
            SDL_GL_DestroyContext(m_context);
        if (m_window)
            SDL_DestroyWindow(m_window);
    }

    void makeCurrent() const
    {
        if (!SDL_GL_MakeCurrent(m_window, m_context))
            throw std::runtime_error(std::string("SDL_GL_MakeCurrent failed: ") + SDL_GetError());
    }

    void swap() const
    {
        SDL_GL_SwapWindow(m_window);
    }

    uint32_t width() const { return m_width; }
    uint32_t height() const { return m_height; }
    SDL_Window* get() const { return m_window; }
    SDL_GLContext context() const { return m_context; }

private:
    SDL_Window* m_window = nullptr;
    SDL_GLContext m_context = nullptr;
    uint32_t m_width = 0u;
    uint32_t m_height = 0u;
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
    throw std::runtime_error("Fusion Phase 1 currently requires the SDL3 Win32 backend");
#endif
}

struct ReadbackStats
{
    uint32_t width = 0u;
    uint32_t height = 0u;
    uint64_t brightPixels = 0u;
    uint32_t minX = UINT32_MAX;
    uint32_t minY = UINT32_MAX;
    uint32_t maxX = 0u;
    uint32_t maxY = 0u;
};

ReadbackStats calculateBrightPixels(const std::vector<uint8_t>& pixels, uint32_t width, uint32_t height)
{
    ReadbackStats stats;
    stats.width = width;
    stats.height = height;

    uint32_t x = 0u;
    uint32_t y = 0u;
    for (size_t i = 0; i + 3u < pixels.size(); i += 4u)
    {
        const uint32_t brightness = static_cast<uint32_t>(pixels[i]) + static_cast<uint32_t>(pixels[i + 1u]) + static_cast<uint32_t>(pixels[i + 2u]);
        if (brightness > 80u)
        {
            ++stats.brightPixels;
            stats.minX = std::min(stats.minX, x);
            stats.minY = std::min(stats.minY, y);
            stats.maxX = std::max(stats.maxX, x);
            stats.maxY = std::max(stats.maxY, y);
        }

        ++x;
        if (x == width)
        {
            x = 0u;
            ++y;
        }
    }

    if (stats.brightPixels == 0u)
    {
        stats.minX = 0u;
        stats.minY = 0u;
    }
    return stats;
}

class FusionEventHandler : public ramses::RendererEventHandlerEmpty, public ramses::RendererSceneControlEventHandlerEmpty
{
public:
    FusionEventHandler(ramses::displayId_t displayId, ramses::sceneId_t sceneId, uint32_t width, uint32_t height)
        : m_displayId(displayId)
        , m_sceneId(sceneId)
        , m_width(width)
        , m_height(height)
    {
    }

    void displayCreated(ramses::displayId_t displayId, ramses::ERendererEventResult result) override
    {
        if (displayId != m_displayId)
            return;

        m_displayCreated = result == ramses::ERendererEventResult::Ok;
        m_displayCreateFailed = result == ramses::ERendererEventResult::Failed;
        std::cout << "Fusion Phase 1 Ramses displayCreated result: " << (m_displayCreated ? "Ok" : "Failed") << "\n";
    }

    void offscreenBufferCreated(ramses::displayId_t displayId,
                                ramses::displayBufferId_t offscreenBufferId,
                                ramses::ERendererEventResult result) override
    {
        if (displayId != m_displayId)
            return;

        m_offscreenCreated = result == ramses::ERendererEventResult::Ok && offscreenBufferId == m_offscreenBuffer;
        m_offscreenCreateFailed = result == ramses::ERendererEventResult::Failed;
        std::cout << "Fusion Phase 1 Ramses offscreenBufferCreated result: " << (m_offscreenCreated ? "Ok" : "Failed") << "\n";
    }

    void sceneStateChanged(ramses::sceneId_t sceneId, ramses::RendererSceneState state) override
    {
        if (sceneId != m_sceneId)
            return;

        m_sceneState = state;
        std::cout << "Fusion Phase 1 Ramses scene state: " << sceneStateName(state) << "\n";
    }

    void framebufferPixelsRead(const uint8_t* pixelData,
                               const uint32_t pixelDataSize,
                               ramses::displayId_t displayId,
                               ramses::displayBufferId_t displayBuffer,
                               ramses::ERendererEventResult result) override
    {
        if (displayId != m_displayId || displayBuffer != m_offscreenBuffer)
            return;

        m_pixelsRead = true;
        m_pixelsReadOk = result == ramses::ERendererEventResult::Ok && pixelData && pixelDataSize == m_width * m_height * 4u;
        if (!m_pixelsReadOk)
        {
            std::cout << "Fusion Phase 1 Ramses readPixels: Failed\n";
            return;
        }

        m_pixels.assign(pixelData, pixelData + pixelDataSize);
        m_ramsesStats = calculateBrightPixels(m_pixels, m_width, m_height);
        std::cout << "Fusion Phase 1 Ramses readPixels bright pixels: " << m_ramsesStats.brightPixels << "\n";
        std::cout << "Fusion Phase 1 Ramses readPixels bright bounds x/y: "
                  << m_ramsesStats.minX << "-" << m_ramsesStats.maxX << "/"
                  << m_ramsesStats.minY << "-" << m_ramsesStats.maxY << "\n";
    }

    void setOffscreenBuffer(ramses::displayBufferId_t offscreenBuffer)
    {
        m_offscreenBuffer = offscreenBuffer;
    }

    void resetPixelsRead()
    {
        m_pixelsRead = false;
        m_pixelsReadOk = false;
        m_pixels.clear();
    }

    bool displayCreated() const { return m_displayCreated; }
    bool displayCreateFailed() const { return m_displayCreateFailed; }
    bool offscreenCreated() const { return m_offscreenCreated; }
    bool offscreenCreateFailed() const { return m_offscreenCreateFailed; }
    bool sceneRendered() const { return m_sceneState == ramses::RendererSceneState::Rendered; }
    bool pixelsRead() const { return m_pixelsRead; }
    bool pixelsReadOk() const { return m_pixelsReadOk; }
    const std::vector<uint8_t>& pixels() const { return m_pixels; }
    const ReadbackStats& ramsesStats() const { return m_ramsesStats; }

private:
    ramses::displayId_t m_displayId;
    ramses::sceneId_t m_sceneId;
    ramses::displayBufferId_t m_offscreenBuffer = ramses::displayBufferId_t::Invalid();
    uint32_t m_width = 0u;
    uint32_t m_height = 0u;
    bool m_displayCreated = false;
    bool m_displayCreateFailed = false;
    bool m_offscreenCreated = false;
    bool m_offscreenCreateFailed = false;
    ramses::RendererSceneState m_sceneState = ramses::RendererSceneState::Unavailable;
    bool m_pixelsRead = false;
    bool m_pixelsReadOk = false;
    std::vector<uint8_t> m_pixels;
    ReadbackStats m_ramsesStats;
};

bool pumpSdlEvents()
{
    SDL_Event event;
    while (SDL_PollEvent(&event))
    {
        if (event.type == SDL_EVENT_QUIT || event.type == SDL_EVENT_WINDOW_CLOSE_REQUESTED)
            return false;
        if (event.type == SDL_EVENT_KEY_DOWN && event.key.key == SDLK_ESCAPE)
            return false;
    }
    return true;
}

void pumpRamsesEvents(ramses::RamsesRenderer& renderer, ramses::RendererSceneControl& sceneControl, FusionEventHandler& handler)
{
    renderer.dispatchEvents(handler);
    sceneControl.dispatchEvents(handler);
    renderer.flush();
    sceneControl.flush();
}

template <typename Predicate, typename Tick>
bool pumpUntil(ramses::RamsesRenderer& renderer,
               ramses::RendererSceneControl& sceneControl,
               FusionEventHandler& handler,
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

        if (handler.displayCreateFailed() || handler.offscreenCreateFailed() || std::chrono::steady_clock::now() >= deadline)
            return false;

        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    return true;
}

std::string objectName(const ramses::RamsesObject* object)
{
    if (!object)
        return "<none>";
    const std::string name{object->getName()};
    return name.empty() ? "<unnamed>" : name;
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
        const float objectHeight = std::max(0.1f, bounds.max.y - bounds.min.y);
        rig.target = {bounds.center.x, bounds.min.y + objectHeight * 0.35f, bounds.center.z};
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
    const float yawDegrees = (orbit ? static_cast<float>(frame) * 0.35f : 0.0f) + viewPresetYawDeltaDegrees(options.viewPreset);
    const float yawRadians = yawDegrees * Pi / 180.0f;
    const float elevation = std::max(1.1f, rig.radius * 0.16f);
    const ramses::vec3f cameraPosition = {
        rig.center.x + rig.distance * std::sin(yawRadians),
        rig.target.y + elevation,
        rig.center.z + rig.distance * std::cos(yawRadians)};

    for (auto* camera : cameras)
    {
        if (camera)
            pointCameraAt(*camera, cameraPosition, rig.target);
    }
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

template <typename Proc>
Proc loadGlProc(const char* name)
{
    SDL_FunctionPointer proc = SDL_GL_GetProcAddress(name);
    if (!proc)
        throw std::runtime_error(std::string("SDL_GL_GetProcAddress failed for ") + name);
    return reinterpret_cast<Proc>(proc);
}

void throwOnGlError(const char* stage)
{
    const GLenum error = glGetError();
    if (error != GL_NO_ERROR)
        throw std::runtime_error(std::string("Fusion Phase 1 GL error after ") + stage + ": " + std::to_string(error));
}

class GlQuadRenderer
{
public:
    GlQuadRenderer(uint32_t textureWidth, uint32_t textureHeight)
        : m_textureWidth(textureWidth)
        , m_textureHeight(textureHeight)
    {
        load();
        createProgram();
        createGeometry();
        createTexture();
    }

    ~GlQuadRenderer()
    {
        if (m_deleteTextures && m_texture)
            m_deleteTextures(1, &m_texture);
        if (m_deleteBuffers && m_vbo)
            m_deleteBuffers(1, &m_vbo);
        if (m_deleteVertexArrays && m_vao)
            m_deleteVertexArrays(1, &m_vao);
        if (m_deleteProgram && m_program)
            m_deleteProgram(m_program);
    }

    void upload(const std::vector<uint8_t>& pixels)
    {
        if (pixels.size() != static_cast<size_t>(m_textureWidth) * static_cast<size_t>(m_textureHeight) * 4u)
            throw std::runtime_error("Fusion Phase 1 texture upload size mismatch");

        m_bindTexture(GL_TEXTURE_2D, m_texture);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
        m_texSubImage2D(GL_TEXTURE_2D, 0, 0, 0, static_cast<GLsizei>(m_textureWidth), static_cast<GLsizei>(m_textureHeight), GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
        throwOnGlError("texture upload");
    }

    void render(uint32_t width, uint32_t height)
    {
        glViewport(0, 0, static_cast<GLsizei>(width), static_cast<GLsizei>(height));
        glDisable(GL_DEPTH_TEST);
        glDisable(GL_CULL_FACE);
        glDisable(GL_BLEND);
        glDisable(GL_STENCIL_TEST);
        glDisable(GL_SCISSOR_TEST);
#if defined(GL_RASTERIZER_DISCARD)
        glDisable(GL_RASTERIZER_DISCARD);
#endif
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glClearColor(0.01f, 0.02f, 0.04f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        m_useProgram(m_program);
        m_activeTexture(GL_TEXTURE0);
        m_bindTexture(GL_TEXTURE_2D, m_texture);
        m_bindVertexArray(m_vao);
        m_drawArrays(GL_TRIANGLES, 0, 6);
        m_bindVertexArray(0);
        m_bindTexture(GL_TEXTURE_2D, 0);
        m_useProgram(0);
        glFinish();
        throwOnGlError("quad render");
    }

    GLuint texture() const
    {
        return m_texture;
    }

private:
    using GlActiveTextureProc = void(APIENTRYP)(GLenum);
    using GlAttachShaderProc = void(APIENTRYP)(GLuint, GLuint);
    using GlBindAttribLocationProc = void(APIENTRYP)(GLuint, GLuint, const GLchar*);
    using GlBindBufferProc = void(APIENTRYP)(GLenum, GLuint);
    using GlBindTextureProc = void(APIENTRYP)(GLenum, GLuint);
    using GlBindVertexArrayProc = void(APIENTRYP)(GLuint);
    using GlBufferDataProc = void(APIENTRYP)(GLenum, GLsizeiptr, const void*, GLenum);
    using GlCompileShaderProc = void(APIENTRYP)(GLuint);
    using GlCreateProgramProc = GLuint(APIENTRYP)();
    using GlCreateShaderProc = GLuint(APIENTRYP)(GLenum);
    using GlDeleteBuffersProc = void(APIENTRYP)(GLsizei, const GLuint*);
    using GlDeleteProgramProc = void(APIENTRYP)(GLuint);
    using GlDeleteShaderProc = void(APIENTRYP)(GLuint);
    using GlDeleteTexturesProc = void(APIENTRYP)(GLsizei, const GLuint*);
    using GlDeleteVertexArraysProc = void(APIENTRYP)(GLsizei, const GLuint*);
    using GlDrawArraysProc = void(APIENTRYP)(GLenum, GLint, GLsizei);
    using GlEnableVertexAttribArrayProc = void(APIENTRYP)(GLuint);
    using GlGenBuffersProc = void(APIENTRYP)(GLsizei, GLuint*);
    using GlGenTexturesProc = void(APIENTRYP)(GLsizei, GLuint*);
    using GlGenVertexArraysProc = void(APIENTRYP)(GLsizei, GLuint*);
    using GlGetAttribLocationProc = GLint(APIENTRYP)(GLuint, const GLchar*);
    using GlGetProgramInfoLogProc = void(APIENTRYP)(GLuint, GLsizei, GLsizei*, GLchar*);
    using GlGetProgramivProc = void(APIENTRYP)(GLuint, GLenum, GLint*);
    using GlGetShaderInfoLogProc = void(APIENTRYP)(GLuint, GLsizei, GLsizei*, GLchar*);
    using GlGetShaderivProc = void(APIENTRYP)(GLuint, GLenum, GLint*);
    using GlGetUniformLocationProc = GLint(APIENTRYP)(GLuint, const GLchar*);
    using GlLinkProgramProc = void(APIENTRYP)(GLuint);
    using GlShaderSourceProc = void(APIENTRYP)(GLuint, GLsizei, const GLchar* const*, const GLint*);
    using GlTexImage2DProc = void(APIENTRYP)(GLenum, GLint, GLint, GLsizei, GLsizei, GLint, GLenum, GLenum, const void*);
    using GlTexParameteriProc = void(APIENTRYP)(GLenum, GLenum, GLint);
    using GlTexSubImage2DProc = void(APIENTRYP)(GLenum, GLint, GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, const void*);
    using GlUniform1iProc = void(APIENTRYP)(GLint, GLint);
    using GlUseProgramProc = void(APIENTRYP)(GLuint);
    using GlVertexAttribPointerProc = void(APIENTRYP)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);

    void load()
    {
        m_activeTexture = loadGlProc<GlActiveTextureProc>("glActiveTexture");
        m_attachShader = loadGlProc<GlAttachShaderProc>("glAttachShader");
        m_bindAttribLocation = loadGlProc<GlBindAttribLocationProc>("glBindAttribLocation");
        m_bindBuffer = loadGlProc<GlBindBufferProc>("glBindBuffer");
        m_bindTexture = loadGlProc<GlBindTextureProc>("glBindTexture");
        m_bindVertexArray = loadGlProc<GlBindVertexArrayProc>("glBindVertexArray");
        m_bufferData = loadGlProc<GlBufferDataProc>("glBufferData");
        m_compileShader = loadGlProc<GlCompileShaderProc>("glCompileShader");
        m_createProgram = loadGlProc<GlCreateProgramProc>("glCreateProgram");
        m_createShader = loadGlProc<GlCreateShaderProc>("glCreateShader");
        m_deleteBuffers = loadGlProc<GlDeleteBuffersProc>("glDeleteBuffers");
        m_deleteProgram = loadGlProc<GlDeleteProgramProc>("glDeleteProgram");
        m_deleteShader = loadGlProc<GlDeleteShaderProc>("glDeleteShader");
        m_deleteTextures = loadGlProc<GlDeleteTexturesProc>("glDeleteTextures");
        m_deleteVertexArrays = loadGlProc<GlDeleteVertexArraysProc>("glDeleteVertexArrays");
        m_drawArrays = loadGlProc<GlDrawArraysProc>("glDrawArrays");
        m_enableVertexAttribArray = loadGlProc<GlEnableVertexAttribArrayProc>("glEnableVertexAttribArray");
        m_genBuffers = loadGlProc<GlGenBuffersProc>("glGenBuffers");
        m_genTextures = loadGlProc<GlGenTexturesProc>("glGenTextures");
        m_genVertexArrays = loadGlProc<GlGenVertexArraysProc>("glGenVertexArrays");
        m_getAttribLocation = loadGlProc<GlGetAttribLocationProc>("glGetAttribLocation");
        m_getProgramInfoLog = loadGlProc<GlGetProgramInfoLogProc>("glGetProgramInfoLog");
        m_getProgramiv = loadGlProc<GlGetProgramivProc>("glGetProgramiv");
        m_getShaderInfoLog = loadGlProc<GlGetShaderInfoLogProc>("glGetShaderInfoLog");
        m_getShaderiv = loadGlProc<GlGetShaderivProc>("glGetShaderiv");
        m_getUniformLocation = loadGlProc<GlGetUniformLocationProc>("glGetUniformLocation");
        m_linkProgram = loadGlProc<GlLinkProgramProc>("glLinkProgram");
        m_shaderSource = loadGlProc<GlShaderSourceProc>("glShaderSource");
        m_texImage2D = loadGlProc<GlTexImage2DProc>("glTexImage2D");
        m_texParameteri = loadGlProc<GlTexParameteriProc>("glTexParameteri");
        m_texSubImage2D = loadGlProc<GlTexSubImage2DProc>("glTexSubImage2D");
        m_uniform1i = loadGlProc<GlUniform1iProc>("glUniform1i");
        m_useProgram = loadGlProc<GlUseProgramProc>("glUseProgram");
        m_vertexAttribPointer = loadGlProc<GlVertexAttribPointerProc>("glVertexAttribPointer");
    }

    GLuint compileShader(GLenum type, const char* source)
    {
        const GLuint shader = m_createShader(type);
        m_shaderSource(shader, 1, &source, nullptr);
        m_compileShader(shader);

        GLint status = 0;
        m_getShaderiv(shader, GL_COMPILE_STATUS, &status);
        if (!status)
        {
            char log[2048] = {};
            GLsizei length = 0;
            m_getShaderInfoLog(shader, sizeof(log), &length, log);
            throw std::runtime_error(std::string("Fusion Phase 1 shader compile failed: ") + log);
        }
        return shader;
    }

    void createProgram()
    {
        const auto* versionString = reinterpret_cast<const char*>(glGetString(GL_VERSION));
        m_glEs = versionString && std::strstr(versionString, "OpenGL ES") != nullptr;
        std::cout << "Fusion Phase 1 shell GL actual version: " << (versionString ? versionString : "<unknown>") << "\n";

        static constexpr const char* vertexShaderDesktop = R"glsl(#version 330 core
in vec2 inPosition;
in vec2 inUv;
out vec2 fragUv;
void main()
{
    gl_Position = vec4(inPosition, 0.0, 1.0);
    fragUv = inUv;
}
)glsl";

        static constexpr const char* fragmentShaderDesktop = R"glsl(#version 330 core
in vec2 fragUv;
layout (location = 0) out vec4 outColor;
uniform sampler2D uTexture;
void main()
{
    outColor = texture(uTexture, fragUv);
}
)glsl";

        static constexpr const char* vertexShaderEs = R"glsl(#version 300 es
in vec2 inPosition;
in vec2 inUv;
out vec2 fragUv;
void main()
{
    gl_Position = vec4(inPosition, 0.0, 1.0);
    fragUv = inUv;
}
)glsl";

static constexpr const char* fragmentShaderEs = R"glsl(#version 300 es
precision mediump float;
in vec2 fragUv;
layout (location = 0) out vec4 outColor;
uniform sampler2D uTexture;
void main()
{
    outColor = texture(uTexture, fragUv);
}
)glsl";

        const char* vertexShader = m_glEs ? vertexShaderEs : vertexShaderDesktop;
        const char* fragmentShader = m_glEs ? fragmentShaderEs : fragmentShaderDesktop;

        const GLuint vs = compileShader(GL_VERTEX_SHADER, vertexShader);
        const GLuint fs = compileShader(GL_FRAGMENT_SHADER, fragmentShader);

        m_program = m_createProgram();
        m_bindAttribLocation(m_program, 0, "inPosition");
        m_bindAttribLocation(m_program, 1, "inUv");
        m_attachShader(m_program, vs);
        m_attachShader(m_program, fs);
        m_linkProgram(m_program);

        GLint status = 0;
        m_getProgramiv(m_program, GL_LINK_STATUS, &status);
        m_deleteShader(vs);
        m_deleteShader(fs);
        if (!status)
        {
            char log[2048] = {};
            GLsizei length = 0;
            m_getProgramInfoLog(m_program, sizeof(log), &length, log);
            throw std::runtime_error(std::string("Fusion Phase 1 shader link failed: ") + log);
        }
        throwOnGlError("shader program link");

        const GLint positionLocation = m_getAttribLocation(m_program, "inPosition");
        const GLint uvLocation = m_getAttribLocation(m_program, "inUv");
        if (positionLocation != 0 || uvLocation != 1)
            throw std::runtime_error("Fusion Phase 1 shader attribute binding mismatch");

        m_useProgram(m_program);
        const GLint samplerLocation = m_getUniformLocation(m_program, "uTexture");
        if (samplerLocation >= 0)
            m_uniform1i(samplerLocation, 0);
        m_useProgram(0);
    }

    void createGeometry()
    {
        const GLfloat vertices[] = {
            -0.88f, -0.72f, 0.0f, 0.0f,
             0.88f, -0.72f, 1.0f, 0.0f,
             0.88f,  0.72f, 1.0f, 1.0f,

             0.88f,  0.72f, 1.0f, 1.0f,
            -0.88f,  0.72f, 0.0f, 1.0f,
            -0.88f, -0.72f, 0.0f, 0.0f,
        };

        m_genVertexArrays(1, &m_vao);
        m_genBuffers(1, &m_vbo);

        m_bindVertexArray(m_vao);
        m_bindBuffer(GL_ARRAY_BUFFER, m_vbo);
        m_bufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices, GL_STATIC_DRAW);
        m_vertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(GLfloat), reinterpret_cast<const void*>(0));
        m_enableVertexAttribArray(0);
        m_vertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(GLfloat), reinterpret_cast<const void*>(2 * sizeof(GLfloat)));
        m_enableVertexAttribArray(1);
        m_bindVertexArray(0);
        throwOnGlError("quad geometry");
    }

    void createTexture()
    {
        m_genTextures(1, &m_texture);
        m_bindTexture(GL_TEXTURE_2D, m_texture);
        m_texParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        m_texParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        m_texParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        m_texParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        m_texImage2D(GL_TEXTURE_2D, 0, m_glEs ? GL_RGBA : GL_RGBA8, static_cast<GLsizei>(m_textureWidth), static_cast<GLsizei>(m_textureHeight), 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        throwOnGlError("texture allocation");
        m_bindTexture(GL_TEXTURE_2D, 0);
    }

    uint32_t m_textureWidth = 0u;
    uint32_t m_textureHeight = 0u;
    GLuint m_program = 0u;
    GLuint m_vao = 0u;
    GLuint m_vbo = 0u;
    GLuint m_texture = 0u;
    bool m_glEs = false;

    GlActiveTextureProc m_activeTexture = nullptr;
    GlAttachShaderProc m_attachShader = nullptr;
    GlBindAttribLocationProc m_bindAttribLocation = nullptr;
    GlBindBufferProc m_bindBuffer = nullptr;
    GlBindTextureProc m_bindTexture = nullptr;
    GlBindVertexArrayProc m_bindVertexArray = nullptr;
    GlBufferDataProc m_bufferData = nullptr;
    GlCompileShaderProc m_compileShader = nullptr;
    GlCreateProgramProc m_createProgram = nullptr;
    GlCreateShaderProc m_createShader = nullptr;
    GlDeleteBuffersProc m_deleteBuffers = nullptr;
    GlDeleteProgramProc m_deleteProgram = nullptr;
    GlDeleteShaderProc m_deleteShader = nullptr;
    GlDeleteTexturesProc m_deleteTextures = nullptr;
    GlDeleteVertexArraysProc m_deleteVertexArrays = nullptr;
    GlDrawArraysProc m_drawArrays = nullptr;
    GlEnableVertexAttribArrayProc m_enableVertexAttribArray = nullptr;
    GlGenBuffersProc m_genBuffers = nullptr;
    GlGenTexturesProc m_genTextures = nullptr;
    GlGenVertexArraysProc m_genVertexArrays = nullptr;
    GlGetAttribLocationProc m_getAttribLocation = nullptr;
    GlGetProgramInfoLogProc m_getProgramInfoLog = nullptr;
    GlGetProgramivProc m_getProgramiv = nullptr;
    GlGetShaderInfoLogProc m_getShaderInfoLog = nullptr;
    GlGetShaderivProc m_getShaderiv = nullptr;
    GlGetUniformLocationProc m_getUniformLocation = nullptr;
    GlLinkProgramProc m_linkProgram = nullptr;
    GlShaderSourceProc m_shaderSource = nullptr;
    GlTexImage2DProc m_texImage2D = nullptr;
    GlTexParameteriProc m_texParameteri = nullptr;
    GlTexSubImage2DProc m_texSubImage2D = nullptr;
    GlUniform1iProc m_uniform1i = nullptr;
    GlUseProgramProc m_useProgram = nullptr;
    GlVertexAttribPointerProc m_vertexAttribPointer = nullptr;
};

ReadbackStats saveShellGlReadback(uint32_t width, uint32_t height, const std::string& path)
{
    std::vector<uint8_t> pixels(static_cast<size_t>(width) * static_cast<size_t>(height) * 4u);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, static_cast<GLsizei>(width), static_cast<GLsizei>(height), GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
    throwOnGlError("shell readback");

    std::unique_ptr<SDL_Surface, decltype(&SDL_DestroySurface)> surface(SDL_CreateSurface(static_cast<int>(width), static_cast<int>(height), SDL_PIXELFORMAT_RGBA32), SDL_DestroySurface);
    if (!surface)
        throw std::runtime_error(std::string("SDL_CreateSurface failed: ") + SDL_GetError());

    auto* destination = static_cast<uint8_t*>(surface->pixels);
    for (uint32_t y = 0; y < height; ++y)
    {
        const auto* sourceRow = pixels.data() + static_cast<size_t>(height - 1u - y) * static_cast<size_t>(width) * 4u;
        auto* destinationRow = destination + static_cast<size_t>(y) * static_cast<size_t>(surface->pitch);
        std::memcpy(destinationRow, sourceRow, static_cast<size_t>(width) * 4u);
    }

    const std::filesystem::path outputPath(path);
    if (outputPath.has_parent_path())
        std::filesystem::create_directories(outputPath.parent_path());
    if (!SDL_SaveBMP(surface.get(), path.c_str()))
        throw std::runtime_error(std::string("SDL_SaveBMP failed: ") + SDL_GetError());

    return calculateBrightPixels(pixels, width, height);
}
} // namespace

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
        SdlGlWindow shellWindow("SGFX Cine Ramses Shell Fusion Phase 1", options.width, options.height);

        std::cout << "Fusion Phase 1 linked Ramses version: " << linkedVersion.string << "\n";
        std::cout << "Fusion Phase 1 profile id: " << options.profileId << "\n";
        std::cout << "Fusion Phase 1 scene file: " << options.sceneFile << "\n";
        std::cout << "Fusion Phase 1 scene metadata Ramses version: " << versionString(metadata->ramsesVersion) << "\n";
        std::cout << "Fusion Phase 1 scene metadata exporter version: " << versionString(metadata->exporterVersion) << "\n";
        std::cout << "Fusion Phase 1 scene metadata feature level: " << static_cast<unsigned>(metadata->featureLevel) << "\n";
        std::cout << "Fusion Phase 1 shell GL context: SDL OpenGL 3.3 core\n";

        ramses::RamsesFrameworkConfig frameworkConfig{metadata->featureLevel};
        frameworkConfig.setRequestedRamsesShellType(ramses::ERamsesShellType::Console);
        frameworkConfig.setPeriodicLogInterval(std::chrono::seconds(1));
        ramses::RamsesFramework framework(frameworkConfig);
        auto& client = *framework.createClient("sgfx-cine-fusion-phase1-client");

        ramses::RendererConfig rendererConfig;
        rendererConfig.setRenderThreadLoopTimingReportingPeriod(std::chrono::milliseconds(500));
        auto& renderer = *framework.createRenderer(rendererConfig);
        auto& sceneControl = *renderer.getSceneControlAPI();

        framework.connect();

        ramses::SceneConfig sceneConfig{ramses::sceneId_t{66u}, ramses::EScenePublicationMode::LocalOnly, ramses::ERenderBackendCompatibility::OpenGL};
        auto* scene = client.loadSceneFromFile(options.sceneFile, sceneConfig);
        if (!scene)
        {
            if (auto issue = framework.getLastError())
                std::cerr << "Ramses last error: " << issue->message << "\n";
            throw std::runtime_error("loadSceneFromFile returned null");
        }

        const ramses::sceneId_t sceneId = scene->getSceneId();
        auto cameras = collectCameras(*scene);
        auto logicEngines = collectLogicEngines(*scene);
        const AuthoredRenderSetup renderSetup = inspectAuthoredRenderSetup(*scene);
        if (!renderSetup.finalFramebufferPass || !renderSetup.finalFramebufferCamera)
            throw std::runtime_error("Scene has no authored framebuffer render pass with a camera");

        const uint32_t producerWidth = options.producerWidth > 0u ? options.producerWidth :
            (renderSetup.preferredWidth > 0u ? renderSetup.preferredWidth : options.width);
        const uint32_t producerHeight = options.producerHeight > 0u ? options.producerHeight :
            (renderSetup.preferredHeight > 0u ? renderSetup.preferredHeight : options.height);
        const std::vector<ramses::Camera*> viewControlCameras = selectAuthoredViewCameras(cameras, renderSetup);
        if (options.autoFrame && viewControlCameras.empty())
            throw std::runtime_error("Auto-frame requested but no authored view-control cameras were found");

        const SceneBounds sceneBounds = estimateSceneBoundsFromMeshNodes(*scene);
        const CameraRig cameraRig = makeCameraRig(sceneBounds, producerWidth, producerHeight, options.zoom);

        std::cout << "Fusion Phase 1 loaded scene id: " << sceneId.getValue() << "\n";
        std::cout << "Fusion Phase 1 cameras: " << cameras.size() << "\n";
        std::cout << "Fusion Phase 1 logic engines/objects: " << logicEngines.size() << "/" << countLogicObjects(logicEngines) << "\n";
        std::cout << "Fusion Phase 1 authored render passes total/enabled/framebuffer/enabledFramebuffer/withFramebufferCamera/offscreenWithCamera/disabled/missingCamera: "
                  << renderSetup.totalPasses << "/"
                  << renderSetup.enabledPasses << "/"
                  << renderSetup.framebufferPasses << "/"
                  << renderSetup.enabledFramebufferPasses << "/"
                  << renderSetup.framebufferPassesWithCamera << "/"
                  << renderSetup.offscreenPassesWithCamera << "/"
                  << renderSetup.disabledPasses << "/"
                  << renderSetup.missingCameraPasses << "\n";
        std::cout << "Fusion Phase 1 final framebuffer pass/camera/order/viewport: "
                  << objectName(renderSetup.finalFramebufferPass) << "/"
                  << objectName(renderSetup.finalFramebufferCamera) << "/"
                  << renderSetup.finalRenderOrder << "/"
                  << renderSetup.preferredWidth << "x" << renderSetup.preferredHeight << "\n";
        std::cout << "Fusion Phase 1 authored view-control cameras: " << cameraListName(viewControlCameras) << "\n";
        std::cout << "Fusion Phase 1 auto-frame/orbit/zoom/view: "
                  << (options.autoFrame ? "on" : "off") << "/"
                  << (options.orbit ? "on" : "off") << "/"
                  << options.zoom << "/"
                  << options.viewPreset << "\n";
        std::cout << "Fusion Phase 1 producer readback size: " << producerWidth << "x" << producerHeight << "\n";
        std::cout << "Fusion Phase 1 shell window size: " << options.width << "x" << options.height << "\n";
        std::cout << "Fusion Phase 1 estimated bounds samples/min/max/center/radius: "
                  << sceneBounds.sampleCount << "/"
                  << sceneBounds.min.x << "," << sceneBounds.min.y << "," << sceneBounds.min.z << "/"
                  << sceneBounds.max.x << "," << sceneBounds.max.y << "," << sceneBounds.max.z << "/"
                  << sceneBounds.center.x << "," << sceneBounds.center.y << "," << sceneBounds.center.z << "/"
                  << sceneBounds.radius << "\n";

        SdlPlainWindow ramsesWindow("SGFX Cine Ramses Hidden Producer", producerWidth, producerHeight, SDL_WINDOW_HIDDEN);
        void* producerHwnd = getWin32Hwnd(ramsesWindow.get());
        std::cout << "Fusion Phase 1 producer HWND: " << producerHwnd << "\n";

        ramses::DisplayConfig displayConfig;
        displayConfig.setWindowType(ramses::EWindowType::Windows);
        displayConfig.setWindowsWindowHandle(producerHwnd);
        displayConfig.setWindowRectangle(0, 0, producerWidth, producerHeight);
        displayConfig.setWindowTitle("SGFX Cine Ramses Hidden Producer");

        const ramses::displayId_t display = renderer.createDisplay(displayConfig);
        if (!display.isValid())
            throw std::runtime_error("Ramses createDisplay returned an invalid display id");
        renderer.setSkippingOfUnmodifiedBuffers(false);
        renderer.flush();

        FusionEventHandler handler(display, sceneId, producerWidth, producerHeight);
        if (!pumpUntil(renderer, sceneControl, handler, [&] { return handler.displayCreated(); }, [] {}, std::chrono::seconds(5)))
            throw std::runtime_error("Timed out waiting for Ramses display creation");

        const ramses::displayBufferId_t offscreenBuffer = renderer.createOffscreenBuffer(display, producerWidth, producerHeight);
        if (!offscreenBuffer.isValid())
            throw std::runtime_error("Ramses createOffscreenBuffer returned an invalid id");
        handler.setOffscreenBuffer(offscreenBuffer);
        renderer.setDisplayBufferClearColor(display, offscreenBuffer, ramses::vec4f{0.01f, 0.02f, 0.04f, 1.0f});
        renderer.flush();
        std::cout << "Fusion Phase 1 Ramses offscreen buffer id/size: " << offscreenBuffer.getValue()
                  << "/" << producerWidth << "x" << producerHeight << "\n";

        if (!pumpUntil(renderer, sceneControl, handler, [&] { return handler.offscreenCreated(); }, [] {}, std::chrono::seconds(5)))
            throw std::runtime_error("Timed out waiting for Ramses offscreen buffer creation");

        auto updateLogicAndViewControl = [&](uint32_t frame, bool orbit, const char* context) {
            if (!updateLogicEngines(logicEngines))
                throw std::runtime_error(std::string("LogicEngine update failed ") + context);
            if (options.autoFrame)
                driveAuthoredCameras(viewControlCameras, cameraRig, frame, orbit, options);
        };

        updateLogicAndViewControl(0u, false, "before scene publish");
        scene->publish(ramses::EScenePublicationMode::LocalOnly);
        scene->flush();

        if (!sceneControl.setSceneMapping(sceneId, display))
            throw std::runtime_error("Ramses setSceneMapping failed");
        if (!sceneControl.setSceneDisplayBufferAssignment(sceneId, offscreenBuffer, 0))
            throw std::runtime_error("Ramses setSceneDisplayBufferAssignment(offscreen) failed");
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

            updateLogicAndViewControl(renderedFrames, options.orbit, "during fusion render loop");
            scene->flush();
            renderer.doOneLoop();
            pumpRamsesEvents(renderer, sceneControl, handler);
            ++renderedFrames;
        }

        handler.resetPixelsRead();
        renderer.readPixels(display, offscreenBuffer, 0u, 0u, producerWidth, producerHeight);
        renderer.flush();
        if (!pumpUntil(renderer, sceneControl, handler, [&] { return handler.pixelsRead(); }, [&] {
                updateLogicAndViewControl(renderedFrames, options.orbit, "while waiting for readPixels");
                scene->flush();
            }, std::chrono::seconds(5)))
            throw std::runtime_error("Timed out waiting for Ramses offscreen readPixels");
        if (!handler.pixelsReadOk() || handler.ramsesStats().brightPixels == 0u)
            throw std::runtime_error("Fusion Phase 1 Ramses offscreen readPixels did not contain visible scene pixels");

        shellWindow.makeCurrent();
        if (SDL_GL_GetCurrentWindow() != shellWindow.get() || SDL_GL_GetCurrentContext() != shellWindow.context())
            throw std::runtime_error("Fusion Phase 1 shell GL context was not current after Ramses readback");
        std::cout << "Fusion Phase 1 shell GL context current after Ramses readback: yes\n";

        GlQuadRenderer quad(producerWidth, producerHeight);
        quad.upload(handler.pixels());
        quad.render(shellWindow.width(), shellWindow.height());

        const ReadbackStats shellStats = saveShellGlReadback(shellWindow.width(), shellWindow.height(), options.screenshotPath);
        shellWindow.swap();
        if (shellStats.brightPixels == 0u)
            throw std::runtime_error("Fusion Phase 1 shell GL readback did not contain visible pixels");

        std::cout << "Fusion Phase 1 frames rendered: " << renderedFrames << "\n";
        std::cout << "Fusion Phase 1 GL texture id: " << quad.texture() << "\n";
        std::cout << "Fusion Phase 1 shell readback path: " << options.screenshotPath << "\n";
        std::cout << "Fusion Phase 1 shell readback bright pixels: " << shellStats.brightPixels << "\n";
        std::cout << "Fusion Phase 1 shell readback bright bounds x/y: "
                  << shellStats.minX << "-" << shellStats.maxX << "/"
                  << shellStats.minY << "-" << shellStats.maxY << "\n";
        std::cout << "Fusion Phase 1 real car pixels landed in shell GL context OK\n";
        return 0;
    }
    catch (const std::exception& ex)
    {
        std::cerr << "Fusion Phase 1 failed: " << ex.what() << "\n";
        return 1;
    }
}
