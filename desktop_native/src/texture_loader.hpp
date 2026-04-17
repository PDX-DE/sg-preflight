#pragma once

#include <d3d11.h>
#include <dxgiformat.h>

#include <filesystem>
#include <string>

namespace sg_preflight::native_shell {

struct DdsTextureHandle {
    ID3D11ShaderResourceView* view = nullptr;
    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    unsigned width = 0;
    unsigned height = 0;
};

void ReleaseTexture(DdsTextureHandle& texture);

bool LoadDdsTexture(
    ID3D11Device* device,
    const std::filesystem::path& path,
    DdsTextureHandle& texture,
    std::string* error = nullptr
);

}  // namespace sg_preflight::native_shell
