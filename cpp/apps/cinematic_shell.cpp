#include <RmlUi/Core.h>
#include <RmlUi/Core/CallbackTexture.h>
#include <RmlUi/Core/Decorator.h>
#include <RmlUi/Core/Element.h>
#include <RmlUi/Core/ElementDocument.h>
#include <RmlUi/Core/Factory.h>
#include <RmlUi/Core/FontEngineInterface.h>
#include <RmlUi/Core/Geometry.h>
#include <RmlUi/Core/MeshUtilities.h>
#include <RmlUi/Core/RenderInterface.h>
#include <RmlUi/Core/RenderManager.h>
#include <RmlUi/Core/StringUtilities.h>
#include <RmlUi/Core/SystemInterface.h>
#include <RmlUi_Renderer_GL3.h>

#include "ramses/client/Camera.h"
#include "ramses/client/Appearance.h"
#include "ramses/client/ArrayResource.h"
#include "ramses/client/AttributeInput.h"
#include "ramses/client/Effect.h"
#include "ramses/client/EffectDescription.h"
#include "ramses/client/EffectInput.h"
#include "ramses/client/Geometry.h"
#include "ramses/client/MeshNode.h"
#include "ramses/client/PerspectiveCamera.h"
#include "ramses/client/RamsesClient.h"
#include "ramses/client/RenderGroup.h"
#include "ramses/client/RenderPass.h"
#include "ramses/client/RenderTarget.h"
#include "ramses/client/Scene.h"
#include "ramses/client/SceneConfig.h"
#include "ramses/client/SceneMetadata.h"
#include "ramses/client/SceneObjectIterator.h"
#include "ramses/client/UniformInput.h"
#include "ramses/client/logic/LogicEngine.h"
#include "ramses/client/logic/LogicObject.h"
#include "ramses/client/logic/LuaInterface.h"
#include "ramses/client/logic/LuaScript.h"
#include "ramses/client/logic/Property.h"
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
#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <initializer_list>
#include <iostream>
#include <limits>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <thread>
#include <utility>
#include <vector>

namespace
{
struct FusionQaPerspective
{
    std::filesystem::path file;
    std::string setName;
    std::string id;
    std::vector<std::string> viewIds;
    bool aspectFromResolution = true;
    float distance = 0.0f;
    float yaw = 0.0f;
    float pitch = 0.0f;
    float roll = 0.0f;
    float horizontalFov = 0.0f;
    float aspectRatio = 0.0f;
    float nearPlane = 0.0f;
    float farPlane = 0.0f;
    float scale = 1.0f;
    ramses::vec3f origin{0.0f, 0.0f, 0.0f};
    ramses::vec2i shift{0, 0};
    int32_t viewportOffsetX = 0;
    int32_t viewportOffsetY = 0;
    uint32_t viewportWidth = 0u;
    uint32_t viewportHeight = 0u;
};

struct Options
{
    int width = 1280;
    int height = 720;
    int frames = 300;
    double fps = 60.0;
    int skipAfterMs = -1;
    bool noDelay = false;
    bool readback = false;
    bool interactive = false;
    int demoMenuFocus = -1;
    int demoMenuPulseAfterMs = -1;
    int demoEnterViewerAfterMs = -1;
    int demoHubNodeIndex = 1;
    int demoHubNodeEnterAfterMs = -1;
    int demoViewerBackAfterMs = -1;
    bool fusionEnabled = false;
    bool fusionAutoFrame = true;
    bool fusionOrbit = false;
    int fusionRenderWidth = 0;
    int fusionRenderHeight = 0;
    int fusionFrames = 60;
    double fusionZoom = 1.0;
    std::string fusionViewPreset = "three-quarter";
    std::string fusionProfileId;
    std::string fusionSceneFile;
    std::string fusionCarsRoot;
    std::string profileRegistryFile;
    std::string fusionPerspectiveSet;
    std::string fusionPerspectiveFile;
    std::string fusionPerspectiveId;
    int demoCarPickIndex = -1;
    int demoCarPickAfterMs = -1;
    bool hubPlanetEnabled = false;
    bool hubNodesEnabled = false;
    int hubPlanetRenderWidth = 1024;
    int hubPlanetRenderHeight = 768;
    int hubPlanetFrames = 48;
    std::string screenshotPath;
    std::filesystem::path assetRoot = std::filesystem::path("assets");
    std::filesystem::path fontRoot = std::filesystem::path("assets") / "fonts";
};

constexpr float kFusionPi = 3.14159265358979323846f;
constexpr uint32_t kFusionInitialReadbackFrames = 8u;
constexpr uint32_t kFusionReadbackRetryFrames = 8u;

struct FusionPerformanceStats
{
    uint32_t producerFrames = 0u;
    uint32_t readbackRequests = 0u;
    uint32_t textureUploads = 0u;
};

double clamp01(double value)
{
    return std::max(0.0, std::min(1.0, value));
}

double easeOutCubic(double value)
{
    value = clamp01(value);
    const double inverse = 1.0 - value;
    return 1.0 - inverse * inverse * inverse;
}

std::string number(double value, int precision = 3)
{
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(precision) << value;
    return stream.str();
}

std::string px(double value)
{
    return number(value, 2) + "px";
}

std::string dp(double value)
{
    return number(value, 2) + "dp";
}

void require(bool condition, const std::string& message)
{
    if (!condition)
        throw std::runtime_error(message);
}

Options parseOptions(int argc, char** argv)
{
    Options options;
    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];
        auto takeValue = [&](const char* name) -> std::string {
            require(i + 1 < argc, std::string("Missing value for ") + name);
            return argv[++i];
        };

        if (arg == "--width")
            options.width = std::stoi(takeValue("--width"));
        else if (arg == "--height")
            options.height = std::stoi(takeValue("--height"));
        else if (arg == "--frames")
            options.frames = std::stoi(takeValue("--frames"));
        else if (arg == "--fps")
            options.fps = std::stod(takeValue("--fps"));
        else if (arg == "--skip-after-ms")
            options.skipAfterMs = std::stoi(takeValue("--skip-after-ms"));
        else if (arg == "--demo-menu-focus")
            options.demoMenuFocus = std::stoi(takeValue("--demo-menu-focus"));
        else if (arg == "--demo-menu-pulse-after-ms")
            options.demoMenuPulseAfterMs = std::stoi(takeValue("--demo-menu-pulse-after-ms"));
        else if (arg == "--demo-enter-viewer-after-ms")
            options.demoEnterViewerAfterMs = std::stoi(takeValue("--demo-enter-viewer-after-ms"));
        else if (arg == "--demo-hub-node-index")
            options.demoHubNodeIndex = std::stoi(takeValue("--demo-hub-node-index"));
        else if (arg == "--demo-hub-node-enter-after-ms")
            options.demoHubNodeEnterAfterMs = std::stoi(takeValue("--demo-hub-node-enter-after-ms"));
        else if (arg == "--demo-viewer-back-after-ms")
            options.demoViewerBackAfterMs = std::stoi(takeValue("--demo-viewer-back-after-ms"));
        else if (arg == "--fusion-scene-file")
        {
            options.fusionSceneFile = takeValue("--fusion-scene-file");
            options.fusionEnabled = true;
        }
        else if (arg == "--fusion-profile-id")
            options.fusionProfileId = takeValue("--fusion-profile-id");
        else if (arg == "--fusion-cars-root")
            options.fusionCarsRoot = takeValue("--fusion-cars-root");
        else if (arg == "--profile-registry-file")
            options.profileRegistryFile = takeValue("--profile-registry-file");
        else if (arg == "--fusion-render-width")
            options.fusionRenderWidth = std::stoi(takeValue("--fusion-render-width"));
        else if (arg == "--fusion-render-height")
            options.fusionRenderHeight = std::stoi(takeValue("--fusion-render-height"));
        else if (arg == "--fusion-frames")
            options.fusionFrames = std::stoi(takeValue("--fusion-frames"));
        else if (arg == "--fusion-no-auto-frame")
            options.fusionAutoFrame = false;
        else if (arg == "--fusion-orbit")
            options.fusionOrbit = true;
        else if (arg == "--fusion-zoom")
            options.fusionZoom = std::stod(takeValue("--fusion-zoom"));
        else if (arg == "--fusion-view-preset")
            options.fusionViewPreset = takeValue("--fusion-view-preset");
        else if (arg == "--fusion-perspective-set")
            options.fusionPerspectiveSet = takeValue("--fusion-perspective-set");
        else if (arg == "--fusion-perspective-file")
            options.fusionPerspectiveFile = takeValue("--fusion-perspective-file");
        else if (arg == "--fusion-perspective-id")
            options.fusionPerspectiveId = takeValue("--fusion-perspective-id");
        else if (arg == "--demo-car-pick-index")
            options.demoCarPickIndex = std::stoi(takeValue("--demo-car-pick-index"));
        else if (arg == "--demo-car-pick-after-ms")
            options.demoCarPickAfterMs = std::stoi(takeValue("--demo-car-pick-after-ms"));
        else if (arg == "--hub-planet")
            options.hubPlanetEnabled = true;
        else if (arg == "--hub-nodes")
            options.hubNodesEnabled = true;
        else if (arg == "--hub-planet-render-width")
            options.hubPlanetRenderWidth = std::stoi(takeValue("--hub-planet-render-width"));
        else if (arg == "--hub-planet-render-height")
            options.hubPlanetRenderHeight = std::stoi(takeValue("--hub-planet-render-height"));
        else if (arg == "--hub-planet-frames")
            options.hubPlanetFrames = std::stoi(takeValue("--hub-planet-frames"));
        else if (arg == "--asset-root")
            options.assetRoot = takeValue("--asset-root");
        else if (arg == "--font-root")
            options.fontRoot = takeValue("--font-root");
        else if (arg == "--readback")
            options.readback = true;
        else if (arg == "--interactive")
            options.interactive = true;
        else if (arg == "--screenshot" || arg == "--readback-path")
        {
            options.readback = true;
            options.screenshotPath = takeValue(arg.c_str());
        }
        else if (arg == "--no-delay")
            options.noDelay = true;
        else if (arg == "--help" || arg == "-h")
        {
            std::cout
                << "Usage: sgfx_cine_cinematic_shell [--frames N] [--readback --screenshot PATH]\n"
                << "       [--skip-after-ms N] [--width N] [--height N] [--no-delay]\n"
                << "       [--interactive]\n"
                << "       [--asset-root PATH] [--font-root PATH]\n"
                << "       [--demo-menu-focus 0..5] [--demo-menu-pulse-after-ms N]\n"
                << "       [--demo-enter-viewer-after-ms N]\n"
                << "       [--demo-hub-node-index 0..5]\n"
                << "       [--demo-hub-node-enter-after-ms N] [--demo-viewer-back-after-ms N]\n"
                << "       [--fusion-scene-file PATH] [--fusion-render-width N] [--fusion-render-height N]\n"
                << "       [--fusion-cars-root PATH] [--profile-registry-file PATH]\n"
                << "       [--fusion-frames MAX_N] [--fusion-orbit] [--fusion-view-preset NAME]\n"
                << "       [--fusion-perspective-set NAME|--fusion-perspective-file PATH] [--fusion-perspective-id ID]\n"
                << "       [--demo-car-pick-index N] [--demo-car-pick-after-ms N]\n"
                << "       [--hub-planet] [--hub-nodes] [--hub-planet-render-width N] [--hub-planet-render-height N] [--hub-planet-frames N]\n";
            std::exit(0);
        }
        else
        {
            throw std::runtime_error("Unknown argument: " + arg);
        }
    }

    require(options.width > 0 && options.height > 0, "Window dimensions must be positive");
    require(options.frames > 0, "--frames must be positive");
    require(options.fps > 0.0, "--fps must be positive");
    require(options.fusionRenderWidth >= 0, "--fusion-render-width must be positive or zero for authored size");
    require(options.fusionRenderHeight >= 0, "--fusion-render-height must be positive or zero for authored size");
    require(options.fusionFrames > 0, "--fusion-frames must be positive");
    require(options.fusionZoom > 0.0 && std::isfinite(options.fusionZoom), "--fusion-zoom must be a finite positive number");
    require(options.hubPlanetRenderWidth > 0, "--hub-planet-render-width must be positive");
    require(options.hubPlanetRenderHeight > 0, "--hub-planet-render-height must be positive");
    require(options.hubPlanetFrames > 0, "--hub-planet-frames must be positive");
    require(!options.hubNodesEnabled || options.hubPlanetEnabled, "--hub-nodes requires --hub-planet");
    require(!options.interactive || options.skipAfterMs < 0, "--interactive cannot be combined with --skip-after-ms");
    require(!options.interactive || options.demoMenuFocus < 0, "--interactive cannot be combined with --demo-menu-focus");
    require(!options.interactive || options.demoMenuPulseAfterMs < 0, "--interactive cannot be combined with --demo-menu-pulse-after-ms");
    require(!options.interactive || options.demoEnterViewerAfterMs < 0, "--interactive cannot be combined with --demo-enter-viewer-after-ms");
    require(!options.interactive || options.demoHubNodeIndex == 1, "--interactive cannot be combined with --demo-hub-node-index");
    require(!options.interactive || options.demoHubNodeEnterAfterMs < 0, "--interactive cannot be combined with --demo-hub-node-enter-after-ms");
    require(!options.interactive || options.demoViewerBackAfterMs < 0, "--interactive cannot be combined with --demo-viewer-back-after-ms");
    require(!options.interactive || options.demoCarPickIndex < 0, "--interactive cannot be combined with --demo-car-pick-index");
    require(!options.interactive || options.demoCarPickAfterMs < 0, "--interactive cannot be combined with --demo-car-pick-after-ms");
    require(options.demoMenuFocus < 0 || options.demoMenuFocus < 6, "--demo-menu-focus must be 0..5");
    require(options.demoHubNodeEnterAfterMs < 0 || options.hubNodesEnabled, "--demo-hub-node-enter-after-ms requires --hub-nodes");
    require(options.demoHubNodeIndex >= 0 && options.demoHubNodeIndex < 6, "--demo-hub-node-index must be 0..5");
    require(options.demoViewerBackAfterMs < 0 || options.demoHubNodeEnterAfterMs >= 0, "--demo-viewer-back-after-ms requires --demo-hub-node-enter-after-ms");
    require(options.demoCarPickIndex < 0 || options.demoCarPickAfterMs >= 0, "--demo-car-pick-index requires --demo-car-pick-after-ms");
    if (options.fusionEnabled)
        require(std::filesystem::is_regular_file(options.fusionSceneFile), "Fusion scene file does not exist: " + options.fusionSceneFile);
    if (!options.fusionPerspectiveFile.empty())
        require(std::filesystem::is_regular_file(options.fusionPerspectiveFile), "Fusion perspective file does not exist: " + options.fusionPerspectiveFile);
    require(options.fusionPerspectiveId.empty() || options.fusionEnabled || !options.fusionCarsRoot.empty(), "--fusion-perspective-id requires --fusion-scene-file or --fusion-cars-root");
    if (options.readback && options.screenshotPath.empty())
        options.screenshotPath = "sgfx-cinematic-shell-readback.bmp";
    return options;
}

class SdlRuntime
{
public:
    SdlRuntime()
    {
        if (!SDL_Init(SDL_INIT_VIDEO))
            throw std::runtime_error(std::string("SDL_Init failed: ") + SDL_GetError());
    }

    ~SdlRuntime()
    {
        SDL_Quit();
    }
};

class SdlWindowRenderer
{
public:
    SdlWindowRenderer(const char* title, int width, int height)
    {
        if (!SDL_CreateWindowAndRenderer(title, width, height, SDL_WINDOW_RESIZABLE, &m_window, &m_renderer))
            throw std::runtime_error(std::string("SDL_CreateWindowAndRenderer failed: ") + SDL_GetError());
    }

    ~SdlWindowRenderer()
    {
        if (m_renderer)
            SDL_DestroyRenderer(m_renderer);
        if (m_window)
            SDL_DestroyWindow(m_window);
    }

    SDL_Window* window() const { return m_window; }
    SDL_Renderer* renderer() const { return m_renderer; }

private:
    SDL_Window* m_window = nullptr;
    SDL_Renderer* m_renderer = nullptr;
};

class SdlGlWindow
{
public:
    SdlGlWindow(const char* title, int width, int height, bool initializeRmlGl = true)
    {
        setGlAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE, "SDL_GL_CONTEXT_PROFILE_MASK");
        setGlAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3, "SDL_GL_CONTEXT_MAJOR_VERSION");
        setGlAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 3, "SDL_GL_CONTEXT_MINOR_VERSION");
        setGlAttribute(SDL_GL_DOUBLEBUFFER, 1, "SDL_GL_DOUBLEBUFFER");
        setGlAttribute(SDL_GL_STENCIL_SIZE, 8, "SDL_GL_STENCIL_SIZE");

        m_window = SDL_CreateWindow(title, width, height, SDL_WINDOW_OPENGL | SDL_WINDOW_RESIZABLE);
        if (!m_window)
            throw std::runtime_error(std::string("SDL_CreateWindow(GL3) failed: ") + SDL_GetError());

        m_context = SDL_GL_CreateContext(m_window);
        if (!m_context)
            throw std::runtime_error(std::string("SDL_GL_CreateContext failed: ") + SDL_GetError());

        if (!SDL_GL_MakeCurrent(m_window, m_context))
            throw std::runtime_error(std::string("SDL_GL_MakeCurrent failed: ") + SDL_GetError());

        SDL_GL_SetSwapInterval(0);

        if (initializeRmlGl)
            initializeRmlGlBackend();
    }

    ~SdlGlWindow()
    {
        if (m_glInitialized)
            RmlGL3::Shutdown();
        if (m_context)
            SDL_GL_DestroyContext(m_context);
        if (m_window)
            SDL_DestroyWindow(m_window);
    }

    SdlGlWindow(const SdlGlWindow&) = delete;
    SdlGlWindow& operator=(const SdlGlWindow&) = delete;

    void initializeRmlGlBackend()
    {
        if (m_glInitialized)
            return;
        makeCurrent();
        Rml::String glMessage;
        if (!RmlGL3::Initialize(&glMessage))
            throw std::runtime_error("RmlUi GL3 initialization failed: " + glMessage);
        m_glInitialized = true;
        m_glInfo = glMessage;
    }

    void reloadRmlGlBackend()
    {
        makeCurrent();
        Rml::String glMessage;
        if (!RmlGL3::Initialize(&glMessage))
            throw std::runtime_error("RmlUi GL3 reload failed: " + glMessage);
        m_glInitialized = true;
        m_glInfo = glMessage;
    }

    SDL_Window* window() const
    {
        return m_window;
    }

    SDL_GLContext context() const
    {
        return m_context;
    }

    void makeCurrent() const
    {
        SDL_GL_MakeCurrent(m_window, nullptr);
        if (!SDL_GL_MakeCurrent(m_window, m_context))
            throw std::runtime_error(std::string("SDL_GL_MakeCurrent failed: ") + SDL_GetError());
    }

    Rml::Vector2i drawableSize() const
    {
        int width = 0;
        int height = 0;
        if (!SDL_GetWindowSizeInPixels(m_window, &width, &height) || width <= 0 || height <= 0)
            SDL_GetWindowSize(m_window, &width, &height);
        return {std::max(1, width), std::max(1, height)};
    }

    void swap()
    {
        SDL_GL_SwapWindow(m_window);
    }

    const std::string& glInfo() const
    {
        return m_glInfo;
    }

private:
    static void setGlAttribute(SDL_GLAttr attribute, int value, const char* name)
    {
        if (!SDL_GL_SetAttribute(attribute, value))
            throw std::runtime_error(std::string(name) + " failed: " + SDL_GetError());
    }

    SDL_Window* m_window = nullptr;
    SDL_GLContext m_context = nullptr;
    bool m_glInitialized = false;
    std::string m_glInfo;
};

class SgfxGl3RenderInterface final : public RenderInterface_GL3
{
public:
    explicit SgfxGl3RenderInterface(std::filesystem::path assetRoot)
        : m_assetRoot(canonicalOrAbsolute(std::move(assetRoot)))
    {
        if (!static_cast<bool>(*this))
            throw std::runtime_error("RmlUi GL3 renderer construction failed");
    }

    Rml::TextureHandle LoadTexture(Rml::Vector2i& textureDimensions, const Rml::String& source) override
    {
        textureDimensions = {0, 0};
        const std::filesystem::path texturePath = resolveAllowedTexturePath(source);
        if (texturePath.empty())
            return {};

        const std::string texturePathString = texturePath.string();
        std::unique_ptr<SDL_Surface, decltype(&SDL_DestroySurface)> loaded(SDL_LoadPNG(texturePathString.c_str()), SDL_DestroySurface);
        if (!loaded)
        {
            std::cerr << "SGFX brand texture load failed: " << texturePathString << " :: " << SDL_GetError() << "\n";
            return {};
        }

        SDL_Surface* textureSurface = loaded.get();
        std::unique_ptr<SDL_Surface, decltype(&SDL_DestroySurface)> converted(nullptr, SDL_DestroySurface);
        if (textureSurface->format != SDL_PIXELFORMAT_RGBA32)
        {
            converted.reset(SDL_ConvertSurface(textureSurface, SDL_PIXELFORMAT_RGBA32));
            if (!converted)
            {
                std::cerr << "SGFX brand texture conversion failed: " << texturePathString << " :: " << SDL_GetError() << "\n";
                return {};
            }
            textureSurface = converted.get();
        }

        premultiplyAlpha(textureSurface);
        textureDimensions = {textureSurface->w, textureSurface->h};
        std::vector<Rml::byte> pixels(static_cast<size_t>(textureDimensions.x) * static_cast<size_t>(textureDimensions.y) * 4);
        const auto* sourcePixels = static_cast<const Rml::byte*>(textureSurface->pixels);
        for (int y = 0; y < textureSurface->h; ++y)
        {
            std::memcpy(
                pixels.data() + static_cast<size_t>(y) * static_cast<size_t>(textureSurface->w) * 4,
                sourcePixels + static_cast<size_t>(y) * static_cast<size_t>(textureSurface->pitch),
                static_cast<size_t>(textureSurface->w) * 4);
        }

        const Rml::TextureHandle texture = RenderInterface_GL3::GenerateTexture({pixels.data(), pixels.size()}, textureDimensions);
        if (!texture)
        {
            std::cerr << "SGFX brand texture GL3 upload failed: " << texturePathString << "\n";
            return {};
        }

        std::cout << "SGFX clean brand texture loaded: " << normaliseTextureSource(source) << " (" << textureDimensions.x << "x" << textureDimensions.y << ")\n";
        return texture;
    }

    void registerBorrowedTexture(Rml::TextureHandle texture)
    {
        if (texture && std::find(m_borrowedTextures.begin(), m_borrowedTextures.end(), texture) == m_borrowedTextures.end())
            m_borrowedTextures.push_back(texture);
    }

    void ReleaseTexture(Rml::TextureHandle texture) override
    {
        if (std::find(m_borrowedTextures.begin(), m_borrowedTextures.end(), texture) != m_borrowedTextures.end())
        {
            ++m_borrowedReleaseSkips;
            std::cout << "SGFX cinematic shell borrowed texture release skipped: " << texture << "\n";
            return;
        }
        RenderInterface_GL3::ReleaseTexture(texture);
    }

    size_t borrowedReleaseSkips() const
    {
        return m_borrowedReleaseSkips;
    }

private:
    static std::filesystem::path canonicalOrAbsolute(std::filesystem::path path)
    {
        std::error_code ec;
        std::filesystem::path canonicalPath = std::filesystem::weakly_canonical(path, ec);
        if (!ec)
            return canonicalPath;
        return std::filesystem::absolute(path);
    }

    static std::string normaliseTextureSource(const std::string& source)
    {
        std::string normalised = source;
        std::replace(normalised.begin(), normalised.end(), '\\', '/');
        while (normalised.rfind("./", 0) == 0)
            normalised.erase(0, 2);
        return normalised;
    }

    static bool isAllowedBrandTexture(const std::string& source)
    {
        static constexpr std::array<const char*, 4> allowedSources = {
            "brand/logo_sgfx.png",
            "brand/framework_sgfx_logo.png",
            "brand/debug_icon.png",
            "brand/sgfx_icon.png",
        };
        return std::find(allowedSources.begin(), allowedSources.end(), source) != allowedSources.end();
    }

    std::filesystem::path resolveAllowedTexturePath(const Rml::String& source) const
    {
        const std::string normalised = normaliseTextureSource(source);
        if (normalised.empty() || normalised.front() == '/' || normalised.find(':') != std::string::npos || normalised.find("..") != std::string::npos)
        {
            std::cerr << "SGFX clean brand texture refused unsafe path: " << source << "\n";
            return {};
        }
        if (!isAllowedBrandTexture(normalised))
        {
            std::cerr << "SGFX clean brand texture refused non-allowlisted asset: " << source << "\n";
            return {};
        }

        const std::filesystem::path candidate = canonicalOrAbsolute(m_assetRoot / std::filesystem::path(normalised));
        if (!std::filesystem::is_regular_file(candidate))
        {
            std::cerr << "SGFX clean brand texture allowlisted but missing: " << candidate.string() << "\n";
            return {};
        }
        return candidate;
    }

    static void premultiplyAlpha(SDL_Surface* surface)
    {
        if (!surface || surface->format != SDL_PIXELFORMAT_RGBA32 || !surface->pixels)
            return;

        const bool locked = SDL_MUSTLOCK(surface);
        if (locked && !SDL_LockSurface(surface))
            return;

        auto* pixels = static_cast<Uint8*>(surface->pixels);
        for (int y = 0; y < surface->h; ++y)
        {
            auto* row = pixels + y * surface->pitch;
            for (int x = 0; x < surface->w; ++x)
            {
                auto* pixel = row + x * 4;
                const int alpha = pixel[3];
                pixel[0] = static_cast<Uint8>((static_cast<int>(pixel[0]) * alpha) / 255);
                pixel[1] = static_cast<Uint8>((static_cast<int>(pixel[1]) * alpha) / 255);
                pixel[2] = static_cast<Uint8>((static_cast<int>(pixel[2]) * alpha) / 255);
            }
        }

        if (locked)
            SDL_UnlockSurface(surface);
    }

    std::filesystem::path m_assetRoot;
    std::vector<Rml::TextureHandle> m_borrowedTextures;
    size_t m_borrowedReleaseSkips = 0u;
};

class SdlRmlRenderInterface final : public Rml::RenderInterface
{
public:
    SdlRmlRenderInterface(SDL_Renderer* renderer, std::filesystem::path assetRoot)
        : m_renderer(renderer)
        , m_assetRoot(canonicalOrAbsolute(std::move(assetRoot)))
    {
        m_blendMode = SDL_ComposeCustomBlendMode(
            SDL_BLENDFACTOR_ONE,
            SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
            SDL_BLENDOPERATION_ADD,
            SDL_BLENDFACTOR_ONE,
            SDL_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
            SDL_BLENDOPERATION_ADD);
    }

    void beginFrame()
    {
        SDL_SetRenderViewport(m_renderer, nullptr);
        SDL_SetRenderClipRect(m_renderer, nullptr);
        renderAdventureDawnGradient();
        SDL_SetRenderDrawBlendMode(m_renderer, m_blendMode);
    }

    Rml::CompiledGeometryHandle CompileGeometry(Rml::Span<const Rml::Vertex> vertices, Rml::Span<const int> indices) override
    {
        auto* geometry = new Geometry;
        geometry->vertices.assign(vertices.data(), vertices.data() + vertices.size());
        geometry->indices.assign(indices.data(), indices.data() + indices.size());
        return reinterpret_cast<Rml::CompiledGeometryHandle>(geometry);
    }

    void RenderGeometry(Rml::CompiledGeometryHandle handle, Rml::Vector2f translation, Rml::TextureHandle texture) override
    {
        const auto* geometry = reinterpret_cast<const Geometry*>(handle);
        if (!geometry || geometry->vertices.empty() || geometry->indices.empty())
            return;

        std::vector<SDL_Vertex> vertices;
        vertices.reserve(geometry->vertices.size());
        for (const Rml::Vertex& vertex : geometry->vertices)
        {
            SDL_Vertex sdlVertex{};
            sdlVertex.position = {vertex.position.x + translation.x, vertex.position.y + translation.y};
            sdlVertex.tex_coord = {vertex.tex_coord.x, vertex.tex_coord.y};
            sdlVertex.color = {
                vertex.colour.red / 255.0f,
                vertex.colour.green / 255.0f,
                vertex.colour.blue / 255.0f,
                vertex.colour.alpha / 255.0f};
            vertices.push_back(sdlVertex);
        }

        SDL_RenderGeometry(
            m_renderer,
            reinterpret_cast<SDL_Texture*>(texture),
            vertices.data(),
            static_cast<int>(vertices.size()),
            geometry->indices.data(),
            static_cast<int>(geometry->indices.size()));
    }

    void ReleaseGeometry(Rml::CompiledGeometryHandle handle) override
    {
        delete reinterpret_cast<Geometry*>(handle);
    }

    Rml::TextureHandle LoadTexture(Rml::Vector2i& textureDimensions, const Rml::String& source) override
    {
        textureDimensions = {0, 0};
        const std::filesystem::path texturePath = resolveAllowedTexturePath(source);
        if (texturePath.empty())
            return {};

        const std::string texturePathString = texturePath.string();
        std::unique_ptr<SDL_Surface, decltype(&SDL_DestroySurface)> loaded(SDL_LoadPNG(texturePathString.c_str()), SDL_DestroySurface);
        if (!loaded)
        {
            std::cerr << "SGFX brand texture load failed: " << texturePathString << " :: " << SDL_GetError() << "\n";
            return {};
        }

        SDL_Surface* textureSurface = loaded.get();
        std::unique_ptr<SDL_Surface, decltype(&SDL_DestroySurface)> converted(nullptr, SDL_DestroySurface);
        if (textureSurface->format != SDL_PIXELFORMAT_RGBA32)
        {
            converted.reset(SDL_ConvertSurface(textureSurface, SDL_PIXELFORMAT_RGBA32));
            if (!converted)
            {
                std::cerr << "SGFX brand texture conversion failed: " << texturePathString << " :: " << SDL_GetError() << "\n";
                return {};
            }
            textureSurface = converted.get();
        }

        premultiplyAlpha(textureSurface);
        SDL_Texture* texture = SDL_CreateTextureFromSurface(m_renderer, textureSurface);
        if (!texture)
        {
            std::cerr << "SGFX brand texture upload failed: " << texturePathString << " :: " << SDL_GetError() << "\n";
            return {};
        }

        SDL_SetTextureBlendMode(texture, m_blendMode);
        SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_LINEAR);
        textureDimensions = {textureSurface->w, textureSurface->h};
        std::cout << "SGFX clean brand texture loaded: " << normaliseTextureSource(source) << " (" << textureDimensions.x << "x" << textureDimensions.y << ")\n";
        return reinterpret_cast<Rml::TextureHandle>(texture);
    }

    Rml::TextureHandle GenerateTexture(Rml::Span<const Rml::byte> source, Rml::Vector2i sourceDimensions) override
    {
        if (!source.data() || sourceDimensions.x <= 0 || sourceDimensions.y <= 0)
            return {};

        SDL_Surface* surface = SDL_CreateSurfaceFrom(
            sourceDimensions.x,
            sourceDimensions.y,
            SDL_PIXELFORMAT_RGBA32,
            const_cast<Rml::byte*>(source.data()),
            sourceDimensions.x * 4);
        if (!surface)
            return {};

        SDL_Texture* texture = SDL_CreateTextureFromSurface(m_renderer, surface);
        SDL_DestroySurface(surface);
        if (texture)
            SDL_SetTextureBlendMode(texture, m_blendMode);

        return reinterpret_cast<Rml::TextureHandle>(texture);
    }

    void ReleaseTexture(Rml::TextureHandle texture) override
    {
        SDL_DestroyTexture(reinterpret_cast<SDL_Texture*>(texture));
    }

    void EnableScissorRegion(bool enable) override
    {
        m_scissorEnabled = enable;
        SDL_SetRenderClipRect(m_renderer, enable ? &m_scissor : nullptr);
    }

    void SetScissorRegion(Rml::Rectanglei region) override
    {
        m_scissor.x = region.Left();
        m_scissor.y = region.Top();
        m_scissor.w = region.Width();
        m_scissor.h = region.Height();
        if (m_scissorEnabled)
            SDL_SetRenderClipRect(m_renderer, &m_scissor);
    }

private:
    struct Geometry
    {
        std::vector<Rml::Vertex> vertices;
        std::vector<int> indices;
    };

    void renderAdventureDawnGradient()
    {
        int width = 0;
        int height = 0;
        if (!SDL_GetCurrentRenderOutputSize(m_renderer, &width, &height) || width <= 0 || height <= 0)
        {
            SDL_SetRenderDrawBlendMode(m_renderer, SDL_BLENDMODE_NONE);
            SDL_SetRenderDrawColor(m_renderer, 27, 44, 102, 255);
            SDL_RenderClear(m_renderer);
            return;
        }

        SDL_SetRenderDrawBlendMode(m_renderer, SDL_BLENDMODE_NONE);
        SDL_SetRenderDrawColor(m_renderer, 27, 44, 102, 255);
        SDL_RenderClear(m_renderer);

        const std::array<std::array<int, 3>, 3> stops = {{
            {255, 179, 107},
            {47, 214, 230},
            {27, 44, 102},
        }};
        const double split = 0.43;
        for (int y = 0; y < height; ++y)
        {
            const double t = height > 1 ? static_cast<double>(y) / static_cast<double>(height - 1) : 0.0;
            const bool topHalf = t <= split;
            const double local = topHalf ? clamp01(t / split) : clamp01((t - split) / (1.0 - split));
            const double eased = local * local * (3.0 - 2.0 * local);
            const auto& a = topHalf ? stops[0] : stops[1];
            const auto& b = topHalf ? stops[1] : stops[2];
            const auto channel = [&](int index) {
                return static_cast<Uint8>(std::round(static_cast<double>(a[index]) + (static_cast<double>(b[index] - a[index]) * eased)));
            };
            SDL_SetRenderDrawColor(m_renderer, channel(0), channel(1), channel(2), 255);
            const SDL_FRect line = {0.0f, static_cast<float>(y), static_cast<float>(width), 1.0f};
            SDL_RenderFillRect(m_renderer, &line);
        }
    }

    static std::filesystem::path canonicalOrAbsolute(std::filesystem::path path)
    {
        std::error_code ec;
        std::filesystem::path canonicalPath = std::filesystem::weakly_canonical(path, ec);
        if (!ec)
            return canonicalPath;
        return std::filesystem::absolute(path);
    }

    static std::string normaliseTextureSource(const std::string& source)
    {
        std::string normalised = source;
        std::replace(normalised.begin(), normalised.end(), '\\', '/');
        while (normalised.rfind("./", 0) == 0)
            normalised.erase(0, 2);
        return normalised;
    }

    static bool isAllowedBrandTexture(const std::string& source)
    {
        static constexpr std::array<const char*, 4> allowedSources = {
            "brand/logo_sgfx.png",
            "brand/framework_sgfx_logo.png",
            "brand/debug_icon.png",
            "brand/sgfx_icon.png",
        };
        return std::find(allowedSources.begin(), allowedSources.end(), source) != allowedSources.end();
    }

    std::filesystem::path resolveAllowedTexturePath(const Rml::String& source) const
    {
        const std::string normalised = normaliseTextureSource(source);
        if (normalised.empty() || normalised.front() == '/' || normalised.find(':') != std::string::npos || normalised.find("..") != std::string::npos)
        {
            std::cerr << "SGFX clean brand texture refused unsafe path: " << source << "\n";
            return {};
        }
        if (!isAllowedBrandTexture(normalised))
        {
            std::cerr << "SGFX clean brand texture refused non-allowlisted asset: " << source << "\n";
            return {};
        }

        const std::filesystem::path candidate = canonicalOrAbsolute(m_assetRoot / std::filesystem::path(normalised));
        if (!std::filesystem::is_regular_file(candidate))
        {
            std::cerr << "SGFX clean brand texture allowlisted but missing: " << candidate.string() << "\n";
            return {};
        }
        return candidate;
    }

    static void premultiplyAlpha(SDL_Surface* surface)
    {
        if (!surface || surface->format != SDL_PIXELFORMAT_RGBA32 || !surface->pixels)
            return;

        const bool locked = SDL_MUSTLOCK(surface);
        if (locked && !SDL_LockSurface(surface))
            return;

        auto* pixels = static_cast<Uint8*>(surface->pixels);
        for (int y = 0; y < surface->h; ++y)
        {
            auto* row = pixels + y * surface->pitch;
            for (int x = 0; x < surface->w; ++x)
            {
                auto* pixel = row + x * 4;
                const int alpha = pixel[3];
                pixel[0] = static_cast<Uint8>((static_cast<int>(pixel[0]) * alpha) / 255);
                pixel[1] = static_cast<Uint8>((static_cast<int>(pixel[1]) * alpha) / 255);
                pixel[2] = static_cast<Uint8>((static_cast<int>(pixel[2]) * alpha) / 255);
            }
        }

        if (locked)
            SDL_UnlockSurface(surface);
    }

    SDL_Renderer* m_renderer = nullptr;
    std::filesystem::path m_assetRoot;
    SDL_BlendMode m_blendMode = SDL_BLENDMODE_BLEND;
    SDL_Rect m_scissor{};
    bool m_scissorEnabled = false;
};

