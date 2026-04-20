#include "audio_player.hpp"

#include <windows.h>
#include <mmsystem.h>
#include <mmreg.h>
#include <objbase.h>
#include <xaudio2.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace sg_preflight::native_shell {
namespace {

struct LoadedWave {
    std::vector<std::uint8_t> format_storage;
    std::vector<float> audio_samples;
    WAVEFORMATEX* format = nullptr;
};

struct OneShotVoice {
    IXAudio2SourceVoice* voice = nullptr;
    std::shared_ptr<LoadedWave> wave;
};

struct AudioEngine {
    std::mutex mutex;
    IXAudio2* xaudio = nullptr;
    IXAudio2MasteringVoice* mastering_voice = nullptr;
    IXAudio2SourceVoice* music_voice = nullptr;
    bool mci_music_open = false;
    std::wstring mci_music_alias = L"sergfx_shell_music";
    std::shared_ptr<LoadedWave> music_wave;
    std::unordered_map<std::wstring, std::shared_ptr<LoadedWave>> wave_cache;
    std::vector<OneShotVoice> one_shots;
    std::string last_error;
    bool init_attempted = false;
    bool initialized = false;
    bool com_initialized = false;
};

AudioEngine g_audio;

constexpr std::uint32_t MakeFourCc(char a, char b, char c, char d) {
    return static_cast<std::uint32_t>(static_cast<unsigned char>(a))
        | (static_cast<std::uint32_t>(static_cast<unsigned char>(b)) << 8U)
        | (static_cast<std::uint32_t>(static_cast<unsigned char>(c)) << 16U)
        | (static_cast<std::uint32_t>(static_cast<unsigned char>(d)) << 24U);
}

std::uint32_t ReadU32(const std::vector<std::uint8_t>& bytes, size_t offset) {
    std::uint32_t value = 0;
    std::memcpy(&value, bytes.data() + offset, sizeof(value));
    return value;
}

std::string FormatPath(const std::filesystem::path& path) {
    return path.string();
}

std::string FormatHr(const char* context, HRESULT hr) {
    std::ostringstream stream;
    stream << context << " failed (0x" << std::hex << std::uppercase << static_cast<unsigned long>(hr) << ").";
    return stream.str();
}

std::string NarrowUtf8(const std::wstring& text) {
    if (text.empty()) {
        return {};
    }

    const int required_bytes = WideCharToMultiByte(
        CP_UTF8,
        0,
        text.c_str(),
        static_cast<int>(text.size()),
        nullptr,
        0,
        nullptr,
        nullptr
    );
    if (required_bytes <= 0) {
        return {};
    }

    std::string result(static_cast<size_t>(required_bytes), '\0');
    WideCharToMultiByte(
        CP_UTF8,
        0,
        text.c_str(),
        static_cast<int>(text.size()),
        result.data(),
        required_bytes,
        nullptr,
        nullptr
    );
    return result;
}

std::wstring EscapeMciPath(const std::wstring& path) {
    std::wstring escaped;
    escaped.reserve(path.size());
    for (const wchar_t character : path) {
        if (character == L'"') {
            escaped.push_back(L'"');
        }
        escaped.push_back(character);
    }
    return escaped;
}

std::string FormatMciError(const wchar_t* context, MCIERROR error_code) {
    wchar_t error_text[256] = {};
    if (!mciGetErrorStringW(error_code, error_text, static_cast<UINT>(std::size(error_text)))) {
        swprintf_s(error_text, L"MCI error %u", static_cast<unsigned>(error_code));
    }

    std::wstring message(context);
    message.append(L" failed: ");
    message.append(error_text);
    return NarrowUtf8(message);
}

float ClampSample(float value) {
    return std::clamp(value, -1.0f, 1.0f);
}

bool ReadWaveSampleAsFloat(
    const std::uint8_t* sample_bytes,
    std::uint16_t format_tag,
    std::uint16_t bits_per_sample,
    float& out_sample
) {
    switch (format_tag) {
    case WAVE_FORMAT_PCM:
        switch (bits_per_sample) {
        case 8:
            out_sample = (static_cast<float>(sample_bytes[0]) - 128.0f) / 128.0f;
            return true;
        case 16: {
            std::int16_t sample = 0;
            std::memcpy(&sample, sample_bytes, sizeof(sample));
            out_sample = static_cast<float>(sample) / 32768.0f;
            return true;
        }
        case 24: {
            std::int32_t sample = static_cast<std::int32_t>(sample_bytes[0])
                | (static_cast<std::int32_t>(sample_bytes[1]) << 8)
                | (static_cast<std::int32_t>(sample_bytes[2]) << 16);
            if ((sample & 0x00800000) != 0) {
                sample |= ~0x00FFFFFF;
            }
            out_sample = static_cast<float>(sample) / 8388608.0f;
            return true;
        }
        case 32: {
            std::int32_t sample = 0;
            std::memcpy(&sample, sample_bytes, sizeof(sample));
            out_sample = static_cast<float>(sample) / 2147483648.0f;
            return true;
        }
        default:
            return false;
        }
    case WAVE_FORMAT_IEEE_FLOAT:
        switch (bits_per_sample) {
        case 32:
            std::memcpy(&out_sample, sample_bytes, sizeof(float));
            out_sample = ClampSample(out_sample);
            return true;
        case 64: {
            double sample = 0.0;
            std::memcpy(&sample, sample_bytes, sizeof(double));
            out_sample = ClampSample(static_cast<float>(sample));
            return true;
        }
        default:
            return false;
        }
    default:
        return false;
    }
}

std::pair<float, float> DownmixFrameToStereo(const std::vector<float>& channels) {
    if (channels.empty()) {
        return {0.0f, 0.0f};
    }
    if (channels.size() == 1U) {
        return {channels[0], channels[0]};
    }
    if (channels.size() == 2U) {
        return {channels[0], channels[1]};
    }
    if (channels.size() >= 6U) {
        float left = channels[0] + channels[2] * 0.75f + channels[4];
        float right = channels[1] + channels[2] * 0.75f + channels[5];
        for (size_t index = 6U; index < channels.size(); ++index) {
            left += channels[index] * 0.25f;
            right += channels[index] * 0.25f;
        }
        return {ClampSample(left), ClampSample(right)};
    }

    float left = channels[0];
    float right = channels[1];
    for (size_t index = 2U; index < channels.size(); ++index) {
        left += channels[index] * 0.25f;
        right += channels[index] * 0.25f;
    }
    return {ClampSample(left), ClampSample(right)};
}

void SetLastErrorLocked(const std::string& error) {
    g_audio.last_error = error;
}

void ClearLastErrorLocked() {
    g_audio.last_error.clear();
}

bool EnsureAudioEngineLocked(std::string* error) {
    if (g_audio.initialized) {
        if (error != nullptr) {
            error->clear();
        }
        return true;
    }

    if (g_audio.init_attempted) {
        if (error != nullptr) {
            *error = g_audio.last_error;
        }
        return false;
    }

    g_audio.init_attempted = true;

    const HRESULT coinit_result = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (SUCCEEDED(coinit_result)) {
        g_audio.com_initialized = true;
    } else if (coinit_result != RPC_E_CHANGED_MODE) {
        SetLastErrorLocked(FormatHr("CoInitializeEx", coinit_result));
        if (error != nullptr) {
            *error = g_audio.last_error;
        }
        return false;
    }

    HRESULT hr = XAudio2Create(&g_audio.xaudio, 0U, XAUDIO2_DEFAULT_PROCESSOR);
    if (FAILED(hr) || g_audio.xaudio == nullptr) {
        SetLastErrorLocked(FormatHr("XAudio2Create", hr));
        if (error != nullptr) {
            *error = g_audio.last_error;
        }
        return false;
    }

    hr = g_audio.xaudio->CreateMasteringVoice(&g_audio.mastering_voice);
    if (FAILED(hr) || g_audio.mastering_voice == nullptr) {
        SetLastErrorLocked(FormatHr("CreateMasteringVoice", hr));
        g_audio.xaudio->Release();
        g_audio.xaudio = nullptr;
        if (error != nullptr) {
            *error = g_audio.last_error;
        }
        return false;
    }

    hr = g_audio.xaudio->StartEngine();
    if (FAILED(hr)) {
        SetLastErrorLocked(FormatHr("IXAudio2::StartEngine", hr));
        g_audio.mastering_voice->DestroyVoice();
        g_audio.mastering_voice = nullptr;
        g_audio.xaudio->Release();
        g_audio.xaudio = nullptr;
        if (error != nullptr) {
            *error = g_audio.last_error;
        }
        return false;
    }

    g_audio.initialized = true;
    ClearLastErrorLocked();
    if (error != nullptr) {
        error->clear();
    }
    return true;
}

void DestroyMusicVoiceLocked() {
    if (g_audio.music_voice != nullptr) {
        g_audio.music_voice->Stop(0U);
        g_audio.music_voice->FlushSourceBuffers();
        g_audio.music_voice->DestroyVoice();
        g_audio.music_voice = nullptr;
    }
    g_audio.music_wave.reset();
}

void StopMciMusicLocked() {
    if (!g_audio.mci_music_open) {
        return;
    }

    const std::wstring stop_command = L"stop " + g_audio.mci_music_alias;
    mciSendStringW(stop_command.c_str(), nullptr, 0U, nullptr);

    const std::wstring close_command = L"close " + g_audio.mci_music_alias;
    mciSendStringW(close_command.c_str(), nullptr, 0U, nullptr);

    g_audio.mci_music_open = false;
}

bool StartLoopingMciMusicLocked(const std::filesystem::path& path, unsigned volume_percent, std::string* error) {
    StopMciMusicLocked();

    const std::wstring open_command =
        L"open \"" + EscapeMciPath(path.wstring()) + L"\" type mpegvideo alias " + g_audio.mci_music_alias;
    MCIERROR mci_error = mciSendStringW(open_command.c_str(), nullptr, 0U, nullptr);
    if (mci_error != 0U) {
        const std::string message = FormatMciError(L"mci open", mci_error);
        SetLastErrorLocked(message);
        if (error != nullptr) {
            *error = message;
        }
        return false;
    }

    g_audio.mci_music_open = true;

    wchar_t volume_command[128] = {};
    swprintf_s(
        volume_command,
        L"setaudio %ls volume to %u",
        g_audio.mci_music_alias.c_str(),
        static_cast<unsigned>(std::clamp(volume_percent, 0U, 100U) * 10U)
    );
    mciSendStringW(volume_command, nullptr, 0U, nullptr);

    const std::wstring play_command = L"play " + g_audio.mci_music_alias + L" repeat";
    mci_error = mciSendStringW(play_command.c_str(), nullptr, 0U, nullptr);
    if (mci_error != 0U) {
        const std::string message = FormatMciError(L"mci play", mci_error);
        StopMciMusicLocked();
        SetLastErrorLocked(message);
        if (error != nullptr) {
            *error = message;
        }
        return false;
    }

    ClearLastErrorLocked();
    if (error != nullptr) {
        error->clear();
    }
    return true;
}

void CleanupStoppedOneShotsLocked() {
    auto it = g_audio.one_shots.begin();
    while (it != g_audio.one_shots.end()) {
        bool destroy = true;
        if (it->voice != nullptr) {
            XAUDIO2_VOICE_STATE state{};
            it->voice->GetState(&state);
            destroy = state.BuffersQueued == 0U;
        }

        if (destroy) {
            if (it->voice != nullptr) {
                it->voice->Stop(0U);
                it->voice->DestroyVoice();
                it->voice = nullptr;
            }
            it = g_audio.one_shots.erase(it);
        } else {
            ++it;
        }
    }
}

bool LoadWaveFile(const std::filesystem::path& path, std::shared_ptr<LoadedWave>& out_wave, std::string* error) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        if (error != nullptr) {
            *error = "Could not open audio file: " + FormatPath(path);
        }
        return false;
    }

    stream.seekg(0, std::ios::end);
    const std::streamoff length = stream.tellg();
    stream.seekg(0, std::ios::beg);
    if (length <= 0) {
        if (error != nullptr) {
            *error = "Audio file is empty: " + FormatPath(path);
        }
        return false;
    }

    std::vector<std::uint8_t> bytes(static_cast<size_t>(length));
    if (!stream.read(reinterpret_cast<char*>(bytes.data()), length)) {
        if (error != nullptr) {
            *error = "Could not read audio file: " + FormatPath(path);
        }
        return false;
    }

    if (bytes.size() < 12U) {
        if (error != nullptr) {
            *error = "Audio file is too small to be a RIFF/WAVE file: " + FormatPath(path);
        }
        return false;
    }

    if (ReadU32(bytes, 0U) != MakeFourCc('R', 'I', 'F', 'F') || ReadU32(bytes, 8U) != MakeFourCc('W', 'A', 'V', 'E')) {
        if (error != nullptr) {
            *error = "Audio file is not a RIFF/WAVE file: " + FormatPath(path);
        }
        return false;
    }

    size_t fmt_offset = 0U;
    size_t fmt_size = 0U;
    size_t data_offset = 0U;
    size_t data_size = 0U;

    for (size_t cursor = 12U; cursor + 8U <= bytes.size();) {
        const std::uint32_t chunk_id = ReadU32(bytes, cursor);
        const std::uint32_t chunk_size = ReadU32(bytes, cursor + 4U);
        const size_t chunk_data_offset = cursor + 8U;
        if (chunk_data_offset + chunk_size > bytes.size()) {
            break;
        }

        if (chunk_id == MakeFourCc('f', 'm', 't', ' ')) {
            fmt_offset = chunk_data_offset;
            fmt_size = chunk_size;
        } else if (chunk_id == MakeFourCc('d', 'a', 't', 'a')) {
            data_offset = chunk_data_offset;
            data_size = chunk_size;
        }

        cursor = chunk_data_offset + chunk_size;
        if ((chunk_size & 1U) != 0U) {
            ++cursor;
        }
    }

    if (fmt_offset == 0U || fmt_size < 16U) {
        if (error != nullptr) {
            *error = "Audio file is missing a valid fmt chunk: " + FormatPath(path);
        }
        return false;
    }
    if (data_offset == 0U || data_size == 0U) {
        if (error != nullptr) {
            *error = "Audio file is missing a data chunk: " + FormatPath(path);
        }
        return false;
    }

    const std::uint16_t source_format_tag = ReadU32(bytes, fmt_offset) & 0xFFFFU;
    const std::uint16_t source_channels = static_cast<std::uint16_t>(ReadU32(bytes, fmt_offset) >> 16U);
    const std::uint32_t source_rate = ReadU32(bytes, fmt_offset + 4U);
    const std::uint16_t source_block_align = static_cast<std::uint16_t>(ReadU32(bytes, fmt_offset + 12U) & 0xFFFFU);
    const std::uint16_t source_bits_per_sample = static_cast<std::uint16_t>(ReadU32(bytes, fmt_offset + 12U) >> 16U);

    if ((source_format_tag != WAVE_FORMAT_PCM && source_format_tag != WAVE_FORMAT_IEEE_FLOAT) || source_channels == 0U || source_rate == 0U || source_block_align == 0U) {
        if (error != nullptr) {
            *error = "Audio file uses an unsupported WAV format for shell playback: " + FormatPath(path);
        }
        return false;
    }
    if ((data_size % source_block_align) != 0U) {
        if (error != nullptr) {
            *error = "Audio file has a truncated data chunk: " + FormatPath(path);
        }
        return false;
    }

    const size_t frame_count = data_size / source_block_align;
    const size_t bytes_per_sample = source_block_align / source_channels;
    if (bytes_per_sample == 0U) {
        if (error != nullptr) {
            *error = "Audio file has an invalid block alignment: " + FormatPath(path);
        }
        return false;
    }

    auto wave = std::make_shared<LoadedWave>();
    wave->audio_samples.reserve(frame_count * 2U);
    std::vector<float> source_frame(static_cast<size_t>(source_channels));

    const std::uint8_t* audio_data = bytes.data() + data_offset;
    for (size_t frame_index = 0U; frame_index < frame_count; ++frame_index) {
        const std::uint8_t* frame_bytes = audio_data + frame_index * source_block_align;
        for (size_t channel_index = 0U; channel_index < source_frame.size(); ++channel_index) {
            float sample = 0.0f;
            if (!ReadWaveSampleAsFloat(
                    frame_bytes + channel_index * bytes_per_sample,
                    source_format_tag,
                    source_bits_per_sample,
                    sample
                )) {
                if (error != nullptr) {
                    *error = "Audio file uses unsupported sample packing for shell playback: " + FormatPath(path);
                }
                return false;
            }
            source_frame[channel_index] = sample;
        }

        const auto [left, right] = DownmixFrameToStereo(source_frame);
        wave->audio_samples.push_back(left);
        wave->audio_samples.push_back(right);
    }

    wave->format_storage.resize(sizeof(WAVEFORMATEX), 0U);
    wave->format = reinterpret_cast<WAVEFORMATEX*>(wave->format_storage.data());
    wave->format->wFormatTag = WAVE_FORMAT_IEEE_FLOAT;
    wave->format->nChannels = 2;
    wave->format->nSamplesPerSec = source_rate;
    wave->format->wBitsPerSample = 32;
    wave->format->nBlockAlign = static_cast<WORD>(wave->format->nChannels * (wave->format->wBitsPerSample / 8U));
    wave->format->nAvgBytesPerSec = wave->format->nSamplesPerSec * wave->format->nBlockAlign;
    wave->format->cbSize = 0;
    out_wave = std::move(wave);
    if (error != nullptr) {
        error->clear();
    }
    return true;
}

