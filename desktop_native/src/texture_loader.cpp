#include "texture_loader.hpp"

#include <wincodec.h>
#include <wrl/client.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <optional>
#include <vector>

namespace sg_preflight::native_shell {
namespace {

using Microsoft::WRL::ComPtr;

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

bool CreateBufferResource(
    ID3D12Device* device,
    UINT64 size,
    D3D12_HEAP_TYPE heap_type,
    D3D12_RESOURCE_STATES initial_state,
    ID3D12Resource** resource
) {
    D3D12_HEAP_PROPERTIES heap_properties{};
    heap_properties.Type = heap_type;

    D3D12_RESOURCE_DESC resource_desc{};
    resource_desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    resource_desc.Width = size;
    resource_desc.Height = 1;
    resource_desc.DepthOrArraySize = 1;
    resource_desc.MipLevels = 1;
    resource_desc.Format = DXGI_FORMAT_UNKNOWN;
    resource_desc.SampleDesc.Count = 1;
    resource_desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;

    return SUCCEEDED(device->CreateCommittedResource(
        &heap_properties,
        D3D12_HEAP_FLAG_NONE,
        &resource_desc,
        initial_state,
        nullptr,
        IID_PPV_ARGS(resource)
    ));
}

bool UploadBgraPixelsToTexture(
    const D3d12TextureUploadContext& context,
    UINT width,
    UINT height,
    const uint8_t* pixels,
    UINT source_row_pitch,
    DdsTextureHandle& texture,
    std::string* error
) {
    D3D12_RESOURCE_DESC description{};
    description.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    description.Alignment = 0;
    description.Width = width;
    description.Height = height;
    description.DepthOrArraySize = 1;
    description.MipLevels = 1;
    description.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    description.SampleDesc.Count = 1;
    description.SampleDesc.Quality = 0;
    description.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    description.Flags = D3D12_RESOURCE_FLAG_NONE;

    D3D12_HEAP_PROPERTIES default_heap{};
    default_heap.Type = D3D12_HEAP_TYPE_DEFAULT;

    ID3D12Resource* texture_resource = nullptr;
    if (FAILED(context.device->CreateCommittedResource(
        &default_heap,
        D3D12_HEAP_FLAG_NONE,
        &description,
        D3D12_RESOURCE_STATE_COPY_DEST,
        nullptr,
        IID_PPV_ARGS(&texture_resource)
    )) || texture_resource == nullptr) {
        if (error != nullptr) {
            *error = "D3D12 failed to create a texture resource for the WIC image.";
        }
        return false;
    }

    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT row_count = 0;
    UINT64 row_size = 0;
    UINT64 upload_buffer_size = 0;
    context.device->GetCopyableFootprints(
        &description,
        0,
        1,
        0,
        &footprint,
        &row_count,
        &row_size,
        &upload_buffer_size
    );

    ID3D12Resource* upload_buffer = nullptr;
    if (!CreateBufferResource(context.device, upload_buffer_size, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ, &upload_buffer) || upload_buffer == nullptr) {
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to create an upload buffer for the WIC image.";
        }
        return false;
    }

    std::byte* mapped = nullptr;
    if (FAILED(upload_buffer->Map(0, nullptr, reinterpret_cast<void**>(&mapped))) || mapped == nullptr) {
        upload_buffer->Release();
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to map the WIC upload buffer.";
        }
        return false;
    }

    for (UINT row = 0; row < row_count; ++row) {
        std::memcpy(
            mapped + footprint.Offset + (static_cast<size_t>(row) * footprint.Footprint.RowPitch),
            pixels + (static_cast<size_t>(row) * source_row_pitch),
            source_row_pitch
        );
    }
    upload_buffer->Unmap(0, nullptr);

