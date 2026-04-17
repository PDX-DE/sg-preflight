#include "texture_loader.hpp"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <vector>

namespace sg_preflight::native_shell {
namespace {

constexpr uint32_t MakeFourCc(char a, char b, char c, char d) {
    return static_cast<uint32_t>(static_cast<uint8_t>(a))
        | (static_cast<uint32_t>(static_cast<uint8_t>(b)) << 8U)
        | (static_cast<uint32_t>(static_cast<uint8_t>(c)) << 16U)
        | (static_cast<uint32_t>(static_cast<uint8_t>(d)) << 24U);
}

constexpr uint32_t kDdsMagic = MakeFourCc('D', 'D', 'S', ' ');
constexpr uint32_t kDxt1FourCc = MakeFourCc('D', 'X', 'T', '1');
constexpr uint32_t kDxt3FourCc = MakeFourCc('D', 'X', 'T', '3');
constexpr uint32_t kDxt5FourCc = MakeFourCc('D', 'X', 'T', '5');
constexpr uint32_t kDx10FourCc = MakeFourCc('D', 'X', '1', '0');
constexpr uint32_t kPixelFormatFourCc = 0x00000004U;
constexpr uint32_t kPixelFormatRgb = 0x00000040U;

struct DdsPixelFormat {
    uint32_t size = 0;
    uint32_t flags = 0;
    uint32_t four_cc = 0;
    uint32_t rgb_bit_count = 0;
    uint32_t r_bit_mask = 0;
    uint32_t g_bit_mask = 0;
    uint32_t b_bit_mask = 0;
    uint32_t a_bit_mask = 0;
};

struct DdsHeader {
    uint32_t size = 0;
    uint32_t flags = 0;
    uint32_t height = 0;
    uint32_t width = 0;
    uint32_t pitch_or_linear_size = 0;
    uint32_t depth = 0;
    uint32_t mip_map_count = 0;
    uint32_t reserved1[11] = {};
    DdsPixelFormat ddspf{};
    uint32_t caps = 0;
    uint32_t caps2 = 0;
    uint32_t caps3 = 0;
    uint32_t caps4 = 0;
    uint32_t reserved2 = 0;
};

struct DdsHeaderDx10 {
    uint32_t dxgi_format = 0;
    uint32_t resource_dimension = 0;
    uint32_t misc_flag = 0;
    uint32_t array_size = 0;
    uint32_t misc_flags2 = 0;
};

bool ReadBinaryFile(const std::filesystem::path& path, std::vector<std::byte>& bytes) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        return false;
    }
    stream.seekg(0, std::ios::end);
    const std::streamsize size = stream.tellg();
    if (size <= 0) {
        return false;
    }
    stream.seekg(0, std::ios::beg);
    bytes.resize(static_cast<size_t>(size));
    stream.read(reinterpret_cast<char*>(bytes.data()), size);
    return stream.good();
}

bool ParseHeader(
    const std::vector<std::byte>& file_bytes,
    DdsHeader& header,
    std::optional<DdsHeaderDx10>& header_dx10,
    size_t& data_offset,
    std::string& error
) {
    if (file_bytes.size() < sizeof(uint32_t) + sizeof(DdsHeader)) {
        error = "DDS file is truncated.";
        return false;
    }

    uint32_t magic = 0;
    std::memcpy(&magic, file_bytes.data(), sizeof(magic));
    if (magic != kDdsMagic) {
        error = "File is not a DDS texture.";
        return false;
    }

    std::memcpy(&header, file_bytes.data() + sizeof(uint32_t), sizeof(DdsHeader));
    if (header.size != 124 || header.ddspf.size != 32) {
        error = "DDS header size is invalid.";
        return false;
    }

    data_offset = sizeof(uint32_t) + sizeof(DdsHeader);
    if ((header.ddspf.flags & kPixelFormatFourCc) != 0U && header.ddspf.four_cc == kDx10FourCc) {
        if (file_bytes.size() < data_offset + sizeof(DdsHeaderDx10)) {
            error = "DDS DX10 header is truncated.";
            return false;
        }
        header_dx10.emplace();
        std::memcpy(&header_dx10.value(), file_bytes.data() + data_offset, sizeof(DdsHeaderDx10));
        data_offset += sizeof(DdsHeaderDx10);
    }

    return true;
}