std::shared_ptr<LoadedWave> GetOrLoadWaveLocked(const std::filesystem::path& path, std::string* error) {
    const std::wstring key = path.lexically_normal().wstring();
    if (const auto existing = g_audio.wave_cache.find(key); existing != g_audio.wave_cache.end()) {
        if (error != nullptr) {
            error->clear();
        }
        return existing->second;
    }

    std::shared_ptr<LoadedWave> wave;
    if (!LoadWaveFile(path, wave, error)) {
        if (error != nullptr && !error->empty()) {
            SetLastErrorLocked(*error);
        }
        return nullptr;
    }

    g_audio.wave_cache.emplace(key, wave);
    ClearLastErrorLocked();
    if (error != nullptr) {
        error->clear();
    }
    return wave;
}

bool SubmitBufferLocked(IXAudio2SourceVoice* voice, const std::shared_ptr<LoadedWave>& wave, bool loop, std::string* error) {
    XAUDIO2_BUFFER buffer{};
    buffer.AudioBytes = static_cast<UINT32>(wave->audio_samples.size() * sizeof(float));
    buffer.pAudioData = reinterpret_cast<const BYTE*>(wave->audio_samples.data());
    buffer.Flags = XAUDIO2_END_OF_STREAM;
    buffer.LoopCount = loop ? XAUDIO2_LOOP_INFINITE : 0U;

    const HRESULT hr = voice->SubmitSourceBuffer(&buffer);
    if (FAILED(hr)) {
        const std::string message = FormatHr("SubmitSourceBuffer", hr);
        SetLastErrorLocked(message);
        if (error != nullptr) {
            *error = message;
        }
        return false;
    }

    if (error != nullptr) {
        error->clear();
    }
    return true;
}

}  // namespace