    if (FAILED(context.command_allocator->Reset()) || FAILED(context.command_list->Reset(context.command_allocator, nullptr))) {
        upload_buffer->Release();
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to reset the WIC upload command list.";
        }
        return false;
    }

    D3D12_TEXTURE_COPY_LOCATION destination{};
    destination.pResource = texture_resource;
    destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    destination.SubresourceIndex = 0;

    D3D12_TEXTURE_COPY_LOCATION source{};
    source.pResource = upload_buffer;
    source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    source.PlacedFootprint = footprint;

    context.command_list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);

    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = texture_resource;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
    context.command_list->ResourceBarrier(1, &barrier);

    if (FAILED(context.command_list->Close())) {
        upload_buffer->Release();
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to close the WIC upload command list.";
        }
        return false;
    }

    ID3D12CommandList* lists[] = { context.command_list };
    context.command_queue->ExecuteCommandLists(1, lists);

    const UINT64 fence_value = ++(*context.next_fence_value);
    if (FAILED(context.command_queue->Signal(context.fence, fence_value))) {
        upload_buffer->Release();
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to signal the WIC upload fence.";
        }
        return false;
    }
    if (context.fence->GetCompletedValue() < fence_value) {
        if (FAILED(context.fence->SetEventOnCompletion(fence_value, context.fence_event))) {
            upload_buffer->Release();
            texture_resource->Release();
            if (error != nullptr) {
                *error = "D3D12 failed to wait for the WIC upload fence.";
            }
            return false;
        }
        WaitForSingleObject(context.fence_event, INFINITE);
    }

    upload_buffer->Release();

    DdsTextureHandle candidate{};
    candidate.resource = texture_resource;
    candidate.format = DXGI_FORMAT_B8G8R8A8_UNORM;
    candidate.width = width;
    candidate.height = height;
    candidate.descriptor_user_data = context.descriptors.user_data;
    candidate.descriptor_free_fn = context.descriptors.free;

    context.descriptors.alloc(context.descriptors.user_data, &candidate.cpu_descriptor, &candidate.gpu_descriptor);
    if (candidate.gpu_descriptor.ptr == 0) {
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to allocate an SRV descriptor for the WIC image.";
        }
        return false;
    }

    D3D12_SHADER_RESOURCE_VIEW_DESC view_description{};
    view_description.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    view_description.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    view_description.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    view_description.Texture2D.MipLevels = 1;
    context.device->CreateShaderResourceView(texture_resource, &view_description, candidate.cpu_descriptor);

    ReleaseTexture(texture);
    texture = candidate;
    return true;
}

bool TrimBgraPixelsByAlpha(
    std::vector<uint8_t>& pixels,
    UINT& width,
    UINT& height,
    uint8_t alpha_trim_threshold
) {
    if (alpha_trim_threshold == 0 || width == 0 || height == 0 || pixels.empty()) {
        return false;
    }

    UINT min_x = width;
    UINT min_y = height;
    UINT max_x = 0;
    UINT max_y = 0;
    bool found = false;
    const UINT row_pitch = width * 4U;
    for (UINT y = 0; y < height; ++y) {
        for (UINT x = 0; x < width; ++x) {
            const size_t pixel_offset = static_cast<size_t>(y) * row_pitch + static_cast<size_t>(x) * 4U;
            if (pixels[pixel_offset + 3U] < alpha_trim_threshold) {
                continue;
            }
            min_x = std::min(min_x, x);
            min_y = std::min(min_y, y);
            max_x = std::max(max_x, x);
            max_y = std::max(max_y, y);
            found = true;
        }
    }

    if (!found) {
        return false;
    }

    const UINT trimmed_width = (max_x - min_x) + 1U;
    const UINT trimmed_height = (max_y - min_y) + 1U;
    if (trimmed_width == width && trimmed_height == height && min_x == 0 && min_y == 0) {
        return false;
    }

    std::vector<uint8_t> trimmed(static_cast<size_t>(trimmed_width) * static_cast<size_t>(trimmed_height) * 4U);
    const UINT trimmed_row_pitch = trimmed_width * 4U;
    for (UINT y = 0; y < trimmed_height; ++y) {
        const size_t source_offset =
            (static_cast<size_t>(min_y + y) * row_pitch) +
            (static_cast<size_t>(min_x) * 4U);
        const size_t destination_offset = static_cast<size_t>(y) * trimmed_row_pitch;
        std::memcpy(
            trimmed.data() + destination_offset,
            pixels.data() + source_offset,
            static_cast<size_t>(trimmed_row_pitch)
        );
    }

    pixels = std::move(trimmed);
    width = trimmed_width;
    height = trimmed_height;
    return true;
}