class ShellSystemInterface final : public Rml::SystemInterface
{
public:
    double GetElapsedTime() override
    {
        return SDL_GetTicks() / 1000.0;
    }
};

struct ProceduralFace
{
    int size = 48;
    Rml::FontMetrics metrics{};
};

using GlyphRows = std::array<const char*, 7>;

GlyphRows glyphRows(char ch)
{
    switch (static_cast<char>(std::toupper(static_cast<unsigned char>(ch))))
    {
    case 'A': return {"01110", "10001", "10001", "11111", "10001", "10001", "10001"};
    case 'B': return {"11110", "10001", "10001", "11110", "10001", "10001", "11110"};
    case 'C': return {"01111", "10000", "10000", "10000", "10000", "10000", "01111"};
    case 'D': return {"11110", "10001", "10001", "10001", "10001", "10001", "11110"};
    case 'E': return {"11111", "10000", "10000", "11110", "10000", "10000", "11111"};
    case 'F': return {"11111", "10000", "10000", "11110", "10000", "10000", "10000"};
    case 'G': return {"01111", "10000", "10000", "10111", "10001", "10001", "01111"};
    case 'H': return {"10001", "10001", "10001", "11111", "10001", "10001", "10001"};
    case 'I': return {"11111", "00100", "00100", "00100", "00100", "00100", "11111"};
    case 'J': return {"00111", "00010", "00010", "00010", "10010", "10010", "01100"};
    case 'K': return {"10001", "10010", "10100", "11000", "10100", "10010", "10001"};
    case 'L': return {"10000", "10000", "10000", "10000", "10000", "10000", "11111"};
    case 'M': return {"10001", "11011", "10101", "10101", "10001", "10001", "10001"};
    case 'N': return {"10001", "11001", "10101", "10011", "10001", "10001", "10001"};
    case 'O': return {"01110", "10001", "10001", "10001", "10001", "10001", "01110"};
    case 'P': return {"11110", "10001", "10001", "11110", "10000", "10000", "10000"};
    case 'Q': return {"01110", "10001", "10001", "10001", "10101", "10010", "01101"};
    case 'R': return {"11110", "10001", "10001", "11110", "10100", "10010", "10001"};
    case 'S': return {"01111", "10000", "10000", "01110", "00001", "00001", "11110"};
    case 'T': return {"11111", "00100", "00100", "00100", "00100", "00100", "00100"};
    case 'U': return {"10001", "10001", "10001", "10001", "10001", "10001", "01110"};
    case 'V': return {"10001", "10001", "10001", "10001", "10001", "01010", "00100"};
    case 'W': return {"10001", "10001", "10001", "10101", "10101", "10101", "01010"};
    case 'X': return {"10001", "10001", "01010", "00100", "01010", "10001", "10001"};
    case 'Y': return {"10001", "10001", "01010", "00100", "00100", "00100", "00100"};
    case 'Z': return {"11111", "00001", "00010", "00100", "01000", "10000", "11111"};
    case '0': return {"01110", "10001", "10011", "10101", "11001", "10001", "01110"};
    case '1': return {"00100", "01100", "00100", "00100", "00100", "00100", "01110"};
    case '2': return {"01110", "10001", "00001", "00010", "00100", "01000", "11111"};
    case '3': return {"11110", "00001", "00001", "01110", "00001", "00001", "11110"};
    case '4': return {"10010", "10010", "10010", "11111", "00010", "00010", "00010"};
    case '5': return {"11111", "10000", "10000", "11110", "00001", "00001", "11110"};
    case '6': return {"01111", "10000", "10000", "11110", "10001", "10001", "01110"};
    case '7': return {"11111", "00001", "00010", "00100", "01000", "01000", "01000"};
    case '8': return {"01110", "10001", "10001", "01110", "10001", "10001", "01110"};
    case '9': return {"01110", "10001", "10001", "01111", "00001", "00001", "11110"};
    case '-': return {"00000", "00000", "00000", "11111", "00000", "00000", "00000"};
    case '_': return {"00000", "00000", "00000", "00000", "00000", "00000", "11111"};
    case ':': return {"00000", "00100", "00100", "00000", "00100", "00100", "00000"};
    case '.': return {"00000", "00000", "00000", "00000", "00000", "01100", "01100"};
    case '/': return {"00001", "00001", "00010", "00100", "01000", "10000", "10000"};
    default: return {"00000", "00000", "00000", "00000", "00000", "00000", "00000"};
    }
}

class ProceduralFontEngine final : public Rml::FontEngineInterface
{
public:
    bool LoadFontFace(const Rml::String&, int, bool, Rml::Style::FontWeight) override
    {
        return true;
    }

    bool LoadFontFace(
        Rml::Span<const Rml::byte>,
        int,
        const Rml::String&,
        Rml::Style::FontStyle,
        Rml::Style::FontWeight,
        bool) override
    {
        return true;
    }

    Rml::FontFaceHandle GetFontFaceHandle(const Rml::String&, Rml::Style::FontStyle, Rml::Style::FontWeight, int size) override
    {
        const int clampedSize = std::max(8, size);
        for (const auto& face : m_faces)
        {
            if (face->size == clampedSize)
                return reinterpret_cast<Rml::FontFaceHandle>(face.get());
        }

        auto face = std::make_unique<ProceduralFace>();
        face->size = clampedSize;
        const float cell = cellSize(*face);
        face->metrics.size = clampedSize;
        face->metrics.ascent = 7.0f * cell;
        face->metrics.descent = 1.0f * cell;
        face->metrics.line_spacing = 9.0f * cell;
        face->metrics.x_height = 5.0f * cell;
        face->metrics.underline_position = 1.0f * cell;
        face->metrics.underline_thickness = std::max(1.0f, cell * 0.32f);
        face->metrics.has_ellipsis = false;

        ProceduralFace* raw = face.get();
        m_faces.push_back(std::move(face));
        return reinterpret_cast<Rml::FontFaceHandle>(raw);
    }

    Rml::FontEffectsHandle PrepareFontEffects(Rml::FontFaceHandle, const Rml::FontEffectList&) override
    {
        return 0;
    }

    const Rml::FontMetrics& GetFontMetrics(Rml::FontFaceHandle handle) override
    {
        return faceFromHandle(handle).metrics;
    }

    int GetStringWidth(
        Rml::FontFaceHandle handle,
        Rml::StringView string,
        const Rml::TextShapingContext&,
        Rml::Character = Rml::Character::Null) override
    {
        const ProceduralFace& face = faceFromHandle(handle);
        const float cell = cellSize(face);
        float width = 0.0f;
        for (const char* it = string.begin(); it != string.end(); ++it)
            width += (*it == ' ') ? 4.0f * cell : 6.0f * cell;
        return static_cast<int>(std::ceil(width));
    }

    int GenerateString(
        Rml::RenderManager&,
        Rml::FontFaceHandle handle,
        Rml::FontEffectsHandle,
        Rml::StringView string,
        Rml::Vector2f position,
        Rml::ColourbPremultiplied colour,
        float opacity,
        const Rml::TextShapingContext&,
        Rml::TexturedMeshList& meshList) override
    {
        const ProceduralFace& face = faceFromHandle(handle);
        const float cell = cellSize(face);
        const float stroke = std::max(1.0f, cell * 0.86f);
        const float top = position.y - face.metrics.ascent;
        float cursor = position.x;

        Rml::ColourbPremultiplied drawColour = colour;
        drawColour.red = static_cast<Rml::byte>(drawColour.red * opacity);
        drawColour.green = static_cast<Rml::byte>(drawColour.green * opacity);
        drawColour.blue = static_cast<Rml::byte>(drawColour.blue * opacity);
        drawColour.alpha = static_cast<Rml::byte>(drawColour.alpha * opacity);

        meshList.resize(1);
        Rml::Mesh& mesh = meshList[0].mesh;

        for (const char* it = string.begin(); it != string.end(); ++it)
        {
            const char ch = *it;
            if (ch == ' ')
            {
                cursor += 4.0f * cell;
                continue;
            }

            const GlyphRows rows = glyphRows(ch);
            for (int y = 0; y < 7; ++y)
            {
                for (int x = 0; x < 5; ++x)
                {
                    if (rows[y][x] != '1')
                        continue;
                    Rml::MeshUtilities::GenerateQuad(
                        mesh,
                        {std::round(cursor + x * cell), std::round(top + y * cell)},
                        {stroke, stroke},
                        drawColour);
                }
            }
            cursor += 6.0f * cell;
        }

        return static_cast<int>(std::ceil(cursor - position.x));
    }

    int GetVersion(Rml::FontFaceHandle) override
    {
        return 1;
    }

private:
    static float cellSize(const ProceduralFace& face)
    {
        return std::max(1.0f, face.size / 7.0f);
    }

    static ProceduralFace& faceFromHandle(Rml::FontFaceHandle handle)
    {
        return *reinterpret_cast<ProceduralFace*>(handle);
    }

    std::vector<std::unique_ptr<ProceduralFace>> m_faces;
};

class RmlRuntime
{
public:
    RmlRuntime()
    {
        if (!Rml::Initialise())
            throw std::runtime_error("Rml::Initialise failed");
    }

    ~RmlRuntime()
    {
        Rml::Shutdown();
    }
};

void loadRequiredFontFace(const std::filesystem::path& fontRoot, const char* fileName, bool fallbackFace)
{
    const std::filesystem::path fontPath = fontRoot / fileName;
    require(std::filesystem::is_regular_file(fontPath), "Missing cinematic shell font: " + fontPath.string());
    require(Rml::LoadFontFace(fontPath.string(), fallbackFace), "RmlUi failed to load font: " + fontPath.string());
}

void loadShellFonts(const std::filesystem::path& fontRoot)
{
    loadRequiredFontFace(fontRoot, "Fredoka.ttf", false);
    loadRequiredFontFace(fontRoot, "Inter.ttf", true);
}

std::string ramsesVersionString(const ramses::VersionInfo& version)
{
    return std::to_string(version.major) + "." + std::to_string(version.minor) + "." + std::to_string(version.patch);
}

const char* ramsesSceneStateName(ramses::RendererSceneState state)
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

class SdlPlainWindow
{
public:
    SdlPlainWindow(const char* title, int width, int height, SDL_WindowFlags flags)
        : m_window(SDL_CreateWindow(title, width, height, flags))
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
    throw std::runtime_error("Ramses fusion currently requires the SDL3 Win32 backend");
#endif
}

struct FusionReadbackStats
{
    uint32_t width = 0u;
    uint32_t height = 0u;
    uint64_t brightPixels = 0u;
    uint64_t transparentPixels = 0u;
    uint64_t translucentPixels = 0u;
    uint8_t minAlpha = 255u;
    uint8_t maxAlpha = 0u;
    uint32_t minX = UINT32_MAX;
    uint32_t minY = UINT32_MAX;
    uint32_t maxX = 0u;
    uint32_t maxY = 0u;
};