bool PrimeAudio(std::string* error) {
    std::lock_guard<std::mutex> lock(g_audio.mutex);
    return EnsureAudioEngineLocked(error);
}

bool PreloadWave(const std::filesystem::path& path, std::string* error) {
    if (path.empty()) {
        if (error != nullptr) {
            *error = "Audio path is empty.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_audio.mutex);
    if (!EnsureAudioEngineLocked(error)) {
        return false;
    }
    return static_cast<bool>(GetOrLoadWaveLocked(path, error));
}

bool PlayWaveOneShot(const std::filesystem::path& path) {
    if (path.empty()) {
        return false;
    }

    std::lock_guard<std::mutex> lock(g_audio.mutex);
    std::string error;
    if (!EnsureAudioEngineLocked(&error)) {
        return false;
    }

    CleanupStoppedOneShotsLocked();

    const std::shared_ptr<LoadedWave> wave = GetOrLoadWaveLocked(path, &error);
    if (!wave) {
        return false;
    }

    IXAudio2SourceVoice* voice = nullptr;
    HRESULT hr = g_audio.xaudio->CreateSourceVoice(&voice, wave->format);
    if (FAILED(hr) || voice == nullptr) {
        SetLastErrorLocked(FormatHr("CreateSourceVoice", hr));
        return false;
    }

    if (!SubmitBufferLocked(voice, wave, false, &error)) {
        voice->DestroyVoice();
        return false;
    }

    hr = voice->Start(0U);
    if (FAILED(hr)) {
        SetLastErrorLocked(FormatHr("IXAudio2SourceVoice::Start", hr));
        voice->DestroyVoice();
        return false;
    }

    g_audio.one_shots.push_back({voice, wave});
    ClearLastErrorLocked();
    return true;
}

bool StartLoopingWaveMusic(const std::filesystem::path& path, unsigned volume_percent) {
    if (path.empty()) {
        return false;
    }

    std::lock_guard<std::mutex> lock(g_audio.mutex);
    std::string error;
    if (!EnsureAudioEngineLocked(&error)) {
        return false;
    }

    CleanupStoppedOneShotsLocked();
    DestroyMusicVoiceLocked();
    StopMciMusicLocked();

    const std::wstring extension = path.extension().wstring();
    if (_wcsicmp(extension.c_str(), L".mp3") == 0) {
        return StartLoopingMciMusicLocked(path, volume_percent, &error);
    }

    const std::shared_ptr<LoadedWave> wave = GetOrLoadWaveLocked(path, &error);
    if (!wave) {
        return false;
    }

    HRESULT hr = g_audio.xaudio->CreateSourceVoice(&g_audio.music_voice, wave->format);
    if (FAILED(hr) || g_audio.music_voice == nullptr) {
        SetLastErrorLocked(FormatHr("CreateSourceVoice", hr));
        g_audio.music_voice = nullptr;
        return false;
    }

    if (!SubmitBufferLocked(g_audio.music_voice, wave, true, &error)) {
        DestroyMusicVoiceLocked();
        return false;
    }

    const float volume = std::clamp(static_cast<float>(volume_percent), 0.0f, 100.0f) / 100.0f;
    g_audio.music_voice->SetVolume(volume);

    hr = g_audio.music_voice->Start(0U);
    if (FAILED(hr)) {
        SetLastErrorLocked(FormatHr("IXAudio2SourceVoice::Start", hr));
        DestroyMusicVoiceLocked();
        return false;
    }

    g_audio.music_wave = wave;
    ClearLastErrorLocked();
    return true;
}

void SetLoopingMusicVolume(float volume) {
    std::lock_guard<std::mutex> lock(g_audio.mutex);

    const float clamped_volume = std::clamp(volume, 0.0f, 1.0f);
    if (g_audio.music_voice != nullptr) {
        g_audio.music_voice->SetVolume(clamped_volume);
    }

    if (g_audio.mci_music_open) {
        wchar_t volume_command[128] = {};
        swprintf_s(
            volume_command,
            L"setaudio %ls volume to %u",
            g_audio.mci_music_alias.c_str(),
            static_cast<unsigned>(clamped_volume * 1000.0f)
        );
        mciSendStringW(volume_command, nullptr, 0U, nullptr);
    }
}

void StopLoopingWaveMusic() {
    std::lock_guard<std::mutex> lock(g_audio.mutex);
    DestroyMusicVoiceLocked();
    StopMciMusicLocked();
    CleanupStoppedOneShotsLocked();
}

std::string GetAudioLastError() {
    std::lock_guard<std::mutex> lock(g_audio.mutex);
    return g_audio.last_error;
}

void ShutdownAudio() {
    std::lock_guard<std::mutex> lock(g_audio.mutex);

    DestroyMusicVoiceLocked();
    StopMciMusicLocked();
    for (OneShotVoice& one_shot : g_audio.one_shots) {
        if (one_shot.voice != nullptr) {
            one_shot.voice->Stop(0U);
            one_shot.voice->DestroyVoice();
            one_shot.voice = nullptr;
        }
    }
    g_audio.one_shots.clear();
    g_audio.wave_cache.clear();

    if (g_audio.mastering_voice != nullptr) {
        g_audio.mastering_voice->DestroyVoice();
        g_audio.mastering_voice = nullptr;
    }
    if (g_audio.xaudio != nullptr) {
        g_audio.xaudio->StopEngine();
        g_audio.xaudio->Release();
        g_audio.xaudio = nullptr;
    }
    if (g_audio.com_initialized) {
        CoUninitialize();
    }

    g_audio.music_wave.reset();
    g_audio.last_error.clear();
    g_audio.init_attempted = false;
    g_audio.initialized = false;
    g_audio.com_initialized = false;
}

}  // namespace sg_preflight::native_shell