std::vector<uint8_t> ResizeBgraPixelsBilinear(
    const std::vector<uint8_t>& source_pixels,
    UINT source_width,
    UINT source_height,
    UINT target_width,
    UINT target_height
) {
    std::vector<uint8_t> target_pixels(static_cast<size_t>(target_width) * static_cast<size_t>(target_height) * 4U, 0U);
    if (source_width == 0 || source_height == 0 || target_width == 0 || target_height == 0) {
        return target_pixels;
    }

    for (UINT y = 0; y < target_height; ++y) {
        const float source_y = (static_cast<float>(y) + 0.5f) * static_cast<float>(source_height) / static_cast<float>(target_height) - 0.5f;
        const UINT y0 = static_cast<UINT>(std::clamp(static_cast<int>(std::floor(source_y)), 0, static_cast<int>(source_height - 1U)));
        const UINT y1 = std::min(y0 + 1U, source_height - 1U);
        const float fy = std::clamp(source_y - static_cast<float>(y0), 0.0f, 1.0f);

        for (UINT x = 0; x < target_width; ++x) {
            const float source_x = (static_cast<float>(x) + 0.5f) * static_cast<float>(source_width) / static_cast<float>(target_width) - 0.5f;
            const UINT x0 = static_cast<UINT>(std::clamp(static_cast<int>(std::floor(source_x)), 0, static_cast<int>(source_width - 1U)));
            const UINT x1 = std::min(x0 + 1U, source_width - 1U);
            const float fx = std::clamp(source_x - static_cast<float>(x0), 0.0f, 1.0f);

            const size_t offset00 = (static_cast<size_t>(y0) * source_width + x0) * 4U;
            const size_t offset10 = (static_cast<size_t>(y0) * source_width + x1) * 4U;
            const size_t offset01 = (static_cast<size_t>(y1) * source_width + x0) * 4U;
            const size_t offset11 = (static_cast<size_t>(y1) * source_width + x1) * 4U;
            const size_t destination_offset = (static_cast<size_t>(y) * target_width + x) * 4U;

            for (size_t channel = 0; channel < 4U; ++channel) {
                const float top = static_cast<float>(source_pixels[offset00 + channel]) * (1.0f - fx)
                    + static_cast<float>(source_pixels[offset10 + channel]) * fx;
                const float bottom = static_cast<float>(source_pixels[offset01 + channel]) * (1.0f - fx)
                    + static_cast<float>(source_pixels[offset11 + channel]) * fx;
                const float value = top * (1.0f - fy) + bottom * fy;
                target_pixels[destination_offset + channel] = static_cast<uint8_t>(std::clamp(std::lround(value), 0l, 255l));
            }
        }
    }

    return target_pixels;
}

