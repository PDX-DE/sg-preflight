#include "ramses/client/ramses-client.h"
#include "ramses/client/ramses-utils.h"
#include "ramses/framework/RamsesFrameworkTypes.h"
#include "ramses/renderer/DisplayConfig.h"
#include "ramses/renderer/IRendererEventHandler.h"
#include "ramses/renderer/IRendererSceneControlEventHandler.h"
#include "ramses/renderer/RamsesRenderer.h"
#include "ramses/renderer/RendererConfig.h"
#include "ramses/renderer/RendererSceneControl.h"

#include <SDL3/SDL.h>

#include <array>
#include <chrono>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace
{
struct Options
{
    uint32_t width = 960u;
    uint32_t height = 540u;
    uint32_t frames = 600u;
    bool readback = false;
    std::string screenshotPath;
    std::string profileId;
};

uint32_t parseUint(const char* value, const char* optionName)
{
    char* end = nullptr;
    const unsigned long parsed = std::strtoul(value, &end, 10);
    if (end == value || *end != '\0' || parsed == 0ul || parsed > UINT32_MAX)
        throw std::runtime_error(std::string("Invalid value for ") + optionName);
    return static_cast<uint32_t>(parsed);
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
        else if (arg == "--screenshot")
            options.screenshotPath = requireValue("--screenshot");
        else if (arg == "--profile-id")
            options.profileId = requireValue("--profile-id");
        else
            throw std::runtime_error("Unknown argument: " + arg);
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
    throw std::runtime_error("C-2 currently requires the SDL3 Win32 backend");
#endif
}

class EmbedEventHandler : public ramses::RendererEventHandlerEmpty, public ramses::RendererSceneControlEventHandlerEmpty
{
public:
    EmbedEventHandler(ramses::displayId_t displayId,
                      ramses::sceneId_t sceneId,
                      uint32_t width,
                      uint32_t height,
                      std::string screenshotPath,
                      std::string sliceLabel)
        : m_displayId(displayId)
        , m_sceneId(sceneId)
        , m_width(width)
        , m_height(height)
        , m_screenshotPath(std::move(screenshotPath))
        , m_sliceLabel(std::move(sliceLabel))
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
            std::cout << m_sliceLabel << " readPixels: Failed\n";
            return;
        }

        std::vector<uint8_t> pixels(pixelData, pixelData + pixelDataSize);
        for (size_t i = 0; i + 3u < pixels.size(); i += 4u)
        {
            const uint32_t brightness = static_cast<uint32_t>(pixels[i]) + static_cast<uint32_t>(pixels[i + 1u]) + static_cast<uint32_t>(pixels[i + 2u]);
            if (brightness > 80u)
                ++m_brightPixels;
        }

        if (!m_screenshotPath.empty())
            m_screenshotSaved = ramses::RamsesUtils::SaveImageBufferToPng(m_screenshotPath, pixels, m_width, m_height, true);

        std::cout << m_sliceLabel << " readPixels bright pixels: " << m_brightPixels << "\n";
        if (!m_screenshotPath.empty())
            std::cout << m_sliceLabel << " screenshot saved: " << (m_screenshotSaved ? m_screenshotPath : "failed") << "\n";
    }

    void renderThreadLoopTimings(ramses::displayId_t displayId,
                                 std::chrono::microseconds maximumLoopTime,
                                 std::chrono::microseconds averageLoopTime) override
    {
        if (displayId != m_displayId)
            return;

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
    std::string m_sliceLabel;
    bool m_displayCreated = false;
    bool m_displayCreateFailed = false;
    ramses::RendererSceneState m_sceneState = ramses::RendererSceneState::Unavailable;
    bool m_pixelsRead = false;
    bool m_pixelsReadOk = false;
    bool m_screenshotSaved = false;
    uint64_t m_brightPixels = 0u;
};

struct TestScene
{
    ramses::Scene* scene = nullptr;
    ramses::MeshNode* mesh = nullptr;
};

