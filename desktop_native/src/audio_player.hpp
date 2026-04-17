#pragma once

#include <filesystem>

namespace sg_preflight::native_shell {

bool PlayWaveOneShot(const std::filesystem::path& path);
bool StartLoopingWaveMusic(const std::filesystem::path& path, unsigned volume_percent = 22U);
void StopLoopingWaveMusic();

}  // namespace sg_preflight::native_shell