FusionReadbackStats calculateFusionBrightPixels(const std::vector<uint8_t>& pixels, uint32_t width, uint32_t height)
{
    FusionReadbackStats stats;
    stats.width = width;
    stats.height = height;

    uint32_t x = 0u;
    uint32_t y = 0u;
    for (size_t i = 0; i + 3u < pixels.size(); i += 4u)
    {
        const uint8_t alpha = pixels[i + 3u];
        stats.minAlpha = std::min(stats.minAlpha, alpha);
        stats.maxAlpha = std::max(stats.maxAlpha, alpha);
        if (alpha == 0u)
            ++stats.transparentPixels;
        else if (alpha < 255u)
            ++stats.translucentPixels;

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

std::string lowerAscii(std::string value)
{
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

bool startsWithInsensitive(const std::string& value, const std::string& prefix)
{
    if (value.size() < prefix.size())
        return false;
    return lowerAscii(value.substr(0u, prefix.size())) == lowerAscii(prefix);
}

bool endsWithInsensitive(const std::string& value, const std::string& suffix)
{
    if (value.size() < suffix.size())
        return false;
    return lowerAscii(value.substr(value.size() - suffix.size())) == lowerAscii(suffix);
}

std::string readTextFile(const std::filesystem::path& path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream)
        throw std::runtime_error("Could not open text file: " + path.string());
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

class JsonCursor
{
public:
    JsonCursor(const std::string& text, size_t position, size_t end)
        : m_text(text)
        , m_position(position)
        , m_end(end)
    {
    }

    size_t position() const
    {
        return m_position;
    }

    void skipWhitespace()
    {
        while (m_position < m_end && std::isspace(static_cast<unsigned char>(m_text[m_position])))
            ++m_position;
    }

    bool consume(char expected)
    {
        skipWhitespace();
        if (m_position < m_end && m_text[m_position] == expected)
        {
            ++m_position;
            return true;
        }
        return false;
    }

    void expect(char expected)
    {
        if (!consume(expected))
            throw std::runtime_error(std::string("Malformed perspective JSON: expected '") + expected + "'");
    }

    std::string parseString()
    {
        skipWhitespace();
        if (m_position >= m_end || m_text[m_position] != '"')
            throw std::runtime_error("Malformed perspective JSON: expected string");
        ++m_position;

        std::string value;
        while (m_position < m_end)
        {
            const char ch = m_text[m_position++];
            if (ch == '"')
                return value;
            if (ch != '\\')
            {
                value.push_back(ch);
                continue;
            }

            if (m_position >= m_end)
                throw std::runtime_error("Malformed perspective JSON: truncated escape");
            const char escaped = m_text[m_position++];
            switch (escaped)
            {
            case '"':
            case '\\':
            case '/':
                value.push_back(escaped);
                break;
            case 'b':
                value.push_back('\b');
                break;
            case 'f':
                value.push_back('\f');
                break;
            case 'n':
                value.push_back('\n');
                break;
            case 'r':
                value.push_back('\r');
                break;
            case 't':
                value.push_back('\t');
                break;
            case 'u':
                if (m_position + 4u > m_end)
                    throw std::runtime_error("Malformed perspective JSON: truncated unicode escape");
                m_position += 4u;
                value.push_back('?');
                break;
            default:
                throw std::runtime_error("Malformed perspective JSON: unsupported escape");
            }
        }
        throw std::runtime_error("Malformed perspective JSON: unterminated string");
    }

    double parseNumber()
    {
        skipWhitespace();
        const char* begin = m_text.c_str() + m_position;
        char* parsedEnd = nullptr;
        const double value = std::strtod(begin, &parsedEnd);
        const size_t nextPosition = static_cast<size_t>(parsedEnd - m_text.c_str());
        if (parsedEnd == begin || nextPosition > m_end || !std::isfinite(value))
            throw std::runtime_error("Malformed perspective JSON: expected finite number");
        m_position = nextPosition;
        return value;
    }

    bool parseBool()
    {
        skipWhitespace();
        if (m_position + 4u <= m_end && m_text.compare(m_position, 4u, "true") == 0)
        {
            m_position += 4u;
            return true;
        }
        if (m_position + 5u <= m_end && m_text.compare(m_position, 5u, "false") == 0)
        {
            m_position += 5u;
            return false;
        }
        throw std::runtime_error("Malformed perspective JSON: expected boolean");
    }

    void skipValue()
    {
        skipWhitespace();
        if (m_position >= m_end)
            throw std::runtime_error("Malformed perspective JSON: missing value");

        const char ch = m_text[m_position];
        if (ch == '"')
        {
            (void)parseString();
            return;
        }
        if (ch == '{')
        {
            ++m_position;
            skipWhitespace();
            if (consume('}'))
                return;
            while (true)
            {
                (void)parseString();
                expect(':');
                skipValue();
                if (consume('}'))
                    return;
                expect(',');
            }
        }
        if (ch == '[')
        {
            ++m_position;
            skipWhitespace();
            if (consume(']'))
                return;
            while (true)
            {
                skipValue();
                if (consume(']'))
                    return;
                expect(',');
            }
        }
        if (ch == 't' || ch == 'f')
        {
            (void)parseBool();
            return;
        }
        if (m_position + 4u <= m_end && m_text.compare(m_position, 4u, "null") == 0)
        {
            m_position += 4u;
            return;
        }
        (void)parseNumber();
    }

private:
    const std::string& m_text;
    size_t m_position = 0u;
    size_t m_end = 0u;
};

struct JsonObjectEntry
{
    std::string name;
    size_t valueBegin = 0u;
    size_t valueEnd = 0u;
};

std::vector<JsonObjectEntry> parseJsonObjectEntries(const std::string& text, size_t begin, size_t end)
{
    JsonCursor cursor(text, begin, end);
    std::vector<JsonObjectEntry> entries;
    cursor.expect('{');
    cursor.skipWhitespace();
    if (cursor.consume('}'))
        return entries;

    while (true)
    {
        const std::string name = cursor.parseString();
        cursor.expect(':');
        cursor.skipWhitespace();
        const size_t valueBegin = cursor.position();
        cursor.skipValue();
        const size_t valueEnd = cursor.position();
        entries.push_back({name, valueBegin, valueEnd});
        if (cursor.consume('}'))
            break;
        cursor.expect(',');
    }
    return entries;
}

const JsonObjectEntry* findJsonEntry(const std::vector<JsonObjectEntry>& entries, const std::string& name)
{
    const auto found = std::find_if(entries.begin(), entries.end(), [&](const JsonObjectEntry& entry) {
        return entry.name == name;
    });
    return found == entries.end() ? nullptr : &*found;
}

std::vector<JsonObjectEntry> requireObjectField(const std::string& text,
                                                const std::vector<JsonObjectEntry>& entries,
                                                const std::string& fieldName)
{
    const auto* entry = findJsonEntry(entries, fieldName);
    if (!entry)
        throw std::runtime_error("Perspective JSON missing object field: " + fieldName);
    return parseJsonObjectEntries(text, entry->valueBegin, entry->valueEnd);
}

double requireNumberField(const std::string& text, const std::vector<JsonObjectEntry>& entries, const std::string& fieldName)
{
    const auto* entry = findJsonEntry(entries, fieldName);
    if (!entry)
        throw std::runtime_error("Perspective JSON missing number field: " + fieldName);
    JsonCursor cursor(text, entry->valueBegin, entry->valueEnd);
    const double value = cursor.parseNumber();
    cursor.skipWhitespace();
    if (cursor.position() != entry->valueEnd)
        throw std::runtime_error("Perspective JSON field is not a plain number: " + fieldName);
    return value;
}

bool requireBoolField(const std::string& text, const std::vector<JsonObjectEntry>& entries, const std::string& fieldName)
{
    const auto* entry = findJsonEntry(entries, fieldName);
    if (!entry)
        throw std::runtime_error("Perspective JSON missing bool field: " + fieldName);
    JsonCursor cursor(text, entry->valueBegin, entry->valueEnd);
    const bool value = cursor.parseBool();
    cursor.skipWhitespace();
    if (cursor.position() != entry->valueEnd)
        throw std::runtime_error("Perspective JSON field is not a plain bool: " + fieldName);
    return value;
}

std::vector<double> requireNumberArrayField(const std::string& text,
                                            const std::vector<JsonObjectEntry>& entries,
                                            const std::string& fieldName,
                                            size_t expectedCount)
{
    const auto* entry = findJsonEntry(entries, fieldName);
    if (!entry)
        throw std::runtime_error("Perspective JSON missing number array field: " + fieldName);

    JsonCursor cursor(text, entry->valueBegin, entry->valueEnd);
    std::vector<double> values;
    cursor.expect('[');
    cursor.skipWhitespace();
    if (!cursor.consume(']'))
    {
        while (true)
        {
            values.push_back(cursor.parseNumber());
            if (cursor.consume(']'))
                break;
            cursor.expect(',');
        }
    }
    cursor.skipWhitespace();
    if (cursor.position() != entry->valueEnd || values.size() != expectedCount)
        throw std::runtime_error("Perspective JSON field has unexpected array shape: " + fieldName);
    return values;
}

std::string perspectiveSetNameFromFile(const std::filesystem::path& file)
{
    std::string name = file.stem().string();
    constexpr std::string_view prefix = "perspectives_";
    if (startsWithInsensitive(name, std::string(prefix)))
        name = name.substr(prefix.size());
    return name;
}

struct FusionCarCandidate
{
    std::string profileId;
    std::string folderName;
    std::string label;
    std::filesystem::path sceneFile;
    std::filesystem::path profileDir;
    std::string defaultPerspectiveSet;
    std::filesystem::path defaultPerspectiveFile;
    int registryRank = 1000000;
    bool registryMatched = false;
};

void appendUniqueProfileId(std::vector<std::string>& profileIds, std::string profileId)
{
    if (profileId.empty())
        return;
    if (std::find_if(profileIds.begin(), profileIds.end(), [&](const std::string& existing) {
            return lowerAscii(existing) == lowerAscii(profileId);
        }) == profileIds.end())
    {
        profileIds.push_back(std::move(profileId));
    }
}

std::vector<std::string> parseProfileRegistryIds(const std::string& text)
{
    std::vector<std::string> profileIds;
    size_t position = 0u;
    while ((position = text.find("\"profile_id\"", position)) != std::string::npos)
    {
        const size_t colon = text.find(':', position);
        if (colon == std::string::npos)
            break;
        size_t valueBegin = colon + 1u;
        while (valueBegin < text.size() && std::isspace(static_cast<unsigned char>(text[valueBegin])))
            ++valueBegin;
        if (valueBegin >= text.size() || text[valueBegin] != '"')
        {
            position = colon + 1u;
            continue;
        }
        const size_t quote = valueBegin;
        const size_t endQuote = text.find('"', quote + 1u);
        if (endQuote == std::string::npos)
            break;
        appendUniqueProfileId(profileIds, text.substr(quote + 1u, endQuote - quote - 1u));
        position = endQuote + 1u;
    }

    position = 0u;
    while ((position = text.find("for profile_id in", position)) != std::string::npos)
    {
        const size_t tupleBegin = text.find('(', position);
        const size_t tupleEnd = tupleBegin == std::string::npos ? std::string::npos : text.find(')', tupleBegin + 1u);
        if (tupleBegin == std::string::npos || tupleEnd == std::string::npos)
            break;

        size_t itemPosition = tupleBegin;
        while (itemPosition < tupleEnd)
        {
            const size_t quote = text.find('"', itemPosition);
            if (quote == std::string::npos || quote >= tupleEnd)
                break;
            const size_t endQuote = text.find('"', quote + 1u);
            if (endQuote == std::string::npos || endQuote > tupleEnd)
                break;
            appendUniqueProfileId(profileIds, text.substr(quote + 1u, endQuote - quote - 1u));
            itemPosition = endQuote + 1u;
        }
        position = tupleEnd + 1u;
    }
    return profileIds;
}

std::vector<std::string> parseBmwModelRegistryIds(const std::string& text)
{
    std::vector<std::string> profileIds;
    std::istringstream stream(text);
    std::string line;
    while (std::getline(stream, line))
    {
        size_t position = 0u;
        while (position < line.size() && std::isspace(static_cast<unsigned char>(line[position])))
            ++position;
        if (position >= line.size() || line[position] != '-')
            continue;
        ++position;
        while (position < line.size() && std::isspace(static_cast<unsigned char>(line[position])))
            ++position;
        constexpr std::string_view nameKey = "name:";
        if (line.compare(position, nameKey.size(), nameKey.data(), nameKey.size()) != 0)
            continue;
        position += nameKey.size();
        while (position < line.size() && std::isspace(static_cast<unsigned char>(line[position])))
            ++position;

        std::string value = line.substr(position);
        const size_t comment = value.find('#');
        if (comment != std::string::npos)
            value.resize(comment);
        while (!value.empty() && std::isspace(static_cast<unsigned char>(value.back())))
            value.pop_back();
        if (value.size() >= 2u && ((value.front() == '"' && value.back() == '"') || (value.front() == '\'' && value.back() == '\'')))
            value = value.substr(1u, value.size() - 2u);
        appendUniqueProfileId(profileIds, value);
    }
    return profileIds;
}

std::filesystem::path findWorkspaceRoot()
{
    std::error_code ec;
    std::filesystem::path current = std::filesystem::current_path(ec);
    if (ec)
        return {};

    while (!current.empty())
    {
        if (std::filesystem::is_regular_file(current / "sg_preflight" / "profiles.py"))
            return current;
        if (current == current.root_path())
            break;
        current = current.parent_path();
    }
    return {};
}

std::filesystem::path resolveProfileRegistryFile(const Options& options)
{
    if (!options.profileRegistryFile.empty())
        return std::filesystem::absolute(options.profileRegistryFile);

    const std::filesystem::path workspaceRoot = findWorkspaceRoot();
    if (!workspaceRoot.empty())
    {
        const std::filesystem::path candidate = workspaceRoot / "sg_preflight" / "profiles.py";
        if (std::filesystem::is_regular_file(candidate))
            return std::filesystem::absolute(candidate);
    }
    return {};
}

std::vector<std::string> loadProfileRegistryIds(const Options& options)
{
    const std::filesystem::path registryFile = resolveProfileRegistryFile(options);
    if (registryFile.empty() || !std::filesystem::is_regular_file(registryFile))
        return {};
    return parseProfileRegistryIds(readTextFile(registryFile));
}

std::filesystem::path environmentPath(const char* name);
std::filesystem::path resolveCarsRoot(const Options& options);

std::filesystem::path resolveBmwModelsBuildConfigFile(const Options& options)
{
    std::vector<std::filesystem::path> candidates;
    const auto addRepoCandidate = [&](const std::filesystem::path& repoRoot) {
        if (!repoRoot.empty())
            candidates.push_back(repoRoot / "ci" / "scripts" / "common" / "models_build_config.yaml");
    };

    std::error_code ec;
    std::filesystem::path carsRoot = resolveCarsRoot(options);
    if (!carsRoot.empty())
    {
        carsRoot = std::filesystem::absolute(carsRoot, ec);
        if (!ec)
        {
            if (lowerAscii(carsRoot.filename().string()) == "bmw" && lowerAscii(carsRoot.parent_path().filename().string()) == "cars")
                addRepoCandidate(carsRoot.parent_path().parent_path());
            else if (lowerAscii(carsRoot.filename().string()) == "cars")
                addRepoCandidate(carsRoot.parent_path());
            else
                addRepoCandidate(carsRoot);
        }
    }

    addRepoCandidate(environmentPath("Digital-3D-Car-Repo"));
    addRepoCandidate(environmentPath("SG_BMW_CAR_MODELS_ROOT"));
    addRepoCandidate(environmentPath("SG_CARMODELS_REPO"));
    candidates.emplace_back("C:\\3D Car git\\digital-3d-car-models\\ci\\scripts\\common\\models_build_config.yaml");

    for (const auto& candidate : candidates)
    {
        if (!candidate.empty() && std::filesystem::is_regular_file(candidate))
            return std::filesystem::absolute(candidate);
    }
    return {};
}

struct FusionProfileRegistry
{
    std::vector<std::string> rankIds;
    size_t registeredCount = 0u;
    std::string countSource = "unavailable";
};

FusionProfileRegistry loadFusionProfileRegistry(const Options& options)
{
    FusionProfileRegistry registry;
    const std::vector<std::string> profileIds = loadProfileRegistryIds(options);
    for (const std::string& id : profileIds)
        appendUniqueProfileId(registry.rankIds, id);
    registry.registeredCount = profileIds.size();
    registry.countSource = profileIds.empty() ? "unavailable" : "sg_preflight/profiles.py";

    const std::filesystem::path bmwConfig = resolveBmwModelsBuildConfigFile(options);
    if (!bmwConfig.empty())
    {
        const std::vector<std::string> bmwIds = parseBmwModelRegistryIds(readTextFile(bmwConfig));
        if (!bmwIds.empty())
        {
            for (const std::string& id : bmwIds)
                appendUniqueProfileId(registry.rankIds, id);
            registry.registeredCount = bmwIds.size();
            registry.countSource = bmwConfig.string();
        }
    }
    return registry;
}

std::filesystem::path environmentPath(const char* name)
{
    const char* value = std::getenv(name);
    if (!value || !*value)
        return {};
    return std::filesystem::path(value);
}

std::filesystem::path resolveCarsRoot(const Options& options)
{
    std::vector<std::filesystem::path> candidates;
    if (!options.fusionCarsRoot.empty())
        candidates.push_back(options.fusionCarsRoot);
    const std::filesystem::path idcRepo = environmentPath("Digital-3D-Car-Repo-IDC23");
    if (!idcRepo.empty())
    {
        candidates.push_back(idcRepo / "cars" / "BMW");
        candidates.push_back(idcRepo);
    }
    candidates.push_back(environmentPath("SGFX_BMW_CARS_ROOT"));
    candidates.emplace_back("C:\\3D Car git\\digital-3d-car-models\\cars\\BMW");
    candidates.emplace_back("C:\\3D Car git\\digital-3d-car-models\\cars");

    for (const auto& candidate : candidates)
    {
        if (candidate.empty())
            continue;
        std::error_code ec;
        const std::filesystem::path absoluteCandidate = std::filesystem::absolute(candidate, ec);
        if (!ec && std::filesystem::is_directory(absoluteCandidate))
        {
            if (std::filesystem::is_directory(absoluteCandidate / "BMW"))
                return std::filesystem::absolute(absoluteCandidate / "BMW");
            return absoluteCandidate;
        }
    }
    return {};
}

std::filesystem::path firstExistingDirectory(std::initializer_list<std::filesystem::path> candidates)
{
    for (const auto& candidate : candidates)
    {
        if (candidate.empty())
            continue;
        std::error_code ec;
        const std::filesystem::path absoluteCandidate = std::filesystem::absolute(candidate, ec);
        if (!ec && std::filesystem::is_directory(absoluteCandidate))
            return absoluteCandidate;
    }
    return {};
}

std::filesystem::path resolveSourceRepoRoot()
{
    return firstExistingDirectory({
        environmentPath("SGFX_SOURCE_REPO_ROOT"),
        std::filesystem::path("C:\\repositories\\trunk"),
        environmentPath("SG_SOURCE_REPO_ROOT"),
        environmentPath("SG_REPO"),
    });
}

std::filesystem::path resolveBmwRepoRoot()
{
    return firstExistingDirectory({
        environmentPath("SGFX_BMW_CAR_MODELS_ROOT"),
        environmentPath("Digital-3D-Car-Repo"),
        std::filesystem::path("C:\\3D Car git\\digital-3d-car-models"),
        environmentPath("SG_BMW_CAR_MODELS_ROOT"),
        environmentPath("SG_CARMODELS_REPO"),
    });
}

std::string quoteCmdArg(const std::string& value)
{
    std::string quoted = "\"";
    for (char ch : value)
    {
        if (ch == '"')
            quoted += "\\\"";
        else
            quoted.push_back(ch);
    }
    quoted += "\"";
    return quoted;
}

std::string quoteCmdArg(const std::filesystem::path& value)
{
    return quoteCmdArg(value.string());
}

std::string pythonLauncherCommand()
{
    const char* configured = std::getenv("SGFX_PYTHON_EXE");
    if (configured && *configured)
        return quoteCmdArg(std::string(configured));
    return "py -3";
}

std::string runProcessCapture(const std::string& command, int& exitCode)
{
    exitCode = 1;
    FILE* pipe = _popen(command.c_str(), "rt");
    if (!pipe)
        return {};

    std::string output;
    std::array<char, 4096> buffer{};
    while (fgets(buffer.data(), static_cast<int>(buffer.size()), pipe))
        output += buffer.data();
    exitCode = _pclose(pipe);
    return output;
}

std::string shortError(const std::string& value)
{
    if (value.empty())
        return {};
    return value.substr(0u, std::min<size_t>(value.size(), 220u));
}

std::string formatSignedPercent(double value)
{
    std::ostringstream stream;
    if (value > 0.0)
        stream << "+";
    stream << std::fixed << std::setprecision(2) << value << "%";
    return stream.str();
}

struct HubCapitalSummary
{
    std::string label;
    bool loaded = false;
    std::string statusText = "UNAVAILABLE";
    std::string primaryText = "DATA UNAVAILABLE";
    std::string secondaryText = "CHECK PYTHON DATA LAYER";
    std::string bannerText = "Evidence unavailable - use Clean dashboard.";
    std::string sourceBanner;
    std::string sourceState;
    std::string sourceRoot;
    std::string bmwRoot;
    std::string error;
    std::string command;
};

struct HubCapitalSummaries
{
    HubCapitalSummary delivery;
    HubCapitalSummary disabledTests;
    HubCapitalSummary apiVersion;
    HubCapitalSummary countryVariants;
    HubCapitalSummary sizeTrend;
};

template <typename Parser>
HubCapitalSummary loadDesktopStateCapital(const std::string& label, const std::string& action, bool includeBmwRoot, Parser parser)
{
    HubCapitalSummary summary;
    summary.label = label;
    const std::filesystem::path workspaceRoot = findWorkspaceRoot();
    const std::filesystem::path sourceRoot = resolveSourceRepoRoot();
    const std::filesystem::path bmwRoot = resolveBmwRepoRoot();

    if (workspaceRoot.empty())
    {
        summary.error = "sg_preflight package root not found";
        summary.secondaryText = summary.error;
        return summary;
    }
    if (sourceRoot.empty())
    {
        summary.error = "source repo root not found";
        summary.secondaryText = summary.error;
        return summary;
    }
    summary.sourceRoot = sourceRoot.string();
    summary.bmwRoot = bmwRoot.string();

    std::ostringstream command;
    command << "set \"PYTHONPATH=" << workspaceRoot.string() << ";%PYTHONPATH%\" && "
            << pythonLauncherCommand()
            << " -B -m sg_preflight desktop-state " << action
            << " --workspace " << quoteCmdArg(sourceRoot)
            << " --repo-root " << quoteCmdArg(sourceRoot);
    if (includeBmwRoot && !bmwRoot.empty())
        command << " --bmw-repo-root " << quoteCmdArg(bmwRoot);
    command << " --json";
    summary.command = command.str();

    int exitCode = 1;
    const std::string output = runProcessCapture(summary.command, exitCode);
    if (exitCode != 0)
    {
        summary.error = output.empty() ? "desktop-state " + action + " failed" : shortError(output);
        summary.secondaryText = summary.error;
        return summary;
    }

    try
    {
        const nlohmann::json payload = nlohmann::json::parse(output);
        summary.sourceState = payload.value("source_state", std::string{});
        summary.sourceBanner = payload.value("manual_review_banner", payload.value("manual_approval_banner", std::string{}));
        summary.bannerText = summary.sourceBanner.empty() ? "Evidence only - manual review required." : "Evidence only - manual review required.";
        parser(payload, summary);
        summary.loaded = true;
    }
    catch (const std::exception& exc)
    {
        summary.error = std::string(action) + " JSON parse failed: " + exc.what();
        summary.secondaryText = summary.error;
    }
    return summary;
}

HubCapitalSummary loadDeliveryCapital()
{
    return loadDesktopStateCapital("Delivery Readiness", "delivery-readiness", true, [](const nlohmann::json& payload, HubCapitalSummary& summary) {
        const nlohmann::json counts = payload.value("counts", nlohmann::json::object());
        const int total = counts.value("total", 0);
        const int delivered = counts.value("delivered", 0);
        const int notDeliveredYet = counts.value("not_delivered_yet", 0);
        const int unknown = counts.value("unknown", 0);
        summary.statusText = std::to_string(delivered) + " / " + std::to_string(notDeliveredYet) + " / " + std::to_string(unknown);
        summary.primaryText = std::to_string(total) + " cars: " + std::to_string(delivered) + " delivered";
        summary.secondaryText = std::to_string(notDeliveredYet) + " not-yet / " + std::to_string(unknown) + " unknown";
        summary.bannerText = "Evidence only - manual approval required.";
    });
}

HubCapitalSummary loadDisabledTestsCapital()
{
    return loadDesktopStateCapital("Disabled Tests", "disabled-tests", true, [](const nlohmann::json& payload, HubCapitalSummary& summary) {
        const nlohmann::json counts = payload.value("counts", nlohmann::json::object());
        const int configured = counts.value("configured", 0);
        const int noConfig = counts.value("no_config", 0);
        const int disabledCalls = counts.value("disabled_call_total", 0);
        const int disabledUnique = counts.value("disabled_unique_total", 0);
        std::string topCar = "none";
        int topDisabled = 0;
        for (const auto& entry : payload.value("entries", nlohmann::json::array()))
        {
            const int disabledCount = entry.value("disabled_count", 0);
            if (disabledCount > topDisabled)
            {
                topDisabled = disabledCount;
                topCar = entry.value("model_id", std::string("unknown"));
            }
        }
        summary.statusText = std::to_string(disabledCalls) + " OFF";
        summary.primaryText = std::to_string(disabledCalls) + " disabled calls";
        summary.secondaryText = topDisabled > 0
            ? topCar + " top: " + std::to_string(topDisabled) + " off / " + std::to_string(disabledUnique) + " unique"
            : std::to_string(configured) + " configured / " + std::to_string(noConfig) + " no config";
    });
}

HubCapitalSummary loadApiVersionCapital()
{
    return loadDesktopStateCapital("API Version", "api-version-coverage", true, [](const nlohmann::json& payload, HubCapitalSummary& summary) {
        const nlohmann::json counts = payload.value("counts", nlohmann::json::object());
        std::string version = "unknown";
        std::string versionDate;
        const nlohmann::json currentVersions = counts.value("current_api_versions", nlohmann::json::object());
        if (currentVersions.is_object() && !currentVersions.empty())
        {
            const auto first = currentVersions.begin();
            version = first.key();
            if (first.value().is_string())
                versionDate = first.value().get<std::string>();
        }
        else if (currentVersions.is_array() && !currentVersions.empty() && currentVersions.front().is_string())
        {
            const std::string combined = currentVersions.front().get<std::string>();
            const size_t separator = combined.find(':');
            if (separator == std::string::npos)
            {
                version = combined;
            }
            else
            {
                version = combined.substr(0u, separator);
                versionDate = combined.substr(separator + 1u);
            }
        }
        const int reviewCars = counts.value("impact_review_car_count", 0);
        const int reviewFiles = counts.value("impact_file_match_count", 0);
        summary.statusText = "API [" + version + "]";
        summary.primaryText = "Current [" + version + "]" + (versionDate.empty() ? std::string{} : " / " + versionDate);
        summary.secondaryText = std::to_string(reviewCars) + " cars / " + std::to_string(reviewFiles) + " files review";
    });
}

HubCapitalSummary loadCountryVariantsCapital()
{
    return loadDesktopStateCapital("Country Variants", "country-variant-coverage", true, [](const nlohmann::json& payload, HubCapitalSummary& summary) {
        const nlohmann::json counts = payload.value("counts", nlohmann::json::object());
        const int rows = counts.value("row_total", 0);
        const int cars = counts.value("car_with_rows_count", 0);
        const int reviews = counts.value("review_row_count", 0);
        const int mappingReviews = counts.value("mapping_review_count", 0);
        summary.statusText = std::to_string(reviews) + " REVIEW";
        summary.primaryText = std::to_string(rows) + " rows / " + std::to_string(cars) + " cars";
        summary.secondaryText = std::to_string(reviews) + " review / " + std::to_string(mappingReviews) + " mapping";
    });
}

HubCapitalSummary loadSizeTrendCapital()
{
    return loadDesktopStateCapital("Size Trend", "export-size-trend", false, [](const nlohmann::json& payload, HubCapitalSummary& summary) {
        const nlohmann::json counts = payload.value("counts", nlohmann::json::object());
        const int workbooks = counts.value("workbook_count", 0);
        const int profiles = counts.value("profile_count", 0);
        const int reviewChanges = counts.value("review_change_count", 0);
        std::vector<std::string> reviewLabels;
        for (const auto& change : payload.value("trend_changes", nlohmann::json::array()))
        {
            if (!change.value("needs_review", false))
                continue;
            const std::string profile = change.value("profile_id", std::string("unknown"));
            const double percent = change.value("delta_percent", 0.0);
            reviewLabels.push_back(profile + " " + formatSignedPercent(percent));
            if (reviewLabels.size() >= 2u)
                break;
        }
        summary.statusText = std::to_string(reviewChanges) + " REVIEW";
        summary.primaryText = std::to_string(workbooks) + " workbooks / " + std::to_string(profiles) + " profiles";
        if (reviewLabels.empty())
            summary.secondaryText = "no significant trend review flags";
        else if (reviewLabels.size() == 1u)
            summary.secondaryText = reviewLabels.front();
        else
            summary.secondaryText = reviewLabels[0] + " / " + reviewLabels[1];
    });
}

HubCapitalSummaries loadHubCapitalSummaries()
{
    HubCapitalSummaries summaries;
    summaries.delivery = loadDeliveryCapital();
    summaries.disabledTests = loadDisabledTestsCapital();
    summaries.apiVersion = loadApiVersionCapital();
    summaries.countryVariants = loadCountryVariantsCapital();
    summaries.sizeTrend = loadSizeTrendCapital();
    return summaries;
}

void logCapitalSummary(const HubCapitalSummary& summary, bool includeBmwRoot)
{
    if (summary.loaded)
    {
        std::cout << "SGFX cinematic shell " << summary.label << " capital: "
                  << summary.primaryText << ", " << summary.secondaryText
                  << ", source=" << (summary.sourceState.empty() ? std::string("unknown") : summary.sourceState)
                  << "\n";
        std::cout << "SGFX cinematic shell " << summary.label << " roots: source="
                  << summary.sourceRoot;
        if (includeBmwRoot)
            std::cout << ", bmw=" << (summary.bmwRoot.empty() ? std::string("unavailable") : summary.bmwRoot);
        std::cout << "\n";
        std::cout << "SGFX cinematic shell " << summary.label << " banner: " << summary.bannerText << "\n";
        if (!summary.sourceBanner.empty())
            std::cout << "SGFX cinematic shell " << summary.label << " source banner: " << summary.sourceBanner << "\n";
    }
    else
    {
        std::cout << "SGFX cinematic shell " << summary.label << " capital unavailable: "
                  << (summary.error.empty() ? std::string("no data") : summary.error) << "\n";
    }
}

void logHubCapitalSummaries(const HubCapitalSummaries& summaries)
{
    logCapitalSummary(summaries.delivery, true);
    logCapitalSummary(summaries.disabledTests, true);
    logCapitalSummary(summaries.apiVersion, true);
    logCapitalSummary(summaries.countryVariants, true);
    logCapitalSummary(summaries.sizeTrend, false);
}

std::string stripEvoSuffix(std::string value)
{
    if (endsWithInsensitive(value, "_EVO"))
        value.resize(value.size() - 4u);
    return value;
}

std::string profileIdFromSceneFile(const std::filesystem::path& sceneFile)
{
    if (sceneFile.empty())
        return {};
    return stripEvoSuffix(sceneFile.parent_path().parent_path().filename().string());
}

std::filesystem::path perspectiveFileForSet(const std::filesystem::path& profileDir, const std::string& setName)
{
    if (profileDir.empty() || setName.empty())
        return {};
    std::string fileName = setName;
    if (!startsWithInsensitive(fileName, "perspectives_"))
        fileName = "perspectives_" + fileName;
    if (!endsWithInsensitive(fileName, ".json"))
        fileName += ".json";
    const std::filesystem::path candidate = profileDir / fileName;
    return std::filesystem::is_regular_file(candidate) ? candidate : std::filesystem::path{};
}

std::filesystem::path findDefaultPerspectiveFile(const std::filesystem::path& profileDir)
{
    for (const std::string& preferredSet : {"CID170_LHD", "CID180_LHD"})
    {
        const std::filesystem::path preferred = perspectiveFileForSet(profileDir, preferredSet);
        if (!preferred.empty())
            return preferred;
    }

    std::error_code ec;
    for (const auto& entry : std::filesystem::directory_iterator(profileDir, ec))
    {
        if (ec)
            break;
        if (!entry.is_regular_file())
            continue;
        const std::string name = entry.path().filename().string();
        if (startsWithInsensitive(name, "perspectives_") && endsWithInsensitive(name, ".json"))
            return entry.path();
    }
    return {};
}

int registryRankForProfileId(const std::vector<std::string>& registryIds, const std::string& profileId)
{
    const std::string normalizedProfile = lowerAscii(profileId);
    for (size_t index = 0u; index < registryIds.size(); ++index)
    {
        if (lowerAscii(registryIds[index]) == normalizedProfile ||
            lowerAscii(stripEvoSuffix(registryIds[index])) == normalizedProfile)
        {
            return static_cast<int>(index);
        }
    }
    return 1000000;
}

struct FusionCarDiscovery
{
    std::vector<FusionCarCandidate> candidates;
    size_t registeredProfileCount = 0u;
    std::string registeredProfileSource = "unavailable";
};

FusionCarDiscovery discoverFusionCarCandidates(const Options& options)
{
    const FusionProfileRegistry registry = loadFusionProfileRegistry(options);
    FusionCarDiscovery discovery;
    discovery.registeredProfileCount = registry.registeredCount;
    discovery.registeredProfileSource = registry.countSource;

    const std::filesystem::path carsRoot = resolveCarsRoot(options);
    if (carsRoot.empty())
        return discovery;

    std::error_code ec;
    for (const auto& entry : std::filesystem::directory_iterator(carsRoot, ec))
    {
        if (ec)
            break;
        if (!entry.is_directory())
            continue;
        const std::string folderName = entry.path().filename().string();
        if (folderName.empty() || folderName[0] == '_')
            continue;

        const std::filesystem::path sceneFile = entry.path() / "export" / "exported.ramses";
        if (!std::filesystem::is_regular_file(sceneFile))
            continue;

        FusionCarCandidate candidate;
        candidate.folderName = folderName;
        candidate.profileId = stripEvoSuffix(folderName);
        candidate.label = candidate.profileId == folderName ? candidate.profileId : candidate.profileId + " (" + folderName + ")";
        candidate.sceneFile = std::filesystem::absolute(sceneFile);
        candidate.profileDir = std::filesystem::absolute(entry.path());
        candidate.defaultPerspectiveFile = findDefaultPerspectiveFile(candidate.profileDir);
        candidate.defaultPerspectiveSet = candidate.defaultPerspectiveFile.empty() ? std::string{} : perspectiveSetNameFromFile(candidate.defaultPerspectiveFile);
        candidate.registryRank = registryRankForProfileId(registry.rankIds, candidate.profileId);
        candidate.registryMatched = candidate.registryRank < 1000000;
        discovery.candidates.push_back(std::move(candidate));
    }

    std::sort(discovery.candidates.begin(), discovery.candidates.end(), [](const FusionCarCandidate& left, const FusionCarCandidate& right) {
        if (left.registryMatched != right.registryMatched)
            return left.registryMatched;
        if (left.registryRank != right.registryRank)
            return left.registryRank < right.registryRank;
        if (lowerAscii(left.profileId) != lowerAscii(right.profileId))
            return lowerAscii(left.profileId) < lowerAscii(right.profileId);
        return lowerAscii(left.folderName) < lowerAscii(right.folderName);
    });
    return discovery;
}

int chooseInitialCarCandidate(const std::vector<FusionCarCandidate>& candidates, const Options& options)
{
    if (candidates.empty())
        return -1;

    if (!options.fusionSceneFile.empty())
    {
        std::error_code ec;
        const std::filesystem::path requested = std::filesystem::weakly_canonical(options.fusionSceneFile, ec);
        for (size_t index = 0u; index < candidates.size(); ++index)
        {
            ec.clear();
            const std::filesystem::path candidate = std::filesystem::weakly_canonical(candidates[index].sceneFile, ec);
            if (!ec && candidate == requested)
                return static_cast<int>(index);
        }
    }

    if (!options.fusionProfileId.empty())
    {
        for (size_t index = 0u; index < candidates.size(); ++index)
        {
            if (lowerAscii(candidates[index].profileId) == lowerAscii(options.fusionProfileId))
                return static_cast<int>(index);
        }
    }

    return 0;
}

Options optionsForCarCandidate(const Options& base, const FusionCarCandidate& candidate, bool preserveRequestedPerspective)
{
    Options result = base;
    result.fusionEnabled = true;
    result.fusionSceneFile = candidate.sceneFile.string();
    result.fusionProfileId = candidate.profileId;

    const std::string requestedPerspectiveId = result.fusionPerspectiveId;
    const std::string requestedPerspectiveSet = result.fusionPerspectiveSet;
    const std::string requestedPerspectiveFile = result.fusionPerspectiveFile;
    result.fusionPerspectiveSet.clear();
    result.fusionPerspectiveFile.clear();
    result.fusionPerspectiveId.clear();

    bool preservedPerspective = false;
    if (preserveRequestedPerspective && !requestedPerspectiveFile.empty() && std::filesystem::is_regular_file(requestedPerspectiveFile))
    {
        result.fusionPerspectiveFile = requestedPerspectiveFile;
        result.fusionPerspectiveSet = perspectiveSetNameFromFile(requestedPerspectiveFile);
        result.fusionPerspectiveId = requestedPerspectiveId;
        preservedPerspective = true;
    }
    else if (preserveRequestedPerspective && !requestedPerspectiveSet.empty())
    {
        const std::filesystem::path requestedFile = perspectiveFileForSet(candidate.profileDir, requestedPerspectiveSet);
        if (!requestedFile.empty())
        {
            result.fusionPerspectiveSet = requestedPerspectiveSet;
            result.fusionPerspectiveId = requestedPerspectiveId;
            preservedPerspective = true;
        }
    }

    if (!preservedPerspective && !candidate.defaultPerspectiveFile.empty())
        result.fusionPerspectiveSet = candidate.defaultPerspectiveSet;

    return result;
}

std::filesystem::path resolveFusionPerspectiveFile(const Options& options)
{
    if (!options.fusionPerspectiveFile.empty())
        return std::filesystem::absolute(options.fusionPerspectiveFile);

    if (options.fusionPerspectiveSet.empty())
    {
        if (!options.fusionPerspectiveId.empty())
            throw std::runtime_error("--fusion-perspective-id requires --fusion-perspective-set or --fusion-perspective-file");
        return {};
    }

    std::string fileName = options.fusionPerspectiveSet;
    if (!startsWithInsensitive(fileName, "perspectives_"))
        fileName = "perspectives_" + fileName;
    if (!endsWithInsensitive(fileName, ".json"))
        fileName += ".json";

    const std::filesystem::path sceneFile = std::filesystem::absolute(options.fusionSceneFile);
    const std::filesystem::path sceneExportDir = sceneFile.parent_path();
    const std::filesystem::path sceneProfileDir = sceneExportDir.parent_path();

    std::vector<std::filesystem::path> candidates;
    if (!sceneProfileDir.empty())
    {
        candidates.push_back(sceneProfileDir / fileName);
        if (!sceneProfileDir.parent_path().empty())
            candidates.push_back(sceneProfileDir.parent_path() / fileName);
    }

    for (const auto& candidate : candidates)
    {
        if (std::filesystem::is_regular_file(candidate))
            return std::filesystem::absolute(candidate);
    }

    std::ostringstream message;
    message << "No fusion perspective file found. Tried:";
    for (const auto& candidate : candidates)
        message << " " << candidate.string();
    throw std::runtime_error(message.str());
}

std::optional<FusionQaPerspective> resolveFusionQaPerspective(const Options& options)
{
    const std::filesystem::path perspectiveFile = resolveFusionPerspectiveFile(options);
    if (perspectiveFile.empty())
        return std::nullopt;

    const std::string text = readTextFile(perspectiveFile);
    const auto rootEntries = parseJsonObjectEntries(text, 0u, text.size());
    if (rootEntries.empty())
        throw std::runtime_error("Perspective file has no top-level views: " + perspectiveFile.string());

    std::string selectedId = options.fusionPerspectiveId;
    if (selectedId.empty())
    {
        if (findJsonEntry(rootEntries, "CID_CARHUB_ALL_GOOD"))
            selectedId = "CID_CARHUB_ALL_GOOD";
        else
            selectedId = rootEntries.front().name;
    }

    const auto* selectedEntry = findJsonEntry(rootEntries, selectedId);
    if (!selectedEntry)
        throw std::runtime_error("Perspective id '" + selectedId + "' was not found in " + perspectiveFile.string());

    const auto viewEntries = parseJsonObjectEntries(text, selectedEntry->valueBegin, selectedEntry->valueEnd);
    const auto craneEntries = requireObjectField(text, viewEntries, "CraneGimbal");
    const auto frustumEntries = requireObjectField(text, viewEntries, "Frustum");
    const auto viewportEntries = requireObjectField(text, viewEntries, "Viewport");
    const auto origin = requireNumberArrayField(text, viewEntries, "Origin", 3u);
    const auto shift = requireNumberArrayField(text, viewEntries, "ShiftXY", 2u);

    FusionQaPerspective perspective;
    perspective.file = perspectiveFile;
    perspective.setName = !options.fusionPerspectiveSet.empty() ? options.fusionPerspectiveSet : perspectiveSetNameFromFile(perspectiveFile);
    perspective.id = selectedId;
    perspective.aspectFromResolution = requireBoolField(text, viewEntries, "AspectFromResolution_isEnabled");
    perspective.distance = static_cast<float>(requireNumberField(text, craneEntries, "Distance"));
    perspective.yaw = static_cast<float>(requireNumberField(text, craneEntries, "Yaw"));
    perspective.pitch = static_cast<float>(requireNumberField(text, craneEntries, "Pitch"));
    perspective.roll = static_cast<float>(requireNumberField(text, craneEntries, "Roll"));
    perspective.horizontalFov = static_cast<float>(requireNumberField(text, frustumEntries, "HorizontalFOV"));
    perspective.aspectRatio = static_cast<float>(requireNumberField(text, frustumEntries, "AspectRatio"));
    perspective.nearPlane = static_cast<float>(requireNumberField(text, frustumEntries, "NearPlane"));
    perspective.farPlane = static_cast<float>(requireNumberField(text, frustumEntries, "FarPlane"));
    perspective.scale = static_cast<float>(requireNumberField(text, viewEntries, "Scale"));
    perspective.origin = {static_cast<float>(origin[0]), static_cast<float>(origin[1]), static_cast<float>(origin[2])};
    perspective.shift = {static_cast<int32_t>(std::lround(shift[0])), static_cast<int32_t>(std::lround(shift[1]))};
    perspective.viewportOffsetX = static_cast<int32_t>(std::lround(requireNumberField(text, viewportEntries, "OffsetX")));
    perspective.viewportOffsetY = static_cast<int32_t>(std::lround(requireNumberField(text, viewportEntries, "OffsetY")));
    perspective.viewportWidth = static_cast<uint32_t>(std::lround(requireNumberField(text, viewportEntries, "Width")));
    perspective.viewportHeight = static_cast<uint32_t>(std::lround(requireNumberField(text, viewportEntries, "Height")));
    perspective.viewIds.reserve(rootEntries.size());
    for (const auto& entry : rootEntries)
        perspective.viewIds.push_back(entry.name);

    if (perspective.distance <= 0.0f || perspective.horizontalFov <= 0.0f ||
        perspective.aspectRatio <= 0.0f || perspective.nearPlane <= 0.0f ||
        perspective.farPlane <= perspective.nearPlane || perspective.scale <= 0.0f ||
        perspective.viewportWidth == 0u || perspective.viewportHeight == 0u)
    {
        throw std::runtime_error("Perspective JSON contains invalid camera-crane values: " + perspective.id);
    }

    return perspective;
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
        std::cout << "Fusion Phase 2 Ramses displayCreated result: " << (m_displayCreated ? "Ok" : "Failed") << "\n";
    }

    void offscreenBufferCreated(ramses::displayId_t displayId,
                                ramses::displayBufferId_t offscreenBufferId,
                                ramses::ERendererEventResult result) override
    {
        if (displayId != m_displayId)
            return;

        m_offscreenCreated = result == ramses::ERendererEventResult::Ok && offscreenBufferId == m_offscreenBuffer;
        m_offscreenCreateFailed = result == ramses::ERendererEventResult::Failed;
        std::cout << "Fusion Phase 2 Ramses offscreenBufferCreated result: " << (m_offscreenCreated ? "Ok" : "Failed") << "\n";
    }

    void sceneStateChanged(ramses::sceneId_t sceneId, ramses::RendererSceneState state) override
    {
        if (sceneId != m_sceneId)
            return;

        m_sceneState = state;
        std::cout << "Fusion Phase 2 Ramses scene state: " << ramsesSceneStateName(state) << "\n";
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
            std::cout << "Fusion Phase 2 Ramses readPixels: Failed\n";
            return;
        }

        m_pixels.assign(pixelData, pixelData + pixelDataSize);
        m_ramsesStats = calculateFusionBrightPixels(m_pixels, m_width, m_height);
        std::cout << "Fusion Phase 2 Ramses readPixels bright pixels: " << m_ramsesStats.brightPixels << "\n";
        std::cout << "Fusion Phase 2 Ramses readPixels bright bounds x/y: "
                  << m_ramsesStats.minX << "-" << m_ramsesStats.maxX << "/"
                  << m_ramsesStats.minY << "-" << m_ramsesStats.maxY << "\n";
        std::cout << "Fusion Phase 3 Ramses readPixels alpha min/max/transparent/translucent: "
                  << static_cast<unsigned>(m_ramsesStats.minAlpha) << "/"
                  << static_cast<unsigned>(m_ramsesStats.maxAlpha) << "/"
                  << m_ramsesStats.transparentPixels << "/"
                  << m_ramsesStats.translucentPixels << "\n";
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
    const FusionReadbackStats& ramsesStats() const { return m_ramsesStats; }

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
    FusionReadbackStats m_ramsesStats;
};

bool pumpSdlEventsForFusion()
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

void pumpFusionEvents(ramses::RamsesRenderer& renderer, ramses::RendererSceneControl& sceneControl, FusionEventHandler& handler)
{
    renderer.dispatchEvents(handler);
    sceneControl.dispatchEvents(handler);
    renderer.flush();
    sceneControl.flush();
}

template <typename Predicate, typename Tick>
bool pumpFusionUntil(ramses::RamsesRenderer& renderer,
                     ramses::RendererSceneControl& sceneControl,
                     FusionEventHandler& handler,
                     Predicate predicate,
                     Tick tick,
                     std::chrono::milliseconds timeout)
{
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (!predicate())
    {
        if (!pumpSdlEventsForFusion())
            return false;

        tick();
        renderer.doOneLoop();
        pumpFusionEvents(renderer, sceneControl, handler);

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

void setFusionCameraViewports(const std::vector<ramses::Camera*>& cameras, uint32_t width, uint32_t height)
{
    for (auto* camera : cameras)
    {
        if (camera && !camera->setViewport(0, 0, width, height))
            throw std::runtime_error("Fusion Phase 2 failed to retarget a camera viewport");
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

float vectorLength(const ramses::vec3f& value)
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
    bounds.radius = std::max(1.0f, vectorLength(extents) * 0.5f);
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

CameraRig makeCameraRig(const SceneBounds& bounds, uint32_t width, uint32_t height, double zoom)
{
    const float safeZoom = std::max(0.2f, static_cast<float>(zoom));
    CameraRig rig;
    rig.center = bounds.valid ? bounds.center : ramses::vec3f{0.0f, 0.8f, 0.0f};
    if (bounds.valid)
    {
        const float boundsHeight = std::max(0.1f, bounds.max.y - bounds.min.y);
        rig.target = {bounds.center.x, bounds.min.y + boundsHeight * 0.35f, bounds.center.z};
    }
    else
    {
        rig.target = rig.center;
    }
    rig.radius = std::max(1.0f, (bounds.valid ? bounds.radius : 5.0f) * 1.05f);
    const float aspect = static_cast<float>(width) / static_cast<float>(height);
    const float verticalFovRadians = rig.fov * kFusionPi / 180.0f;
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

float fusionViewPresetYawDeltaDegrees(const std::string& viewPreset)
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
                          const Options& options)
{
    const float yawDegrees = (options.fusionOrbit ? static_cast<float>(frame) * 0.35f : 0.0f) + fusionViewPresetYawDeltaDegrees(options.fusionViewPreset);
    const float yawRadians = yawDegrees * kFusionPi / 180.0f;
    const float elevation = std::max(1.1f, rig.radius * 0.16f);
    const ramses::vec3f cameraPosition{
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
bool setFusionCameraCraneProperty(ramses::Property& root,
                                  std::initializer_list<std::string_view> path,
                                  T value,
                                  std::string_view targetName,
                                  bool logFailures)
{
    auto* property = findPropertyPath(&root, path);
    if (!property)
    {
        if (logFailures)
            std::cout << "Fusion Phase 3 QA perspective logic missing property: " << targetName << "/"
                      << propertyPathText(path) << "\n";
        return false;
    }

    if (!property->set<T>(value))
    {
        if (logFailures)
            std::cout << "Fusion Phase 3 QA perspective logic set failed: " << targetName << "/"
                      << propertyPathText(path) << "\n";
        return false;
    }
    return true;
}

bool driveFusionCameraCraneRoot(ramses::Property& root,
                                uint32_t frame,
                                bool orbit,
                                double zoom,
                                const FusionQaPerspective& perspective,
                                std::string_view targetName,
                                bool logFailures)
{
    const float safeZoom = std::max(0.2f, static_cast<float>(zoom));
    const float yaw = perspective.yaw + (orbit ? static_cast<float>(frame) * 0.35f : 0.0f);
    bool ok = true;
    ok &= setFusionCameraCraneProperty<bool>(root, {"AutoAspect"}, perspective.aspectFromResolution, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<float>(root, {"CraneGimbal", "Distance"}, perspective.distance / safeZoom, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<float>(root, {"CraneGimbal", "Pitch"}, perspective.pitch, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<float>(root, {"CraneGimbal", "Roll"}, perspective.roll, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<float>(root, {"CraneGimbal", "Yaw"}, yaw, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<float>(root, {"Frustum", "AspectRatio"}, perspective.aspectRatio, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<float>(root, {"Frustum", "FarPlane"}, perspective.farPlane, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<float>(root, {"Frustum", "HorizontalFOV"}, perspective.horizontalFov, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<float>(root, {"Frustum", "NearPlane"}, perspective.nearPlane, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<float>(root, {"Scale"}, perspective.scale, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<ramses::vec2i>(root, {"ShiftXY"}, perspective.shift, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<ramses::vec3f>(root, {"Origin"}, perspective.origin, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<int32_t>(root, {"Viewport", "Height"}, static_cast<int32_t>(perspective.viewportHeight), targetName, logFailures);
    ok &= setFusionCameraCraneProperty<int32_t>(root, {"Viewport", "OffsetX"}, perspective.viewportOffsetX, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<int32_t>(root, {"Viewport", "OffsetY"}, perspective.viewportOffsetY, targetName, logFailures);
    ok &= setFusionCameraCraneProperty<int32_t>(root, {"Viewport", "Width"}, static_cast<int32_t>(perspective.viewportWidth), targetName, logFailures);
    return ok;
}

ramses::Property* findFusionCameraCraneRoot(ramses::LogicNode& node)
{
    auto* inputs = node.getInputs();
    if (!inputs)
        return nullptr;

    if (inputs->hasChild("Interface_CameraCrane"))
    {
        if (auto* interfaceInput = inputs->getChild("Interface_CameraCrane"))
            return interfaceInput;
    }
    if (inputs->hasChild("CraneGimbal") && inputs->hasChild("Frustum") && inputs->hasChild("Viewport"))
        return inputs;
    return nullptr;
}

size_t driveFusionQaPerspectiveLogic(const std::vector<ramses::LogicEngine*>& engines,
                                     uint32_t frame,
                                     bool orbit,
                                     double zoom,
                                     const FusionQaPerspective& perspective,
                                     bool logTargets)
{
    size_t candidates = 0u;
    size_t driven = 0u;

    auto tryNode = [&](ramses::LogicNode& node, std::string_view kind) {
        auto* cameraCraneRoot = findFusionCameraCraneRoot(node);
        if (!cameraCraneRoot)
            return;

        ++candidates;
        const std::string targetName = std::string(kind) + " " + objectName(&node);
        if (logTargets)
            std::cout << "Fusion Phase 3 QA perspective logic target: " << targetName << "\n";
        if (driveFusionCameraCraneRoot(*cameraCraneRoot, frame, orbit, zoom, perspective, targetName, logTargets))
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
        std::cout << "Fusion Phase 3 QA perspective logic camera-crane driven/candidates: " << driven << "/" << candidates << "\n";
    return driven;
}

void throwOnFusionGlError(const char* stage)
{
    const GLenum error = glGetError();
    if (error != GL_NO_ERROR)
        throw std::runtime_error(std::string("Fusion Phase 2 GL error after ") + stage + ": " + std::to_string(error));
}

void prepareShellGlBackbufferForRml(Rml::Vector2i drawableSize)
{
    while (glGetError() != GL_NO_ERROR)
    {
    }

    using GlBindFramebufferProc = void(APIENTRY*)(GLenum, GLuint);
    using GlDrawBufferProc = void(APIENTRY*)(GLenum);
    using GlUseProgramProc = void(APIENTRY*)(GLuint);
    using GlBindVertexArrayProc = void(APIENTRY*)(GLuint);
    using GlBindBufferProc = void(APIENTRY*)(GLenum, GLuint);

    const auto bindFramebuffer = reinterpret_cast<GlBindFramebufferProc>(SDL_GL_GetProcAddress("glBindFramebuffer"));
    const auto drawBuffer = reinterpret_cast<GlDrawBufferProc>(SDL_GL_GetProcAddress("glDrawBuffer"));
    const auto useProgram = reinterpret_cast<GlUseProgramProc>(SDL_GL_GetProcAddress("glUseProgram"));
    const auto bindVertexArray = reinterpret_cast<GlBindVertexArrayProc>(SDL_GL_GetProcAddress("glBindVertexArray"));
    const auto bindBuffer = reinterpret_cast<GlBindBufferProc>(SDL_GL_GetProcAddress("glBindBuffer"));
    if (!bindFramebuffer || !drawBuffer || !useProgram || !bindVertexArray || !bindBuffer)
        throw std::runtime_error("Fusion Phase 2 shell GL reset could not resolve required GL3 entry points");

    bindFramebuffer(GL_FRAMEBUFFER, 0);
    drawBuffer(GL_BACK);
    glViewport(0, 0, drawableSize.x, drawableSize.y);
    glScissor(0, 0, drawableSize.x, drawableSize.y);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glDepthMask(GL_TRUE);
    glStencilMask(GLuint(-1));
    useProgram(0);
    glBindTexture(GL_TEXTURE_2D, 0);
    bindVertexArray(0);
    bindBuffer(GL_ARRAY_BUFFER, 0);
    bindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
    glDisable(GL_SCISSOR_TEST);
    glDisable(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_STENCIL_TEST);
    throwOnFusionGlError("shell GL state reset for RmlUi");
}

class FusionCarTexture
{
public:
    FusionCarTexture(const Options& options, SdlGlWindow& shellWindow)
        : m_shellWindow(shellWindow)
    {
        reload(options);
    }

    ~FusionCarTexture()
    {
        if (m_texture)
        {
            m_shellWindow.makeCurrent();
            glDeleteTextures(1, &m_texture);
        }
    }

    bool ready() const
    {
        return m_ready && m_texture != 0u;
    }

    Rml::TextureHandle textureHandle() const
    {
        return static_cast<Rml::TextureHandle>(m_texture);
    }

    Rml::Vector2i textureDimensions() const
    {
        return {static_cast<int>(m_width), static_cast<int>(m_height)};
    }

    GLuint glTexture() const
    {
        return m_texture;
    }

    const FusionReadbackStats& ramsesStats() const
    {
        return m_ramsesStats;
    }

    const std::optional<FusionQaPerspective>& qaPerspective() const
    {
        return m_qaPerspective;
    }

    const FusionPerformanceStats& performanceStats() const
    {
        return m_performanceStats;
    }

    const std::string& profileId() const
    {
        return m_profileId;
    }

    const std::filesystem::path& sceneFile() const
    {
        return m_sceneFile;
    }

    void reload(const Options& options)
    {
        m_ready = false;
        m_width = 0u;
        m_height = 0u;
        m_ramsesStats = {};
        m_performanceStats = {};
        m_qaPerspective.reset();
        m_framework.reset();
        m_ramsesWindow.reset();
        loadInitialFrame(options);
    }

private:
    void loadInitialFrame(const Options& options)
    {
        m_profileId = options.fusionProfileId.empty() ? profileIdFromSceneFile(options.fusionSceneFile) : options.fusionProfileId;
        m_sceneFile = std::filesystem::absolute(options.fusionSceneFile);
        const auto linkedVersion = ramses::GetRamsesVersion();
        const std::optional<ramses::SceneMetadata> metadata = ramses::RamsesClient::GetMetadataFromFile(options.fusionSceneFile);
        if (!metadata)
            throw std::runtime_error("Could not read Ramses metadata from fusion scene file");
        m_qaPerspective = resolveFusionQaPerspective(options);

        std::cout << "Fusion Phase 2 linked Ramses version: " << linkedVersion.string << "\n";
        std::cout << "Fusion Phase 2 profile id: " << m_profileId << "\n";
        std::cout << "Fusion Phase 2 scene file: " << options.fusionSceneFile << "\n";
        std::cout << "Fusion Phase 2 scene metadata Ramses version: " << ramsesVersionString(metadata->ramsesVersion) << "\n";
        std::cout << "Fusion Phase 2 scene metadata exporter version: " << ramsesVersionString(metadata->exporterVersion) << "\n";
        std::cout << "Fusion Phase 2 scene metadata feature level: " << static_cast<unsigned>(metadata->featureLevel) << "\n";
        if (m_qaPerspective)
        {
            std::cout << "Fusion Phase 3 QA perspective file: " << m_qaPerspective->file.string() << "\n";
            std::cout << "Fusion Phase 3 QA perspective set/id/count: "
                      << m_qaPerspective->setName << "/"
                      << m_qaPerspective->id << "/"
                      << m_qaPerspective->viewIds.size() << "\n";
            std::cout << "Fusion Phase 3 QA perspective distance/yaw/pitch/hfov: "
                      << m_qaPerspective->distance << "/"
                      << m_qaPerspective->yaw << "/"
                      << m_qaPerspective->pitch << "/"
                      << m_qaPerspective->horizontalFov << "\n";
            std::cout << "Fusion Phase 3 QA perspective origin/shift/viewport: "
                      << m_qaPerspective->origin.x << "," << m_qaPerspective->origin.y << "," << m_qaPerspective->origin.z << "/"
                      << m_qaPerspective->shift.x << "," << m_qaPerspective->shift.y << "/"
                      << m_qaPerspective->viewportWidth << "x" << m_qaPerspective->viewportHeight << "@"
                      << m_qaPerspective->viewportOffsetX << "," << m_qaPerspective->viewportOffsetY << "\n";
        }

        ramses::RamsesFrameworkConfig frameworkConfig{metadata->featureLevel};
        frameworkConfig.setRequestedRamsesShellType(ramses::ERamsesShellType::Console);
        frameworkConfig.setPeriodicLogInterval(std::chrono::seconds(1));
        m_framework = std::make_unique<ramses::RamsesFramework>(frameworkConfig);
        auto& client = *m_framework->createClient("sgfx-cine-fusion-phase2-client");

        ramses::RendererConfig rendererConfig;
        rendererConfig.setRenderThreadLoopTimingReportingPeriod(std::chrono::milliseconds(500));
        auto& renderer = *m_framework->createRenderer(rendererConfig);
        auto& sceneControl = *renderer.getSceneControlAPI();

        m_framework->connect();

        ramses::SceneConfig sceneConfig{ramses::sceneId_t{67u}, ramses::EScenePublicationMode::LocalOnly, ramses::ERenderBackendCompatibility::OpenGL};
        auto* scene = client.loadSceneFromFile(options.fusionSceneFile, sceneConfig);
        if (!scene)
        {
            if (auto issue = m_framework->getLastError())
                std::cerr << "Ramses last error: " << issue->message << "\n";
            throw std::runtime_error("loadSceneFromFile returned null");
        }

        const ramses::sceneId_t sceneId = scene->getSceneId();
        auto cameras = collectCameras(*scene);
        auto logicEngines = collectLogicEngines(*scene);
        const AuthoredRenderSetup renderSetup = inspectAuthoredRenderSetup(*scene);
        if (!renderSetup.finalFramebufferPass || !renderSetup.finalFramebufferCamera)
            throw std::runtime_error("Fusion Phase 2 scene has no authored framebuffer render pass with a camera");

        m_width = options.fusionRenderWidth > 0 ? static_cast<uint32_t>(options.fusionRenderWidth) :
            (renderSetup.preferredWidth > 0u ? renderSetup.preferredWidth : static_cast<uint32_t>(options.width));
        m_height = options.fusionRenderHeight > 0 ? static_cast<uint32_t>(options.fusionRenderHeight) :
            (renderSetup.preferredHeight > 0u ? renderSetup.preferredHeight : static_cast<uint32_t>(options.height));

        const std::vector<ramses::Camera*> viewControlCameras = selectAuthoredViewCameras(cameras, renderSetup);
        if (options.fusionAutoFrame && viewControlCameras.empty())
            throw std::runtime_error("Fusion auto-frame requested but no authored view-control cameras were found");

        const SceneBounds sceneBounds = estimateSceneBoundsFromMeshNodes(*scene);
        const CameraRig cameraRig = makeCameraRig(sceneBounds, m_width, m_height, options.fusionZoom);

        std::cout << "Fusion Phase 2 loaded scene id: " << sceneId.getValue() << "\n";
        std::cout << "Fusion Phase 2 cameras: " << cameras.size() << "\n";
        std::cout << "Fusion Phase 2 logic engines/objects: " << logicEngines.size() << "/" << countLogicObjects(logicEngines) << "\n";
        std::cout << "Fusion Phase 2 authored render passes total/enabled/framebuffer/enabledFramebuffer/withFramebufferCamera/offscreenWithCamera/disabled/missingCamera: "
                  << renderSetup.totalPasses << "/"
                  << renderSetup.enabledPasses << "/"
                  << renderSetup.framebufferPasses << "/"
                  << renderSetup.enabledFramebufferPasses << "/"
                  << renderSetup.framebufferPassesWithCamera << "/"
                  << renderSetup.offscreenPassesWithCamera << "/"
                  << renderSetup.disabledPasses << "/"
                  << renderSetup.missingCameraPasses << "\n";
        std::cout << "Fusion Phase 2 final framebuffer pass/camera/order/viewport: "
                  << objectName(renderSetup.finalFramebufferPass) << "/"
                  << objectName(renderSetup.finalFramebufferCamera) << "/"
                  << renderSetup.finalRenderOrder << "/"
                  << renderSetup.preferredWidth << "x" << renderSetup.preferredHeight << "\n";
        std::cout << "Fusion Phase 2 authored view-control cameras: " << cameraListName(viewControlCameras) << "\n";
        std::cout << "Fusion Phase 2 auto-frame/orbit/zoom/view: "
                  << (options.fusionAutoFrame ? "on" : "off") << "/"
                  << (options.fusionOrbit ? "on" : "off") << "/"
                  << options.fusionZoom << "/"
                  << options.fusionViewPreset << "\n";
        std::cout << "Fusion Phase 2 RmlUi texture readback size: " << m_width << "x" << m_height << "\n";
        std::cout << "Fusion Phase 4 render-on-demand policy: static QA perspective cache, no per-shell-frame Ramses readPixels\n";
        std::cout << "Fusion Phase 4 render-on-demand max producer frames/readback batch: "
                  << options.fusionFrames << "/" << kFusionInitialReadbackFrames << "\n";
        std::cout << "Fusion Phase 2 retargeting authored camera viewports to offscreen texture size\n";

        m_ramsesWindow = std::make_unique<SdlPlainWindow>("SGFX Cine Ramses Hidden RmlUi Producer", static_cast<int>(m_width), static_cast<int>(m_height), SDL_WINDOW_HIDDEN);
        void* producerHwnd = getWin32Hwnd(m_ramsesWindow->get());
        std::cout << "Fusion Phase 2 producer HWND: " << producerHwnd << "\n";

        ramses::DisplayConfig displayConfig;
        displayConfig.setWindowType(ramses::EWindowType::Windows);
        displayConfig.setWindowsWindowHandle(producerHwnd);
        displayConfig.setWindowRectangle(0, 0, m_width, m_height);
        displayConfig.setWindowTitle("SGFX Cine Ramses Hidden RmlUi Producer");

        const ramses::displayId_t display = renderer.createDisplay(displayConfig);
        if (!display.isValid())
            throw std::runtime_error("Ramses createDisplay returned an invalid display id");
        renderer.setSkippingOfUnmodifiedBuffers(false);
        renderer.flush();

        FusionEventHandler handler(display, sceneId, m_width, m_height);
        if (!pumpFusionUntil(renderer, sceneControl, handler, [&] { return handler.displayCreated(); }, [] {}, std::chrono::seconds(5)))
            throw std::runtime_error("Timed out waiting for Ramses display creation");

        const ramses::displayBufferId_t offscreenBuffer = renderer.createOffscreenBuffer(display, m_width, m_height);
        if (!offscreenBuffer.isValid())
            throw std::runtime_error("Ramses createOffscreenBuffer returned an invalid id");
        handler.setOffscreenBuffer(offscreenBuffer);
        renderer.setDisplayBufferClearColor(display, offscreenBuffer, ramses::vec4f{0.01f, 0.02f, 0.04f, 1.0f});
        renderer.flush();
        std::cout << "Fusion Phase 2 Ramses offscreen buffer id/size: " << offscreenBuffer.getValue()
                  << "/" << m_width << "x" << m_height << "\n";

        if (!pumpFusionUntil(renderer, sceneControl, handler, [&] { return handler.offscreenCreated(); }, [] {}, std::chrono::seconds(5)))
            throw std::runtime_error("Timed out waiting for Ramses offscreen buffer creation");

        bool qaLogicLogged = false;
        auto updateLogicAndViewControl = [&](uint32_t frame, const char* context) {
            bool qaPerspectiveLogicDriven = false;
            if (m_qaPerspective)
            {
                qaPerspectiveLogicDriven =
                    driveFusionQaPerspectiveLogic(logicEngines, frame, options.fusionOrbit, options.fusionZoom, *m_qaPerspective, !qaLogicLogged) > 0u;
                qaLogicLogged = true;
            }

            if (!updateLogicEngines(logicEngines))
                throw std::runtime_error(std::string("LogicEngine update failed ") + context);

            if (!qaPerspectiveLogicDriven)
            {
                if (options.fusionAutoFrame)
                    driveAuthoredCameras(viewControlCameras, cameraRig, frame, options);
                setFusionCameraViewports(cameras, m_width, m_height);
            }
        };

        updateLogicAndViewControl(0u, "before scene publish");
        scene->publish(ramses::EScenePublicationMode::LocalOnly);
        scene->flush();

        if (!sceneControl.setSceneMapping(sceneId, display))
            throw std::runtime_error("Ramses setSceneMapping failed");
        if (!sceneControl.setSceneDisplayBufferAssignment(sceneId, offscreenBuffer, 0))
            throw std::runtime_error("Ramses setSceneDisplayBufferAssignment(offscreen) failed");
        if (!sceneControl.setSceneState(sceneId, ramses::RendererSceneState::Rendered))
            throw std::runtime_error("Ramses setSceneState(Rendered) failed");
        sceneControl.flush();

        if (!pumpFusionUntil(renderer, sceneControl, handler, [&] { return handler.sceneRendered(); }, [&] {
                updateLogicAndViewControl(0u, "while waiting for Rendered");
                scene->flush();
            }, std::chrono::seconds(10)))
            throw std::runtime_error("Timed out waiting for Ramses scene to reach Rendered");

        uint32_t renderedFrames = 0u;
        const uint32_t maxProducerFrames = static_cast<uint32_t>(options.fusionFrames);
        auto renderUntil = [&](uint32_t targetFrame) {
            while (renderedFrames < targetFrame)
            {
                updateLogicAndViewControl(renderedFrames, "during fusion render-on-demand settle");
                scene->flush();
                renderer.doOneLoop();
                pumpFusionEvents(renderer, sceneControl, handler);
                ++renderedFrames;
            }
        };

        bool visibleReadback = false;
        uint32_t nextReadbackFrame = std::min(maxProducerFrames, kFusionInitialReadbackFrames);
        while (!visibleReadback)
        {
            renderUntil(nextReadbackFrame);

            handler.resetPixelsRead();
            ++m_performanceStats.readbackRequests;
            renderer.readPixels(display, offscreenBuffer, 0u, 0u, m_width, m_height);
            renderer.flush();
            if (!pumpFusionUntil(renderer, sceneControl, handler, [&] { return handler.pixelsRead(); }, [&] {
                    updateLogicAndViewControl(renderedFrames, "while waiting for readPixels");
                    scene->flush();
                }, std::chrono::seconds(5)))
                throw std::runtime_error("Timed out waiting for Ramses offscreen readPixels");

            visibleReadback = handler.pixelsReadOk() && handler.ramsesStats().brightPixels > 0u;
            if (visibleReadback)
                break;

            std::cout << "Fusion Phase 4 render-on-demand empty readback at producer frame/request: "
                      << renderedFrames << "/" << m_performanceStats.readbackRequests << "\n";
            if (renderedFrames >= maxProducerFrames)
                break;
            nextReadbackFrame = std::min(maxProducerFrames, renderedFrames + kFusionReadbackRetryFrames);
        }

        m_performanceStats.producerFrames = renderedFrames;
        if (!handler.pixelsReadOk() || handler.ramsesStats().brightPixels == 0u)
        {
            std::ostringstream message;
            message << "Fusion Phase 4 Ramses offscreen readPixels did not contain visible scene pixels after "
                    << renderedFrames << " producer frames and "
                    << m_performanceStats.readbackRequests << " readback request(s)";
            throw std::runtime_error(message.str());
        }

        m_shellWindow.makeCurrent();
        if (SDL_GL_GetCurrentWindow() != m_shellWindow.window() || SDL_GL_GetCurrentContext() != m_shellWindow.context())
            throw std::runtime_error("Fusion Phase 2 shell GL context was not current after Ramses readback");
        std::cout << "Fusion Phase 2 shell GL context current after Ramses readback: yes\n";

        createTexture(handler.pixels());
        m_performanceStats.textureUploads = 1u;
        m_ramsesStats = handler.ramsesStats();
        m_ready = true;
        std::cout << "Fusion Phase 4 render-on-demand producer frames/readPixels/uploads: "
                  << m_performanceStats.producerFrames << "/"
                  << m_performanceStats.readbackRequests << "/"
                  << m_performanceStats.textureUploads << "\n";
        std::cout << "Fusion Phase 2 GL texture id: " << m_texture << "\n";
        std::cout << "Fusion Phase 2 Ramses texture upload for RmlUi CallbackTexture OK\n";
    }

    void createTexture(const std::vector<uint8_t>& pixels)
    {
        if (pixels.size() != static_cast<size_t>(m_width) * static_cast<size_t>(m_height) * 4u)
            throw std::runtime_error("Fusion Phase 2 texture upload size mismatch");

        while (glGetError() != GL_NO_ERROR)
        {
        }
        using GlActiveTextureProc = void(APIENTRY*)(GLenum);
        using GlBindBufferProc = void(APIENTRY*)(GLenum, GLuint);
        const auto activeTexture = reinterpret_cast<GlActiveTextureProc>(SDL_GL_GetProcAddress("glActiveTexture"));
        const auto bindBuffer = reinterpret_cast<GlBindBufferProc>(SDL_GL_GetProcAddress("glBindBuffer"));
        if (activeTexture)
            activeTexture(GL_TEXTURE0);
        if (bindBuffer)
            bindBuffer(GL_PIXEL_UNPACK_BUFFER, 0);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
#ifdef GL_UNPACK_ROW_LENGTH
        glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
#endif
#ifdef GL_UNPACK_SKIP_PIXELS
        glPixelStorei(GL_UNPACK_SKIP_PIXELS, 0);
#endif
#ifdef GL_UNPACK_SKIP_ROWS
        glPixelStorei(GL_UNPACK_SKIP_ROWS, 0);
#endif
        throwOnFusionGlError("RmlUi texture unpack-state reset");

        std::vector<uint8_t> uploadPixels = pixels;
        uint64_t forcedAlphaPixels = 0u;
        for (size_t i = 3u; i < uploadPixels.size(); i += 4u)
        {
            if (uploadPixels[i] != 255u)
                ++forcedAlphaPixels;
            uploadPixels[i] = 255u;
        }

        const GLuint previousTexture = m_texture;
        const bool previousTextureAlive = previousTexture != 0u && glIsTexture(previousTexture) == GL_TRUE;
        if (previousTexture != 0u && !previousTextureAlive)
        {
            std::cout << "Fusion Phase 2 RmlUi texture handle was no longer live before upload: " << previousTexture << "\n";
            m_texture = 0u;
            m_allocatedWidth = 0u;
            m_allocatedHeight = 0u;
        }
        throwOnFusionGlError("RmlUi texture liveness query");

        if (m_texture == 0u)
            glGenTextures(1, &m_texture);
        const bool updateExistingTexture = m_texture != 0u && m_allocatedWidth == m_width && m_allocatedHeight == m_height;
        std::cout << "Fusion Phase 2 RmlUi texture upload target previous/current/alive/update: "
                  << previousTexture << "/" << m_texture << "/"
                  << (previousTextureAlive ? "yes" : "no") << "/"
                  << (updateExistingTexture ? "subimage" : "allocate") << "\n";
        glBindTexture(GL_TEXTURE_2D, m_texture);
        throwOnFusionGlError("RmlUi texture bind");
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        throwOnFusionGlError("RmlUi texture parameters");
        if (updateExistingTexture)
        {
            glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, static_cast<GLsizei>(m_width), static_cast<GLsizei>(m_height), GL_RGBA, GL_UNSIGNED_BYTE, uploadPixels.data());
            throwOnFusionGlError("RmlUi texture subimage upload");
        }
        else
        {
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, static_cast<GLsizei>(m_width), static_cast<GLsizei>(m_height), 0, GL_RGBA, GL_UNSIGNED_BYTE, uploadPixels.data());
            throwOnFusionGlError("RmlUi texture allocation upload");
            m_allocatedWidth = m_width;
            m_allocatedHeight = m_height;
        }
        glBindTexture(GL_TEXTURE_2D, 0);
        std::cout << "Fusion Phase 3 RmlUi texture upload alpha policy: forced opaque alpha on "
                  << forcedAlphaPixels << " / " << (uploadPixels.size() / 4u) << " pixels\n";
    }

    SdlGlWindow& m_shellWindow;
    uint32_t m_width = 0u;
    uint32_t m_height = 0u;
    GLuint m_texture = 0u;
    bool m_ready = false;
    uint32_t m_allocatedWidth = 0u;
    uint32_t m_allocatedHeight = 0u;
    std::string m_profileId;
    std::filesystem::path m_sceneFile;
    FusionReadbackStats m_ramsesStats;
    FusionPerformanceStats m_performanceStats;
    std::optional<FusionQaPerspective> m_qaPerspective;
    std::unique_ptr<SdlPlainWindow> m_ramsesWindow;
    std::unique_ptr<ramses::RamsesFramework> m_framework;
};

struct HubPlanetScene
{
    ramses::Scene* scene = nullptr;
    ramses::MeshNode* planet = nullptr;
};

HubPlanetScene createHubPlanetScene(ramses::RamsesClient& client, ramses::sceneId_t sceneId, uint32_t width, uint32_t height)
{
    ramses::SceneConfig sceneConfig{sceneId, ramses::EScenePublicationMode::LocalOnly, ramses::ERenderBackendCompatibility::OpenGL};
    auto* scene = client.createScene(sceneConfig, "sgfx h1 procedural seriengrafik planet scene");
    if (!scene)
        throw std::runtime_error("Hub H1 createScene returned null");

    auto* camera = scene->createPerspectiveCamera("hub planet camera");
    if (!camera)
        throw std::runtime_error("Hub H1 failed to create camera");
    camera->setViewport(0, 0, width, height);
    camera->setFrustum(30.0f, static_cast<float>(width) / static_cast<float>(height), 0.1f, 100.0f);
    camera->setTranslation({0.0f, 0.0f, 4.8f});

    auto* renderPass = scene->createRenderPass("hub planet render pass");
    if (!renderPass)
        throw std::runtime_error("Hub H1 failed to create render pass");
    renderPass->setClearFlags(ramses::EClearFlag::All);
    renderPass->setClearColor(ramses::vec4f{0.01f, 0.02f, 0.05f, 1.0f});
    renderPass->setCamera(*camera);

    auto* renderGroup = scene->createRenderGroup("hub planet render group");
    if (!renderGroup)
        throw std::runtime_error("Hub H1 failed to create render group");
    renderPass->addRenderGroup(*renderGroup);

    struct PlanetVertex
    {
        ramses::vec3f position;
        ramses::vec4f color;
    };

    constexpr uint32_t rings = 18u;
    constexpr uint32_t segments = 42u;
    constexpr float radius = 1.46f;
    const ramses::vec3f lightDirection = glm::normalize(ramses::vec3f{-0.42f, 0.64f, 0.64f});
    const std::array<ramses::vec4f, 7u> regionColors = {
        ramses::vec4f{0.07f, 0.82f, 0.78f, 1.0f},
        ramses::vec4f{0.98f, 0.72f, 0.22f, 1.0f},
        ramses::vec4f{0.94f, 0.28f, 0.44f, 1.0f},
        ramses::vec4f{0.20f, 0.56f, 0.96f, 1.0f},
        ramses::vec4f{0.58f, 0.41f, 0.95f, 1.0f},
        ramses::vec4f{0.28f, 0.86f, 0.44f, 1.0f},
        ramses::vec4f{0.98f, 0.47f, 0.16f, 1.0f},
    };
    struct CapitalGlow
    {
        float u;
        float v;
        ramses::vec4f color;
        float intensity;
    };
    const std::array<CapitalGlow, 7u> capitalGlows = {{
        {0.07f, 0.51f, ramses::vec4f{1.00f, 0.79f, 0.24f, 1.0f}, 1.35f},
        {0.24f, 0.32f, ramses::vec4f{0.18f, 0.84f, 0.90f, 1.0f}, 0.78f},
        {0.30f, 0.68f, ramses::vec4f{1.00f, 0.42f, 0.54f, 1.0f}, 0.72f},
        {0.50f, 0.20f, ramses::vec4f{0.74f, 0.91f, 1.00f, 1.0f}, 0.68f},
        {0.76f, 0.36f, ramses::vec4f{0.16f, 0.91f, 0.76f, 1.0f}, 0.70f},
        {0.78f, 0.66f, ramses::vec4f{0.92f, 0.98f, 1.00f, 1.0f}, 0.64f},
        {0.52f, 0.82f, ramses::vec4f{1.00f, 0.55f, 0.22f, 1.0f}, 0.66f},
    }};
    const auto wrapDistance = [](float a, float b) {
        const float distance = std::abs(a - b);
        return std::min(distance, 1.0f - distance);
    };
    const auto clampUnit = [](float value) {
        return std::max(0.0f, std::min(1.0f, value));
    };

    std::vector<ramses::vec3f> positions;
    std::vector<ramses::vec4f> colors;
    std::vector<uint16_t> indices;
    positions.reserve(static_cast<size_t>((rings + 1u) * (segments + 1u)));
    colors.reserve(positions.capacity());
    indices.reserve(static_cast<size_t>(rings * segments * 6u));

    for (uint32_t ring = 0u; ring <= rings; ++ring)
    {
        const float v = static_cast<float>(ring) / static_cast<float>(rings);
        const float theta = v * kFusionPi;
        const float sinTheta = std::sin(theta);
        const float cosTheta = std::cos(theta);
        for (uint32_t segment = 0u; segment <= segments; ++segment)
        {
            const float u = static_cast<float>(segment) / static_cast<float>(segments);
            const float phi = u * kFusionPi * 2.0f;
            const ramses::vec3f normal{
                std::cos(phi) * sinTheta,
                cosTheta,
                std::sin(phi) * sinTheta};
            positions.emplace_back(normal * radius);

            const size_t regionIndex = static_cast<size_t>(((segment / 6u) + (ring / 3u) * 2u + ((segment + ring) % 3u)) % regionColors.size());
            const auto& region = regionColors[regionIndex];
            const float plateSignal = 0.72f +
                0.16f * std::sin((u * 5.0f + v * 7.0f) * kFusionPi) +
                0.12f * std::sin((u * 13.0f - v * 4.0f) * kFusionPi);
            const float latitudeShape = 0.86f + 0.14f * std::cos((v - 0.5f) * kFusionPi);
            const float light = 0.38f + 0.62f * std::max(0.0f, glm::dot(normal, lightDirection));
            const float rim = std::pow(std::max(0.0f, 1.0f - normal.z), 2.8f) * 0.34f;
            const float equator = clampUnit(1.0f - std::abs(v - 0.50f) / 0.018f);
            const float latitudeLine = (ring > 0u && ring < rings && ring % 3u == 0u) ? 0.09f : 0.0f;
            float routeLine = 0.0f;
            float capitalLightR = 0.0f;
            float capitalLightG = 0.0f;
            float capitalLightB = 0.0f;
            for (const CapitalGlow& capital : capitalGlows)
            {
                const float longitudeDistance = wrapDistance(u, capital.u);
                routeLine = std::max(routeLine, clampUnit(1.0f - longitudeDistance / 0.018f) * (0.18f + 0.22f * std::sin(v * kFusionPi)));
                const float du = longitudeDistance * std::max(0.24f, sinTheta);
                const float dv = std::abs(v - capital.v);
                const float glow = std::exp(-(du * du + dv * dv) / 0.0027f) * capital.intensity;
                capitalLightR += capital.color.x * glow;
                capitalLightG += capital.color.y * glow;
                capitalLightB += capital.color.z * glow;
            }

            colors.emplace_back(ramses::vec4f{
                clampUnit(region.x * plateSignal * latitudeShape * light + 0.03f + rim * 0.30f + equator * 0.20f + latitudeLine * 0.12f + routeLine * 0.30f + capitalLightR * 0.58f),
                clampUnit(region.y * plateSignal * latitudeShape * light + 0.05f + rim * 0.42f + equator * 0.17f + latitudeLine * 0.16f + routeLine * 0.42f + capitalLightG * 0.58f),
                clampUnit(region.z * plateSignal * latitudeShape * light + 0.07f + rim * 0.58f + equator * 0.22f + latitudeLine * 0.20f + routeLine * 0.48f + capitalLightB * 0.58f),
                1.0f});
        }
    }

    for (uint32_t ring = 0u; ring < rings; ++ring)
    {
        for (uint32_t segment = 0u; segment < segments; ++segment)
        {
            const auto a = static_cast<uint16_t>(ring * (segments + 1u) + segment);
            const auto b = static_cast<uint16_t>(a + 1u);
            const auto c = static_cast<uint16_t>((ring + 1u) * (segments + 1u) + segment + 1u);
            const auto d = static_cast<uint16_t>((ring + 1u) * (segments + 1u) + segment);
            indices.push_back(a);
            indices.push_back(d);
            indices.push_back(b);
            indices.push_back(b);
            indices.push_back(d);
            indices.push_back(c);
        }
    }

    auto* vertexPositions = scene->createArrayResource(positions.size(), positions.data(), "hub planet positions");
    auto* vertexColors = scene->createArrayResource(colors.size(), colors.data(), "hub planet colors");
    auto* triangleIndices = scene->createArrayResource(indices.size(), indices.data(), "hub planet indices");
    if (!vertexPositions || !vertexColors || !triangleIndices)
        throw std::runtime_error("Hub H1 failed to create planet resources");

    ramses::EffectDescription effectDesc;
    effectDesc.setVertexShader(R"glsl(
#version 100
uniform highp mat4 mvpMatrix;
attribute vec3 a_position;
attribute vec4 a_color;
varying mediump vec4 v_color;
void main()
{
    v_color = a_color;
    gl_Position = mvpMatrix * vec4(a_position, 1.0);
}
)glsl");
    effectDesc.setFragmentShader(R"glsl(
#version 100
varying mediump vec4 v_color;
void main()
{
    gl_FragColor = v_color;
}
)glsl");
    effectDesc.setUniformSemantic("mvpMatrix", ramses::EEffectUniformSemantic::ModelViewProjectionMatrix);

    auto* effect = scene->createEffect(effectDesc, "hub planet vertex color effect");
    auto* appearance = effect ? scene->createAppearance(*effect, "hub planet appearance") : nullptr;
    auto* geometry = effect ? scene->createGeometry(*effect, "hub planet geometry") : nullptr;
    if (!effect || !appearance || !geometry)
        throw std::runtime_error("Hub H1 failed to create planet effect/appearance/geometry");

    geometry->setIndices(*triangleIndices);
    const std::optional<ramses::AttributeInput> positionInput = effect->findAttributeInput("a_position");
    const std::optional<ramses::AttributeInput> colorInput = effect->findAttributeInput("a_color");
    if (!positionInput || !colorInput)
        throw std::runtime_error("Hub H1 shader inputs were not reflected");
    geometry->setInputBuffer(*positionInput, *vertexPositions);
    geometry->setInputBuffer(*colorInput, *vertexColors);

    auto* planet = scene->createMeshNode("seriengrafik planet procedural sphere");
    if (!planet)
        throw std::runtime_error("Hub H1 failed to create planet mesh");
    planet->setAppearance(*appearance);
    planet->setGeometry(*geometry);
    planet->setTranslation({0.0f, -0.03f, -2.05f});
    renderGroup->addMeshNode(*planet);

    return {scene, planet};
}

class HubPlanetTexture
{
public:
    explicit HubPlanetTexture(const Options& options)
    {
        loadInitialFrame(options);
    }

    bool ready() const
    {
        return m_ready && !m_pixels.empty();
    }

    Rml::Vector2i textureDimensions() const
    {
        return {static_cast<int>(m_width), static_cast<int>(m_height)};
    }

    const std::vector<Rml::byte>& pixels() const
    {
        return m_pixels;
    }

    const FusionReadbackStats& ramsesStats() const
    {
        return m_ramsesStats;
    }

    const FusionPerformanceStats& performanceStats() const
    {
        return m_performanceStats;
    }

private:
    void loadInitialFrame(const Options& options)
    {
        m_width = static_cast<uint32_t>(options.hubPlanetRenderWidth);
        m_height = static_cast<uint32_t>(options.hubPlanetRenderHeight);
        const auto linkedVersion = ramses::GetRamsesVersion();
        std::cout << "Hub H1 linked Ramses version: " << linkedVersion.string << "\n";
        std::cout << "Hub H1 procedural planet source: SGFX-owned faceted sphere, not Earth, not game art\n";
        std::cout << "Hub H1 fusion pipe: Ramses scene -> offscreen buffer -> readPixels -> RmlUi-owned CallbackTexture decorator\n";
        std::cout << "Hub H1 planet render size/frames: " << m_width << "x" << m_height << "/" << options.hubPlanetFrames << "\n";
        std::cout << "Hub H4 planet polish: soft atlas background, SGFX world-map plates, route lines, rim halo, capital glow\n";

        ramses::RamsesFrameworkConfig frameworkConfig{ramses::EFeatureLevel_01};
        frameworkConfig.setRequestedRamsesShellType(ramses::ERamsesShellType::Console);
        frameworkConfig.setPeriodicLogInterval(std::chrono::seconds(1));
        ramses::RamsesFramework framework(frameworkConfig);
        auto& client = *framework.createClient("sgfx-cine-hub-planet-h1-client");

        ramses::RendererConfig rendererConfig;
        rendererConfig.setRenderThreadLoopTimingReportingPeriod(std::chrono::milliseconds(500));
        auto& renderer = *framework.createRenderer(rendererConfig);
        auto& sceneControl = *renderer.getSceneControlAPI();
        framework.connect();

        SdlPlainWindow producerWindow("SGFX Cine Ramses Hidden Hub Planet Producer", static_cast<int>(m_width), static_cast<int>(m_height), SDL_WINDOW_HIDDEN);
        void* producerHwnd = getWin32Hwnd(producerWindow.get());
        std::cout << "Hub H1 producer HWND: " << producerHwnd << "\n";

        ramses::DisplayConfig displayConfig;
        displayConfig.setWindowType(ramses::EWindowType::Windows);
        displayConfig.setWindowsWindowHandle(producerHwnd);
        displayConfig.setWindowRectangle(0, 0, m_width, m_height);
        displayConfig.setWindowTitle("SGFX Cine Ramses Hidden Hub Planet Producer");

        const ramses::displayId_t display = renderer.createDisplay(displayConfig);
        if (!display.isValid())
            throw std::runtime_error("Hub H1 Ramses createDisplay returned an invalid display id");
        renderer.setSkippingOfUnmodifiedBuffers(false);
        renderer.flush();

        const ramses::sceneId_t sceneId{91u};
        FusionEventHandler handler(display, sceneId, m_width, m_height);
        if (!pumpFusionUntil(renderer, sceneControl, handler, [&] { return handler.displayCreated(); }, [] {}, std::chrono::seconds(5)))
            throw std::runtime_error("Hub H1 timed out waiting for Ramses display creation");

        const ramses::displayBufferId_t offscreenBuffer = renderer.createOffscreenBuffer(display, m_width, m_height);
        if (!offscreenBuffer.isValid())
            throw std::runtime_error("Hub H1 Ramses createOffscreenBuffer returned an invalid id");
        handler.setOffscreenBuffer(offscreenBuffer);
        renderer.setDisplayBufferClearColor(display, offscreenBuffer, ramses::vec4f{0.01f, 0.02f, 0.05f, 1.0f});
        renderer.flush();
        std::cout << "Hub H1 Ramses offscreen buffer id/size: " << offscreenBuffer.getValue()
                  << "/" << m_width << "x" << m_height << "\n";

        if (!pumpFusionUntil(renderer, sceneControl, handler, [&] { return handler.offscreenCreated(); }, [] {}, std::chrono::seconds(5)))
            throw std::runtime_error("Hub H1 timed out waiting for Ramses offscreen buffer creation");

        HubPlanetScene planetScene = createHubPlanetScene(client, sceneId, m_width, m_height);
        planetScene.scene->publish(ramses::EScenePublicationMode::LocalOnly);
        planetScene.scene->flush();

        if (!sceneControl.setSceneMapping(sceneId, display))
            throw std::runtime_error("Hub H1 Ramses setSceneMapping failed");
        if (!sceneControl.setSceneDisplayBufferAssignment(sceneId, offscreenBuffer, 0))
            throw std::runtime_error("Hub H1 Ramses setSceneDisplayBufferAssignment(offscreen) failed");
        if (!sceneControl.setSceneState(sceneId, ramses::RendererSceneState::Rendered))
            throw std::runtime_error("Hub H1 Ramses setSceneState(Rendered) failed");
        sceneControl.flush();

        if (!pumpFusionUntil(renderer, sceneControl, handler, [&] { return handler.sceneRendered(); }, [&] { planetScene.scene->flush(); }, std::chrono::seconds(5)))
            throw std::runtime_error("Hub H1 timed out waiting for Ramses scene to reach Rendered");

        uint32_t renderedFrames = 0u;
        while (renderedFrames < static_cast<uint32_t>(options.hubPlanetFrames))
        {
            const float yaw = static_cast<float>(renderedFrames) * 0.85f + 18.0f;
            planetScene.planet->setRotation({-7.0f, yaw, 0.0f}, ramses::ERotationType::Euler_XYZ);
            planetScene.scene->flush();
            renderer.doOneLoop();
            pumpFusionEvents(renderer, sceneControl, handler);
            ++renderedFrames;
        }

        handler.resetPixelsRead();
        ++m_performanceStats.readbackRequests;
        renderer.readPixels(display, offscreenBuffer, 0u, 0u, m_width, m_height);
        renderer.flush();
        if (!pumpFusionUntil(renderer, sceneControl, handler, [&] { return handler.pixelsRead(); }, [&] { planetScene.scene->flush(); }, std::chrono::seconds(5)))
            throw std::runtime_error("Hub H1 timed out waiting for Ramses planet readPixels");
        m_performanceStats.producerFrames = renderedFrames;

        if (!handler.pixelsReadOk() || handler.ramsesStats().brightPixels == 0u)
            throw std::runtime_error("Hub H1 Ramses planet readPixels did not contain visible pixels");

        storePixels(handler.pixels());
        m_performanceStats.textureUploads = 1u;
        m_ramsesStats = handler.ramsesStats();
        m_ready = true;
        std::cout << "Hub H1 Ramses planet bright pixels: " << m_ramsesStats.brightPixels << "\n";
        std::cout << "Hub H1 Ramses planet bright bounds x/y: "
                  << m_ramsesStats.minX << "-" << m_ramsesStats.maxX << "/"
                  << m_ramsesStats.minY << "-" << m_ramsesStats.maxY << "\n";
        std::cout << "Hub H1 render-on-demand producer frames/readPixels/uploads: "
                  << m_performanceStats.producerFrames << "/"
                  << m_performanceStats.readbackRequests << "/"
                  << m_performanceStats.textureUploads << "\n";
        std::cout << "Hub H1 RmlUi texture source bytes: " << m_pixels.size() << "\n";
    }

    void storePixels(const std::vector<uint8_t>& pixels)
    {
        if (pixels.size() != static_cast<size_t>(m_width) * static_cast<size_t>(m_height) * 4u)
            throw std::runtime_error("Hub H1 texture source size mismatch");

        m_pixels.assign(pixels.begin(), pixels.end());
        size_t backgroundPixels = 0u;
        size_t visiblePixels = 0u;
        const size_t pixelCount = m_pixels.size() / 4u;
        for (size_t pixel = 0u; pixel < pixelCount; ++pixel)
        {
            const size_t i = pixel * 4u + 3u;
            const int brightness = static_cast<int>(m_pixels[i - 3u]) + static_cast<int>(m_pixels[i - 2u]) + static_cast<int>(m_pixels[i - 1u]);
            if (brightness <= 28)
            {
                const float x = static_cast<float>(pixel % m_width) / static_cast<float>(std::max(1u, m_width));
                const float y = static_cast<float>(pixel / m_width) / static_cast<float>(std::max(1u, m_height));
                const float dx = x - 0.50f;
                const float dy = (y - 0.50f) * 1.18f;
                const float halo = std::max(0.0f, 1.0f - std::sqrt(dx * dx + dy * dy) / 0.58f);
                m_pixels[i - 3u] = static_cast<Rml::byte>(14u + static_cast<uint8_t>(22.0f * halo));
                m_pixels[i - 2u] = static_cast<Rml::byte>(21u + static_cast<uint8_t>(54.0f * halo));
                m_pixels[i - 1u] = static_cast<Rml::byte>(48u + static_cast<uint8_t>(62.0f * halo));
                m_pixels[i] = 255u;
                ++backgroundPixels;
            }
            else
            {
                m_pixels[i] = 255u;
                ++visiblePixels;
            }
        }
        std::cout << "Hub H4 planet atlas pixels visible/background: "
                  << visiblePixels << "/" << backgroundPixels << "\n";
    }

    uint32_t m_width = 0u;
    uint32_t m_height = 0u;
    bool m_ready = false;
    std::vector<Rml::byte> m_pixels;
    FusionReadbackStats m_ramsesStats;
    FusionPerformanceStats m_performanceStats;
};

class RamsesCarDecorator : public Rml::Decorator
{
public:
    RamsesCarDecorator(Rml::CallbackTexture callbackTexture, const FusionCarTexture* source)
        : m_callbackTexture(std::move(callbackTexture))
        , m_source(source)
    {
        AddTexture(m_callbackTexture);
    }

    Rml::DecoratorDataHandle GenerateElementData(Rml::Element* element, Rml::BoxArea paintArea) const override
    {
        if (!m_source || !m_source->ready())
            return Rml::Decorator::INVALID_DECORATORDATAHANDLE;

        const Rml::RenderBox renderBox = element->GetRenderBox(paintArea);
        const Rml::Vector2f fillOffset = renderBox.GetFillOffset();
        const Rml::Vector2f fillSize = renderBox.GetFillSize();
        const Rml::Vector2i textureSize = m_source->textureDimensions();
        if (fillSize.x <= 0.0f || fillSize.y <= 0.0f || textureSize.x <= 0 || textureSize.y <= 0)
            return Rml::Decorator::INVALID_DECORATORDATAHANDLE;

        const TextureRegion textureRegion = makeTextureRegion(m_source->ramsesStats(), textureSize, fillSize.x / fillSize.y);

        Rml::Mesh mesh;
        Rml::MeshUtilities::GenerateQuad(
            mesh,
            fillOffset,
            fillSize,
            Rml::ColourbPremultiplied(255, 255, 255, 255),
            textureRegion.topLeftUv,
            textureRegion.bottomRightUv);

        auto* data = new DecoratorData(element->GetRenderManager()->MakeGeometry(std::move(mesh)), paintArea);
        return reinterpret_cast<Rml::DecoratorDataHandle>(data);
    }

    void ReleaseElementData(Rml::DecoratorDataHandle elementData) const override
    {
        delete reinterpret_cast<DecoratorData*>(elementData);
    }

    void RenderElement(Rml::Element* element, Rml::DecoratorDataHandle elementData) const override
    {
        auto* data = reinterpret_cast<DecoratorData*>(elementData);
        if (!data)
            return;
        data->geometry.Render(element->GetAbsoluteOffset(Rml::BoxArea::Border), GetTexture());
    }

private:
    struct TextureRegion
    {
        Rml::Vector2f topLeftUv{0.0f, 1.0f};
        Rml::Vector2f bottomRightUv{1.0f, 0.0f};
    };

    struct DecoratorData
    {
        DecoratorData(Rml::Geometry&& geometry, Rml::BoxArea paintArea)
            : geometry(std::move(geometry))
            , paintArea(paintArea)
        {
        }

        Rml::Geometry geometry;
        Rml::BoxArea paintArea;
    };

    static TextureRegion makeTextureRegion(const FusionReadbackStats& stats, Rml::Vector2i textureSize, float fillAspect)
    {
        if (stats.brightPixels == 0u || stats.minX >= stats.maxX || stats.minY >= stats.maxY || fillAspect <= 0.0f || !std::isfinite(fillAspect))
            return {};

        const float sourceWidth = static_cast<float>(textureSize.x);
        const float sourceHeight = static_cast<float>(textureSize.y);
        const float boundsMinX = static_cast<float>(stats.minX);
        const float boundsMaxX = static_cast<float>(stats.maxX + 1u);
        const float boundsMinY = static_cast<float>(stats.minY);
        const float boundsMaxY = static_cast<float>(stats.maxY + 1u);
        const float boundsWidth = std::max(1.0f, boundsMaxX - boundsMinX);
        const float boundsHeight = std::max(1.0f, boundsMaxY - boundsMinY);
        const float boundsCenterX = (boundsMinX + boundsMaxX) * 0.5f;
        const float boundsCenterY = (boundsMinY + boundsMaxY) * 0.5f;

        float cropWidth = boundsWidth / 0.44f;
        float cropHeight = boundsHeight / 0.60f;
        if (cropWidth / cropHeight < fillAspect)
            cropWidth = cropHeight * fillAspect;
        else
            cropHeight = cropWidth / fillAspect;

        cropWidth = std::min(cropWidth, sourceWidth);
        cropHeight = std::min(cropHeight, sourceHeight);

        auto centerCrop = [](float center, float size, float limit) {
            float min = center - size * 0.5f;
            min = std::max(0.0f, std::min(min, limit - size));
            return min;
        };

        const float cropMinX = centerCrop(boundsCenterX, cropWidth, sourceWidth);
        const float cropMinY = centerCrop(boundsCenterY, cropHeight, sourceHeight);
        const float cropMaxX = cropMinX + cropWidth;
        const float cropMaxY = cropMinY + cropHeight;

        return {
            {cropMinX / sourceWidth, cropMaxY / sourceHeight},
            {cropMaxX / sourceWidth, cropMinY / sourceHeight}};
    }

    Rml::CallbackTexture m_callbackTexture;
    const FusionCarTexture* m_source = nullptr;
};

class RamsesCarDecoratorInstancer : public Rml::DecoratorInstancer
{
public:
    explicit RamsesCarDecoratorInstancer(const FusionCarTexture* source)
        : m_source(source)
    {
    }

    Rml::SharedPtr<Rml::Decorator> InstanceDecorator(const Rml::String&, const Rml::PropertyDictionary&, const Rml::DecoratorInstancerInterface& instancerInterface) override
    {
        if (!m_source || !m_source->ready())
            return nullptr;

        Rml::CallbackTexture callbackTexture = instancerInterface.GetRenderManager().MakeCallbackTexture([source = m_source](const Rml::CallbackTextureInterface& textureInterface) -> bool {
            if (!source || !source->ready())
                return false;
            textureInterface.SetTextureHandle(source->textureHandle(), source->textureDimensions());
            return true;
        });

        std::cout << "Fusion Phase 2 RmlUi CallbackTexture registered handle/dims: "
                  << m_source->textureHandle() << "/"
                  << m_source->textureDimensions().x << "x" << m_source->textureDimensions().y << "\n";
        return Rml::MakeShared<RamsesCarDecorator>(std::move(callbackTexture), m_source);
    }

private:
    const FusionCarTexture* m_source = nullptr;
};

class HubPlanetDecorator : public Rml::Decorator
{
public:
    HubPlanetDecorator(Rml::CallbackTexture callbackTexture, const HubPlanetTexture* source)
        : m_callbackTexture(std::move(callbackTexture))
        , m_source(source)
    {
        AddTexture(m_callbackTexture);
    }

    Rml::DecoratorDataHandle GenerateElementData(Rml::Element* element, Rml::BoxArea paintArea) const override
    {
        if (!m_source || !m_source->ready())
            return Rml::Decorator::INVALID_DECORATORDATAHANDLE;

        const Rml::RenderBox renderBox = element->GetRenderBox(paintArea);
        const Rml::Vector2f fillOffset = renderBox.GetFillOffset();
        const Rml::Vector2f fillSize = renderBox.GetFillSize();
        const Rml::Vector2i textureSize = m_source->textureDimensions();
        if (fillSize.x <= 0.0f || fillSize.y <= 0.0f || textureSize.x <= 0 || textureSize.y <= 0)
            return Rml::Decorator::INVALID_DECORATORDATAHANDLE;
        static bool loggedGeometry = false;
        if (!loggedGeometry)
        {
            const Rml::Vector2f absoluteOffset = element->GetAbsoluteOffset(Rml::BoxArea::Border);
            std::cout << "Hub H1 RmlUi decorator box offset/size: "
                      << absoluteOffset.x << "," << absoluteOffset.y << "/"
                      << fillSize.x << "x" << fillSize.y << "\n";
            loggedGeometry = true;
        }
        const TextureRegion textureRegion = makeTextureRegion(m_source->ramsesStats(), textureSize, fillSize.x / fillSize.y);

        Rml::Mesh mesh;
        Rml::MeshUtilities::GenerateQuad(
            mesh,
            fillOffset,
            fillSize,
            Rml::ColourbPremultiplied(255, 255, 255, 255),
            textureRegion.topLeftUv,
            textureRegion.bottomRightUv);

        auto* data = new DecoratorData(element->GetRenderManager()->MakeGeometry(std::move(mesh)), paintArea);
        return reinterpret_cast<Rml::DecoratorDataHandle>(data);
    }

    void ReleaseElementData(Rml::DecoratorDataHandle elementData) const override
    {
        delete reinterpret_cast<DecoratorData*>(elementData);
    }

    void RenderElement(Rml::Element* element, Rml::DecoratorDataHandle elementData) const override
    {
        auto* data = reinterpret_cast<DecoratorData*>(elementData);
        if (!data)
            return;
        Rml::RenderManager* renderManager = element->GetRenderManager();
        if (!renderManager)
            return;

        const Rml::RenderState renderState = renderManager->GetState();
        const Rml::RenderBox renderBox = element->GetRenderBox(data->paintArea);
        const Rml::Vector2f absoluteFillOffset = element->GetAbsoluteOffset(Rml::BoxArea::Border) + renderBox.GetFillOffset();
        const Rml::Vector2f fillSize = renderBox.GetFillSize();
        renderManager->SetTransform(nullptr);
        renderManager->SetScissorRegion(Rml::Rectanglei::FromPositionSize(
            Rml::Vector2i{static_cast<int>(std::round(absoluteFillOffset.x)), static_cast<int>(std::round(absoluteFillOffset.y))},
            Rml::Vector2i{std::max(1, static_cast<int>(std::round(fillSize.x))), std::max(1, static_cast<int>(std::round(fillSize.y)))}));
        data->geometry.Render(element->GetAbsoluteOffset(Rml::BoxArea::Border), GetTexture());
        renderManager->SetState(renderState);
    }

private:
    struct TextureRegion
    {
        Rml::Vector2f topLeftUv{0.0f, 1.0f};
        Rml::Vector2f bottomRightUv{1.0f, 0.0f};
    };

    struct DecoratorData
    {
        DecoratorData(Rml::Geometry&& geometry, Rml::BoxArea paintArea)
            : geometry(std::move(geometry))
            , paintArea(paintArea)
        {
        }

        Rml::Geometry geometry;
        Rml::BoxArea paintArea;
    };

    static TextureRegion makeTextureRegion(const FusionReadbackStats& stats, Rml::Vector2i textureSize, float fillAspect)
    {
        if (stats.brightPixels == 0u || stats.minX >= stats.maxX || stats.minY >= stats.maxY || fillAspect <= 0.0f || !std::isfinite(fillAspect))
            return {};

        const float sourceWidth = static_cast<float>(textureSize.x);
        const float sourceHeight = static_cast<float>(textureSize.y);
        const float boundsMinX = static_cast<float>(stats.minX);
        const float boundsMaxX = static_cast<float>(stats.maxX + 1u);
        const float boundsMinY = static_cast<float>(stats.minY);
        const float boundsMaxY = static_cast<float>(stats.maxY + 1u);
        const float boundsWidth = std::max(1.0f, boundsMaxX - boundsMinX);
        const float boundsHeight = std::max(1.0f, boundsMaxY - boundsMinY);
        const float boundsCenterX = (boundsMinX + boundsMaxX) * 0.5f;
        const float boundsCenterY = (boundsMinY + boundsMaxY) * 0.5f;

        float cropWidth = boundsWidth * 1.22f;
        float cropHeight = boundsHeight * 1.18f;
        if (cropWidth / cropHeight < fillAspect)
            cropWidth = cropHeight * fillAspect;
        else
            cropHeight = cropWidth / fillAspect;

        cropWidth = std::min(cropWidth, sourceWidth);
        cropHeight = std::min(cropHeight, sourceHeight);

        auto centerCrop = [](float center, float size, float limit) {
            float min = center - size * 0.5f;
            min = std::max(0.0f, std::min(min, limit - size));
            return min;
        };

        const float cropMinX = centerCrop(boundsCenterX, cropWidth, sourceWidth);
        const float cropMinY = centerCrop(boundsCenterY, cropHeight, sourceHeight);
        const float cropMaxX = cropMinX + cropWidth;
        const float cropMaxY = cropMinY + cropHeight;

        return {
            {cropMinX / sourceWidth, cropMaxY / sourceHeight},
            {cropMaxX / sourceWidth, cropMinY / sourceHeight}};
    }

    Rml::CallbackTexture m_callbackTexture;
    const HubPlanetTexture* m_source = nullptr;
};

class HubPlanetDecoratorInstancer : public Rml::DecoratorInstancer
{
public:
    explicit HubPlanetDecoratorInstancer(const HubPlanetTexture* source)
        : m_source(source)
    {
    }

    Rml::SharedPtr<Rml::Decorator> InstanceDecorator(const Rml::String&, const Rml::PropertyDictionary&, const Rml::DecoratorInstancerInterface& instancerInterface) override
    {
        if (!m_source || !m_source->ready())
            return nullptr;

        Rml::CallbackTexture callbackTexture = instancerInterface.GetRenderManager().MakeCallbackTexture([source = m_source](const Rml::CallbackTextureInterface& textureInterface) -> bool {
            if (!source || !source->ready())
                return false;
            return textureInterface.GenerateTexture({source->pixels().data(), source->pixels().size()}, source->textureDimensions());
        });

        std::cout << "Hub H1 RmlUi CallbackTexture generated from Ramses pixels/dims: "
                  << m_source->pixels().size() << "/"
                  << m_source->textureDimensions().x << "x" << m_source->textureDimensions().y << "\n";
        return Rml::MakeShared<HubPlanetDecorator>(std::move(callbackTexture), m_source);
    }

private:
    const HubPlanetTexture* m_source = nullptr;
};

std::string escapeRmlText(const std::string& value)
{
    std::string escaped;
    escaped.reserve(value.size());
    for (char ch : value)
    {
        switch (ch)
        {
        case '&':
            escaped += "&amp;";
            break;
        case '<':
            escaped += "&lt;";
            break;
        case '>':
            escaped += "&gt;";
            break;
        case '"':
            escaped += "&quot;";
            break;
        default:
            escaped.push_back(ch);
            break;
        }
    }
    return escaped;
}

std::string shortenPerspectiveId(const std::string& id)
{
    constexpr size_t maxLength = 28u;
    if (id.size() <= maxLength)
        return id;
    return id.substr(0u, maxLength - 1u) + ".";
}

struct HubNodeDefinition
{
    const char* elementId;
    const char* label;
    const char* status;
    const char* accent;
    bool live;
    double x;
    double y;
    double width;
    double height;
};

constexpr int kHubNodeCount = 6;
constexpr int kHubNodeLiveIndex = 0;
constexpr int kHubNodeDeliveryIndex = 1;
constexpr int kHubNodeDisabledIndex = 2;
constexpr int kHubNodeApiIndex = 3;
constexpr int kHubNodeCountryIndex = 4;
constexpr int kHubNodeSizeIndex = 5;
constexpr int kHubDataNodeCount = kHubNodeCount - 1;
constexpr std::array<HubNodeDefinition, kHubNodeCount> kHubNodes = {{
    {"hub-node-car", "3D Car", "LIVE QA SURFACE", "#FFC94D", true, 818.0, 308.0, 174.0, 50.0},
    {"hub-node-delivery", "Delivery", "LOADING", "#FF6B81", false, 552.0, 412.0, 166.0, 44.0},
    {"hub-node-disabled", "Disabled Tests", "LOADING", "#2FD6E6", false, 562.0, 228.0, 176.0, 44.0},
    {"hub-node-api", "API Version", "LOADING", "#BFE9FF", false, 744.0, 136.0, 166.0, 44.0},
    {"hub-node-country", "Country Variants", "LOADING", "#25E8C8", false, 982.0, 242.0, 184.0, 44.0},
    {"hub-node-size", "Size Trend", "LOADING", "#FFB36B", false, 990.0, 430.0, 148.0, 44.0},
}};

bool isHubDeliveryNode(int index)
{
    return index == kHubNodeDeliveryIndex;
}

const HubCapitalSummary* hubCapitalForIndex(int index, const HubCapitalSummaries& summaries)
{
    switch (index)
    {
    case kHubNodeDeliveryIndex: return &summaries.delivery;
    case kHubNodeDisabledIndex: return &summaries.disabledTests;
    case kHubNodeApiIndex: return &summaries.apiVersion;
    case kHubNodeCountryIndex: return &summaries.countryVariants;
    case kHubNodeSizeIndex: return &summaries.sizeTrend;
    default: return nullptr;
    }
}

bool isHubDataNode(int index)
{
    return index >= kHubNodeDeliveryIndex && index <= kHubNodeSizeIndex;
}

bool isHubDataNodeLoaded(int index, const HubCapitalSummaries& summaries)
{
    const HubCapitalSummary* capital = hubCapitalForIndex(index, summaries);
    return capital && capital->loaded;
}

int loadedHubCapitalCount(const HubCapitalSummaries& summaries)
{
    int count = 0;
    for (int index = kHubNodeDeliveryIndex; index <= kHubNodeSizeIndex; ++index)
    {
        if (isHubDataNodeLoaded(index, summaries))
            ++count;
    }
    return count;
}

std::string hubWiringSummary(const HubCapitalSummaries& summaries)
{
    const int loaded = loadedHubCapitalCount(summaries);
    const int unavailable = kHubDataNodeCount - loaded;
    std::ostringstream text;
    text << "wired=" << loaded << " data capitals";
    if (unavailable > 0)
        text << ", unavailable=" << unavailable;
    return text.str();
}

std::string hubNodeStatusText(const HubNodeDefinition& node, int index, const HubCapitalSummaries& summaries)
{
    const HubCapitalSummary* capital = hubCapitalForIndex(index, summaries);
    if (capital)
        return capital->loaded ? capital->statusText : "UNAVAILABLE";
    return node.status;
}

std::string buildHubNodeCss()
{
    std::ostringstream css;
    for (const HubNodeDefinition& node : kHubNodes)
    {
        css << "#" << node.elementId << " { left: " << number(node.x, 0) << "px; top: " << number(node.y, 0)
            << "px; width: " << number(node.width, 0) << "px; height: " << number(node.height, 0)
            << "px; border: 1px " << node.accent << "; box-shadow: " << node.accent
            << "88 0px 0px " << (node.live ? "26px 3px" : "16px 1px") << "; }\n";
    }
    return css.str();
}

std::string buildHubNodeMarkup(const HubCapitalSummaries& summaries)
{
    std::ostringstream markup;
    for (int index = 0; index < kHubNodeCount; ++index)
    {
        const HubNodeDefinition& node = kHubNodes[static_cast<size_t>(index)];
        markup << "<div id=\"" << node.elementId << "\" class=\"hub-node";
        if (node.live || isHubDataNodeLoaded(index, summaries))
            markup << " hub-node-live";
        markup << "\">";
        markup << "<div class=\"hub-node-beacon\"></div>";
        markup << "<div class=\"hub-node-label\">" << escapeRmlText(node.label) << "</div>";
        markup << "<div class=\"hub-node-status\">" << escapeRmlText(hubNodeStatusText(node, index, summaries)) << "</div>";
        markup << "</div>";
    }
    return markup.str();
}

std::string buildPerspectivePickerInner(const std::optional<FusionQaPerspective>& perspective)
{
    std::ostringstream markup;
    markup << "<div class=\"perspective-kicker\">QA PERSPECTIVE</div>";

    if (!perspective)
    {
        markup << "<div class=\"perspective-row perspective-row-active\">AUTHORED CAMERA</div>";
        markup << "<div class=\"perspective-meta\">fallback view preset</div>";
        return markup.str();
    }

    markup << "<div class=\"perspective-set\">" << escapeRmlText(perspective->setName) << " / "
           << perspective->viewIds.size() << " views</div>";

    auto selected = std::find(perspective->viewIds.begin(), perspective->viewIds.end(), perspective->id);
    const size_t selectedIndex = selected == perspective->viewIds.end() ? 0u :
        static_cast<size_t>(std::distance(perspective->viewIds.begin(), selected));
    const size_t firstIndex = selectedIndex > 1u ? selectedIndex - 1u : 0u;
    const size_t lastIndex = std::min(perspective->viewIds.size(), firstIndex + 4u);

    for (size_t index = firstIndex; index < lastIndex; ++index)
    {
        const bool active = perspective->viewIds[index] == perspective->id;
        markup << "<div class=\"perspective-row";
        if (active)
            markup << " perspective-row-active";
        markup << "\">" << escapeRmlText(shortenPerspectiveId(perspective->viewIds[index])) << "</div>";
    }
    return markup.str();
}

std::string buildPerspectivePickerMarkup(const std::optional<FusionQaPerspective>& perspective)
{
    return "<div id=\"viewer-perspective-picker\">" + buildPerspectivePickerInner(perspective) + "</div>";
}

std::string buildRegisteredCarCountText(size_t exportedCount, size_t registeredProfileCount)
{
    std::ostringstream markup;
    markup << exportedCount << " with exports / ";
    if (registeredProfileCount > 0u)
        markup << registeredProfileCount << " registered";
    else
        markup << "registry unavailable";
    return markup.str();
}

std::string buildCarPickerInner(const std::vector<FusionCarCandidate>& candidates, int selectedIndex, size_t registeredProfileCount)
{
    std::ostringstream markup;
    markup << "<div class=\"car-kicker\">CAR EXPORT</div>";
    if (candidates.empty())
    {
        markup << "<div class=\"car-row car-row-active\">NO EXPORTS FOUND</div>";
        markup << "<div class=\"car-meta\">" << buildRegisteredCarCountText(0u, registeredProfileCount) << "</div>";
        return markup.str();
    }

    markup << "<div class=\"car-meta\">" << buildRegisteredCarCountText(candidates.size(), registeredProfileCount) << "</div>";
    for (size_t index = 0u; index < candidates.size(); ++index)
    {
        const FusionCarCandidate& candidate = candidates[index];
        const bool active = static_cast<int>(index) == selectedIndex;
        markup << "<div class=\"car-row";
        if (active)
            markup << " car-row-active";
        markup << "\">" << escapeRmlText(candidate.label) << "</div>";
    }
    return markup.str();
}

std::string buildCarPickerMarkup(const std::vector<FusionCarCandidate>& candidates, int selectedIndex, size_t registeredProfileCount)
{
    return "<div id=\"viewer-car-picker\">" + buildCarPickerInner(candidates, selectedIndex, registeredProfileCount) + "</div>";
}

std::string resolveHubActiveProfileText(
    bool fusionEnabled,
    const std::vector<FusionCarCandidate>& candidates,
    int selectedCarIndex,
    const std::string& activeProfileId)
{
    if (!activeProfileId.empty())
        return activeProfileId;
    if (selectedCarIndex >= 0 && selectedCarIndex < static_cast<int>(candidates.size()))
        return candidates[static_cast<size_t>(selectedCarIndex)].profileId;
    return fusionEnabled ? "CAR LOADING" : "PICK 3D CAR";
}

std::string buildHubStatusMarkup(
    bool fusionEnabled,
    const std::vector<FusionCarCandidate>& candidates,
    int selectedCarIndex,
    size_t registeredProfileCount,
    const std::string& activeProfileId,
    const HubCapitalSummaries& summaries)
{
    std::ostringstream markup;
    markup << "<div id=\"hub-status-panel\">";
    markup << "<div class=\"hub-status-kicker\">QA BOARD STATUS</div>";
    markup << "<div class=\"hub-status-row\"><div class=\"hub-status-label\">ACTIVE PROFILE</div><div id=\"hub-status-profile\" class=\"hub-status-value\">"
           << escapeRmlText(resolveHubActiveProfileText(fusionEnabled, candidates, selectedCarIndex, activeProfileId))
           << "</div></div>";
    markup << "<div class=\"hub-status-row\"><div class=\"hub-status-label\">CAR FLEET</div><div id=\"hub-status-fleet\" class=\"hub-status-value\">"
           << escapeRmlText(buildRegisteredCarCountText(candidates.size(), registeredProfileCount))
           << "</div></div>";
    markup << "<div class=\"hub-status-row\"><div class=\"hub-status-label\">BUCKET B</div><div class=\"hub-status-value\">"
           << escapeRmlText(std::to_string(loadedHubCapitalCount(summaries)) + " DATA CAPITALS WIRED")
           << "</div></div>";
    markup << "<div class=\"hub-status-row\"><div class=\"hub-status-label\">DELIVERY</div><div class=\"hub-status-value\">"
           << escapeRmlText(summaries.delivery.loaded ? summaries.delivery.primaryText : std::string("UNAVAILABLE"))
           << "</div></div>";
    markup << "<div class=\"hub-status-row\"><div class=\"hub-status-label\">REVIEW</div><div class=\"hub-status-value\">"
           << escapeRmlText(summaries.sizeTrend.loaded ? summaries.sizeTrend.secondaryText : std::string("SEE CLEAN BOARD"))
           << "</div></div>";
    markup << "</div>";
    return markup.str();
}

std::string buildHubActionMarkup()
{
    std::ostringstream markup;
    markup << "<div id=\"hub-action-panel\">";
    markup << "<div class=\"hub-action-kicker\">SELECTED CAPITAL</div>";
    markup << "<div id=\"hub-action-target\">3D Car / LIVE QA SURFACE</div>";
    markup << "<div id=\"hub-action-primary\">DIVE INTO CAPITAL</div>";
    markup << "<div id=\"hub-action-secondary\">SELECT AREA</div>";
    markup << "<div id=\"hub-action-banner\">Evidence only.</div>";
    markup << "</div>";
    return markup.str();
}

std::string fusionLiveBadgeText(const std::string& profileId)
{
    return "LIVE RAMSES " + (profileId.empty() ? std::string("CAR") : profileId) + " / RMLUI COMPOSITE";
}

std::string buildDocument(
    bool fusionEnabled,
    const std::optional<FusionQaPerspective>& perspective,
    const std::vector<FusionCarCandidate>& carCandidates,
    int selectedCarIndex,
    size_t registeredProfileCount,
    const std::string& activeProfileId,
    bool hubPlanetEnabled,
    bool hubNodesEnabled,
    const HubCapitalSummaries& summaries)
{
    std::string document = R"rml(
<rml>
<head>
<style>
body {
  margin: 0px;
  background-color: #0000;
  color: #f8fbff;
  font-family: Inter;
  font-size: 28px;
}
.scene {
  position: absolute;
  left: 0px;
  top: 0px;
  width: 1280px;
  height: 720px;
  opacity: 0;
}
.sky-top {
  position: absolute;
  left: 0px;
  top: 0px;
  width: 1280px;
  height: 720px;
  decorator: linear-gradient(to bottom, #FFB36B 0%, #2FD6E6 43%, #1B2C66 100%);
}
.sky-mid {
  position: absolute;
  left: 0px;
  top: 0px;
  width: 0px;
  height: 0px;
  background-color: #0000;
}
.sky-deep {
  position: absolute;
  left: 0px;
  top: 0px;
  width: 0px;
  height: 0px;
  background-color: #0000;
}
.sun-plate {
  position: absolute;
  left: 360px;
  top: 86px;
  width: 560px;
  height: 560px;
  decorator: radial-gradient(circle, #fc85 0%, #f686 42%, transparent 70%);
}
.frame {
  position: absolute;
  left: 88px;
  top: 72px;
  width: 1104px;
  height: 576px;
  background-color: #0E1530ee;
  border: 2px #25E8C8;
  box-shadow: #2fd8 0px 0px 28px 2px, #fc64 0px 0px 54px 4px;
}
.hairline {
  position: absolute;
  left: 132px;
  top: 594px;
  width: 1016px;
  height: 2px;
  background-color: #FFC94D;
}
#splash-logo {
  position: absolute;
  left: 500px;
  top: 118px;
  width: 280px;
  height: 280px;
}
#splash-subtitle {
  position: absolute;
  left: 0px;
  top: 424px;
  width: 1280px;
  text-align: center;
  font-family: Fredoka;
  font-size: 34px;
  color: #FFFFFF;
  font-effect: glow(2dp 7dp #25E8C8), outline(1dp #0E1530);
}
#debug-icon {
  position: absolute;
  left: 584px;
  top: 484px;
  width: 112px;
  height: 112px;
}
#hero-logo {
  position: absolute;
  left: 525px;
  top: 70px;
  width: 230px;
  height: 230px;
}
#hero-title-bloom {
  position: absolute;
  left: 0px;
  top: 292px;
  width: 1280px;
  text-align: center;
  font-family: Fredoka;
  font-size: 90px;
  color: #25E8C8;
  opacity: 0;
  font-effect: blur(8dp #2FD6E6), glow(3dp 11dp #25E8C8);
}
#hero-title {
  position: absolute;
  left: 0px;
  top: 300px;
  width: 1280px;
  text-align: center;
  font-family: Fredoka;
  font-size: 82px;
  color: #FFFFFF;
  font-effect: glow(2dp 8dp #25E8C8), outline(1dp #0E1530), shadow(0px 3dp #FF6B81);
}
#hero-kicker {
  position: absolute;
  left: 0px;
  top: 416px;
  width: 1280px;
  text-align: center;
  font-size: 30px;
  color: #FFC94D;
  font-effect: glow(2dp 7dp #FF6B81), outline(1dp #0E1530);
}
#hero-zone {
  position: absolute;
  left: 0px;
  top: 486px;
  width: 1280px;
  text-align: center;
  font-size: 24px;
  color: #E9FBFF;
}
#menu-title {
  position: absolute;
  left: 108px;
  top: 96px;
  width: 720px;
  font-family: Fredoka;
  font-size: 64px;
  color: #FFFFFF;
  font-effect: glow(2dp 8dp #25E8C8), outline(1dp #0E1530);
}
#menu-list {
  position: absolute;
  left: 116px;
  top: 212px;
  width: 720px;
  height: 330px;
}
.menu-item {
  position: absolute;
  left: 0px;
  width: 522px;
  height: 35px;
  padding-left: 18px;
  padding-top: 8px;
  font-size: 23px;
  color: #E9FBFF;
  background-color: #0E1530;
  border: 2px #2FD6E6;
  box-shadow: #2fd4 0px 0px 14px 1px;
  opacity: 0;
  transform: translate(0dp, 26dp) scale(0.98);
  transform-origin: 50% 50%;
}
#menu-item-0 {
  top: 0px;
}
#menu-item-1 {
  top: 54px;
  color: #FF6B81;
}
#menu-item-2 {
  top: 108px;
}
#menu-item-3 {
  top: 162px;
}
#menu-item-4 {
  top: 216px;
}
#menu-item-5 {
  top: 270px;
}
#viewer-zone {
  position: absolute;
  left: 718px;
  top: 204px;
  width: 398px;
  height: 252px;
  border: 2px #FFC94D;
  background-color: #0E1530dd;
  __SGFX_FUSION_VIEWER_ZONE_DECORATOR__
  box-shadow: #fc67 0px 0px 32px 3px, #2fd5 0px 0px 18px 1px;
  transform-origin: 50% 50%;
}
#menu-icon {
  position: absolute;
  left: 862px;
  top: 226px;
  width: 110px;
  height: 110px;
  transform-origin: 50% 50%;
}
#viewer-zone-label {
  position: absolute;
  left: 748px;
  top: 356px;
  width: 338px;
  text-align: center;
  font-family: Fredoka;
  font-size: 28px;
  color: #25E8C8;
  font-effect: glow(2dp 8dp #25E8C8), outline(1dp #0E1530);
}
#menu-tag {
  position: absolute;
  left: 726px;
  top: 482px;
  width: 384px;
  font-size: 18px;
  text-align: center;
  color: #FFC94D;
}
#viewer-screen {
  opacity: 0;
  display: none;
}
#viewer-stage {
  position: absolute;
  left: 96px;
  top: 86px;
  width: 1088px;
  height: 548px;
  background-color: #0E1530ef;
  border: 2px #FFC94D;
  box-shadow: #fc8a 0px 0px 48px 5px, #2fda 0px 0px 32px 3px;
  transform-origin: 50% 50%;
}
#viewer-screen-icon {
  position: absolute;
  left: 156px;
  top: 136px;
  width: 132px;
  height: 132px;
}
#viewer-title {
  position: absolute;
  left: 318px;
  top: 130px;
  width: 790px;
  font-family: Fredoka;
  font-size: 62px;
  color: #FFFFFF;
  font-effect: glow(2dp 9dp #25E8C8), outline(1dp #0E1530), shadow(0px 3dp #FF6B81);
}
#viewer-subtitle {
  position: absolute;
  left: 322px;
  top: 230px;
  width: 770px;
  font-size: 25px;
  color: #FFC94D;
}
#viewer-port {
  position: absolute;
  left: 154px;
  top: 292px;
  width: 900px;
  height: 270px;
  background-color: #12224bdd;
  __SGFX_FUSION_VIEWER_PORT_DECORATOR__
  border: 2px #25E8C8;
  box-shadow: #2fd9 0px 0px 24px 2px;
}
#viewer-port-title {
  position: absolute;
  left: 190px;
  top: 354px;
  width: 720px;
  font-family: Fredoka;
  font-size: 35px;
  color: #25E8C8;
  opacity: __SGFX_FUSION_PLACEHOLDER_OPACITY__;
  font-effect: glow(2dp 8dp #25E8C8), outline(1dp #0E1530);
}
#viewer-port-copy {
  position: absolute;
  left: 192px;
  top: 424px;
  width: 700px;
  font-size: 22px;
  color: #E9FBFF;
  opacity: __SGFX_FUSION_PLACEHOLDER_OPACITY__;
}
#viewer-live-badge {
  position: absolute;
  left: 174px;
  top: 306px;
  width: 332px;
  height: 28px;
  padding-left: 14px;
  padding-top: 7px;
  background-color: #0E1530cc;
  border: 1px #25E8C8;
  color: #FFC94D;
  font-size: 19px;
  opacity: __SGFX_FUSION_LIVE_OPACITY__;
  font-effect: glow(1dp 5dp #25E8C8), outline(1dp #0E1530);
}
#viewer-perspective-picker {
  position: absolute;
  left: 792px;
  top: 306px;
  width: 236px;
  min-height: 132px;
  padding-left: 12px;
  padding-top: 10px;
  background-color: #0E1530dd;
  border: 1px #FFC94D;
  box-shadow: #fc66 0px 0px 20px 1px, #2fd4 0px 0px 14px 1px;
  opacity: __SGFX_FUSION_LIVE_OPACITY__;
}
.perspective-kicker {
  display: block;
  width: 210px;
  height: 16px;
  font-size: 13px;
  color: #FFC94D;
  font-effect: glow(1dp 4dp #FF6B81), outline(1dp #0E1530);
}
.perspective-set {
  display: block;
  width: 210px;
  height: 16px;
  margin-top: 3px;
  margin-bottom: 5px;
  font-size: 13px;
  color: #BFE9FF;
}
.perspective-row {
  display: block;
  width: 208px;
  height: 19px;
  margin-top: 4px;
  padding-left: 8px;
  padding-top: 3px;
  font-size: 12px;
  color: #E9FBFF;
  background-color: #12224bcc;
  border: 1px #2FD6E6;
}
.perspective-row-active {
  color: #0E1530;
  background-color: #FFC94D;
  border: 1px #FFFFFF;
}
.perspective-meta {
  margin-top: 6px;
  font-size: 13px;
  color: #BFE9FF;
}
#viewer-car-picker {
  position: absolute;
  left: 174px;
  top: 350px;
  width: 250px;
  min-height: 154px;
  padding-left: 12px;
  padding-top: 10px;
  background-color: #0E1530dd;
  border: 1px #25E8C8;
  box-shadow: #2fd6 0px 0px 20px 1px, #fc44 0px 0px 14px 1px;
  opacity: __SGFX_FUSION_LIVE_OPACITY__;
}
.car-kicker {
  display: block;
  width: 224px;
  height: 16px;
  font-size: 13px;
  color: #25E8C8;
  font-effect: glow(1dp 4dp #25E8C8), outline(1dp #0E1530);
}
.car-meta {
  display: block;
  width: 224px;
  height: 16px;
  margin-top: 3px;
  margin-bottom: 5px;
  font-size: 13px;
  color: #BFE9FF;
}
.car-row {
  display: block;
  width: 222px;
  height: 18px;
  margin-top: 4px;
  padding-left: 8px;
  padding-top: 3px;
  font-size: 13px;
  color: #E9FBFF;
  background-color: #12224bcc;
  border: 1px #2FD6E6;
}
.car-row-active {
  color: #0E1530;
  background-color: #25E8C8;
  border: 1px #FFFFFF;
}
#viewer-return-label {
  position: absolute;
  left: 792px;
  top: 574px;
  width: 320px;
  text-align: right;
  font-size: 20px;
  color: #BFE9FF;
}
#hub-screen {
  opacity: 0;
  display: none;
  z-index: 40;
}
#hub-stage {
  position: absolute;
  left: 82px;
  top: 66px;
  width: 1116px;
  height: 594px;
  opacity: 0;
  background-color: #0E1530e8;
  border: 2px #25E8C8;
  box-shadow: #2fd8 0px 0px 40px 4px, #fc66 0px 0px 54px 4px;
  transform-origin: 50% 50%;
  z-index: 42;
}
#hub-title {
  position: absolute;
  left: 116px;
  top: 92px;
  width: 650px;
  font-family: Fredoka;
  font-size: 58px;
  color: #FFFFFF;
  opacity: 0;
  font-effect: glow(2dp 8dp #25E8C8), outline(1dp #0E1530), shadow(0px 3dp #FF6B81);
  z-index: 45;
}
#hub-subtitle {
  position: absolute;
  left: 120px;
  top: 176px;
  width: 610px;
  font-size: 23px;
  color: #FFC94D;
  opacity: 0;
  z-index: 45;
}
#hub-planet-halo {
  position: absolute;
  left: 526px;
  top: 116px;
  width: 626px;
  height: 492px;
  opacity: 0;
  decorator: radial-gradient(circle, #ffc94d28 0%, #25e8c866 40%, #2fd6e628 58%, transparent 76%);
  z-index: 43;
}
#hub-planet {
  position: absolute;
  left: 584px;
  top: 170px;
  width: 520px;
  height: 390px;
  background-color: #0000;
  __SGFX_HUB_PLANET_DECORATOR__
  border: 0px #0000;
  box-shadow: #fc64 0px 0px 46px 5px, #2fd7 0px 0px 34px 3px;
  opacity: 0;
  transform-origin: 50% 50%;
  overflow: hidden;
  z-index: 46;
}
#hub-planet-placeholder {
  position: absolute;
  left: 650px;
  top: 316px;
  width: 390px;
  text-align: center;
  font-family: Fredoka;
  font-size: 34px;
  color: #25E8C8;
  opacity: 0;
  font-effect: glow(2dp 8dp #25E8C8), outline(1dp #0E1530);
  z-index: 46;
}
.hub-node {
  position: absolute;
  padding-left: 13px;
  padding-top: 6px;
  background-color: #07112fca;
  color: #E9FBFF;
  opacity: 0;
  transform-origin: 50% 50%;
  z-index: 50;
}
.hub-node-live {
  background-color: #192857e8;
  color: #FFFFFF;
}
.hub-node-beacon {
  position: absolute;
  left: -17px;
  top: 17px;
  width: 13px;
  height: 13px;
  background-color: #FFC94D;
  border: 1px #FFFFFF;
  box-shadow: #fc9a 0px 0px 22px 4px;
}
.hub-node-label {
  display: block;
  width: 148px;
  height: 17px;
  font-family: Fredoka;
  font-size: 17px;
  color: #FFFFFF;
  font-effect: glow(1dp 5dp #25E8C8), outline(1dp #0E1530);
}
.hub-node-status {
  display: block;
  width: 148px;
  height: 14px;
  margin-top: 2px;
  font-size: 12px;
  color: #BFE9FF;
}
__SGFX_HUB_NODE_CSS__
#hub-h1-badge {
  position: absolute;
  left: 128px;
  top: 494px;
  width: 310px;
  height: 30px;
  padding-left: 14px;
  padding-top: 8px;
  background-color: #0E1530cc;
  border: 1px #FFC94D;
  color: #E9FBFF;
  font-size: 18px;
  opacity: 0;
  box-shadow: #fc65 0px 0px 18px 1px;
  z-index: 45;
}
#hub-status-panel {
  position: absolute;
  left: 124px;
  top: 226px;
  width: 326px;
  min-height: 226px;
  padding-left: 16px;
  padding-top: 14px;
  background-color: #07112fdd;
  border: 1px #2FD6E6;
  box-shadow: #2fd6 0px 0px 22px 2px, #fc43 0px 0px 18px 1px;
  opacity: 0;
  z-index: 48;
}
.hub-status-kicker {
  display: block;
  width: 292px;
  height: 18px;
  margin-bottom: 9px;
  font-size: 15px;
  color: #FFC94D;
  font-effect: glow(1dp 5dp #FF6B81), outline(1dp #0E1530);
}
.hub-status-row {
  display: block;
  width: 294px;
  height: 33px;
  margin-bottom: 5px;
}
.hub-status-label {
  display: block;
  width: 116px;
  height: 13px;
  font-size: 11px;
  color: #BFE9FF;
}
.hub-status-value {
  display: block;
  width: 294px;
  height: 16px;
  margin-top: 1px;
  font-size: 15px;
  color: #FFFFFF;
  font-effect: outline(1dp #0E1530);
}
#hub-action-panel {
  position: absolute;
  left: 938px;
  top: 560px;
  width: 222px;
  height: 96px;
  padding-left: 12px;
  padding-top: 9px;
  background-color: #07112fe8;
  border: 1px #FFC94D;
  box-shadow: #fc76 0px 0px 22px 2px, #2fd4 0px 0px 18px 1px;
  opacity: 0;
  z-index: 53;
}
.hub-action-kicker {
  display: block;
  width: 198px;
  height: 13px;
  font-size: 11px;
  color: #BFE9FF;
}
#hub-action-target {
  display: block;
  width: 198px;
  height: 16px;
  margin-top: 1px;
  font-size: 14px;
  color: #FFFFFF;
  font-effect: outline(1dp #0E1530);
}
#hub-action-primary {
  display: block;
  width: 192px;
  height: 19px;
  margin-top: 5px;
  padding-left: 7px;
  padding-top: 4px;
  background-color: #FFC94D;
  border: 1px #FFFFFF;
  color: #0E1530;
  font-size: 14px;
  box-shadow: #fc98 0px 0px 18px 2px;
}
#hub-action-secondary {
  display: block;
  width: 192px;
  height: 15px;
  margin-top: 4px;
  padding-left: 7px;
  padding-top: 3px;
  background-color: #0E1530cc;
  border: 1px #2FD6E6;
  color: #E9FBFF;
  font-size: 12px;
}
#hub-action-banner {
  display: block;
  width: 198px;
  height: 14px;
  margin-top: 4px;
  color: #BFE9FF;
  font-size: 10px;
}
#hub-return-label {
  position: absolute;
  left: 128px;
  top: 608px;
  width: 320px;
  text-align: left;
  font-size: 20px;
  color: #BFE9FF;
  opacity: 0;
  z-index: 45;
}
</style>
</head>
<body>
  <div id="splash" class="scene">
    <div class="sky-top"></div>
    <div class="sky-mid"></div>
    <div class="sky-deep"></div>
    <div class="sun-plate"></div>
    <div class="frame"></div>
    <img id="splash-logo" src="brand/logo_sgfx.png"/>
    <div id="splash-subtitle">PROJECT QUALITY HERO</div>
    <img id="debug-icon" src="brand/debug_icon.png"/>
    <div class="hairline"></div>
  </div>
  <div id="hero" class="scene">
    <div class="sky-top"></div>
    <div class="sky-mid"></div>
    <div class="sky-deep"></div>
    <div class="sun-plate"></div>
    <div class="frame"></div>
    <img id="hero-logo" src="brand/framework_sgfx_logo.png"/>
    <div id="hero-title-bloom">SERIENGRAFIK</div>
    <div id="hero-title">SERIENGRAFIK</div>
    <div id="hero-kicker">QA BOARD</div>
    <div id="hero-zone">3D CAR VIEWER ZONE READY</div>
    <div class="hairline"></div>
  </div>
  <div id="menu" class="scene">
    <div class="sky-top"></div>
    <div class="sky-mid"></div>
    <div class="sky-deep"></div>
    <div class="sun-plate"></div>
    <div class="frame"></div>
    <div id="menu-title">QA BOARD</div>
    <div id="menu-list">
      <div id="menu-item-0" class="menu-item">RESUME LAST REVIEW</div>
      <div id="menu-item-1" class="menu-item">START A QA PASS</div>
      <div id="menu-item-2" class="menu-item">MODULES / PIPELINES</div>
      <div id="menu-item-3" class="menu-item">SETTINGS</div>
      <div id="menu-item-4" class="menu-item">ABOUT</div>
      <div id="menu-item-5" class="menu-item">EXIT</div>
    </div>
    <div id="viewer-zone"></div>
    <img id="menu-icon" src="brand/sgfx_icon.png"/>
    <div id="viewer-zone-label">3D CAR<br/>VIEWER CORE</div>
    <div id="menu-tag">faithful Ramses viewer preserved</div>
    <div class="hairline"></div>
  </div>
  <div id="viewer-screen" class="scene">
    <div class="sky-top"></div>
    <div class="sky-mid"></div>
    <div class="sky-deep"></div>
    <div class="sun-plate"></div>
    <div id="viewer-stage"></div>
    <img id="viewer-screen-icon" src="brand/sgfx_icon.png"/>
    <div id="viewer-title">RAMSES 3D CAR VIEWER</div>
    <div id="viewer-subtitle">authored compositor / camera-crane QA perspective path</div>
    <div id="viewer-port"></div>
    <div id="viewer-port-title">VIEWER CORE DESTINATION READY</div>
    <div id="viewer-port-copy">Faithful Ramses render path, authored compositor, and camera-crane QA perspective flow preserved.</div>
    <div id="viewer-live-badge">__SGFX_FUSION_LIVE_BADGE_TEXT__</div>
    __SGFX_FUSION_CAR_PICKER__
    __SGFX_FUSION_PERSPECTIVE_PICKER__
    <div id="viewer-return-label">BACK TO QA BOARD</div>
    <div class="hairline"></div>
  </div>
  <div id="hub-screen" class="scene">
    <div id="hub-stage"></div>
    <div id="hub-title">SERIENGRAFIK WORLD</div>
    <div id="hub-subtitle">own-art scope map / live car capital first</div>
    <div id="hub-planet-halo"></div>
    <div id="hub-planet"></div>
    <div id="hub-planet-placeholder">PLANET PRODUCER<br/>NOT ENABLED</div>
    __SGFX_HUB_STATUS__
    __SGFX_HUB_NODES__
    __SGFX_HUB_ACTIONS__
    <div id="hub-h1-badge">__SGFX_HUB_BADGE_TEXT__</div>
    <div id="hub-return-label">BACK TO QA BOARD</div>
    <div class="hairline"></div>
  </div>