std::array<const char*, 7u> glyphRows(char character)
{
    switch (character)
    {
    case '5':
        return {"11111", "10000", "11110", "00001", "00001", "10001", "01110"};
    case '6':
        return {"01110", "10000", "10000", "11110", "10001", "10001", "01110"};
    case 'G':
        return {"01110", "10001", "10000", "10111", "10001", "10001", "01110"};
    default:
        return {"11111", "00001", "00010", "00100", "00000", "00100", "00100"};
    }
}

void addProfileIdOverlay(ramses::Scene& scene,
                         ramses::RenderGroup& renderGroup,
                         const ramses::Effect& effect,
                         const std::string& profileId)
{
    if (profileId.empty())
        return;

    constexpr float cellSize = 0.065f;
    constexpr float cellGap = 0.010f;
    constexpr float characterGap = 0.055f;
    constexpr float startX = 0.93f;
    constexpr float startY = 0.82f;
    constexpr float z = -1.85f;

    std::vector<ramses::vec3f> positions;
    std::vector<uint16_t> indices;

    float cursorX = startX;
    for (char rawCharacter : profileId)
    {
        const char character = static_cast<char>(std::toupper(static_cast<unsigned char>(rawCharacter)));
        const auto rows = glyphRows(character);

        for (size_t row = 0u; row < rows.size(); ++row)
        {
            for (size_t column = 0u; rows[row][column] != '\0'; ++column)
            {
                if (rows[row][column] != '1')
                    continue;

                const float x0 = cursorX + static_cast<float>(column) * (cellSize + cellGap);
                const float y0 = startY - static_cast<float>(row) * (cellSize + cellGap);
                const float x1 = x0 + cellSize;
                const float y1 = y0 - cellSize;
                const auto baseIndex = static_cast<uint16_t>(positions.size());

                positions.emplace_back(ramses::vec3f{x0, y1, z});
                positions.emplace_back(ramses::vec3f{x1, y1, z});
                positions.emplace_back(ramses::vec3f{x1, y0, z});
                positions.emplace_back(ramses::vec3f{x0, y0, z});

                indices.push_back(baseIndex);
                indices.push_back(static_cast<uint16_t>(baseIndex + 1u));
                indices.push_back(static_cast<uint16_t>(baseIndex + 2u));
                indices.push_back(baseIndex);
                indices.push_back(static_cast<uint16_t>(baseIndex + 2u));
                indices.push_back(static_cast<uint16_t>(baseIndex + 3u));
            }
        }

        cursorX += 5.0f * (cellSize + cellGap) + characterGap;
    }

    if (positions.empty())
        return;

    auto* vertexPositions = scene.createArrayResource(positions.size(), positions.data());
    auto* overlayIndices = scene.createArrayResource(indices.size(), indices.data());
    auto* appearance = scene.createAppearance(effect, "profile id appearance");
    auto* geometry = scene.createGeometry(effect, "profile id geometry");
    geometry->setIndices(*overlayIndices);

    const std::optional<ramses::AttributeInput> positionsInput = effect.findAttributeInput("a_position");
    const std::optional<ramses::UniformInput> colorInput = effect.findUniformInput("color");
    if (!positionsInput || !colorInput)
        throw std::runtime_error("Ramses shader inputs were not reflected for profile overlay");

    geometry->setInputBuffer(*positionsInput, *vertexPositions);
    appearance->setInputValue(*colorInput, ramses::vec4f{0.95f, 0.82f, 0.32f, 1.0f});

    auto* mesh = scene.createMeshNode("sg_preflight profile id overlay");
    mesh->setAppearance(*appearance);
    mesh->setGeometry(*geometry);
    renderGroup.addMeshNode(*mesh);
}

