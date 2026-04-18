#pragma once

#include <filesystem>
#include <string>

namespace sg_preflight::native_shell {

bool PrimeAudio(std::string* error = nullptr);
bool PreloadWave(const std::filesystem::path& path, std::string* error = nullptr);
bool PlayWaveOneShot(const std::filesystem::path& path);
bool StartLoopingWaveMusic(const std::filesystem::path& path, unsigned volume_percent = 22U);
void StopLoopingWaveMusic();
std::string GetAudioLastError();
void ShutdownAudio();

}  // namespace sg_preflight::native_shell
