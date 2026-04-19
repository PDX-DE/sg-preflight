cmake_minimum_required(VERSION 3.24)

project(sg_preflight_native_shell LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)

set(SG_NATIVE_SHELL_VERSION "1.0.0")

FetchContent_Declare(
  imgui
  URL https://github.com/ocornut/imgui/archive/refs/tags/v1.92.7-docking.zip
)

FetchContent_Declare(
  nlohmann_json
  URL https://github.com/nlohmann/json/archive/refs/tags/v3.12.0.zip
)

FetchContent_MakeAvailable(imgui nlohmann_json)

add_library(
  sg_preflight_imgui STATIC
  ${imgui_SOURCE_DIR}/imgui.cpp
  ${imgui_SOURCE_DIR}/imgui_demo.cpp
  ${imgui_SOURCE_DIR}/imgui_draw.cpp
  ${imgui_SOURCE_DIR}/imgui_tables.cpp
  ${imgui_SOURCE_DIR}/imgui_widgets.cpp
  ${imgui_SOURCE_DIR}/backends/imgui_impl_dx12.cpp
  ${imgui_SOURCE_DIR}/backends/imgui_impl_win32.cpp
)

target_include_directories(
  sg_preflight_imgui
  PUBLIC
    ${imgui_SOURCE_DIR}
    ${imgui_SOURCE_DIR}/backends
)

target_compile_definitions(
  sg_preflight_imgui
  PUBLIC
    UNICODE
    _UNICODE
    WIN32_LEAN_AND_MEAN
    NOMINMAX
    IMGUI_IMPL_DX12_CPP
)

target_link_libraries(
  sg_preflight_imgui
  PUBLIC
    d3d12
    dxgi
    dwmapi
    gdi32
    user32
    shell32
)

add_executable(
  sg_preflight_native_shell WIN32
  src/audio_player.cpp
  src/backend_bridge.cpp
  src/localization.cpp
  src/main.cpp
  src/native_shell.rc
  src/screenshot_capture.cpp
  src/texture_loader.cpp
)

target_include_directories(
  sg_preflight_native_shell
  PRIVATE
    src
)

target_compile_definitions(
  sg_preflight_native_shell
  PRIVATE
    SG_NATIVE_SHELL_VERSION="${SG_NATIVE_SHELL_VERSION}"
)

target_link_libraries(
  sg_preflight_native_shell
  PRIVATE
    sg_preflight_imgui
    nlohmann_json::nlohmann_json
    ole32
    windowscodecs
    xaudio2
    winmm
)

if(MSVC)
  target_compile_options(
    sg_preflight_native_shell
    PRIVATE
      /W4
      /permissive-
  )
  target_compile_options(
    sg_preflight_imgui
    PRIVATE
      /W3
      /permissive-
  )
endif()
