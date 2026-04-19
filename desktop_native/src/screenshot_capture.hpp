#pragma once

#include <d3d12.h>
#include <dxgiformat.h>
#include <windows.h>

#include <filesystem>
#include <string>

namespace sg_preflight::native_shell {

struct D3d12PngCaptureContext {
    ID3D12Device* device = nullptr;
    ID3D12CommandQueue* command_queue = nullptr;
    ID3D12Fence* fence = nullptr;
    HANDLE fence_event = nullptr;
    UINT64* next_fence_value = nullptr;
};

bool CapturePresentedBackBufferToPng(
    const D3d12PngCaptureContext& context,
    ID3D12Resource* source,
    DXGI_FORMAT format,
    const std::filesystem::path& output_path,
    std::string* error = nullptr
);

}  // namespace sg_preflight::native_shell