bool ResolveFormat(
    const DdsHeader& header,
    const std::optional<DdsHeaderDx10>& header_dx10,
    DXGI_FORMAT& format,
    bool& block_compressed,
    size_t& bytes_per_block_or_pixel,
    std::string& error
) {
    format = DXGI_FORMAT_UNKNOWN;
    block_compressed = false;
    bytes_per_block_or_pixel = 0U;

    if (header_dx10.has_value()) {
        format = static_cast<DXGI_FORMAT>(header_dx10->dxgi_format);
        switch (format) {
        case DXGI_FORMAT_BC1_UNORM:
        case DXGI_FORMAT_BC1_UNORM_SRGB:
            block_compressed = true;
            bytes_per_block_or_pixel = 8U;
            return true;
        case DXGI_FORMAT_BC2_UNORM:
        case DXGI_FORMAT_BC2_UNORM_SRGB:
        case DXGI_FORMAT_BC3_UNORM:
        case DXGI_FORMAT_BC3_UNORM_SRGB:
        case DXGI_FORMAT_BC7_UNORM:
        case DXGI_FORMAT_BC7_UNORM_SRGB:
            block_compressed = true;
            bytes_per_block_or_pixel = 16U;
            return true;
        case DXGI_FORMAT_B8G8R8A8_UNORM:
        case DXGI_FORMAT_R8G8B8A8_UNORM:
            block_compressed = false;
            bytes_per_block_or_pixel = 4U;
            return true;
        default:
            error = "DDS format is unsupported by the native shell loader.";
            return false;
        }
    }

    if ((header.ddspf.flags & kPixelFormatFourCc) != 0U) {
        switch (header.ddspf.four_cc) {
        case kDxt1FourCc:
            format = DXGI_FORMAT_BC1_UNORM;
            block_compressed = true;
            bytes_per_block_or_pixel = 8U;
            return true;
        case kDxt3FourCc:
            format = DXGI_FORMAT_BC2_UNORM;
            block_compressed = true;
            bytes_per_block_or_pixel = 16U;
            return true;
        case kDxt5FourCc:
            format = DXGI_FORMAT_BC3_UNORM;
            block_compressed = true;
            bytes_per_block_or_pixel = 16U;
            return true;
        default:
            error = "DDS FOURCC is unsupported by the native shell loader.";
            return false;
        }
    }

    if (
        (header.ddspf.flags & kPixelFormatRgb) != 0U
        && header.ddspf.rgb_bit_count == 32U
        && header.ddspf.r_bit_mask == 0x00ff0000U
        && header.ddspf.g_bit_mask == 0x0000ff00U
        && header.ddspf.b_bit_mask == 0x000000ffU
        && header.ddspf.a_bit_mask == 0xff000000U
    ) {
        format = DXGI_FORMAT_B8G8R8A8_UNORM;
        block_compressed = false;
        bytes_per_block_or_pixel = 4U;
        return true;
    }

    if (
        (header.ddspf.flags & kPixelFormatRgb) != 0U
        && header.ddspf.rgb_bit_count == 32U
        && header.ddspf.r_bit_mask == 0x000000ffU
        && header.ddspf.g_bit_mask == 0x0000ff00U
        && header.ddspf.b_bit_mask == 0x00ff0000U
        && header.ddspf.a_bit_mask == 0xff000000U
    ) {
        format = DXGI_FORMAT_R8G8B8A8_UNORM;
        block_compressed = false;
        bytes_per_block_or_pixel = 4U;
        return true;
    }

    error = "DDS pixel format is unsupported by the native shell loader.";
    return false;
}

}  // namespace

void ReleaseTexture(DdsTextureHandle& texture) {
    if (texture.view != nullptr) {
        texture.view->Release();
        texture.view = nullptr;
    }
    texture.format = DXGI_FORMAT_UNKNOWN;
    texture.width = 0;
    texture.height = 0;
}

