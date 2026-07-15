#pragma once

#include <ramses/framework/RamsesFrameworkTypes.h>
#include <ramses/renderer/IRendererEventHandler.h>
#include <ramses/renderer/IRendererSceneControlEventHandler.h>
#include <ramses/renderer/RamsesRenderer.h>
#include <ramses/renderer/RendererSceneControl.h>

#include <SDL3/SDL.h>

#include <cstdint>
#include <vector>

namespace sgfx::cine::render_support
{
class SdlGuard
{
public:
    SdlGuard() { m_initialized = SDL_Init(SDL_INIT_VIDEO); }

    ~SdlGuard()
    {
        if (m_initialized)
            SDL_Quit();
    }

    SdlGuard(const SdlGuard&) = delete;
    SdlGuard& operator=(const SdlGuard&) = delete;

    bool initialized() const { return m_initialized; }

private:
    bool m_initialized = false;
};

class HiddenWindow
{
public:
    HiddenWindow(std::uint32_t width, std::uint32_t height)
    {
        m_window = SDL_CreateWindow(
            "SGFX Ramses Offscreen",
            static_cast<int>(width),
            static_cast<int>(height),
            SDL_WINDOW_HIDDEN);
    }

    ~HiddenWindow()
    {
        if (m_window)
            SDL_DestroyWindow(m_window);
    }

    HiddenWindow(const HiddenWindow&) = delete;
    HiddenWindow& operator=(const HiddenWindow&) = delete;

    bool valid() const { return m_window != nullptr; }

    void* nativeHandle() const
    {
#if defined(_WIN32)
        if (!m_window)
            return nullptr;
        const SDL_PropertiesID properties = SDL_GetWindowProperties(m_window);
        return SDL_GetPointerProperty(properties, SDL_PROP_WINDOW_WIN32_HWND_POINTER, nullptr);
#else
        return nullptr;
#endif
    }

private:
    SDL_Window* m_window = nullptr;
};

class RenderEventHandler final : public ramses::RendererEventHandlerEmpty,
                                 public ramses::RendererSceneControlEventHandlerEmpty
{
public:
    RenderEventHandler(ramses::displayId_t display, ramses::sceneId_t scene, std::uint32_t width,
                       std::uint32_t height)
        : m_display(display)
        , m_scene(scene)
        , m_width(width)
        , m_height(height)
    {
    }

    void displayCreated(ramses::displayId_t display, ramses::ERendererEventResult result) override
    {
        if (display != m_display)
            return;
        m_displayCreated = result == ramses::ERendererEventResult::Ok;
        m_failed = result == ramses::ERendererEventResult::Failed;
    }

    void offscreenBufferCreated(
        ramses::displayId_t display,
        ramses::displayBufferId_t buffer,
        ramses::ERendererEventResult result) override
    {
        if (display != m_display || buffer != m_buffer)
            return;
        m_bufferCreated = result == ramses::ERendererEventResult::Ok;
        m_failed = result == ramses::ERendererEventResult::Failed;
    }

    void sceneStateChanged(ramses::sceneId_t scene, ramses::RendererSceneState state) override
    {
        if (scene == m_scene)
            m_sceneState = state;
    }

    void framebufferPixelsRead(
        const std::uint8_t* data,
        const std::uint32_t size,
        ramses::displayId_t display,
        ramses::displayBufferId_t buffer,
        ramses::ERendererEventResult result) override
    {
        if (display != m_display || buffer != m_buffer)
            return;
        m_pixelsReceived = true;
        const auto expected = static_cast<std::uint64_t>(m_width) * m_height * 4u;
        if (result != ramses::ERendererEventResult::Ok || !data || size != expected)
        {
            m_failed = true;
            return;
        }
        m_pixels.assign(data, data + size);
    }

    void setBuffer(ramses::displayBufferId_t buffer) { m_buffer = buffer; }

    void resetPixels()
    {
        m_pixelsReceived = false;
        m_pixels.clear();
    }

    bool displayReady() const { return m_displayCreated; }
    bool bufferReady() const { return m_bufferCreated; }
    bool failed() const { return m_failed; }
    bool sceneAvailable() const { return m_sceneState == ramses::RendererSceneState::Available; }
    bool sceneReady() const { return m_sceneState == ramses::RendererSceneState::Ready; }
    bool sceneRendered() const { return m_sceneState == ramses::RendererSceneState::Rendered; }
    bool pixelsReceived() const { return m_pixelsReceived; }
    const std::vector<std::uint8_t>& pixels() const { return m_pixels; }

private:
    ramses::displayId_t m_display;
    ramses::sceneId_t m_scene;
    ramses::displayBufferId_t m_buffer = ramses::displayBufferId_t::Invalid();
    std::uint32_t m_width;
    std::uint32_t m_height;
    bool m_displayCreated = false;
    bool m_bufferCreated = false;
    bool m_failed = false;
    bool m_pixelsReceived = false;
    ramses::RendererSceneState m_sceneState = ramses::RendererSceneState::Unavailable;
    std::vector<std::uint8_t> m_pixels;
};

inline void pumpPlatformEvents()
{
    SDL_Event event;
    while (SDL_PollEvent(&event))
    {
    }
}

inline void pumpRamses(
    ramses::RamsesRenderer& renderer,
    ramses::RendererSceneControl& sceneControl,
    RenderEventHandler& handler)
{
    pumpPlatformEvents();
    renderer.doOneLoop();
    renderer.dispatchEvents(handler);
    sceneControl.dispatchEvents(handler);
    renderer.flush();
    sceneControl.flush();
}
}