TestScene createTriangleScene(ramses::RamsesClient& client, ramses::sceneId_t sceneId, uint32_t width, uint32_t height, const std::string& profileId)
{
    auto* scene = client.createScene(sceneId, "sgfx c2 sdl hwnd test scene");

    auto* camera = scene->createPerspectiveCamera("camera");
    camera->setViewport(0, 0, width, height);
    camera->setFrustum(25.0f, static_cast<float>(width) / static_cast<float>(height), 0.1f, 100.0f);
    camera->setTranslation({0.0f, 0.0f, 4.0f});

    auto* renderPass = scene->createRenderPass("render pass");
    renderPass->setClearFlags(ramses::EClearFlag::All);
    renderPass->setCamera(*camera);

    auto* renderGroup = scene->createRenderGroup("render group");
    renderPass->addRenderGroup(*renderGroup);

    const std::array<ramses::vec3f, 3u> positions{
        ramses::vec3f{-0.9f, -0.7f, -2.0f},
        ramses::vec3f{0.9f, -0.7f, -2.0f},
        ramses::vec3f{0.0f, 0.9f, -2.0f}
    };
    const std::array<uint16_t, 3u> indices{0u, 1u, 2u};

    auto* vertexPositions = scene->createArrayResource(positions.size(), positions.data());
    auto* triangleIndices = scene->createArrayResource(indices.size(), indices.data());

    ramses::EffectDescription effectDesc;
    effectDesc.setVertexShader(R"glsl(
#version 100
uniform highp mat4 mvpMatrix;
attribute vec3 a_position;
void main()
{
    gl_Position = mvpMatrix * vec4(a_position, 1.0);
}
)glsl");
    effectDesc.setFragmentShader(R"glsl(
#version 100
uniform highp vec4 color;
void main()
{
    gl_FragColor = color;
}
)glsl");
    effectDesc.setUniformSemantic("mvpMatrix", ramses::EEffectUniformSemantic::ModelViewProjectionMatrix);

    auto* effect = scene->createEffect(effectDesc, "flat color effect");
    auto* appearance = scene->createAppearance(*effect, "triangle appearance");
    auto* geometry = scene->createGeometry(*effect, "triangle geometry");
    geometry->setIndices(*triangleIndices);

    const std::optional<ramses::AttributeInput> positionsInput = effect->findAttributeInput("a_position");
    const std::optional<ramses::UniformInput> colorInput = effect->findUniformInput("color");
    if (!positionsInput || !colorInput)
        throw std::runtime_error("Ramses shader inputs were not reflected");

    geometry->setInputBuffer(*positionsInput, *vertexPositions);
    appearance->setInputValue(*colorInput, ramses::vec4f{0.10f, 0.90f, 0.75f, 1.0f});

    auto* mesh = scene->createMeshNode("rotating triangle");
    mesh->setAppearance(*appearance);
    mesh->setGeometry(*geometry);
    renderGroup->addMeshNode(*mesh);

    addProfileIdOverlay(*scene, *renderGroup, *effect, profileId);

    return {scene, mesh};
}

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

void pumpRamsesEvents(ramses::RamsesRenderer& renderer, ramses::RendererSceneControl& sceneControl, EmbedEventHandler& handler)
{
    renderer.dispatchEvents(handler);
    sceneControl.dispatchEvents(handler);
    renderer.flush();
    sceneControl.flush();
}

template <typename Predicate, typename Tick>
bool pumpUntil(ramses::RamsesRenderer& renderer,
               ramses::RendererSceneControl& sceneControl,
               EmbedEventHandler& handler,
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
}

