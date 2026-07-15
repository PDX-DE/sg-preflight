cmake_minimum_required(VERSION 3.24)

project(sgfx_cine
  VERSION 0.1.0
  DESCRIPTION "SGFX cinematic C++ walking skeleton"
  LANGUAGES CXX
)

include(FetchContent)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(SGFX_CINE_RAMSES_VERSION "28.16.0" CACHE STRING "Ramses SDK version required by the C++ viewer")
set(SGFX_CINE_SDL3_VERSION "release-3.4.8" CACHE STRING "SDL3 release tag used when SDL3 is not provided by the toolchain")
set(SGFX_CINE_RMLUI_VERSION "6.2" CACHE STRING "RmlUi release tag used when RmlUi is not provided by the toolchain")
set(SGFX_CINE_FREETYPE_VERSION "VER-2-13-3" CACHE STRING "FreeType release tag used when FreeType is not provided by the toolchain")
option(SGFX_CINE_FETCH_SDL3 "Fetch SDL3 from libsdl-org/SDL when find_package(SDL3) fails" ON)
option(SGFX_CINE_FETCH_RMLUI "Fetch RmlUi from mikke89/RmlUi when find_package(RmlUi) fails" ON)
option(SGFX_CINE_FETCH_FREETYPE "Fetch FreeType from freedesktop when find_package(Freetype) fails" ON)

find_package(ramses-shared-lib ${SGFX_CINE_RAMSES_VERSION} REQUIRED CONFIG)
find_package(SDL3 CONFIG QUIET)
find_package(RmlUi ${SGFX_CINE_RMLUI_VERSION} CONFIG QUIET)
find_package(OpenGL REQUIRED)

FetchContent_Declare(
  nlohmann_json
  URL https://github.com/nlohmann/json/archive/refs/tags/v3.12.0.zip
)
FetchContent_MakeAvailable(nlohmann_json)