bool FitBgraPixelsIntoSquareCanvas(
    std::vector<uint8_t>& pixels,
    UINT& width,
    UINT& height,
    UINT fit_square_canvas_size
) {
    if (fit_square_canvas_size == 0 || width == 0 || height == 0 || pixels.empty()) {
        return false;
    }

    const float scale = std::min(
        static_cast<float>(fit_square_canvas_size) / static_cast<float>(width),
        static_cast<float>(fit_square_canvas_size) / static_cast<float>(height)
    );
    const UINT resized_width = std::max(1U, static_cast<UINT>(std::lround(static_cast<float>(width) * scale)));
    const UINT resized_height = std::max(1U, static_cast<UINT>(std::lround(static_cast<float>(height) * scale)));

    std::vector<uint8_t> resized = ResizeBgraPixelsBilinear(pixels, width, height, resized_width, resized_height);
    std::vector<uint8_t> canvas(
        static_cast<size_t>(fit_square_canvas_size) * static_cast<size_t>(fit_square_canvas_size) * 4U,
        0U
    );

    const UINT x_offset = (fit_square_canvas_size - resized_width) / 2U;
    const UINT y_offset = (fit_square_canvas_size - resized_height) / 2U;
    const UINT resized_row_pitch = resized_width * 4U;
    const UINT canvas_row_pitch = fit_square_canvas_size * 4U;
    for (UINT row = 0; row < resized_height; ++row) {
        const size_t source_offset = static_cast<size_t>(row) * resized_row_pitch;
        const size_t destination_offset =
            (static_cast<size_t>(y_offset + row) * canvas_row_pitch) +
            (static_cast<size_t>(x_offset) * 4U);
        std::memcpy(
            canvas.data() + destination_offset,
            resized.data() + source_offset,
            static_cast<size_t>(resized_row_pitch)
        );
    }

    pixels = std::move(canvas);
    width = fit_square_canvas_size;
    height = fit_square_canvas_size;
    return true;
}

}  // namespace

void ReleaseTexture(DdsTextureHandle& texture) {
    if (texture.resource != nullptr) {
        texture.resource->Release();
        texture.resource = nullptr;
    }
    if (texture.descriptor_free_fn != nullptr && texture.gpu_descriptor.ptr != 0) {
        texture.descriptor_free_fn(texture.descriptor_user_data, texture.cpu_descriptor, texture.gpu_descriptor);
    }
    texture.cpu_descriptor.ptr = 0;
    texture.gpu_descriptor.ptr = 0;
    texture.format = DXGI_FORMAT_UNKNOWN;
    texture.width = 0;
    texture.height = 0;
    texture.descriptor_user_data = nullptr;
    texture.descriptor_free_fn = nullptr;
}