</body>
</rml>
)rml";
    const auto replaceAll = [](std::string& value, const std::string& needle, const std::string& replacement) {
        size_t position = 0u;
        while ((position = value.find(needle, position)) != std::string::npos)
        {
            value.replace(position, needle.size(), replacement);
            position += replacement.size();
        }
    };

    replaceAll(document, "__SGFX_FUSION_VIEWER_ZONE_DECORATOR__", fusionEnabled ? "decorator: sgfx-ramses-car();" : "");
    replaceAll(document, "__SGFX_FUSION_VIEWER_PORT_DECORATOR__", fusionEnabled ? "decorator: sgfx-ramses-car();" : "");
    replaceAll(document, "__SGFX_FUSION_PLACEHOLDER_OPACITY__", fusionEnabled ? "0" : "1");
    replaceAll(document, "__SGFX_FUSION_LIVE_OPACITY__", fusionEnabled ? "1" : "0");
    replaceAll(document, "__SGFX_FUSION_LIVE_BADGE_TEXT__", fusionLiveBadgeText(activeProfileId));
    replaceAll(document, "__SGFX_FUSION_CAR_PICKER__", fusionEnabled ? buildCarPickerMarkup(carCandidates, selectedCarIndex, registeredProfileCount) : "");
    replaceAll(document, "__SGFX_FUSION_PERSPECTIVE_PICKER__", fusionEnabled ? buildPerspectivePickerMarkup(perspective) : "");
    replaceAll(document, "__SGFX_HUB_PLANET_DECORATOR__", hubPlanetEnabled ? "decorator: sgfx-hub-planet();" : "");
    replaceAll(document, "__SGFX_HUB_NODE_CSS__", buildHubNodeCss());
    replaceAll(document, "__SGFX_HUB_STATUS__", buildHubStatusMarkup(fusionEnabled, carCandidates, selectedCarIndex, registeredProfileCount, activeProfileId, summaries));
    replaceAll(document, "__SGFX_HUB_NODES__", buildHubNodeMarkup(summaries));
    replaceAll(document, "__SGFX_HUB_ACTIONS__", buildHubActionMarkup());
    replaceAll(document, "__SGFX_HUB_BADGE_TEXT__", hubNodesEnabled ? "H4: WORLD-MAP PLANET ONLINE" : "H4: RAMSES PLANET POLISHED");
    return document;
}

