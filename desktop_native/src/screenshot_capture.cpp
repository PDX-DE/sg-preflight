#include "screenshot_capture.hpp"

#include <wincodec.h>
#include <wrl/client.h>

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace sg_preflight::native_shell {
namespace {

using Microsoft::WRL::ComPtr;

void SetError(std::string* error, std::string message) {
    if (error != nullptr) {
        *error = std::move(message);
    }
}

std::wstring ToWide(const std::string& text) {
    if (text.empty()) {
        return {};
    }
    const int length = MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, nullptr, 0);
    if (length <= 0) {
        return {};
    }
    std::wstring buffer(static_cast<size_t>(length), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, buffer.data(), length);
    buffer.resize(static_cast<size_t>(length - 1));
    return buffer;
}

std::string WideToUtf8(const std::wstring& text) {
    if (text.empty()) {
        return {};
    }
    const int length = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), -1, nullptr, 0, nullptr, nullptr);
    if (length <= 0) {
        return {};
    }
    std::string buffer(static_cast<size_t>(length), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.c_str(), -1, buffer.data(), length, nullptr, nullptr);
    buffer.resize(static_cast<size_t>(length - 1));
    return buffer;
}

bool SaveMappedTextureAsPng(
    const std::filesystem::path& output_path,
    const void* mapped_data,
    UINT width,
    UINT height,
    UINT row_pitch,
    DXGI_FORMAT format,
    std::string* error
) {
    if (format != DXGI_FORMAT_R8G8B8A8_UNORM && format != DXGI_FORMAT_B8G8R8A8_UNORM) {
        SetError(error, "PNG capture only supports RGBA/BGRA render targets.");
        return false;
    }

    std::vector<uint8_t> packed_bgra(static_cast<size_t>(width) * static_cast<size_t>(height) * 4U);
    const auto* source_bytes = static_cast<const uint8_t*>(mapped_data);
    for (UINT y = 0; y < height; ++y) {
        const uint8_t* source_row = source_bytes + static_cast<size_t>(y) * row_pitch;
        uint8_t* dest_row = packed_bgra.data() + (static_cast<size_t>(y) * static_cast<size_t>(width) * 4U);
        if (format == DXGI_FORMAT_B8G8R8A8_UNORM) {
            std::memcpy(dest_row, source_row, static_cast<size_t>(width) * 4U);
            continue;
        }

        for (UINT x = 0; x < width; ++x) {
            const uint8_t* src = source_row + static_cast<size_t>(x) * 4U;
            uint8_t* dst = dest_row + static_cast<size_t>(x) * 4U;
            dst[0] = src[2];
            dst[1] = src[1];
            dst[2] = src[0];
            dst[3] = src[3];
        }
    }

    WICPixelFormatGUID pixel_format = GUID_WICPixelFormat32bppBGRA;
    const UINT packed_row_pitch = width * 4U;
    const UINT packed_buffer_size = packed_row_pitch * height;

    HRESULT init_result = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    const bool should_uninitialize = SUCCEEDED(init_result);
    if (FAILED(init_result) && init_result != RPC_E_CHANGED_MODE) {
        SetError(error, "CoInitializeEx failed for PNG capture.");
        return false;
    }

    bool saved = false;
    do {
        std::error_code create_error;
        std::filesystem::create_directories(output_path.parent_path(), create_error);

        ComPtr<IWICImagingFactory> factory;
        if (FAILED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory))) || factory == nullptr) {
            SetError(error, "Failed to create WIC imaging factory.");
            break;
        }

        ComPtr<IWICStream> stream;
        if (FAILED(factory->CreateStream(&stream)) || stream == nullptr) {
            SetError(error, "Failed to create WIC stream.");
            break;
        }

        const std::wstring wide_path = output_path.wstring();
        if (FAILED(stream->InitializeFromFilename(wide_path.c_str(), GENERIC_WRITE))) {
            SetError(error, "Failed to open PNG output path \"" + WideToUtf8(wide_path) + "\".");
            break;
        }

        ComPtr<IWICBitmapEncoder> encoder;
        if (FAILED(factory->CreateEncoder(GUID_ContainerFormatPng, nullptr, &encoder)) || encoder == nullptr) {
            SetError(error, "Failed to create PNG encoder.");
            break;
        }
        if (FAILED(encoder->Initialize(stream.Get(), WICBitmapEncoderNoCache))) {
            SetError(error, "Failed to initialize PNG encoder.");
            break;
        }

        ComPtr<IWICBitmapFrameEncode> frame;
        ComPtr<IPropertyBag2> properties;
        if (FAILED(encoder->CreateNewFrame(&frame, &properties)) || frame == nullptr) {
            SetError(error, "Failed to create PNG frame.");
            break;
        }
        if (FAILED(frame->Initialize(properties.Get()))) {
            SetError(error, "Failed to initialize PNG frame.");
            break;
        }
        if (FAILED(frame->SetSize(width, height))) {
            SetError(error, "Failed to set PNG frame size.");
            break;
        }

        WICPixelFormatGUID actual_format = pixel_format;
        if (FAILED(frame->SetPixelFormat(&actual_format))) {
            SetError(error, "Failed to set PNG pixel format.");
            break;
        }
        if (InlineIsEqualGUID(actual_format, pixel_format)) {
            if (FAILED(frame->WritePixels(height, packed_row_pitch, packed_buffer_size, packed_bgra.data()))) {
                SetError(error, "Failed to write PNG pixels.");
                break;
            }
        } else {
            ComPtr<IWICBitmap> bitmap;
            if (FAILED(factory->CreateBitmapFromMemory(
                    width,
                    height,
                    pixel_format,
                    packed_row_pitch,
                    packed_buffer_size,
                    packed_bgra.data(),
                    &bitmap)) || bitmap == nullptr) {
                SetError(error, "Failed to create intermediate bitmap for PNG capture.");
                break;
            }

            ComPtr<IWICFormatConverter> converter;
            if (FAILED(factory->CreateFormatConverter(&converter)) || converter == nullptr) {
                SetError(error, "Failed to create WIC format converter.");
                break;
            }
            if (FAILED(converter->Initialize(
                    bitmap.Get(),
                    actual_format,
                    WICBitmapDitherTypeNone,
                    nullptr,
                    0.0,
                    WICBitmapPaletteTypeCustom))) {
                SetError(error, "Failed to convert capture bitmap for PNG encoding.");
                break;
            }
            if (FAILED(frame->WriteSource(converter.Get(), nullptr))) {
                SetError(error, "Failed to write converted PNG pixels.");
                break;
            }
        }
        if (FAILED(frame->Commit())) {
            SetError(error, "Failed to commit PNG frame.");
            break;
        }
        if (FAILED(encoder->Commit())) {
            SetError(error, "Failed to commit PNG encoder.");
            break;
        }

        saved = true;
    } while (false);

    if (should_uninitialize) {
        CoUninitialize();
    }
    return saved;
}

}  // namespace