bool LoadDdsTexture(
    const D3d12TextureUploadContext& context,
    const std::filesystem::path& path,
    DdsTextureHandle& texture,
    std::string* error
) {
    if (
        context.device == nullptr
        || context.command_queue == nullptr
        || context.command_allocator == nullptr
        || context.command_list == nullptr
        || context.fence == nullptr
        || context.fence_event == nullptr
        || context.next_fence_value == nullptr
        || context.descriptors.alloc == nullptr
    ) {
        if (error != nullptr) {
            *error = "D3D12 texture upload context is not initialized.";
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
    D3D12_RESOURCE_DESC description{};
    description.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    description.Alignment = 0;
    description.Width = header.width;
    description.Height = header.height;
    description.DepthOrArraySize = 1;
    description.MipLevels = static_cast<UINT16>(mip_levels);
    description.Format = format;
    description.SampleDesc.Count = 1;
    description.SampleDesc.Quality = 0;
    description.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    description.Flags = D3D12_RESOURCE_FLAG_NONE;

    D3D12_HEAP_PROPERTIES default_heap{};
    default_heap.Type = D3D12_HEAP_TYPE_DEFAULT;

    ID3D12Resource* texture_resource = nullptr;
    if (FAILED(context.device->CreateCommittedResource(
        &default_heap,
        D3D12_HEAP_FLAG_NONE,
        &description,
        D3D12_RESOURCE_STATE_COPY_DEST,
        nullptr,
        IID_PPV_ARGS(&texture_resource)
    )) || texture_resource == nullptr) {
        if (error != nullptr) {
            *error = "D3D12 failed to create a texture resource from the DDS data.";
        }
        return false;
    }

    std::vector<D3D12_PLACED_SUBRESOURCE_FOOTPRINT> footprints(mip_levels);
    std::vector<UINT> row_counts(mip_levels);
    std::vector<UINT64> row_sizes(mip_levels);
    UINT64 upload_buffer_size = 0;
    context.device->GetCopyableFootprints(
        &description,
        0,
        mip_levels,
        0,
        footprints.data(),
        row_counts.data(),
        row_sizes.data(),
        &upload_buffer_size
    );

    ID3D12Resource* upload_buffer = nullptr;
    if (!CreateBufferResource(context.device, upload_buffer_size, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ, &upload_buffer) || upload_buffer == nullptr) {
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to create a texture upload buffer.";
        }
        return false;
    }

    std::byte* mapped = nullptr;
    if (FAILED(upload_buffer->Map(0, nullptr, reinterpret_cast<void**>(&mapped))) || mapped == nullptr) {
        upload_buffer->Release();
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to map the texture upload buffer.";
        }
        return false;
    }

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
            upload_buffer->Unmap(0, nullptr);
            upload_buffer->Release();
            texture_resource->Release();
            if (error != nullptr) {
                *error = "DDS mip data is truncated.";
            }
            return false;
        }

        const auto& footprint = footprints[mip];
        std::byte* destination = mapped + footprint.Offset;
        const std::byte* source = file_bytes.data() + current_offset;
        for (UINT row = 0; row < row_counts[mip]; ++row) {
            std::memcpy(
                destination + (row * footprint.Footprint.RowPitch),
                source + (row * row_pitch),
                row_pitch
            );
        }

        current_offset += slice_pitch;
    }
    upload_buffer->Unmap(0, nullptr);

    if (FAILED(context.command_allocator->Reset()) || FAILED(context.command_list->Reset(context.command_allocator, nullptr))) {
        upload_buffer->Release();
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to reset the upload command list.";
        }
        return false;
    }

    for (uint32_t mip = 0; mip < mip_levels; ++mip) {
        D3D12_TEXTURE_COPY_LOCATION destination{};
        destination.pResource = texture_resource;
        destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        destination.SubresourceIndex = mip;

        D3D12_TEXTURE_COPY_LOCATION source{};
        source.pResource = upload_buffer;
        source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        source.PlacedFootprint = footprints[mip];

        context.command_list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
    }

    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = texture_resource;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
    context.command_list->ResourceBarrier(1, &barrier);

    if (FAILED(context.command_list->Close())) {
        upload_buffer->Release();
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to close the upload command list.";
        }
        return false;
    }

    ID3D12CommandList* lists[] = { context.command_list };
    context.command_queue->ExecuteCommandLists(1, lists);

    const UINT64 fence_value = ++(*context.next_fence_value);
    if (FAILED(context.command_queue->Signal(context.fence, fence_value))) {
        upload_buffer->Release();
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to signal the texture upload fence.";
        }
        return false;
    }
    if (context.fence->GetCompletedValue() < fence_value) {
        if (FAILED(context.fence->SetEventOnCompletion(fence_value, context.fence_event))) {
            upload_buffer->Release();
            texture_resource->Release();
            if (error != nullptr) {
                *error = "D3D12 failed to wait for the texture upload fence.";
            }
            return false;
        }
        WaitForSingleObject(context.fence_event, INFINITE);
    }

    upload_buffer->Release();

    DdsTextureHandle candidate{};
    candidate.resource = texture_resource;
    candidate.format = format;
    candidate.width = header.width;
    candidate.height = header.height;
    candidate.descriptor_user_data = context.descriptors.user_data;
    candidate.descriptor_free_fn = context.descriptors.free;

    context.descriptors.alloc(context.descriptors.user_data, &candidate.cpu_descriptor, &candidate.gpu_descriptor);
    if (candidate.gpu_descriptor.ptr == 0) {
        texture_resource->Release();
        if (error != nullptr) {
            *error = "D3D12 failed to allocate an SRV descriptor for the DDS texture.";
        }
        return false;
    }

    D3D12_SHADER_RESOURCE_VIEW_DESC view_description{};
    view_description.Format = format;
    view_description.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    view_description.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    view_description.Texture2D.MipLevels = mip_levels;
    context.device->CreateShaderResourceView(texture_resource, &view_description, candidate.cpu_descriptor);

    ReleaseTexture(texture);
    texture = candidate;
    return true;
}