struct Elements
{
    Rml::Element* splash = nullptr;
    Rml::Element* hero = nullptr;
    Rml::Element* menu = nullptr;
    Rml::Element* splashLogo = nullptr;
    Rml::Element* heroTitleBloom = nullptr;
    Rml::Element* heroTitle = nullptr;
    Rml::Element* menuTitle = nullptr;
    std::array<Rml::Element*, 6> menuItems{};
    Rml::Element* viewerZone = nullptr;
    Rml::Element* menuIcon = nullptr;
    Rml::Element* viewerZoneLabel = nullptr;
    Rml::Element* menuTag = nullptr;
    Rml::Element* viewerScreen = nullptr;
    Rml::Element* viewerStage = nullptr;
    Rml::Element* viewerScreenIcon = nullptr;
    Rml::Element* viewerLiveBadge = nullptr;
    Rml::Element* viewerCarPicker = nullptr;
    Rml::Element* viewerPerspectivePicker = nullptr;
    Rml::Element* hubScreen = nullptr;
    Rml::Element* hubStage = nullptr;
    Rml::Element* hubTitle = nullptr;
    Rml::Element* hubSubtitle = nullptr;
    Rml::Element* hubPlanetHalo = nullptr;
    Rml::Element* hubPlanet = nullptr;
    Rml::Element* hubPlanetPlaceholder = nullptr;
    Rml::Element* hubStatusPanel = nullptr;
    Rml::Element* hubStatusProfile = nullptr;
    Rml::Element* hubStatusFleet = nullptr;
    std::array<Rml::Element*, kHubNodeCount> hubNodes{};
    Rml::Element* hubActionPanel = nullptr;
    Rml::Element* hubActionTarget = nullptr;
    Rml::Element* hubActionPrimary = nullptr;
    Rml::Element* hubActionSecondary = nullptr;
    Rml::Element* hubActionBanner = nullptr;
    Rml::Element* hubBadge = nullptr;
    Rml::Element* hubReturnLabel = nullptr;
};