bool LoadDdsTexture(
    ID3D11Device* device,
    const std::filesystem::path& path,
    DdsTextureHandle& texture,
    std::string* error
) {
    if (device == nullptr) {
        if (error != nullptr) {
            *error = "D3D11 device is not initialized.";
        }
        return false;
    }

    std::vector<std::byte> file_bytes;
    if (!ReadBinaryFile(path, file_bytes)) {
        if (error != nullptr) {
            *error = "Could not read DDS file: " + path.string();
        }
        return false;
    }

    DdsHeader header{};
    std::optional<DdsHeaderDx10> header_dx10;
    size_t data_offset = 0U;
    std::string local_error;
    if (!ParseHeader(file_bytes, header, header_dx10, data_offset, local_error)) {
        if (error != nullptr) {
            *error = local_error;
        }
        return false;
    }

    DXGI_FORMAT format = DXGI_FORMAT_UNKNOWN;
    bool block_compressed = false;
    size_t bytes_per_block_or_pixel = 0U;
    if (!ResolveFormat(header, header_dx10, format, block_compressed, bytes_per_block_or_pixel, local_error)) {
        if (error != nullptr) {
            *error = local_error;
        }
        return false;
    }

    const uint32_t mip_levels = std::max(1U, header.mip_map_count);
    std::vector<D3D11_SUBRESOURCE_DATA> subresources;
    subresources.reserve(mip_levels);

    uint32_t width = header.width;
    uint32_t height = header.height;
    size_t current_offset = data_offset;
    for (uint32_t mip = 0; mip < mip_levels; ++mip) {
        const uint32_t current_width = std::max(1U, width >> mip);
        const uint32_t current_height = std::max(1U, height >> mip);
        const uint32_t row_pitch = block_compressed
            ? std::max(1U, (current_width + 3U) / 4U) * static_cast<uint32_t>(bytes_per_block_or_pixel)
            : current_width * static_cast<uint32_t>(bytes_per_block_or_pixel);
        const uint32_t slice_pitch = block_compressed
            ? row_pitch * std::max(1U, (current_height + 3U) / 4U)
            : row_pitch * current_height;

        if (current_offset + slice_pitch > file_bytes.size()) {
            if (error != nullptr) {
                *error = "DDS mip data is truncated.";
            }
            return false;
        }

        D3D11_SUBRESOURCE_DATA subresource{};
        subresource.pSysMem = file_bytes.data() + current_offset;
        subresource.SysMemPitch = row_pitch;
        subresource.SysMemSlicePitch = slice_pitch;
        subresources.push_back(subresource);
        current_offset += slice_pitch;
    }

    D3D11_TEXTURE2D_DESC description{};
    description.Width = header.width;
    description.Height = header.height;
    description.MipLevels = mip_levels;
    description.ArraySize = 1;
    description.Format = format;
    description.SampleDesc.Count = 1;
    description.Usage = D3D11_USAGE_DEFAULT;
    description.BindFlags = D3D11_BIND_SHADER_RESOURCE;

    ID3D11Texture2D* texture_handle = nullptr;
    const HRESULT texture_result = device->CreateTexture2D(
        &description,
        subresources.data(),
        &texture_handle
    );
    if (FAILED(texture_result) || texture_handle == nullptr) {
        if (error != nullptr) {
            *error = "D3D11 failed to create a texture from the DDS data.";
        }
        return false;
    }

    D3D11_SHADER_RESOURCE_VIEW_DESC view_description{};
    view_description.Format = description.Format;
    view_description.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
    view_description.Texture2D.MipLevels = description.MipLevels;

    ID3D11ShaderResourceView* shader_view = nullptr;
    const HRESULT view_result = device->CreateShaderResourceView(texture_handle, &view_description, &shader_view);
    texture_handle->Release();
    if (FAILED(view_result) || shader_view == nullptr) {
        if (error != nullptr) {
            *error = "D3D11 failed to create a shader resource view for the DDS texture.";
        }
        return false;
    }

    ReleaseTexture(texture);
    texture.view = shader_view;
    texture.format = format;
    texture.width = header.width;
    texture.height = header.height;
    return true;
}

}  // namespace sg_preflight::native_shell
