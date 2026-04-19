#pragma once

#include <d3d12.h>
#include <dxgiformat.h>
#include <windows.h>

#include <filesystem>
#include <string>

namespace sg_preflight::native_shell {

struct D3d12DescriptorAllocator {
    void* user_data = nullptr;
    void (*alloc)(void* user_data, D3D12_CPU_DESCRIPTOR_HANDLE* out_cpu_desc_handle, D3D12_GPU_DESCRIPTOR_HANDLE* out_gpu_desc_handle) = nullptr;
    void (*free)(void* user_data, D3D12_CPU_DESCRIPTOR_HANDLE cpu_desc_handle, D3D12_GPU_DESCRIPTOR_HANDLE gpu_desc_handle) = nullptr;
};

struct D3d12TextureUploadContext {
    ID3D12Device* device = nullptr;
    ID3D12CommandQueue* command_queue = nullptr;
    ID3D12CommandAllocator* command_allocator = nullptr;
    ID3D12GraphicsCommandList* command_list = nullptr;
    ID3D12Fence* fence = nullptr;
    HANDLE fence_event = nullptr;
    UINT64* next_fence_value = nullptr;
    D3d12DescriptorAllocator descriptors;
};

struct DdsTextureHandle {
    ID3D12Resource* resource = nullptr;
    D3D12_CPU_DESCRIPTOR_HANDLE cpu_descriptor{};
    D3D12_GPU_DESCRIPTOR_HANDLE gpu_descriptor{};
    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    unsigned width = 0;
    unsigned height = 0;
    void* descriptor_user_data = nullptr;
    void (*descriptor_free_fn)(void* user_data, D3D12_CPU_DESCRIPTOR_HANDLE cpu_desc_handle, D3D12_GPU_DESCRIPTOR_HANDLE gpu_desc_handle) = nullptr;
};

void ReleaseTexture(DdsTextureHandle& texture);

bool LoadDdsTexture(
    const D3d12TextureUploadContext& context,
    const std::filesystem::path& path,
    DdsTextureHandle& texture,
    std::string* error = nullptr
);

bool LoadWicTexture(
    const D3d12TextureUploadContext& context,
    const std::filesystem::path& path,
    DdsTextureHandle& texture,
    std::string* error = nullptr
);

}  // namespace sg_preflight::native_shell