bool LoadWicTexture(
    const D3d12TextureUploadContext& context,
    const std::filesystem::path& path,
    DdsTextureHandle& texture,
    uint8_t alpha_trim_threshold,
    uint32_t fit_square_canvas_size,
    std::string* error
) {
    if (
        context.device == nullptr
        || context.command_queue == nullptr
        || context.command_allocator == nullptr
        || context.command_list == nullptr
        || context.fence == nullptr
        || context.fence_event == nullptr
        || context.next_fence_value == nullptr
        || context.descriptors.alloc == nullptr
    ) {
        if (error != nullptr) {
            *error = "D3D12 texture upload context is not initialized.";
        }
        return false;
    }

    const HRESULT init_result = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    const bool should_uninitialize = SUCCEEDED(init_result);
    if (FAILED(init_result) && init_result != RPC_E_CHANGED_MODE) {
        if (error != nullptr) {
            *error = "CoInitializeEx failed for WIC texture loading.";
        }
        return false;
    }

    bool loaded = false;
    do {
        ComPtr<IWICImagingFactory> factory;
        if (FAILED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory))) || factory == nullptr) {
            if (error != nullptr) {
                *error = "Failed to create WIC imaging factory.";
            }
            break;
        }

        ComPtr<IWICBitmapDecoder> decoder;
        const std::wstring wide_path = path.wstring();
        if (FAILED(factory->CreateDecoderFromFilename(wide_path.c_str(), nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand, &decoder)) || decoder == nullptr) {
            if (error != nullptr) {
                *error = "Failed to open WIC texture file: " + path.string();
            }
            break;
        }

        ComPtr<IWICBitmapFrameDecode> frame;
        if (FAILED(decoder->GetFrame(0, &frame)) || frame == nullptr) {
            if (error != nullptr) {
                *error = "Failed to read the first WIC texture frame.";
            }
            break;
        }

        UINT width = 0;
        UINT height = 0;
        if (FAILED(frame->GetSize(&width, &height)) || width == 0 || height == 0) {
            if (error != nullptr) {
                *error = "WIC texture size is invalid.";
            }
            break;
        }

        ComPtr<IWICFormatConverter> converter;
        if (FAILED(factory->CreateFormatConverter(&converter)) || converter == nullptr) {
            if (error != nullptr) {
                *error = "Failed to create a WIC format converter.";
            }
            break;
        }

        if (FAILED(converter->Initialize(
                frame.Get(),
                GUID_WICPixelFormat32bppBGRA,
                WICBitmapDitherTypeNone,
                nullptr,
                0.0,
                WICBitmapPaletteTypeCustom))) {
            if (error != nullptr) {
                *error = "Failed to convert the WIC texture to BGRA.";
            }
            break;
        }

        UINT row_pitch = width * 4U;
        std::vector<uint8_t> pixels(static_cast<size_t>(row_pitch) * static_cast<size_t>(height));
        if (FAILED(converter->CopyPixels(nullptr, row_pitch, static_cast<UINT>(pixels.size()), pixels.data()))) {
            if (error != nullptr) {
                *error = "Failed to copy the WIC texture pixels.";
            }
            break;
        }

        if (TrimBgraPixelsByAlpha(pixels, width, height, alpha_trim_threshold)) {
            row_pitch = width * 4U;
        }
        if (FitBgraPixelsIntoSquareCanvas(pixels, width, height, fit_square_canvas_size)) {
            row_pitch = width * 4U;
        }

        loaded = UploadBgraPixelsToTexture(context, width, height, pixels.data(), row_pitch, texture, error);
    } while (false);

    if (should_uninitialize) {
        CoUninitialize();
    }
    return loaded;
}

}  // namespace sg_preflight::native_shell