Elements getElements(Rml::ElementDocument& document)
{
    Elements elements;
    elements.splash = document.GetElementById("splash");
    elements.hero = document.GetElementById("hero");
    elements.menu = document.GetElementById("menu");
    elements.splashLogo = document.GetElementById("splash-logo");
    elements.heroTitleBloom = document.GetElementById("hero-title-bloom");
    elements.heroTitle = document.GetElementById("hero-title");
    elements.menuTitle = document.GetElementById("menu-title");
    for (int i = 0; i < static_cast<int>(elements.menuItems.size()); ++i)
        elements.menuItems[static_cast<size_t>(i)] = document.GetElementById("menu-item-" + std::to_string(i));
    elements.viewerZone = document.GetElementById("viewer-zone");
    elements.menuIcon = document.GetElementById("menu-icon");
    elements.viewerZoneLabel = document.GetElementById("viewer-zone-label");
    elements.menuTag = document.GetElementById("menu-tag");
    elements.viewerScreen = document.GetElementById("viewer-screen");
    elements.viewerStage = document.GetElementById("viewer-stage");
    elements.viewerScreenIcon = document.GetElementById("viewer-screen-icon");
    elements.viewerLiveBadge = document.GetElementById("viewer-live-badge");
    elements.viewerCarPicker = document.GetElementById("viewer-car-picker");
    elements.viewerPerspectivePicker = document.GetElementById("viewer-perspective-picker");
    elements.hubScreen = document.GetElementById("hub-screen");
    elements.hubStage = document.GetElementById("hub-stage");
    elements.hubTitle = document.GetElementById("hub-title");
    elements.hubSubtitle = document.GetElementById("hub-subtitle");
    elements.hubPlanetHalo = document.GetElementById("hub-planet-halo");
    elements.hubPlanet = document.GetElementById("hub-planet");
    elements.hubPlanetPlaceholder = document.GetElementById("hub-planet-placeholder");
    elements.hubStatusPanel = document.GetElementById("hub-status-panel");
    elements.hubStatusProfile = document.GetElementById("hub-status-profile");
    elements.hubStatusFleet = document.GetElementById("hub-status-fleet");
    for (int i = 0; i < kHubNodeCount; ++i)
        elements.hubNodes[static_cast<size_t>(i)] = document.GetElementById(kHubNodes[static_cast<size_t>(i)].elementId);
    elements.hubActionPanel = document.GetElementById("hub-action-panel");
    elements.hubActionTarget = document.GetElementById("hub-action-target");
    elements.hubActionPrimary = document.GetElementById("hub-action-primary");
    elements.hubActionSecondary = document.GetElementById("hub-action-secondary");
    elements.hubActionBanner = document.GetElementById("hub-action-banner");
    elements.hubBadge = document.GetElementById("hub-h1-badge");
    elements.hubReturnLabel = document.GetElementById("hub-return-label");
    require(
        elements.splash && elements.hero && elements.menu && elements.splashLogo && elements.heroTitleBloom && elements.heroTitle &&
            elements.menuTitle && elements.viewerZone && elements.menuIcon && elements.viewerZoneLabel && elements.menuTag &&
            elements.viewerScreen && elements.viewerStage && elements.viewerScreenIcon && elements.viewerLiveBadge &&
            elements.hubScreen && elements.hubStage && elements.hubTitle && elements.hubSubtitle && elements.hubPlanetHalo &&
            elements.hubPlanet && elements.hubPlanetPlaceholder && elements.hubStatusPanel && elements.hubStatusProfile &&
            elements.hubStatusFleet && elements.hubActionPanel && elements.hubActionTarget && elements.hubActionPrimary &&
            elements.hubActionSecondary && elements.hubActionBanner && elements.hubBadge && elements.hubReturnLabel &&
            std::all_of(elements.hubNodes.begin(), elements.hubNodes.end(), [](const Rml::Element* item) { return item != nullptr; }) &&
            std::all_of(elements.menuItems.begin(), elements.menuItems.end(), [](const Rml::Element* item) { return item != nullptr; }),
        "Missing cinematic shell RmlUi element");
    return elements;
}

void setProperty(Rml::Element& element, const std::string& name, const std::string& value)
{
    if (!element.SetProperty(name, value))
        throw std::runtime_error("RmlUi failed to set property " + name + "=" + value);
}

struct CarPickerController
{
    int selected = -1;
    int active = -1;
    int hovered = -1;
    size_t registeredProfileCount = 0u;
    double pulseStartedAt = -100.0;
    bool demoPickFired = false;
};

enum class ShellState
{
    Splash,
    Hero,
    Menu,
    FlyToViewer,
    ViewerZone,
    FlyBackToMenu,
    FlyToHub,
    Hub,
    FlyHubToViewer,
    FlyViewerBackToHub,
    FlyBackToHubMenu
};

const char* stateName(ShellState state)
{
    switch (state)
    {
    case ShellState::Splash: return "splash";
    case ShellState::Hero: return "hero-title";
    case ShellState::Menu: return "menu";
    case ShellState::FlyToViewer: return "fly-to-viewer";
    case ShellState::ViewerZone: return "viewer-zone";
    case ShellState::FlyBackToMenu: return "fly-back-to-menu";
    case ShellState::FlyToHub: return "fly-to-hub";
    case ShellState::Hub: return "hub";
    case ShellState::FlyHubToViewer: return "fly-hub-to-viewer";
    case ShellState::FlyViewerBackToHub: return "fly-viewer-back-to-hub";
    case ShellState::FlyBackToHubMenu: return "fly-back-to-hub-menu";
    }
    return "unknown";
}

ShellState applyIntroFrame(Elements& elements, double elapsed, bool skipped)
{
    constexpr double splashIn = 0.3;
    constexpr double splashHold = 1.2;
    constexpr double splashOut = 0.3;
    constexpr double titleIn = 0.5;
    constexpr double titleHold = 1.6;
    constexpr double titleOut = 0.4;
    constexpr double splashTotal = splashIn + splashHold + splashOut;
    constexpr double titleTotal = titleIn + titleHold + titleOut;

    double splashOpacity = 0.0;
    double heroOpacity = 0.0;
    double menuOpacity = 0.0;
    double splashLogoSize = 280.0;
    double heroFontSize = 82.0;
    ShellState state = ShellState::Splash;

    if (skipped || elapsed >= splashTotal + titleTotal)
    {
        menuOpacity = 1.0;
        state = ShellState::Menu;
    }
    else if (elapsed < splashTotal)
    {
        state = ShellState::Splash;
        if (elapsed < splashIn)
        {
            const double p = easeOutCubic(elapsed / splashIn);
            splashOpacity = p;
            splashLogoSize = 248.0 + 32.0 * p;
        }
        else if (elapsed < splashIn + splashHold)
        {
            splashOpacity = 1.0;
            splashLogoSize = 280.0;
        }
        else
        {
            const double p = easeOutCubic((elapsed - splashIn - splashHold) / splashOut);
            splashOpacity = 1.0 - p;
            splashLogoSize = 280.0 + 18.0 * p;
        }
    }
    else
    {
        state = ShellState::Hero;
        const double t = elapsed - splashTotal;
        if (t < titleIn)
        {
            const double p = easeOutCubic(t / titleIn);
            heroOpacity = p;
            heroFontSize = 70.0 + 12.0 * p;
        }
        else if (t < titleIn + titleHold)
        {
            heroOpacity = 1.0;
            heroFontSize = 82.0;
        }
        else
        {
            const double p = easeOutCubic((t - titleIn - titleHold) / titleOut);
            heroOpacity = 1.0 - p;
            heroFontSize = 82.0 + 4.0 * p;
        }
    }

    setProperty(*elements.splash, "opacity", number(splashOpacity));
    setProperty(*elements.hero, "opacity", number(heroOpacity));
    setProperty(*elements.menu, "opacity", number(menuOpacity));
    setProperty(*elements.splashLogo, "width", px(splashLogoSize));
    setProperty(*elements.splashLogo, "height", px(splashLogoSize));
    setProperty(*elements.splashLogo, "left", px((1280.0 - splashLogoSize) * 0.5));
    setProperty(*elements.heroTitleBloom, "opacity", "0");
    setProperty(*elements.heroTitleBloom, "font-size", px(heroFontSize + 8.0));
    setProperty(*elements.heroTitle, "font-size", px(heroFontSize));
    return state;
}

constexpr int kMenuItemCount = 6;
constexpr double kMenuListLeft = 116.0;
constexpr double kMenuListTop = 212.0;
constexpr double kMenuItemWidth = 540.0;
constexpr double kMenuItemHeight = 45.0;
constexpr double kMenuItemStep = 54.0;
constexpr double kMenuItemRevealSeconds = 0.25;
constexpr double kMenuItemStaggerSeconds = 0.07;
constexpr double kMenuPulseSeconds = 0.18;
constexpr double kViewerFlyInSeconds = 0.70;
constexpr double kViewerFlyBackSeconds = 0.50;
constexpr double kHubStatusRevealDelaySeconds = 0.15;
constexpr double kHubStatusRevealSeconds = 0.65;
constexpr double kHubNodeRevealDelaySeconds = 0.55;
constexpr double kHubNodeRevealSeconds = 0.55;
constexpr double kHubNodeStaggerSeconds = 0.18;
constexpr double kHubActionRevealDelaySeconds = 1.65;
constexpr double kHubActionRevealSeconds = 0.65;
constexpr double kHubRevealCompleteSeconds = kHubActionRevealDelaySeconds + kHubActionRevealSeconds;
constexpr double kPi = 3.14159265358979323846;
constexpr double kCarPickerLeft = 174.0;
constexpr double kCarPickerTop = 350.0;
constexpr double kCarPickerWidth = 250.0;
constexpr double kCarPickerRowTop = 404.0;
constexpr double kCarPickerRowHeight = 21.0;
constexpr double kCarPickerRowStep = 25.0;
constexpr double kHubActionLeft = 938.0;
constexpr double kHubActionTop = 560.0;
constexpr double kHubActionWidth = 234.0;
constexpr double kHubActionHeight = 108.0;

constexpr std::array<const char*, kMenuItemCount> kMenuItemLabels = {
    "Resume last review",
    "Start a QA pass",
    "Modules / Pipelines",
    "Settings",
    "About",
    "Exit",
};

struct MenuController
{
    int selected = 0;
    int hovered = -1;
    int pressed = -1;
    double enteredAt = -1.0;
    double pulseStartedAt = -100.0;
    bool demoPulseFired = false;
    bool activationLogged = false;
};

struct ViewerTransition
{
    double startedAt = -100.0;
    double enteredAt = -100.0;
    bool demoEnterFired = false;
    bool demoHubNodeEnterFired = false;
    bool demoViewerBackFired = false;
    bool enteredFromHub = false;
    bool h3ViewerReached = false;
    bool h3ReturnedToHub = false;
    bool enteredLogged = false;
    bool returnedLogged = false;
    bool hubRevealStartedLogged = false;
    bool hubRevealCompleteLogged = false;
};

struct HubController
{
    int selected = kHubNodeDeliveryIndex;
    int hovered = -1;
    double readyAt = -1.0;
    double pulseStartedAt = -100.0;
    bool readyLogged = false;
};

double easeOutBack(double value)
{
    value = clamp01(value);
    constexpr double c1 = 1.70158;
    constexpr double c3 = c1 + 1.0;
    const double shifted = value - 1.0;
    return 1.0 + c3 * shifted * shifted * shifted + c1 * shifted * shifted;
}

double easeInCubic(double value)
{
    value = clamp01(value);
    return value * value * value;
}

int clampMenuIndex(int index)
{
    return std::max(0, std::min(kMenuItemCount - 1, index));
}

int clampCarIndex(const std::vector<FusionCarCandidate>& candidates, int index)
{
    if (candidates.empty())
        return -1;
    const int count = static_cast<int>(candidates.size());
    return std::max(0, std::min(count - 1, index));
}

bool isViewerMenuIndex(int index)
{
    return index == 1;
}

bool isHubMenuIndex(int index)
{
    return index == 2;
}

int hitTestMenuItem(double x, double y)
{
    const double localX = x - kMenuListLeft;
    const double localY = y - kMenuListTop;
    if (localX < 0.0 || localX > kMenuItemWidth || localY < 0.0)
        return -1;

    for (int i = 0; i < kMenuItemCount; ++i)
    {
        const double itemTop = static_cast<double>(i) * kMenuItemStep;
        if (localY >= itemTop && localY <= itemTop + kMenuItemHeight)
            return i;
    }
    return -1;
}

bool hitTestViewerZone(double x, double y)
{
    return x >= 718.0 && x <= 1116.0 && y >= 204.0 && y <= 456.0;
}

int hitTestCarPickerRow(double x, double y, const std::vector<FusionCarCandidate>& candidates)
{
    if (candidates.empty())
        return -1;
    if (x < kCarPickerLeft || x > kCarPickerLeft + kCarPickerWidth || y < kCarPickerRowTop)
        return -1;
    const int index = static_cast<int>((y - kCarPickerRowTop) / kCarPickerRowStep);
    if (index < 0 || index >= static_cast<int>(candidates.size()))
        return -1;
    const double rowTop = kCarPickerRowTop + static_cast<double>(index) * kCarPickerRowStep;
    return y <= rowTop + kCarPickerRowHeight ? index : -1;
}

int hitTestHubNode(double x, double y)
{
    for (int i = kHubNodeCount - 1; i >= 0; --i)
    {
        const HubNodeDefinition& node = kHubNodes[static_cast<size_t>(i)];
        if (x >= node.x - 22.0 && x <= node.x + node.width + 32.0 &&
            y >= node.y - 6.0 && y <= node.y + node.height + 16.0)
        {
            return i;
        }
    }
    return -1;
}

bool hitTestHubAction(double x, double y)
{
    return x >= kHubActionLeft && x <= kHubActionLeft + kHubActionWidth &&
        y >= kHubActionTop && y <= kHubActionTop + kHubActionHeight;
}

void startMenuPulse(MenuController& menu, double elapsed)
{
    menu.pulseStartedAt = elapsed;
    menu.pressed = menu.selected;
    menu.activationLogged = false;
}

void moveMenuSelection(MenuController& menu, int delta, double elapsed)
{
    const int next = (menu.selected + delta + kMenuItemCount) % kMenuItemCount;
    if (next != menu.selected)
    {
        menu.selected = next;
        startMenuPulse(menu, elapsed);
    }
}