int main(int argc, char** argv)
{
    try
    {
        const Options options = parseOptions(argc, argv);
        const std::string sliceLabel = options.profileId.empty() ? "C-2" : "C-4";
        SdlGuard sdl;
        SdlWindow window("SGFX Cine C-2 Ramses HWND Embed", options.width, options.height);
        void* hwnd = getWin32Hwnd(window.get());

        std::cout << sliceLabel << " SDL3 window created: " << options.width << "x" << options.height << "\n";
        std::cout << sliceLabel << " SDL3 Win32 HWND: " << hwnd << "\n";
        if (!options.profileId.empty())
            std::cout << "C-4 sg_preflight profile id: " << options.profileId << "\n";

        ramses::RamsesFrameworkConfig frameworkConfig{ramses::EFeatureLevel_01};
        frameworkConfig.setRequestedRamsesShellType(ramses::ERamsesShellType::Console);
        frameworkConfig.setPeriodicLogInterval(std::chrono::seconds(1));
        ramses::RamsesFramework framework(frameworkConfig);
        auto& client = *framework.createClient("sgfx-cine-c2-client");

        ramses::RendererConfig rendererConfig;
        rendererConfig.setRenderThreadLoopTimingReportingPeriod(std::chrono::milliseconds(500));
        auto& renderer = *framework.createRenderer(rendererConfig);
        auto& sceneControl = *renderer.getSceneControlAPI();

        framework.connect();

        ramses::DisplayConfig displayConfig;
        displayConfig.setWindowType(ramses::EWindowType::Windows);
        displayConfig.setWindowsWindowHandle(hwnd);
        displayConfig.setWindowRectangle(0, 0, options.width, options.height);
        displayConfig.setWindowTitle("SGFX Cine C-2 Ramses HWND Embed");

        const ramses::displayId_t display = renderer.createDisplay(displayConfig);
        if (!display.isValid())
            throw std::runtime_error("Ramses createDisplay returned an invalid display id");
        renderer.setSkippingOfUnmodifiedBuffers(false);
        renderer.setDisplayBufferClearColor(display, ramses::displayBufferId_t::Invalid(), ramses::vec4f{0.02f, 0.03f, 0.05f, 1.0f});
        renderer.flush();

        const ramses::sceneId_t sceneId{42u};
        EmbedEventHandler handler(display, sceneId, options.width, options.height, options.screenshotPath, sliceLabel);
        if (!pumpUntil(renderer, sceneControl, handler, [&] { return handler.displayCreated(); }, [] {}, std::chrono::seconds(5)))
            throw std::runtime_error("Timed out waiting for Ramses display creation");

        TestScene testScene = createTriangleScene(client, sceneId, options.width, options.height, options.profileId);
        testScene.scene->publish(ramses::EScenePublicationMode::LocalOnly);
        testScene.scene->flush();

        sceneControl.setSceneMapping(sceneId, display);
        sceneControl.setSceneState(sceneId, ramses::RendererSceneState::Rendered);
        sceneControl.flush();

        if (!pumpUntil(renderer, sceneControl, handler, [&] { return handler.sceneRendered(); }, [&] { testScene.scene->flush(); }, std::chrono::seconds(5)))
            throw std::runtime_error("Timed out waiting for Ramses scene to reach Rendered");

        uint32_t renderedFrames = 0u;
        while (renderedFrames < options.frames)
        {
            if (!pumpSdlEvents())
                break;

            const float rotation = static_cast<float>(renderedFrames % 360u);
            testScene.mesh->setRotation({0.0f, 0.0f, rotation}, ramses::ERotationType::Euler_XYZ);
            testScene.scene->flush();

            renderer.doOneLoop();
            pumpRamsesEvents(renderer, sceneControl, handler);
            ++renderedFrames;
        }

        if (options.readback)
        {
            renderer.readPixels(display, renderer.getDisplayFramebuffer(display), 0u, 0u, options.width, options.height);
            renderer.flush();
            if (!pumpUntil(renderer, sceneControl, handler, [&] { return handler.pixelsRead(); }, [&] { testScene.scene->flush(); }, std::chrono::seconds(5)))
                throw std::runtime_error("Timed out waiting for Ramses framebuffer readback");
            if (!handler.pixelsReadOk() || handler.brightPixels() == 0u)
                throw std::runtime_error("Ramses framebuffer readback did not contain visible triangle pixels");
        }

        renderer.logRendererInfo();
        renderer.flush();
        renderer.doOneLoop();
        pumpRamsesEvents(renderer, sceneControl, handler);

        std::cout << sliceLabel << " frames rendered: " << renderedFrames << "\n";
        std::cout << sliceLabel << " SDL/Ramses HWND embed OK\n";
        return 0;
    }
    catch (const std::exception& ex)
    {
        std::cerr << "C-2 SDL/Ramses HWND embed failed: " << ex.what() << "\n";
        return 1;
    }
}