if(NOT SDL3_FOUND AND SGFX_CINE_FETCH_SDL3)
  set(SDL_SHARED ON CACHE BOOL "" FORCE)
  set(SDL_STATIC OFF CACHE BOOL "" FORCE)
  set(SDL_TEST_LIBRARY OFF CACHE BOOL "" FORCE)
  set(SDL_TESTS OFF CACHE BOOL "" FORCE)
  set(SDL_EXAMPLES OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(SDL3
    GIT_REPOSITORY https://github.com/libsdl-org/SDL.git
    GIT_TAG ${SGFX_CINE_SDL3_VERSION}
    GIT_SHALLOW TRUE
  )
  FetchContent_MakeAvailable(SDL3)
endif()

set(SGFX_CINE_SDL3_TARGET "")
foreach(_sgfx_cine_sdl3_candidate IN ITEMS SDL3::SDL3 SDL3::SDL3-shared SDL3::SDL3-static)
  if(TARGET ${_sgfx_cine_sdl3_candidate})
    set(SGFX_CINE_SDL3_TARGET ${_sgfx_cine_sdl3_candidate})
    break()
  endif()
endforeach()

if(NOT SGFX_CINE_SDL3_TARGET)
  message(FATAL_ERROR "SDL3 was not found and could not be fetched")
endif()

if(NOT TARGET RmlUi::Core AND SGFX_CINE_FETCH_RMLUI)
  find_package(Freetype QUIET)
  if(NOT TARGET Freetype::Freetype AND SGFX_CINE_FETCH_FREETYPE)
    set(FT_DISABLE_ZLIB ON CACHE BOOL "" FORCE)
    set(FT_DISABLE_BZIP2 ON CACHE BOOL "" FORCE)
    set(FT_DISABLE_PNG ON CACHE BOOL "" FORCE)
    set(FT_DISABLE_HARFBUZZ ON CACHE BOOL "" FORCE)
    set(FT_DISABLE_BROTLI ON CACHE BOOL "" FORCE)
    set(FT_REQUIRE_ZLIB OFF CACHE BOOL "" FORCE)
    set(FT_REQUIRE_BZIP2 OFF CACHE BOOL "" FORCE)
    set(FT_REQUIRE_PNG OFF CACHE BOOL "" FORCE)
    set(FT_REQUIRE_HARFBUZZ OFF CACHE BOOL "" FORCE)
    set(FT_REQUIRE_BROTLI OFF CACHE BOOL "" FORCE)
    FetchContent_Declare(freetype
      GIT_REPOSITORY https://gitlab.freedesktop.org/freetype/freetype.git
      GIT_TAG ${SGFX_CINE_FREETYPE_VERSION}
      GIT_SHALLOW TRUE
    )
    FetchContent_MakeAvailable(freetype)
    if(TARGET freetype AND NOT TARGET Freetype::Freetype)
      add_library(Freetype::Freetype ALIAS freetype)
    endif()
  endif()
  if(NOT TARGET Freetype::Freetype)
    message(FATAL_ERROR "Freetype::Freetype was not found and could not be fetched; required for the cinematic shell RmlUi FreeType font engine")
  endif()
  set(RMLUI_SAMPLES OFF CACHE BOOL "" FORCE)
  set(RMLUI_FONT_ENGINE "freetype" CACHE STRING "" FORCE)
  set(RMLUI_LUA_BINDINGS OFF CACHE BOOL "" FORCE)
  set(RMLUI_LOTTIE_PLUGIN OFF CACHE BOOL "" FORCE)
  set(RMLUI_SVG_PLUGIN OFF CACHE BOOL "" FORCE)
  set(RMLUI_PRECOMPILED_HEADERS OFF CACHE BOOL "" FORCE)
  set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(RmlUi
    GIT_REPOSITORY https://github.com/mikke89/RmlUi.git
    GIT_TAG ${SGFX_CINE_RMLUI_VERSION}
    GIT_SHALLOW TRUE
  )
  FetchContent_MakeAvailable(RmlUi)
endif()

if(NOT TARGET RmlUi::Core)
  message(FATAL_ERROR "RmlUi::Core was not found and could not be fetched")
endif()

set(SGFX_CINE_RMLUI_BACKENDS_DIR "")
foreach(_sgfx_cine_rmlui_source_var IN ITEMS rmlui_SOURCE_DIR RmlUi_SOURCE_DIR)
  if(DEFINED ${_sgfx_cine_rmlui_source_var}
      AND EXISTS "${${_sgfx_cine_rmlui_source_var}}/Backends/RmlUi_Renderer_GL3.cpp")
    set(SGFX_CINE_RMLUI_BACKENDS_DIR "${${_sgfx_cine_rmlui_source_var}}/Backends")
    break()
  endif()
endforeach()

if(NOT SGFX_CINE_RMLUI_BACKENDS_DIR)
  message(FATAL_ERROR "RmlUi GL3 backend sources were not found; SGFX cinematic shell requires RmlUi_Renderer_GL3.cpp")
endif()

add_library(sgfx_cine
  src/ramses_probe.cpp
  src/ramses_preview.cpp
)
add_library(sgfx::cine ALIAS sgfx_cine)

target_include_directories(sgfx_cine
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

target_link_libraries(sgfx_cine
  PUBLIC
    ramses::ramses
  PRIVATE
    nlohmann_json::nlohmann_json
    ${SGFX_CINE_SDL3_TARGET}
)

add_executable(sgfx_cine_ramses_link_probe
  apps/ramses_link_probe.cpp
)

target_link_libraries(sgfx_cine_ramses_link_probe
  PRIVATE
    sgfx::cine
)

set(SGFX_CINE_RAMSES_RUNTIME_DLLS)
foreach(_sgfx_cine_ramses_import_lib IN LISTS ramses-shared-lib_LIBRARIES)
  if(_sgfx_cine_ramses_import_lib MATCHES "\\.lib$")
    get_filename_component(_sgfx_cine_ramses_bin_dir "${_sgfx_cine_ramses_import_lib}" DIRECTORY)
    get_filename_component(_sgfx_cine_ramses_name "${_sgfx_cine_ramses_import_lib}" NAME_WE)
    list(APPEND SGFX_CINE_RAMSES_RUNTIME_DLLS
      "${_sgfx_cine_ramses_bin_dir}/${_sgfx_cine_ramses_name}.dll"
    )
    foreach(_sgfx_cine_ramses_runtime_suffix IN ITEMS "-headless" "-renderer")
      set(_sgfx_cine_ramses_runtime_sibling
        "${_sgfx_cine_ramses_bin_dir}/${_sgfx_cine_ramses_name}${_sgfx_cine_ramses_runtime_suffix}.dll")
      if(EXISTS "${_sgfx_cine_ramses_runtime_sibling}")
        list(APPEND SGFX_CINE_RAMSES_RUNTIME_DLLS "${_sgfx_cine_ramses_runtime_sibling}")
      endif()
    endforeach()
  endif()
endforeach()
list(REMOVE_DUPLICATES SGFX_CINE_RAMSES_RUNTIME_DLLS)

function(sgfx_cine_copy_ramses_runtime_dlls target_name)
  add_custom_command(TARGET ${target_name} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
      ${SGFX_CINE_RAMSES_RUNTIME_DLLS}
      $<TARGET_FILE_DIR:${target_name}>
    COMMAND_EXPAND_LISTS
  )
endfunction()

function(sgfx_cine_copy_sdl_runtime_dll target_name)
  if(WIN32)
    add_custom_command(TARGET ${target_name} POST_BUILD
      COMMAND ${CMAKE_COMMAND} -E copy_if_different
        $<TARGET_FILE:${SGFX_CINE_SDL3_TARGET}>
        $<TARGET_FILE_DIR:${target_name}>
    )
  endif()
endfunction()

sgfx_cine_copy_ramses_runtime_dlls(sgfx_cine_ramses_link_probe)

add_executable(sgfx_cine_ramses_preview_cli
  apps/ramses_preview_cli.cpp
)

target_link_libraries(sgfx_cine_ramses_preview_cli
  PRIVATE
    sgfx::cine
    nlohmann_json::nlohmann_json
)

sgfx_cine_copy_ramses_runtime_dlls(sgfx_cine_ramses_preview_cli)
sgfx_cine_copy_sdl_runtime_dll(sgfx_cine_ramses_preview_cli)

set(SGFX_CINE_PREVIEW_RUNTIME_DIR "${CMAKE_CURRENT_SOURCE_DIR}/bin" CACHE PATH "Local SGFX preview-helper runtime directory")
add_custom_command(TARGET sgfx_cine_ramses_preview_cli POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E make_directory
    ${SGFX_CINE_PREVIEW_RUNTIME_DIR}
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
    $<TARGET_FILE:sgfx_cine_ramses_preview_cli>
    ${SGFX_CINE_PREVIEW_RUNTIME_DIR}
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
    ${SGFX_CINE_RAMSES_RUNTIME_DLLS}
    ${SGFX_CINE_PREVIEW_RUNTIME_DIR}
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
    $<TARGET_FILE:${SGFX_CINE_SDL3_TARGET}>
    ${SGFX_CINE_PREVIEW_RUNTIME_DIR}
  COMMAND_EXPAND_LISTS
)

add_executable(sgfx_cine_sdl_ramses_embed
  apps/ramses_sdl_embed.cpp
)

target_compile_definitions(sgfx_cine_sdl_ramses_embed
  PRIVATE
    SDL_MAIN_HANDLED
)

target_link_libraries(sgfx_cine_sdl_ramses_embed
  PRIVATE
    sgfx::cine
    ${SGFX_CINE_SDL3_TARGET}
)

sgfx_cine_copy_ramses_runtime_dlls(sgfx_cine_sdl_ramses_embed)

if(WIN32)
  add_custom_command(TARGET sgfx_cine_sdl_ramses_embed POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
      $<TARGET_FILE:${SGFX_CINE_SDL3_TARGET}>
      $<TARGET_FILE_DIR:sgfx_cine_sdl_ramses_embed>
  )
endif()

add_executable(sgfx_cine_ramses_real_scene
  apps/ramses_real_scene.cpp
)

target_compile_definitions(sgfx_cine_ramses_real_scene
  PRIVATE
    SDL_MAIN_HANDLED
)

target_link_libraries(sgfx_cine_ramses_real_scene
  PRIVATE
    sgfx::cine
    ${SGFX_CINE_SDL3_TARGET}
)

sgfx_cine_copy_ramses_runtime_dlls(sgfx_cine_ramses_real_scene)

if(WIN32)
  add_custom_command(TARGET sgfx_cine_ramses_real_scene POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
      $<TARGET_FILE:${SGFX_CINE_SDL3_TARGET}>
      $<TARGET_FILE_DIR:sgfx_cine_ramses_real_scene>
  )
endif()

add_executable(sgfx_cine_ramses_shell_fusion_probe
  apps/ramses_shell_fusion_probe.cpp
)

target_compile_definitions(sgfx_cine_ramses_shell_fusion_probe
  PRIVATE
    SDL_MAIN_HANDLED
)

target_link_libraries(sgfx_cine_ramses_shell_fusion_probe
  PRIVATE
    sgfx::cine
    ${SGFX_CINE_SDL3_TARGET}
    OpenGL::GL
)

sgfx_cine_copy_ramses_runtime_dlls(sgfx_cine_ramses_shell_fusion_probe)
sgfx_cine_copy_sdl_runtime_dll(sgfx_cine_ramses_shell_fusion_probe)

add_executable(sgfx_cine_cinematic_shell
  apps/cinematic_shell.cpp
  ${SGFX_CINE_RMLUI_BACKENDS_DIR}/RmlUi_Renderer_GL3.cpp
)

target_compile_definitions(sgfx_cine_cinematic_shell
  PRIVATE
    SDL_MAIN_HANDLED
)

target_link_libraries(sgfx_cine_cinematic_shell
  PRIVATE
    sgfx::cine
    ${SGFX_CINE_SDL3_TARGET}
    RmlUi::Core
    nlohmann_json::nlohmann_json
    OpenGL::GL
)

target_include_directories(sgfx_cine_cinematic_shell
  PRIVATE
    ${SGFX_CINE_RMLUI_BACKENDS_DIR}
)

sgfx_cine_copy_ramses_runtime_dlls(sgfx_cine_cinematic_shell)
sgfx_cine_copy_sdl_runtime_dll(sgfx_cine_cinematic_shell)

add_custom_command(TARGET sgfx_cine_cinematic_shell POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_directory
    ${CMAKE_CURRENT_SOURCE_DIR}/assets
    $<TARGET_FILE_DIR:sgfx_cine_cinematic_shell>/assets
)

enable_testing()
add_test(NAME sgfx_cine_ramses_link_probe COMMAND sgfx_cine_ramses_link_probe)
set_tests_properties(sgfx_cine_ramses_link_probe PROPERTIES
  PASS_REGULAR_EXPRESSION "Ramses linked OK"
)

add_executable(sgfx_cine_ramses_preview_contract_test
  tests/ramses_preview_contract_test.cpp
)

target_link_libraries(sgfx_cine_ramses_preview_contract_test
  PRIVATE
    sgfx::cine
)

sgfx_cine_copy_ramses_runtime_dlls(sgfx_cine_ramses_preview_contract_test)
sgfx_cine_copy_sdl_runtime_dll(sgfx_cine_ramses_preview_contract_test)

add_test(NAME sgfx_cine_ramses_preview_contract COMMAND sgfx_cine_ramses_preview_contract_test)
set_tests_properties(sgfx_cine_ramses_preview_contract PROPERTIES
  PASS_REGULAR_EXPRESSION "Ramses preview contract OK"
)

add_executable(sgfx_cine_ramses_probe_units_test
  tests/ramses_probe_units_test.cpp
)

target_link_libraries(sgfx_cine_ramses_probe_units_test
  PRIVATE
    sgfx::cine
    nlohmann_json::nlohmann_json
)

sgfx_cine_copy_ramses_runtime_dlls(sgfx_cine_ramses_probe_units_test)

add_test(NAME sgfx_cine_ramses_probe_units COMMAND sgfx_cine_ramses_probe_units_test)
set_tests_properties(sgfx_cine_ramses_probe_units PROPERTIES
  PASS_REGULAR_EXPRESSION "Ramses probe units OK"
)

add_executable(sgfx_cine_ramses_probe
  apps/ramses_probe_main.cpp
)

target_link_libraries(sgfx_cine_ramses_probe
  PRIVATE
    sgfx::cine
)

sgfx_cine_copy_ramses_runtime_dlls(sgfx_cine_ramses_probe)

install(TARGETS sgfx_cine sgfx_cine_ramses_link_probe sgfx_cine_ramses_preview_cli sgfx_cine_sdl_ramses_embed sgfx_cine_ramses_real_scene sgfx_cine_ramses_shell_fusion_probe sgfx_cine_cinematic_shell sgfx_cine_ramses_probe)
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY assets/ DESTINATION assets)