void refreshCarPickerUi(Elements& elements,
                        const std::vector<FusionCarCandidate>& candidates,
                        const CarPickerController& carPicker,
                        const FusionCarTexture* fusionCar)
{
    if (elements.viewerLiveBadge && fusionCar)
        elements.viewerLiveBadge->SetInnerRML(escapeRmlText(fusionLiveBadgeText(fusionCar->profileId())));
    if (elements.viewerCarPicker)
        elements.viewerCarPicker->SetInnerRML(buildCarPickerInner(candidates, carPicker.selected, carPicker.registeredProfileCount));
    if (elements.viewerPerspectivePicker)
        elements.viewerPerspectivePicker->SetInnerRML(buildPerspectivePickerInner(fusionCar ? fusionCar->qaPerspective() : std::nullopt));
    if (elements.hubStatusProfile)
    {
        const std::string profile = resolveHubActiveProfileText(
            fusionCar && fusionCar->ready(),
            candidates,
            carPicker.active,
            fusionCar ? fusionCar->profileId() : std::string{});
        elements.hubStatusProfile->SetInnerRML(escapeRmlText(profile));
    }
    if (elements.hubStatusFleet)
        elements.hubStatusFleet->SetInnerRML(escapeRmlText(buildRegisteredCarCountText(candidates.size(), carPicker.registeredProfileCount)));
}

void startCarPickerPulse(CarPickerController& carPicker, int index, double elapsed)
{
    carPicker.selected = index;
    carPicker.pulseStartedAt = elapsed;
}

void moveCarSelection(CarPickerController& carPicker, const std::vector<FusionCarCandidate>& candidates, int delta, double elapsed)
{
    if (candidates.empty())
        return;
    const int count = static_cast<int>(candidates.size());
    const int base = carPicker.selected >= 0 ? carPicker.selected : 0;
    const int next = (base + delta + count) % count;
    if (next != carPicker.selected)
        startCarPickerPulse(carPicker, next, elapsed);
}

bool activateCarCandidate(Options& activeOptions,
                          Elements& elements,
                          SgfxGl3RenderInterface& renderInterface,
                          FusionCarTexture* fusionCar,
                          const std::vector<FusionCarCandidate>& candidates,
                          CarPickerController& carPicker,
                          int index,
                          double elapsed)
{
    if (!fusionCar || candidates.empty())
        return false;

    const int selected = clampCarIndex(candidates, index);
    if (selected < 0)
        return false;

    startCarPickerPulse(carPicker, selected, elapsed);
    if (selected == carPicker.active && fusionCar->ready())
    {
        refreshCarPickerUi(elements, candidates, carPicker, fusionCar);
        return false;
    }

    const FusionCarCandidate& candidate = candidates[static_cast<size_t>(selected)];
    std::cout << "SGFX cinematic shell car picker activated: " << candidate.profileId
              << " -> " << candidate.sceneFile.string() << "\n";
    const Options selectedOptions = optionsForCarCandidate(activeOptions, candidate, false);
    fusionCar->reload(selectedOptions);
    activeOptions = selectedOptions;
    renderInterface.registerBorrowedTexture(fusionCar->textureHandle());
    carPicker.active = selected;
    carPicker.selected = selected;
    refreshCarPickerUi(elements, candidates, carPicker, fusionCar);
    std::cout << "SGFX cinematic shell car picker loaded: " << fusionCar->profileId()
              << " P4 producer frames/readPixels/uploads "
              << fusionCar->performanceStats().producerFrames << "/"
              << fusionCar->performanceStats().readbackRequests << "/"
              << fusionCar->performanceStats().textureUploads << "\n";
    return true;
}

void startHubNodePulse(HubController& hub, int index, double elapsed)
{
    hub.selected = std::max(0, std::min(kHubNodeCount - 1, index));
    hub.pulseStartedAt = elapsed;
}

void moveHubNodeSelection(HubController& hub, int delta, double elapsed)
{
    const int next = (hub.selected + delta + kHubNodeCount) % kHubNodeCount;
    if (next != hub.selected)
        startHubNodePulse(hub, next, elapsed);
}

std::string hubActionTargetText(const HubNodeDefinition& node, int index, const HubCapitalSummaries& summaries)
{
    const HubCapitalSummary* capital = hubCapitalForIndex(index, summaries);
    if (capital)
        return std::string(node.label) + " / " + (capital->loaded ? capital->statusText : "UNAVAILABLE");
    return std::string(node.label) + " / " + node.status;
}

std::string hubActionPrimaryText(const HubNodeDefinition& node, int index, const HubCapitalSummaries& summaries)
{
    if (node.live)
        return "DIVE INTO CAPITAL";
    const HubCapitalSummary* capital = hubCapitalForIndex(index, summaries);
    if (capital)
        return capital->primaryText;
    return "AREA COMING";
}

std::string hubActionSecondaryText(const HubNodeDefinition& node, int index, const HubCapitalSummaries& summaries)
{
    if (node.live)
        return "SELECT AREA";
    const HubCapitalSummary* capital = hubCapitalForIndex(index, summaries);
    if (capital)
        return capital->secondaryText;
    return "SELECT WIRED CAPITAL";
}

std::string hubActionBannerText(const HubNodeDefinition& node, int index, const HubCapitalSummaries& summaries)
{
    if (node.live)
        return "Live Ramses viewer path.";
    const HubCapitalSummary* capital = hubCapitalForIndex(index, summaries);
    if (capital)
        return capital->bannerText;
    return "Not wired yet - honest placeholder.";
}

void logHubNodeActivation(int index, const HubCapitalSummaries& summaries)
{
    const HubNodeDefinition& node = kHubNodes[static_cast<size_t>(std::max(0, std::min(kHubNodeCount - 1, index)))];
    const HubCapitalSummary* capital = hubCapitalForIndex(index, summaries);
    std::cout << "SGFX cinematic shell H2 hub node activated: " << node.label << " / " << hubNodeStatusText(node, index, summaries);
    if (node.live)
    {
        std::cout << " (H3 target: live 3D Car viewer)";
    }
    else if (capital && capital->loaded)
    {
        std::cout << " (" << capital->label << ": " << capital->primaryText << "; " << capital->secondaryText << ")";
    }
    else if (capital)
    {
        std::cout << " (" << capital->label << " unavailable: " << (capital->error.empty() ? "no data" : capital->error) << ")";
    }
    else
    {
        std::cout << " (honest coming placeholder)";
    }
    std::cout << "\n";
}

void startHubNodeFlyIn(ShellState& state, ViewerTransition& transition, int index, double elapsed, bool fusionReady)
{
    const HubNodeDefinition& node = kHubNodes[static_cast<size_t>(std::max(0, std::min(kHubNodeCount - 1, index)))];
    state = ShellState::FlyHubToViewer;
    transition.startedAt = elapsed;
    transition.enteredAt = -100.0;
    transition.enteredFromHub = true;
    transition.enteredLogged = false;
    transition.returnedLogged = false;
    transition.h3ViewerReached = false;
    transition.h3ReturnedToHub = false;
    std::cout << "SGFX cinematic shell H3 node fly-into started: " << node.label
              << " -> " << (fusionReady ? "live Ramses car viewer" : "3D Car viewer placeholder") << "\n";
}

void activateHubNode(
    ShellState& state,
    ViewerTransition& transition,
    HubController& hub,
    int index,
    double elapsed,
    bool fusionReady,
    const HubCapitalSummaries& summaries)
{
    startHubNodePulse(hub, index, elapsed);
    logHubNodeActivation(index, summaries);
    const HubNodeDefinition& node = kHubNodes[static_cast<size_t>(hub.selected)];
    if (node.live)
        startHubNodeFlyIn(state, transition, hub.selected, elapsed, fusionReady);
    else if (isHubDataNode(hub.selected))
        std::cout << "SGFX cinematic shell data capital held in hub with real desktop-state summary: " << node.label << "\n";
    else
        std::cout << "SGFX cinematic shell H3 coming node held in hub: " << node.label << "\n";
}

void startViewerFlyIn(ShellState& state, ViewerTransition& transition, double elapsed)
{
    state = ShellState::FlyToViewer;
    transition.startedAt = elapsed;
    transition.enteredAt = -100.0;
    transition.enteredFromHub = false;
    transition.enteredLogged = false;
    transition.returnedLogged = false;
    transition.hubRevealStartedLogged = false;
    transition.hubRevealCompleteLogged = false;
    std::cout << "SGFX cinematic shell fly-into-zone started: 3D Car viewer core\n";
}

void startViewerFlyBack(ShellState& state, ViewerTransition& transition, double elapsed)
{
    state = transition.enteredFromHub ? ShellState::FlyViewerBackToHub : ShellState::FlyBackToMenu;
    transition.startedAt = elapsed;
    transition.returnedLogged = false;
    std::cout << "SGFX cinematic shell fly-back started: "
              << (transition.enteredFromHub ? "Seriengrafik planet hub" : "QA Board menu") << "\n";
}

void startHubFlyIn(ShellState& state, ViewerTransition& transition, HubController& hub, double elapsed)
{
    state = ShellState::FlyToHub;
    transition.startedAt = elapsed;
    transition.enteredAt = -100.0;
    transition.enteredFromHub = false;
    transition.enteredLogged = false;
    transition.returnedLogged = false;
    transition.h3ReturnedToHub = false;
    transition.hubRevealStartedLogged = false;
    transition.hubRevealCompleteLogged = false;
    hub.readyAt = -1.0;
    hub.readyLogged = false;
    std::cout << "SGFX cinematic shell fly-into-hub started: Seriengrafik world planet\n";
}

void startHubFlyBack(ShellState& state, ViewerTransition& transition, double elapsed)
{
    state = ShellState::FlyBackToHubMenu;
    transition.startedAt = elapsed;
    transition.returnedLogged = false;
    std::cout << "SGFX cinematic shell hub fly-back started: QA Board menu\n";
}

void applyMenuFrame(Elements& elements, MenuController& menu, ShellState state, double elapsed)
{
    if (state != ShellState::Menu)
        return;

    if (menu.enteredAt < 0.0)
    {
        menu.enteredAt = elapsed;
        std::cout << "SGFX cinematic shell menu animation: staggered reveal + focus spring + click pulse\n";
    }

    const double menuTime = std::max(0.0, elapsed - menu.enteredAt);
    const int focusIndex = menu.hovered >= 0 ? menu.hovered : menu.selected;
    const double activePulseT = clamp01((elapsed - menu.pulseStartedAt) / kMenuPulseSeconds);
    const double pulse = (elapsed >= menu.pulseStartedAt && activePulseT < 1.0) ? std::sin(activePulseT * kPi) : 0.0;

    const double titleReveal = easeOutBack(menuTime / 0.30);
    setProperty(*elements.menuTitle, "opacity", number(clamp01(menuTime / 0.18)));
    setProperty(*elements.menuTitle, "transform", "translate(" + dp(-20.0 * (1.0 - titleReveal)) + ", " + dp(0.0) + ") scale(" + number(0.96 + 0.04 * titleReveal) + ")");

    for (int i = 0; i < kMenuItemCount; ++i)
    {
        Rml::Element& item = *elements.menuItems[static_cast<size_t>(i)];
        const double revealT = clamp01((menuTime - static_cast<double>(i) * kMenuItemStaggerSeconds) / kMenuItemRevealSeconds);
        const double reveal = easeOutBack(revealT);
        const bool focused = i == focusIndex;
        const bool pulsing = i == menu.pressed;
        const double itemPulse = pulsing ? pulse : 0.0;
        const double focusScale = focused ? 1.035 : 1.0;
        const double scale = (0.96 + 0.04 * reveal) * (focusScale + itemPulse * 0.055);
        const double x = (focused ? 18.0 : 0.0) + itemPulse * 8.0;
        const double y = 26.0 * (1.0 - reveal) - itemPulse * 2.0;

        setProperty(item, "opacity", number(revealT));
        setProperty(item, "transform", "translate(" + dp(x) + ", " + dp(y) + ") scale(" + number(scale) + ")");

        if (focused)
        {
            setProperty(item, "color", "#0E1530");
            setProperty(item, "background-color", i == 1 ? "#FF6B81" : "#FFC94D");
            setProperty(item, "border", "2px #FFFFFF");
            setProperty(item, "box-shadow", "#fc8a 0px 0px 24px 2px, #2fda 0px 0px 18px 1px");
        }
        else
        {
            setProperty(item, "color", i == 1 ? "#FF6B81" : "#E9FBFF");
            setProperty(item, "background-color", "#0E1530");
            setProperty(item, "border", "2px #2FD6E6");
            setProperty(item, "box-shadow", "#2fd4 0px 0px 14px 1px");
        }
    }

    const bool viewerFocused = focusIndex == 1 || focusIndex == 2;
    const double viewerPulse = viewerFocused ? pulse : 0.0;
    const double viewerScale = viewerFocused ? 1.025 + viewerPulse * 0.035 : 1.0;
    setProperty(*elements.viewerZone, "transform", "scale(" + number(viewerScale) + ")");
    setProperty(*elements.menuIcon, "transform", "scale(" + number(viewerFocused ? 1.05 + viewerPulse * 0.05 : 1.0) + ")");
    setProperty(*elements.viewerZone, "box-shadow", viewerFocused ? "#fc8a 0px 0px 38px 4px, #2fda 0px 0px 24px 2px" : "#fc67 0px 0px 32px 3px, #2fd5 0px 0px 18px 1px");

    if (pulse <= 0.001 && elapsed - menu.pulseStartedAt > kMenuPulseSeconds)
        menu.pressed = -1;
}

void setHubContentOpacity(Elements& elements, const std::string& opacity, bool hubPlanetEnabled, bool hubNodesEnabled);

void applyViewerTransitionFrame(
    Elements& elements,
    ShellState& state,
    ViewerTransition& transition,
    double elapsed,
    bool fusionReady,
    bool hubPlanetEnabled,
    bool hubNodesEnabled)
{
    if (state == ShellState::FlyHubToViewer)
    {
        const double t = clamp01((elapsed - transition.startedAt) / kViewerFlyInSeconds);
        const double push = easeInCubic(t);
        const double resolve = easeOutCubic(t);
        const std::string viewerOpacity = number(resolve);
        const std::string hubOpacity = number(1.0 - resolve);

        setProperty(*elements.menu, "display", "none");
        setProperty(*elements.menu, "opacity", "0");
        setProperty(*elements.hubScreen, "display", "block");
        setProperty(*elements.hubScreen, "opacity", hubOpacity);
        setHubContentOpacity(elements, hubOpacity, hubPlanetEnabled, hubNodesEnabled);
        setProperty(*elements.hubStage, "transform", "scale(" + number(1.0 + push * 0.08) + ")");
        setProperty(*elements.hubPlanet, "transform", "translate(" + dp(-42.0 * push) + ", " + dp(-18.0 * push) + ") scale(" + number(1.0 + push * 0.16) + ")");
        setProperty(*elements.viewerScreen, "display", "block");
        setProperty(*elements.viewerScreen, "opacity", viewerOpacity);
        setProperty(*elements.viewerStage, "transform", "scale(" + number(0.92 + 0.08 * resolve) + ")");
        setProperty(*elements.viewerScreenIcon, "transform", "scale(" + number(0.88 + 0.12 * resolve) + ")");

        if (t >= 1.0)
        {
            state = ShellState::ViewerZone;
            transition.enteredAt = elapsed;
            transition.h3ViewerReached = true;
            setProperty(*elements.hubScreen, "display", "none");
            setProperty(*elements.hubScreen, "opacity", "0");
            setHubContentOpacity(elements, "0", hubPlanetEnabled, hubNodesEnabled);
            setProperty(*elements.viewerScreen, "display", "block");
            setProperty(*elements.viewerScreen, "opacity", "1");
            if (!transition.enteredLogged)
            {
                std::cout << "SGFX cinematic shell H3 node destination ready: "
                          << (fusionReady ? "live Ramses 3D Car viewer" : "3D Car viewer placeholder") << "\n";
                transition.enteredLogged = true;
            }
        }
        return;
    }

    if (state == ShellState::FlyToViewer)
    {
        const double t = clamp01((elapsed - transition.startedAt) / kViewerFlyInSeconds);
        const double push = easeInCubic(t);
        const double resolve = easeOutCubic(t);
        const double cardScale = 1.0 + push * 2.05;
        const double cardX = -320.0 * push;
        const double cardY = -118.0 * push;
        const double iconScale = 1.05 + push * 1.30;
        const double iconX = -224.0 * push;
        const double iconY = -82.0 * push;

        setProperty(*elements.viewerScreen, "display", "block");
        setProperty(*elements.menu, "opacity", number(1.0 - clamp01(t * 1.15)));
        setProperty(*elements.viewerScreen, "opacity", number(resolve));
        setProperty(*elements.viewerZone, "transform", "translate(" + dp(cardX) + ", " + dp(cardY) + ") scale(" + number(cardScale) + ")");
        setProperty(*elements.menuIcon, "transform", "translate(" + dp(iconX) + ", " + dp(iconY) + ") scale(" + number(iconScale) + ")");
        setProperty(*elements.viewerZoneLabel, "opacity", number(1.0 - t));
        setProperty(*elements.menuTag, "opacity", number(1.0 - t));
        setProperty(*elements.viewerStage, "transform", "scale(" + number(0.96 + 0.04 * resolve) + ")");
        setProperty(*elements.viewerScreenIcon, "transform", "scale(" + number(0.90 + 0.10 * resolve) + ")");

        if (t >= 1.0)
        {
            state = ShellState::ViewerZone;
            transition.enteredAt = elapsed;
            setProperty(*elements.menu, "opacity", "0");
            setProperty(*elements.viewerScreen, "display", "block");
            setProperty(*elements.viewerScreen, "opacity", "1");
            if (!transition.enteredLogged)
            {
                std::cout << "SGFX cinematic shell viewer zone ready: sgfx_cine_ramses_real_scene destination\n";
                transition.enteredLogged = true;
            }
        }
        return;
    }

    if (state == ShellState::ViewerZone)
    {
        setProperty(*elements.menu, "opacity", "0");
        setProperty(*elements.hubScreen, "display", "none");
        setProperty(*elements.hubScreen, "opacity", "0");
        setHubContentOpacity(elements, "0", hubPlanetEnabled, hubNodesEnabled);
        setProperty(*elements.viewerScreen, "display", "block");
        setProperty(*elements.viewerScreen, "opacity", "1");
        return;
    }

    if (state == ShellState::FlyBackToMenu)
    {
        const double t = clamp01((elapsed - transition.startedAt) / kViewerFlyBackSeconds);
        const double pull = easeOutCubic(t);
        const double reverse = 1.0 - pull;
        const double cardScale = 1.0 + reverse * 2.05;
        const double cardX = -320.0 * reverse;
        const double cardY = -118.0 * reverse;
        const double iconScale = 1.05 + reverse * 1.30;
        const double iconX = -224.0 * reverse;
        const double iconY = -82.0 * reverse;

        setProperty(*elements.viewerScreen, "display", "block");
        setProperty(*elements.menu, "opacity", number(pull));
        setProperty(*elements.viewerScreen, "opacity", number(1.0 - pull));
        setProperty(*elements.viewerZone, "transform", "translate(" + dp(cardX) + ", " + dp(cardY) + ") scale(" + number(cardScale) + ")");
        setProperty(*elements.menuIcon, "transform", "translate(" + dp(iconX) + ", " + dp(iconY) + ") scale(" + number(iconScale) + ")");
        setProperty(*elements.viewerZoneLabel, "opacity", number(pull));
        setProperty(*elements.menuTag, "opacity", number(pull));
        setProperty(*elements.viewerStage, "transform", "scale(" + number(0.96 + 0.04 * reverse) + ")");
        setProperty(*elements.viewerScreenIcon, "transform", "scale(" + number(0.90 + 0.10 * reverse) + ")");

        if (t >= 1.0)
        {
            state = ShellState::Menu;
            setProperty(*elements.viewerScreen, "display", "none");
            setProperty(*elements.viewerScreen, "opacity", "0");
            setProperty(*elements.menu, "opacity", "1");
            setProperty(*elements.viewerZone, "transform", "scale(1.0)");
            setProperty(*elements.menuIcon, "transform", "scale(1.0)");
            setProperty(*elements.viewerZoneLabel, "opacity", "1");
            setProperty(*elements.menuTag, "opacity", "1");
            if (!transition.returnedLogged)
            {
                std::cout << "SGFX cinematic shell fly-back complete: QA Board menu\n";
                transition.returnedLogged = true;
            }
        }
        return;
    }

    if (state == ShellState::FlyViewerBackToHub)
    {
        const double t = clamp01((elapsed - transition.startedAt) / kViewerFlyBackSeconds);
        const double pull = easeOutCubic(t);
        const double reverse = 1.0 - pull;

        setProperty(*elements.viewerScreen, "display", "block");
        setProperty(*elements.viewerScreen, "opacity", number(reverse));
        setProperty(*elements.viewerStage, "transform", "scale(" + number(0.92 + 0.08 * reverse) + ")");
        setProperty(*elements.viewerScreenIcon, "transform", "scale(" + number(0.88 + 0.12 * reverse) + ")");
        setProperty(*elements.hubScreen, "display", "block");
        setProperty(*elements.hubScreen, "opacity", number(pull));
        setHubContentOpacity(elements, number(pull), hubPlanetEnabled, hubNodesEnabled);
        setProperty(*elements.hubStage, "transform", "scale(" + number(0.94 + 0.06 * pull) + ")");
        setProperty(*elements.hubPlanet, "transform", "translate(" + dp(24.0 * reverse) + ", " + dp(-10.0 * reverse) + ") scale(" + number(0.86 + 0.14 * pull) + ")");

        if (t >= 1.0)
        {
            state = ShellState::Hub;
            transition.enteredFromHub = false;
            transition.h3ReturnedToHub = true;
            setProperty(*elements.viewerScreen, "display", "none");
            setProperty(*elements.viewerScreen, "opacity", "0");
            setProperty(*elements.hubScreen, "display", "block");
            setProperty(*elements.hubScreen, "opacity", "1");
            setHubContentOpacity(elements, "1", hubPlanetEnabled, hubNodesEnabled);
            setProperty(*elements.hubPlanet, "transform", "none");
            if (!transition.returnedLogged)
            {
                std::cout << "SGFX cinematic shell H3 fly-back complete: live car viewer -> Seriengrafik planet hub\n";
                transition.returnedLogged = true;
            }
        }
    }
}

void setMenuContentOpacity(Elements& elements, const std::string& opacity)
{
    setProperty(*elements.menuTitle, "opacity", opacity);
    setProperty(*elements.viewerZone, "opacity", opacity);
    setProperty(*elements.menuIcon, "opacity", opacity);
    setProperty(*elements.viewerZoneLabel, "opacity", opacity);
    setProperty(*elements.menuTag, "opacity", opacity);
    for (auto* item : elements.menuItems)
        setProperty(*item, "opacity", opacity);
}

void setHubContentOpacity(Elements& elements, const std::string& opacity, bool hubPlanetEnabled)
{
    setProperty(*elements.hubStage, "opacity", opacity);
    setProperty(*elements.hubTitle, "opacity", opacity);
    setProperty(*elements.hubSubtitle, "opacity", opacity);
    setProperty(*elements.hubPlanetHalo, "opacity", opacity);
    setProperty(*elements.hubStatusPanel, "opacity", opacity);
    setProperty(*elements.hubActionPanel, "opacity", opacity);
    setProperty(*elements.hubBadge, "opacity", opacity);
    setProperty(*elements.hubReturnLabel, "opacity", opacity);
    setProperty(*elements.hubPlanet, "opacity", hubPlanetEnabled ? opacity : "0");
    setProperty(*elements.hubPlanetPlaceholder, "opacity", hubPlanetEnabled ? "0" : opacity);
}

void setHubContentOpacity(Elements& elements, const std::string& opacity, bool hubPlanetEnabled, bool hubNodesEnabled)
{
    setHubContentOpacity(elements, opacity, hubPlanetEnabled);
    for (auto* node : elements.hubNodes)
        setProperty(*node, "opacity", hubNodesEnabled ? opacity : "0");
    setProperty(*elements.hubActionPanel, "opacity", hubNodesEnabled ? opacity : "0");
}

void setHubArrivalContentOpacity(Elements& elements, const std::string& opacity, bool hubPlanetEnabled)
{
    setProperty(*elements.hubStage, "opacity", opacity);
    setProperty(*elements.hubTitle, "opacity", opacity);
    setProperty(*elements.hubSubtitle, "opacity", opacity);
    setProperty(*elements.hubPlanetHalo, "opacity", opacity);
    setProperty(*elements.hubBadge, "opacity", opacity);
    setProperty(*elements.hubReturnLabel, "opacity", opacity);
    setProperty(*elements.hubPlanet, "opacity", hubPlanetEnabled ? opacity : "0");
    setProperty(*elements.hubPlanetPlaceholder, "opacity", hubPlanetEnabled ? "0" : opacity);
}

void setHubNavigationOpacity(Elements& elements, const std::string& opacity, bool hubNodesEnabled)
{
    setProperty(*elements.hubStatusPanel, "opacity", opacity);
    setProperty(*elements.hubActionPanel, "opacity", hubNodesEnabled ? opacity : "0");
    for (auto* node : elements.hubNodes)
        setProperty(*node, "opacity", hubNodesEnabled ? opacity : "0");
}

double delayedEaseOut(double age, double delay, double duration)
{
    return easeOutCubic((age - delay) / duration);
}

void applyHubStagedRevealFrame(Elements& elements, double age, bool hubPlanetEnabled, bool hubNodesEnabled)
{
    setHubArrivalContentOpacity(elements, "1", hubPlanetEnabled);

    const double statusReveal = delayedEaseOut(age, kHubStatusRevealDelaySeconds, kHubStatusRevealSeconds);
    const double actionReveal = delayedEaseOut(age, kHubActionRevealDelaySeconds, kHubActionRevealSeconds);

    setProperty(*elements.hubStatusPanel, "opacity", number(statusReveal));
    setProperty(
        *elements.hubStatusPanel,
        "transform",
        "translate(" + dp(-18.0 * (1.0 - statusReveal)) + ", 0dp) scale(" + number(0.98 + 0.02 * statusReveal) + ")");
    setProperty(*elements.hubActionPanel, "opacity", hubNodesEnabled ? number(actionReveal) : "0");
    setProperty(
        *elements.hubActionPanel,
        "transform",
        "translate(0dp, " + dp(18.0 * (1.0 - actionReveal)) + ") scale(" + number(0.98 + 0.02 * actionReveal) + ")");

    if (!hubNodesEnabled)
    {
        for (auto* node : elements.hubNodes)
            setProperty(*node, "opacity", "0");
    }
}

void applyHubNodeFrame(
    Elements& elements,
    HubController& hub,
    ShellState state,
    double elapsed,
    bool hubNodesEnabled,
    const HubCapitalSummaries& summaries)
{
    if (!hubNodesEnabled)
        return;

    if (state == ShellState::Hub && !hub.readyLogged)
    {
        std::cout << "SGFX cinematic shell H2 hub capital nodes ready: "
                  << kHubNodeCount << " nodes, live=3D Car, " << hubWiringSummary(summaries) << "\n";
        hub.readyAt = elapsed;
        hub.readyLogged = true;
    }

    const int focused = hub.hovered >= 0 ? hub.hovered : hub.selected;
    const HubNodeDefinition& selectedNode = kHubNodes[static_cast<size_t>(hub.selected)];
    const double pulseT = clamp01((elapsed - hub.pulseStartedAt) / 0.22);
    const double pulse = (elapsed >= hub.pulseStartedAt && pulseT < 1.0) ? std::sin(pulseT * kPi) : 0.0;

    elements.hubActionTarget->SetInnerRML(
        escapeRmlText(hubActionTargetText(selectedNode, hub.selected, summaries)));
    elements.hubActionPrimary->SetInnerRML(escapeRmlText(hubActionPrimaryText(selectedNode, hub.selected, summaries)));
    elements.hubActionSecondary->SetInnerRML(escapeRmlText(hubActionSecondaryText(selectedNode, hub.selected, summaries)));
    elements.hubActionBanner->SetInnerRML(escapeRmlText(hubActionBannerText(selectedNode, hub.selected, summaries)));
    const bool selectedWired = selectedNode.live || isHubDataNodeLoaded(hub.selected, summaries);
    setProperty(*elements.hubActionPrimary, "background-color", selectedWired ? "#FFC94D" : "#12224bcc");
    setProperty(*elements.hubActionPrimary, "color", selectedWired ? "#0E1530" : "#BFE9FF");
    setProperty(*elements.hubActionPrimary, "border", std::string("1px ") + (selectedWired ? "#FFFFFF" : "#2FD6E6"));

    for (int i = 0; i < kHubNodeCount; ++i)
    {
        const HubNodeDefinition& definition = kHubNodes[static_cast<size_t>(i)];
        Rml::Element& node = *elements.hubNodes[static_cast<size_t>(i)];
        const bool live = definition.live || isHubDataNodeLoaded(i, summaries);
        const bool selected = i == hub.selected;
        const bool highlighted = i == focused;
        double revealOpacity = 1.0;
        double revealScale = 1.0;
        double revealLift = 0.0;
        if (state == ShellState::Hub && hub.readyAt >= 0.0)
        {
            const double revealT = clamp01(
                (elapsed - hub.readyAt - kHubNodeRevealDelaySeconds - static_cast<double>(i) * kHubNodeStaggerSeconds) /
                kHubNodeRevealSeconds);
            const double reveal = easeOutBack(revealT);
            revealOpacity = easeOutCubic(revealT);
            revealScale = 0.92 + 0.08 * reveal;
            revealLift = 18.0 * (1.0 - revealOpacity);
            setProperty(node, "opacity", number(revealOpacity));
        }

        const double scale = ((live ? 1.035 : 1.0) + (highlighted ? 0.035 : 0.0) + (selected ? pulse * 0.035 : 0.0)) * revealScale;
        const double lift = (highlighted ? -4.0 - pulse * 2.0 : 0.0) + revealLift;

        setProperty(node, "transform", "translate(" + dp(0.0) + ", " + dp(lift) + ") scale(" + number(scale) + ")");
        setProperty(node, "background-color", live ? "#16224ff0" : (highlighted ? "#142855ee" : "#0E1530d8"));
        setProperty(node, "color", "#FFFFFF");
        setProperty(node, "border", std::string(highlighted ? "2px " : "1px ") + (highlighted ? "#FFFFFF" : definition.accent));
        setProperty(
            node,
            "box-shadow",
            std::string(definition.accent) + (live || highlighted ? "aa 0px 0px 28px 3px" : "77 0px 0px 16px 1px"));
    }
}

void applyHubTransitionFrame(
    Elements& elements,
    ShellState& state,
    ViewerTransition& transition,
    double elapsed,
    bool hubPlanetEnabled,
    bool hubNodesEnabled)
{
    if (state == ShellState::FlyToHub)
    {
        const double t = clamp01((elapsed - transition.startedAt) / kViewerFlyInSeconds);
        const double push = easeInCubic(t);
        const double resolve = easeOutCubic(t);
        const double planetScale = 0.86 + 0.14 * resolve;
        const std::string hubOpacity = number(resolve);

        setProperty(*elements.menu, "display", "block");
        setProperty(*elements.menu, "opacity", number(1.0 - clamp01(t * 1.15)));
        setMenuContentOpacity(elements, number(1.0 - clamp01(t * 1.15)));
        setProperty(*elements.viewerScreen, "display", "none");
        setProperty(*elements.viewerScreen, "opacity", "0");
        setProperty(*elements.hubScreen, "display", "block");
        setProperty(*elements.hubScreen, "opacity", hubOpacity);
        setHubArrivalContentOpacity(elements, hubOpacity, hubPlanetEnabled);
        setHubNavigationOpacity(elements, "0", hubNodesEnabled);
        setProperty(*elements.hubStage, "transform", "scale(" + number(0.94 + 0.06 * resolve) + ")");
        setProperty(*elements.hubPlanet, "transform", "translate(" + dp(24.0 * (1.0 - resolve)) + ", " + dp(-10.0 * (1.0 - resolve)) + ") scale(" + number(planetScale + push * 0.02) + ")");

        if (t >= 1.0)
        {
            state = ShellState::Hub;
            transition.enteredAt = elapsed;
            setProperty(*elements.menu, "display", "none");
            setProperty(*elements.menu, "opacity", "0");
            setMenuContentOpacity(elements, "0");
            setProperty(*elements.viewerScreen, "display", "none");
            setProperty(*elements.hubScreen, "display", "block");
            setProperty(*elements.hubScreen, "opacity", "1");
            setHubArrivalContentOpacity(elements, "1", hubPlanetEnabled);
            setHubNavigationOpacity(elements, "0", hubNodesEnabled);
            setProperty(*elements.hubPlanet, "transform", "none");
            if (!transition.enteredLogged)
            {
                std::cout << "SGFX cinematic shell planet hub ready: Ramses procedural planet centerpiece\n";
                transition.enteredLogged = true;
            }
        }
        return;
    }

    if (state == ShellState::Hub)
    {
        setProperty(*elements.menu, "display", "none");
        setProperty(*elements.menu, "opacity", "0");
        setMenuContentOpacity(elements, "0");
        setProperty(*elements.viewerScreen, "display", "none");
        setProperty(*elements.viewerScreen, "opacity", "0");
        setProperty(*elements.hubScreen, "display", "block");
        setProperty(*elements.hubScreen, "opacity", "1");
        if (transition.h3ReturnedToHub || transition.enteredAt < -10.0)
        {
            setHubContentOpacity(elements, "1", hubPlanetEnabled, hubNodesEnabled);
            setProperty(*elements.hubStatusPanel, "transform", "translate(0dp, 0dp) scale(1.000)");
            setProperty(*elements.hubActionPanel, "transform", "translate(0dp, 0dp) scale(1.000)");
        }
        else
        {
            const double revealAge = std::max(0.0, elapsed - transition.enteredAt);
            applyHubStagedRevealFrame(elements, revealAge, hubPlanetEnabled, hubNodesEnabled);
            if (!transition.hubRevealStartedLogged)
            {
                std::cout << "SGFX cinematic shell staged hub reveal started: status/action panels + capital nodes over "
                          << number(kHubRevealCompleteSeconds, 1) << "s\n";
                transition.hubRevealStartedLogged = true;
            }
            if (revealAge >= kHubRevealCompleteSeconds && !transition.hubRevealCompleteLogged)
            {
                std::cout << "SGFX cinematic shell staged hub reveal complete: world-map chrome settled\n";
                transition.hubRevealCompleteLogged = true;
            }
        }
        setProperty(*elements.hubPlanet, "transform", "none");
        return;
    }

    if (state == ShellState::FlyBackToHubMenu)
    {
        const double t = clamp01((elapsed - transition.startedAt) / kViewerFlyBackSeconds);
        const double pull = easeOutCubic(t);
        const double reverse = 1.0 - pull;
        const std::string hubOpacity = number(1.0 - pull);

        setProperty(*elements.menu, "display", "block");
        setProperty(*elements.menu, "opacity", number(pull));
        setMenuContentOpacity(elements, number(pull));
        setProperty(*elements.viewerScreen, "display", "none");
        setProperty(*elements.hubScreen, "display", "block");
        setProperty(*elements.hubScreen, "opacity", hubOpacity);
        setHubContentOpacity(elements, hubOpacity, hubPlanetEnabled, hubNodesEnabled);
        setProperty(*elements.hubStage, "transform", "scale(" + number(0.94 + 0.06 * reverse) + ")");
        setProperty(*elements.hubPlanet, "transform", "translate(" + dp(24.0 * pull) + ", " + dp(-10.0 * pull) + ") scale(" + number(0.86 + 0.14 * reverse) + ")");

        if (t >= 1.0)
        {
            state = ShellState::Menu;
            setProperty(*elements.hubScreen, "display", "none");
            setProperty(*elements.hubScreen, "opacity", "0");
            setHubContentOpacity(elements, "0", hubPlanetEnabled, hubNodesEnabled);
            setProperty(*elements.viewerScreen, "display", "none");
            setProperty(*elements.menu, "display", "block");
            setProperty(*elements.menu, "opacity", "1");
            setMenuContentOpacity(elements, "1");
            setProperty(*elements.hubPlanet, "transform", "none");
            if (!transition.returnedLogged)
            {
                std::cout << "SGFX cinematic shell hub fly-back complete: QA Board menu\n";
                transition.returnedLogged = true;
            }
        }
    }
}

