#include "audio_player.hpp"

#include <windows.h>
#include <mmsystem.h>

#include <string>

namespace sg_preflight::native_shell {
namespace {

constexpr const wchar_t* kMusicAlias = L"sg_preflight_native_bgm";

std::wstring QuoteMciPath(const std::filesystem::path& path) {
    return L"\"" + path.wstring() + L"\"";
}

}  // namespace

bool PlayWaveOneShot(const std::filesystem::path& path) {
    if (path.empty()) {
        return false;
    }
    return PlaySoundW(
        path.wstring().c_str(),
        nullptr,
        SND_FILENAME | SND_ASYNC | SND_NODEFAULT
    ) == TRUE;
}

bool StartLoopingWaveMusic(const std::filesystem::path& path, unsigned volume_percent) {
    if (path.empty()) {
        return false;
    }

    StopLoopingWaveMusic();

    const std::wstring open_command = L"open " + QuoteMciPath(path) + L" type waveaudio alias " + std::wstring(kMusicAlias);
    if (mciSendStringW(open_command.c_str(), nullptr, 0, nullptr) != 0) {
        return false;
    }

    const unsigned clamped_volume = volume_percent > 100U ? 100U : volume_percent;
    const unsigned scaled_volume = static_cast<unsigned>((1000U * clamped_volume) / 100U);
    const std::wstring volume_command = L"setaudio " + std::wstring(kMusicAlias) + L" volume to " + std::to_wstring(scaled_volume);
    mciSendStringW(volume_command.c_str(), nullptr, 0, nullptr);

    const std::wstring play_command = L"play " + std::wstring(kMusicAlias) + L" repeat";
    if (mciSendStringW(play_command.c_str(), nullptr, 0, nullptr) != 0) {
        StopLoopingWaveMusic();
        return false;
    }

    return true;
}

void StopLoopingWaveMusic() {
    mciSendStringW((L"stop " + std::wstring(kMusicAlias)).c_str(), nullptr, 0, nullptr);
    mciSendStringW((L"close " + std::wstring(kMusicAlias)).c_str(), nullptr, 0, nullptr);
}

}  // namespace sg_preflight::native_shell