bool CapturePresentedBackBufferToPng(
    const D3d12PngCaptureContext& context,
    ID3D12Resource* source,
    DXGI_FORMAT format,
    const std::filesystem::path& output_path,
    std::string* error
) {
    if (
        context.device == nullptr
        || context.command_queue == nullptr
        || context.fence == nullptr
        || context.fence_event == nullptr
        || context.next_fence_value == nullptr
        || source == nullptr
    ) {
        SetError(error, "Capture context is incomplete.");
        return false;
    }

    const D3D12_RESOURCE_DESC source_desc = source->GetDesc();
    if (source_desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || source_desc.Width == 0 || source_desc.Height == 0) {
        SetError(error, "Capture source is not a valid 2D back buffer.");
        return false;
    }

    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT64 row_size_bytes = 0;
    UINT num_rows = 0;
    UINT64 total_bytes = 0;
    context.device->GetCopyableFootprints(&source_desc, 0, 1, 0, &footprint, &num_rows, &row_size_bytes, &total_bytes);
    if (total_bytes == 0) {
        SetError(error, "Capture footprint size resolved to zero bytes.");
        return false;
    }

    ComPtr<ID3D12CommandAllocator> allocator;
    if (FAILED(context.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator))) || allocator == nullptr) {
        SetError(error, "Failed to create capture command allocator.");
        return false;
    }

    ComPtr<ID3D12GraphicsCommandList> command_list;
    if (FAILED(context.device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&command_list))) || command_list == nullptr) {
        SetError(error, "Failed to create capture command list.");
        return false;
    }

    D3D12_HEAP_PROPERTIES readback_heap{};
    readback_heap.Type = D3D12_HEAP_TYPE_READBACK;
    readback_heap.CPUPageProperty = D3D12_CPU_PAGE_PROPERTY_UNKNOWN;
    readback_heap.MemoryPoolPreference = D3D12_MEMORY_POOL_UNKNOWN;
    readback_heap.CreationNodeMask = 1;
    readback_heap.VisibleNodeMask = 1;

    D3D12_RESOURCE_DESC readback_desc{};
    readback_desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    readback_desc.Alignment = 0;
    readback_desc.Width = total_bytes;
    readback_desc.Height = 1;
    readback_desc.DepthOrArraySize = 1;
    readback_desc.MipLevels = 1;
    readback_desc.Format = DXGI_FORMAT_UNKNOWN;
    readback_desc.SampleDesc.Count = 1;
    readback_desc.SampleDesc.Quality = 0;
    readback_desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    readback_desc.Flags = D3D12_RESOURCE_FLAG_NONE;

    ComPtr<ID3D12Resource> readback_buffer;
    if (FAILED(context.device->CreateCommittedResource(
            &readback_heap,
            D3D12_HEAP_FLAG_NONE,
            &readback_desc,
            D3D12_RESOURCE_STATE_COPY_DEST,
            nullptr,
            IID_PPV_ARGS(&readback_buffer))) || readback_buffer == nullptr) {
        SetError(error, "Failed to create capture readback buffer.");
        return false;
    }

    D3D12_RESOURCE_BARRIER to_copy{};
    to_copy.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    to_copy.Transition.pResource = source;
    to_copy.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    to_copy.Transition.StateBefore = D3D12_RESOURCE_STATE_PRESENT;
    to_copy.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    command_list->ResourceBarrier(1, &to_copy);

    D3D12_TEXTURE_COPY_LOCATION src_location{};
    src_location.pResource = source;
    src_location.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    src_location.SubresourceIndex = 0;

    D3D12_TEXTURE_COPY_LOCATION dst_location{};
    dst_location.pResource = readback_buffer.Get();
    dst_location.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst_location.PlacedFootprint = footprint;

    command_list->CopyTextureRegion(&dst_location, 0, 0, 0, &src_location, nullptr);

    D3D12_RESOURCE_BARRIER to_present = to_copy;
    to_present.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE;
    to_present.Transition.StateAfter = D3D12_RESOURCE_STATE_PRESENT;
    command_list->ResourceBarrier(1, &to_present);

    if (FAILED(command_list->Close())) {
        SetError(error, "Failed to close capture command list.");
        return false;
    }

    ID3D12CommandList* command_lists[] = { command_list.Get() };
    context.command_queue->ExecuteCommandLists(1, command_lists);
    const UINT64 fence_value = ++(*context.next_fence_value);
    if (FAILED(context.command_queue->Signal(context.fence, fence_value))) {
        SetError(error, "Failed to signal capture fence.");
        return false;
    }
    if (context.fence->GetCompletedValue() < fence_value) {
        if (FAILED(context.fence->SetEventOnCompletion(fence_value, context.fence_event))) {
            SetError(error, "Failed to arm capture fence event.");
            return false;
        }
        WaitForSingleObject(context.fence_event, INFINITE);
    }

    D3D12_RANGE read_range{0, static_cast<SIZE_T>(total_bytes)};
    void* mapped_data = nullptr;
    if (FAILED(readback_buffer->Map(0, &read_range, &mapped_data)) || mapped_data == nullptr) {
        SetError(error, "Failed to map capture readback buffer.");
        return false;
    }

    const bool saved = SaveMappedTextureAsPng(
        output_path,
        mapped_data,
        static_cast<UINT>(source_desc.Width),
        static_cast<UINT>(source_desc.Height),
        footprint.Footprint.RowPitch,
        format,
        error
    );

    D3D12_RANGE written_range{0, 0};
    readback_buffer->Unmap(0, &written_range);
    return saved;
}

}  // namespace sg_preflight::native_shell