struct ReadbackStats
{
    int width = 0;
    int height = 0;
    std::uint64_t brightPixels = 0;
    int minX = 0;
    int minY = 0;
    int maxX = -1;
    int maxY = -1;
};

ReadbackStats saveReadback(SDL_Renderer* renderer, const std::string& path)
{
    std::unique_ptr<SDL_Surface, decltype(&SDL_DestroySurface)> surface(SDL_RenderReadPixels(renderer, nullptr), SDL_DestroySurface);
    if (!surface)
        throw std::runtime_error(std::string("SDL_RenderReadPixels failed: ") + SDL_GetError());

    const std::filesystem::path outputPath(path);
    if (outputPath.has_parent_path())
        std::filesystem::create_directories(outputPath.parent_path());
    if (!SDL_SaveBMP(surface.get(), path.c_str()))
        throw std::runtime_error(std::string("SDL_SaveBMP failed: ") + SDL_GetError());

    ReadbackStats stats;
    stats.width = surface->w;
    stats.height = surface->h;
    stats.minX = stats.width;
    stats.minY = stats.height;

    for (int y = 0; y < surface->h; ++y)
    {
        for (int x = 0; x < surface->w; ++x)
        {
            Uint8 r = 0;
            Uint8 g = 0;
            Uint8 b = 0;
            Uint8 a = 0;
            if (!SDL_ReadSurfacePixel(surface.get(), x, y, &r, &g, &b, &a))
                continue;
            if (a > 0 && static_cast<int>(r) + static_cast<int>(g) + static_cast<int>(b) > 96)
            {
                ++stats.brightPixels;
                stats.minX = std::min(stats.minX, x);
                stats.minY = std::min(stats.minY, y);
                stats.maxX = std::max(stats.maxX, x);
                stats.maxY = std::max(stats.maxY, y);
            }
        }
    }

    if (stats.brightPixels == 0)
    {
        stats.minX = 0;
        stats.minY = 0;
    }
    return stats;
}

ReadbackStats saveReadbackGl(Rml::Vector2i dimensions, const std::string& path)
{
    using GlPixelStoreiProc = void(APIENTRYP)(GLenum, GLint);
    using GlReadBufferProc = void(APIENTRYP)(GLenum);
    using GlReadPixelsProc = void(APIENTRYP)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, GLvoid*);
    using GlGetErrorProc = GLenum(APIENTRYP)();

    auto loadGlProc = [](const char* name) -> SDL_FunctionPointer {
        SDL_FunctionPointer proc = SDL_GL_GetProcAddress(name);
        if (!proc)
            throw std::runtime_error(std::string("SDL_GL_GetProcAddress failed for ") + name);
        return proc;
    };

    const auto glPixelStoreiProc = reinterpret_cast<GlPixelStoreiProc>(loadGlProc("glPixelStorei"));
    const auto glReadBufferProc = reinterpret_cast<GlReadBufferProc>(loadGlProc("glReadBuffer"));
    const auto glReadPixelsProc = reinterpret_cast<GlReadPixelsProc>(loadGlProc("glReadPixels"));
    const auto glGetErrorProc = reinterpret_cast<GlGetErrorProc>(loadGlProc("glGetError"));

    const int width = std::max(1, dimensions.x);
    const int height = std::max(1, dimensions.y);
    std::vector<Uint8> pixels(static_cast<size_t>(width) * static_cast<size_t>(height) * 4);

    while (glGetErrorProc() != GL_NO_ERROR)
    {
    }
    glPixelStoreiProc(GL_PACK_ALIGNMENT, 1);
    glReadBufferProc(GL_BACK);
    glReadPixelsProc(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
    const GLenum readError = glGetErrorProc();
    if (readError != GL_NO_ERROR)
        throw std::runtime_error("glReadPixels failed with GL error " + std::to_string(readError));

    std::unique_ptr<SDL_Surface, decltype(&SDL_DestroySurface)> surface(SDL_CreateSurface(width, height, SDL_PIXELFORMAT_RGBA32), SDL_DestroySurface);
    if (!surface)
        throw std::runtime_error(std::string("SDL_CreateSurface failed for GL readback: ") + SDL_GetError());

    auto* destinationPixels = static_cast<Uint8*>(surface->pixels);
    for (int y = 0; y < height; ++y)
    {
        const auto* sourceRow = pixels.data() + static_cast<size_t>(height - 1 - y) * static_cast<size_t>(width) * 4;
        auto* destinationRow = destinationPixels + static_cast<size_t>(y) * static_cast<size_t>(surface->pitch);
        std::memcpy(destinationRow, sourceRow, static_cast<size_t>(width) * 4);
    }

    const std::filesystem::path outputPath(path);
    if (outputPath.has_parent_path())
        std::filesystem::create_directories(outputPath.parent_path());
    if (!SDL_SaveBMP(surface.get(), path.c_str()))
        throw std::runtime_error(std::string("SDL_SaveBMP failed: ") + SDL_GetError());

    ReadbackStats stats;
    stats.width = surface->w;
    stats.height = surface->h;
    stats.minX = stats.width;
    stats.minY = stats.height;

    for (int y = 0; y < surface->h; ++y)
    {
        for (int x = 0; x < surface->w; ++x)
        {
            Uint8 r = 0;
            Uint8 g = 0;
            Uint8 b = 0;
            Uint8 a = 0;
            if (!SDL_ReadSurfacePixel(surface.get(), x, y, &r, &g, &b, &a))
                continue;
            if (a > 0 && static_cast<int>(r) + static_cast<int>(g) + static_cast<int>(b) > 96)
            {
                ++stats.brightPixels;
                stats.minX = std::min(stats.minX, x);
                stats.minY = std::min(stats.minY, y);
                stats.maxX = std::max(stats.maxX, x);
                stats.maxY = std::max(stats.maxY, y);
            }
        }
    }

    if (stats.brightPixels == 0)
    {
        stats.minX = 0;
        stats.minY = 0;
    }
    return stats;
}

bool isIntroState(ShellState state)
{
    return state == ShellState::Splash || state == ShellState::Hero;
}

bool wantsFusionCarDiscovery(const Options& options)
{
    return options.fusionEnabled ||
        !options.fusionCarsRoot.empty() ||
        !options.fusionProfileId.empty() ||
        !options.fusionPerspectiveSet.empty() ||
        !options.fusionPerspectiveFile.empty() ||
        !options.fusionPerspectiveId.empty() ||
        options.demoCarPickIndex >= 0 ||
        options.demoCarPickAfterMs >= 0;
}

int run(int argc, char** argv)
{
    Options options = parseOptions(argc, argv);
    const FusionCarDiscovery carDiscovery = wantsFusionCarDiscovery(options) ? discoverFusionCarCandidates(options) : FusionCarDiscovery{};
    const std::vector<FusionCarCandidate>& carCandidates = carDiscovery.candidates;
    int activeCarIndex = chooseInitialCarCandidate(carCandidates, options);
    if (activeCarIndex >= 0)
        options = optionsForCarCandidate(options, carCandidates[static_cast<size_t>(activeCarIndex)], true);
    const HubCapitalSummaries hubCapitals = loadHubCapitalSummaries();

    SdlRuntime sdl;
    SdlGlWindow windowRenderer("SGFX Cinematic Shell", options.width, options.height);
    ShellSystemInterface systemInterface;
    SgfxGl3RenderInterface renderInterface(options.assetRoot);
    renderInterface.SetViewport(options.width, options.height);
    std::unique_ptr<FusionCarTexture> fusionCar;
    std::unique_ptr<HubPlanetTexture> hubPlanet;
    std::unique_ptr<RamsesCarDecoratorInstancer> fusionDecoratorInstancer;
    std::unique_ptr<HubPlanetDecoratorInstancer> hubPlanetDecoratorInstancer;

    if (options.fusionEnabled)
        fusionCar = std::make_unique<FusionCarTexture>(options, windowRenderer);
    if (options.hubPlanetEnabled)
        hubPlanet = std::make_unique<HubPlanetTexture>(options);

    if ((fusionCar && fusionCar->ready()) || (hubPlanet && hubPlanet->ready()))
        windowRenderer.reloadRmlGlBackend();

    if (fusionCar && fusionCar->ready())
        renderInterface.registerBorrowedTexture(fusionCar->textureHandle());
    Rml::SetSystemInterface(&systemInterface);
    Rml::SetRenderInterface(&renderInterface);
    RmlRuntime rml;
    loadShellFonts(options.fontRoot);
    if (fusionCar && fusionCar->ready())
    {
        fusionDecoratorInstancer = std::make_unique<RamsesCarDecoratorInstancer>(fusionCar.get());
        Rml::Factory::RegisterDecoratorInstancer("sgfx-ramses-car", fusionDecoratorInstancer.get());
        std::cout << "Fusion Phase 2 RmlUi decorator registered: sgfx-ramses-car\n";
    }
    if (hubPlanet && hubPlanet->ready())
    {
        hubPlanetDecoratorInstancer = std::make_unique<HubPlanetDecoratorInstancer>(hubPlanet.get());
        Rml::Factory::RegisterDecoratorInstancer("sgfx-hub-planet", hubPlanetDecoratorInstancer.get());
        std::cout << "Hub H1 RmlUi decorator registered: sgfx-hub-planet\n";
    }
    Rml::Context* context = Rml::CreateContext("sgfx-cinematic-shell", Rml::Vector2i(options.width, options.height));
    if (!context)
        throw std::runtime_error("Rml::CreateContext failed");

    Rml::ElementDocument* document = context->LoadDocumentFromMemory(
        buildDocument(
            fusionCar && fusionCar->ready(),
            fusionCar ? fusionCar->qaPerspective() : std::nullopt,
            carCandidates,
            activeCarIndex,
            carDiscovery.registeredProfileCount,
            fusionCar ? fusionCar->profileId() : std::string{},
            hubPlanet && hubPlanet->ready(),
            options.hubNodesEnabled,
            hubCapitals));
    if (!document)
        throw std::runtime_error("RmlUi document failed to load");
    document->Show();
    Elements elements = getElements(*document);

    bool quit = false;
    bool skipped = false;
    bool scriptedSkipFired = false;
    ShellState state = ShellState::Splash;
    MenuController menuController;
    if (options.demoMenuFocus >= 0)
        menuController.selected = clampMenuIndex(options.demoMenuFocus);
    ViewerTransition viewerTransition;
    HubController hubController;
    hubController.selected = std::max(0, std::min(kHubNodeCount - 1, options.demoHubNodeIndex));
    CarPickerController carPickerController;
    carPickerController.selected = activeCarIndex;
    carPickerController.active = activeCarIndex;
    carPickerController.registeredProfileCount = carDiscovery.registeredProfileCount;
    double elapsed = 0.0;

    std::cout << "SGFX cinematic shell RmlUi version: " << Rml::GetVersion() << "\n";
    std::cout << "SGFX cinematic shell RmlUi font engine: freetype\n";
    std::cout << "SGFX cinematic shell renderer backend: RmlUi GL3\n";
    std::cout << "SGFX cinematic shell GL: " << windowRenderer.glInfo() << "\n";
    std::cout << "SGFX cinematic shell window: " << options.width << "x" << options.height << "\n";
    std::cout << "SGFX cinematic shell asset root: " << std::filesystem::absolute(options.assetRoot).string() << "\n";
    std::cout << "SGFX cinematic shell font root: " << std::filesystem::absolute(options.fontRoot).string() << "\n";
    std::cout << "SGFX cinematic shell brand allowlist: logo_sgfx.png, framework_sgfx_logo.png, debug_icon.png, sgfx_icon.png\n";
    std::cout << "SGFX cinematic shell renderer look: native GL3 Adventure Dawn gradients + box-shadow glow accents\n";
    std::cout << "SGFX cinematic shell timings: splash 0.3/1.2/0.3s, hero 0.5/1.6/0.4s, house ease-out\n";
    std::cout << "SGFX cinematic shell menu animation: item reveal 0.25s, stagger 70ms, feedback 120ms\n";
    std::cout << "SGFX cinematic shell menu controls: pointer hover/click, Up/Down, Enter/Space\n";
    std::cout << "SGFX cinematic shell fly-into-zone: 0.70s in, 0.50s back, 3D Car viewer core destination\n";
    std::cout << "SGFX cinematic shell mode: " << (options.interactive ? "interactive run-until-close" : "framed evidence run") << "\n";
    std::cout << "SGFX cinematic shell skip: any key/click during splash or hero -> menu\n";
    logHubCapitalSummaries(hubCapitals);
    std::cout << "SGFX cinematic shell car picker discovered exports: " << carCandidates.size() << "\n";
    std::cout << "SGFX cinematic shell car picker registered profiles: "
              << carDiscovery.registeredProfileCount
              << " source=" << carDiscovery.registeredProfileSource << "\n";
    for (size_t index = 0u; index < carCandidates.size(); ++index)
    {
        const FusionCarCandidate& candidate = carCandidates[index];
        std::cout << "SGFX cinematic shell car picker candidate[" << index << "]: "
                  << candidate.profileId
                  << " registry=" << (candidate.registryMatched ? std::to_string(candidate.registryRank) : std::string("unmatched"))
                  << " perspective=" << (candidate.defaultPerspectiveSet.empty() ? std::string("none") : candidate.defaultPerspectiveSet)
                  << " scene=" << candidate.sceneFile.string() << "\n";
    }
    if (fusionCar && fusionCar->ready())
    {
        std::cout << "SGFX cinematic shell viewer zone: Ramses readPixels -> app GL texture -> RmlUi CallbackTexture decorator\n";
        std::cout << "SGFX cinematic shell active car picker profile/scene: "
                  << fusionCar->profileId() << " / " << fusionCar->sceneFile().string() << "\n";
        std::cout << "SGFX cinematic shell fusion texture id/dims: " << fusionCar->glTexture() << "/"
                  << fusionCar->textureDimensions().x << "x" << fusionCar->textureDimensions().y << "\n";
        std::cout << "SGFX cinematic shell fusion Ramses bright pixels: " << fusionCar->ramsesStats().brightPixels << "\n";
        std::cout << "SGFX cinematic shell fusion P4 producer frames/readPixels/uploads: "
                  << fusionCar->performanceStats().producerFrames << "/"
                  << fusionCar->performanceStats().readbackRequests << "/"
                  << fusionCar->performanceStats().textureUploads << "\n";
        if (fusionCar->qaPerspective())
        {
            std::cout << "SGFX cinematic shell QA perspective picker: "
                      << fusionCar->qaPerspective()->setName << "/"
                      << fusionCar->qaPerspective()->id << " ("
                      << fusionCar->qaPerspective()->viewIds.size() << " views)\n";
        }
    }
    else
    {
        std::cout << "SGFX cinematic shell viewer zone: sgfx_cine_ramses_real_scene is preserved as the 3D Car core\n";
    }
    if (hubPlanet && hubPlanet->ready())
    {
        std::cout << "SGFX cinematic shell planet hub: Ramses procedural planet -> RmlUi-owned CallbackTexture decorator\n";
        std::cout << "SGFX cinematic shell hub planet texture dims/source bytes: "
                  << hubPlanet->textureDimensions().x << "x" << hubPlanet->textureDimensions().y << "/"
                  << hubPlanet->pixels().size() << "\n";
        std::cout << "SGFX cinematic shell hub planet Ramses bright pixels: " << hubPlanet->ramsesStats().brightPixels << "\n";
        std::cout << "SGFX cinematic shell hub H4 producer frames/readPixels/uploads: "
                  << hubPlanet->performanceStats().producerFrames << "/"
                  << hubPlanet->performanceStats().readbackRequests << "/"
                  << hubPlanet->performanceStats().textureUploads << "\n";
        if (options.hubNodesEnabled)
        {
            std::cout << "SGFX cinematic shell hub H4 nodes: polished RmlUi world-map labels, "
                      << kHubNodeCount << " capitals, live=3D Car, " << hubWiringSummary(hubCapitals) << "\n";
            std::cout << "SGFX cinematic shell world-map layout chrome: status panel top-left, dive/select action bottom-right\n";
        }
    }
    else
    {
        std::cout << "SGFX cinematic shell planet hub: disabled until --hub-planet is supplied\n";
    }

    const Uint64 startTicks = SDL_GetTicks();
    for (int frame = 0; !quit && (options.interactive || frame < options.frames); ++frame)
    {
        if (!options.noDelay)
            elapsed = static_cast<double>(SDL_GetTicks() - startTicks) / 1000.0;
        else
            elapsed = frame / options.fps;
        if (isIntroState(state) || state == ShellState::Menu)
            state = applyIntroFrame(elements, elapsed, skipped);

        SDL_Event event;
        while (SDL_PollEvent(&event))
        {
            if (event.type == SDL_EVENT_QUIT || event.type == SDL_EVENT_WINDOW_CLOSE_REQUESTED)
                quit = true;
            else if (event.type == SDL_EVENT_WINDOW_RESIZED || event.type == SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED)
            {
                const int width = std::max(1, event.window.data1);
                const int height = std::max(1, event.window.data2);
                context->SetDimensions({width, height});
                renderInterface.SetViewport(width, height);
            }
            else if (event.type == SDL_EVENT_KEY_DOWN)
            {
                if (state == ShellState::ViewerZone && (event.key.key == SDLK_ESCAPE || event.key.key == SDLK_BACKSPACE))
                    startViewerFlyBack(state, viewerTransition, elapsed);
                else if (state == ShellState::ViewerZone && !carCandidates.empty())
                {
                    if (event.key.key == SDLK_UP || event.key.key == SDLK_LEFT || event.key.key == SDLK_A || event.key.key == SDLK_W)
                    {
                        moveCarSelection(carPickerController, carCandidates, -1, elapsed);
                        refreshCarPickerUi(elements, carCandidates, carPickerController, fusionCar.get());
                    }
                    else if (event.key.key == SDLK_DOWN || event.key.key == SDLK_RIGHT || event.key.key == SDLK_D || event.key.key == SDLK_S)
                    {
                        moveCarSelection(carPickerController, carCandidates, 1, elapsed);
                        refreshCarPickerUi(elements, carCandidates, carPickerController, fusionCar.get());
                    }
                    else if (event.key.key == SDLK_RETURN || event.key.key == SDLK_KP_ENTER || event.key.key == SDLK_SPACE)
                    {
                        activateCarCandidate(options, elements, renderInterface, fusionCar.get(), carCandidates, carPickerController, carPickerController.selected, elapsed);
                    }
                }
                else if (state == ShellState::Hub && (event.key.key == SDLK_ESCAPE || event.key.key == SDLK_BACKSPACE))
                    startHubFlyBack(state, viewerTransition, elapsed);
                else if (state == ShellState::Hub && options.hubNodesEnabled)
                {
                    if (event.key.key == SDLK_LEFT || event.key.key == SDLK_UP || event.key.key == SDLK_A || event.key.key == SDLK_W)
                        moveHubNodeSelection(hubController, -1, elapsed);
                    else if (event.key.key == SDLK_RIGHT || event.key.key == SDLK_DOWN || event.key.key == SDLK_D || event.key.key == SDLK_S)
                        moveHubNodeSelection(hubController, 1, elapsed);
                    else if (event.key.key == SDLK_RETURN || event.key.key == SDLK_KP_ENTER || event.key.key == SDLK_SPACE)
                    {
                        activateHubNode(state, viewerTransition, hubController, hubController.selected, elapsed, fusionCar && fusionCar->ready(), hubCapitals);
                    }
                }
                else if (event.key.key == SDLK_ESCAPE)
                    quit = true;
                else if (isIntroState(state))
                {
                    skipped = true;
                }
                else if (state == ShellState::Menu)
                {
                    if (event.key.key == SDLK_UP || event.key.key == SDLK_W)
                        moveMenuSelection(menuController, -1, elapsed);
                    else if (event.key.key == SDLK_DOWN || event.key.key == SDLK_S)
                        moveMenuSelection(menuController, 1, elapsed);
                    else if (event.key.key == SDLK_RETURN || event.key.key == SDLK_KP_ENTER || event.key.key == SDLK_SPACE)
                    {
                        startMenuPulse(menuController, elapsed);
                        std::cout << "SGFX cinematic shell menu activated: " << kMenuItemLabels[static_cast<size_t>(menuController.selected)] << "\n";
                        if (menuController.selected == 5)
                            quit = true;
                        else if (isViewerMenuIndex(menuController.selected))
                            startViewerFlyIn(state, viewerTransition, elapsed);
                        else if (isHubMenuIndex(menuController.selected))
                            startHubFlyIn(state, viewerTransition, hubController, elapsed);
                    }
                }
            }
            else if (event.type == SDL_EVENT_MOUSE_MOTION && state == ShellState::Menu)
            {
                menuController.hovered = hitTestMenuItem(event.motion.x, event.motion.y);
                if (menuController.hovered >= 0)
                    menuController.selected = menuController.hovered;
            }
            else if (event.type == SDL_EVENT_MOUSE_MOTION && state == ShellState::Hub && options.hubNodesEnabled)
            {
                hubController.hovered = hitTestHubNode(event.motion.x, event.motion.y);
                if (hubController.hovered >= 0)
                    hubController.selected = hubController.hovered;
            }
            else if (event.type == SDL_EVENT_MOUSE_MOTION && state == ShellState::ViewerZone && !carCandidates.empty())
            {
                carPickerController.hovered = hitTestCarPickerRow(event.motion.x, event.motion.y, carCandidates);
                if (carPickerController.hovered >= 0)
                {
                    carPickerController.selected = carPickerController.hovered;
                    refreshCarPickerUi(elements, carCandidates, carPickerController, fusionCar.get());
                }
            }
            else if (event.type == SDL_EVENT_MOUSE_BUTTON_DOWN && isIntroState(state))
            {
                skipped = true;
            }
            else if (event.type == SDL_EVENT_MOUSE_BUTTON_DOWN && state == ShellState::Menu)
            {
                const int hit = hitTestMenuItem(event.button.x, event.button.y);
                if (hit >= 0)
                {
                    menuController.selected = hit;
                    menuController.hovered = hit;
                    startMenuPulse(menuController, elapsed);
                    std::cout << "SGFX cinematic shell menu clicked: " << kMenuItemLabels[static_cast<size_t>(menuController.selected)] << "\n";
                    if (menuController.selected == 5)
                        quit = true;
                    else if (isViewerMenuIndex(menuController.selected))
                        startViewerFlyIn(state, viewerTransition, elapsed);
                    else if (isHubMenuIndex(menuController.selected))
                        startHubFlyIn(state, viewerTransition, hubController, elapsed);
                }
                else if (hitTestViewerZone(event.button.x, event.button.y))
                {
                    menuController.selected = 1;
                    menuController.hovered = 1;
                    startMenuPulse(menuController, elapsed);
                    std::cout << "SGFX cinematic shell viewer zone clicked: 3D Car viewer core\n";
                    startViewerFlyIn(state, viewerTransition, elapsed);
                }
            }
            else if (event.type == SDL_EVENT_MOUSE_BUTTON_DOWN && state == ShellState::Hub && options.hubNodesEnabled)
            {
                const int hit = hitTestHubNode(event.button.x, event.button.y);
                if (hit >= 0)
                {
                    hubController.hovered = hit;
                    activateHubNode(state, viewerTransition, hubController, hit, elapsed, fusionCar && fusionCar->ready(), hubCapitals);
                }
                else if (hitTestHubAction(event.button.x, event.button.y))
                {
                    activateHubNode(state, viewerTransition, hubController, hubController.selected, elapsed, fusionCar && fusionCar->ready(), hubCapitals);
                }
            }
            else if (event.type == SDL_EVENT_MOUSE_BUTTON_DOWN && state == ShellState::ViewerZone && !carCandidates.empty())
            {
                const int hit = hitTestCarPickerRow(event.button.x, event.button.y, carCandidates);
                if (hit >= 0)
                {
                    carPickerController.hovered = hit;
                    activateCarCandidate(options, elements, renderInterface, fusionCar.get(), carCandidates, carPickerController, hit, elapsed);
                }
            }
        }

        if (!scriptedSkipFired && options.skipAfterMs >= 0 && elapsed * 1000.0 >= options.skipAfterMs && isIntroState(state))
        {
            skipped = true;
            scriptedSkipFired = true;
            state = applyIntroFrame(elements, elapsed, skipped);
            std::cout << "SGFX cinematic shell scripted skip fired at " << options.skipAfterMs << " ms\n";
        }

        if (state == ShellState::Menu)
        {
            if (options.demoMenuFocus >= 0)
                menuController.selected = clampMenuIndex(options.demoMenuFocus);
            applyMenuFrame(elements, menuController, state, elapsed);
            if (!menuController.demoPulseFired && options.demoMenuPulseAfterMs >= 0 &&
                (elapsed - menuController.enteredAt) * 1000.0 >= static_cast<double>(options.demoMenuPulseAfterMs))
            {
                startMenuPulse(menuController, elapsed);
                menuController.demoPulseFired = true;
                std::cout << "SGFX cinematic shell demo menu pulse fired: " << kMenuItemLabels[static_cast<size_t>(menuController.selected)] << "\n";
                applyMenuFrame(elements, menuController, state, elapsed);
            }
            if (!viewerTransition.demoEnterFired && options.demoEnterViewerAfterMs >= 0 &&
                menuController.enteredAt >= 0.0 &&
                (elapsed - menuController.enteredAt) * 1000.0 >= static_cast<double>(options.demoEnterViewerAfterMs))
            {
                startMenuPulse(menuController, elapsed);
                if (isHubMenuIndex(menuController.selected))
                    startHubFlyIn(state, viewerTransition, hubController, elapsed);
                else
                    startViewerFlyIn(state, viewerTransition, elapsed);
                viewerTransition.demoEnterFired = true;
                std::cout << "SGFX cinematic shell demo zone fly-in fired\n";
            }
        }
        if (state == ShellState::Hub && options.demoHubNodeEnterAfterMs >= 0 &&
            hubController.readyAt >= 0.0 && !viewerTransition.demoHubNodeEnterFired &&
            (elapsed - hubController.readyAt) * 1000.0 >= static_cast<double>(options.demoHubNodeEnterAfterMs))
        {
            activateHubNode(state, viewerTransition, hubController, kHubNodeLiveIndex, elapsed, fusionCar && fusionCar->ready(), hubCapitals);
            viewerTransition.demoHubNodeEnterFired = true;
            std::cout << "SGFX cinematic shell H3 demo hub node fly-in fired\n";
        }
        if (state == ShellState::ViewerZone && options.demoViewerBackAfterMs >= 0 &&
            viewerTransition.enteredAt >= 0.0 && !viewerTransition.demoViewerBackFired &&
            (elapsed - viewerTransition.enteredAt) * 1000.0 >= static_cast<double>(options.demoViewerBackAfterMs))
        {
            startViewerFlyBack(state, viewerTransition, elapsed);
            viewerTransition.demoViewerBackFired = true;
            std::cout << "SGFX cinematic shell H3 demo viewer-back fired\n";
        }
        if (state == ShellState::ViewerZone && options.demoCarPickAfterMs >= 0 &&
            viewerTransition.enteredAt >= 0.0 && !carPickerController.demoPickFired &&
            (elapsed - viewerTransition.enteredAt) * 1000.0 >= static_cast<double>(options.demoCarPickAfterMs))
        {
            const int targetIndex = options.demoCarPickIndex >= 0 ? options.demoCarPickIndex :
                (carPickerController.active + 1);
            activateCarCandidate(options, elements, renderInterface, fusionCar.get(), carCandidates, carPickerController, targetIndex, elapsed);
            carPickerController.demoPickFired = true;
            std::cout << "SGFX cinematic shell demo car picker fired: index " << clampCarIndex(carCandidates, targetIndex) << "\n";
        }
        applyViewerTransitionFrame(
            elements,
            state,
            viewerTransition,
            elapsed,
            fusionCar && fusionCar->ready(),
            hubPlanet && hubPlanet->ready(),
            options.hubNodesEnabled);
        applyHubTransitionFrame(elements, state, viewerTransition, elapsed, hubPlanet && hubPlanet->ready(), options.hubNodesEnabled);
        applyHubNodeFrame(elements, hubController, state, elapsed, options.hubNodesEnabled, hubCapitals);

        context->Update();
        windowRenderer.makeCurrent();
        prepareShellGlBackbufferForRml(windowRenderer.drawableSize());
        renderInterface.Clear();
        renderInterface.BeginFrame();
        context->Render();
        renderInterface.EndFrame();
        windowRenderer.swap();

        if (!options.noDelay)
            SDL_Delay(static_cast<Uint32>(std::max(1.0, 1000.0 / options.fps)));
    }

    if (options.readback)
    {
        context->Update();
        windowRenderer.makeCurrent();
        prepareShellGlBackbufferForRml(windowRenderer.drawableSize());
        renderInterface.Clear();
        renderInterface.BeginFrame();
        context->Render();
        renderInterface.EndFrame();
        const ReadbackStats stats = saveReadbackGl(windowRenderer.drawableSize(), options.screenshotPath);
        windowRenderer.swap();
        std::cout << "SGFX cinematic shell readback path: " << options.screenshotPath << "\n";
        std::cout << "SGFX cinematic shell readback bright pixels: " << stats.brightPixels << "\n";
        std::cout << "SGFX cinematic shell readback bounds: " << stats.minX << "," << stats.minY << " -> " << stats.maxX << "," << stats.maxY << "\n";
        if (stats.brightPixels == 0)
            throw std::runtime_error("SGFX cinematic shell readback did not contain visible UI pixels");
    }

    std::cout << "SGFX cinematic shell final state: " << stateName(state) << "\n";
    std::cout << "SGFX cinematic shell skipped intro: " << (skipped ? "true" : "false") << "\n";
    if (state == ShellState::Menu)
        std::cout << "SGFX cinematic shell menu selected item: " << kMenuItemLabels[static_cast<size_t>(menuController.selected)] << "\n";
    if (state == ShellState::ViewerZone)
    {
        std::cout << "SGFX cinematic shell viewer zone destination: "
                  << ((fusionCar && fusionCar->ready()) ? "RmlUi CallbackTexture Ramses fusion" : "sgfx_cine_ramses_real_scene")
                  << "\n";
        if (fusionCar && fusionCar->ready())
            std::cout << "SGFX cinematic shell car picker active profile/scene: "
                      << fusionCar->profileId() << " / " << fusionCar->sceneFile().string() << "\n";
        if (!carCandidates.empty() && carPickerController.selected >= 0)
            std::cout << "SGFX cinematic shell car picker selected row: "
                      << carCandidates[static_cast<size_t>(carPickerController.selected)].label << "\n";
        if (viewerTransition.h3ViewerReached)
            std::cout << "SGFX cinematic shell H3 route destination: planet hub 3D Car node -> live car viewer\n";
    }
    if (state == ShellState::Hub)
    {
        std::cout << "SGFX cinematic shell hub destination: "
                  << ((hubPlanet && hubPlanet->ready()) ? "RmlUi CallbackTexture Ramses planet fusion" : "planet placeholder")
                  << "\n";
        if (viewerTransition.h3ReturnedToHub)
            std::cout << "SGFX cinematic shell H3 roundtrip complete: planet -> 3D Car viewer -> planet\n";
    }
    if (state == ShellState::Hub && options.hubNodesEnabled)
    {
        const HubNodeDefinition& selectedNode = kHubNodes[static_cast<size_t>(hubController.selected)];
        std::cout << "SGFX cinematic shell hub H2 selected capital: " << selectedNode.label
                  << " / " << hubNodeStatusText(selectedNode, hubController.selected, hubCapitals) << "\n";
        std::cout << "SGFX cinematic shell hub H2 nodes summary: "
                  << kHubNodeCount << " capitals, 3D Car live, " << hubWiringSummary(hubCapitals) << "\n";
        std::cout << "SGFX cinematic shell hub world-map layout: status panel + dive/select affordance\n";
    }
    std::cout << "SGFX cinematic shell splash->hero beat OK\n";
    if (state == ShellState::ViewerZone || state == ShellState::FlyToViewer || state == ShellState::FlyBackToMenu ||
        state == ShellState::FlyHubToViewer || state == ShellState::FlyViewerBackToHub)
        std::cout << "SGFX cinematic shell fly-into-zone beat OK\n";
    if (state == ShellState::Hub || state == ShellState::FlyToHub || state == ShellState::FlyBackToHubMenu ||
        state == ShellState::FlyHubToViewer || state == ShellState::FlyViewerBackToHub)
        std::cout << "SGFX cinematic shell planet hub H1 beat OK\n";
    if (options.hubNodesEnabled && (state == ShellState::Hub || state == ShellState::FlyToHub || state == ShellState::FlyBackToHubMenu ||
        state == ShellState::FlyHubToViewer || state == ShellState::FlyViewerBackToHub))
        std::cout << "SGFX cinematic shell planet hub H2 nodes beat OK\n";
    if (hubPlanet && hubPlanet->ready() && options.hubNodesEnabled &&
        (state == ShellState::Hub || state == ShellState::FlyToHub || state == ShellState::FlyBackToHubMenu ||
            state == ShellState::FlyHubToViewer || state == ShellState::FlyViewerBackToHub))
    {
        std::cout << "SGFX cinematic shell planet hub H4 world-map polish beat OK\n";
        std::cout << "SGFX cinematic shell planet hub layout-refinement beat OK\n";
    }
    if (viewerTransition.h3ViewerReached)
        std::cout << "SGFX cinematic shell planet hub H3 node fly-into beat OK\n";
    if (viewerTransition.h3ReturnedToHub)
        std::cout << "SGFX cinematic shell planet hub H3 roundtrip beat OK\n";
    if (!carCandidates.empty() && fusionCar && fusionCar->ready())
        std::cout << "SGFX cinematic shell car picker beat OK\n";

    return 0;
}
} // namespace

int main(int argc, char** argv)
{
    try
    {
        return run(argc, argv);
    }
    catch (const std::exception& ex)
    {
        std::cerr << "SGFX cinematic shell failed: " << ex.what() << "\n";
        return 1;
    }
}
