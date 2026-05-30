#include "sgfx_shell/sgfx_diagnostic_overlay.hpp"

#include <windows.h>

#include <array>
#include <cstdio>
#include <cstdlib>
#include <string>

namespace sg_preflight::sgfx_shell {

namespace {

std::wstring StateForPath(const std::filesystem::path& path) {
    return std::filesystem::exists(path) ? L"available" : L"missing";
}

std::wstring PathDetail(const std::filesystem::path& path) {
    return path.wstring();
}

bool DirectoryEnumerable(const std::filesystem::path& path) {
    std::error_code error;
    if (!std::filesystem::is_directory(path, error)) {
        return false;
    }
    std::filesystem::directory_iterator iterator(path, error);
    return !error;
}

std::wstring ToolLookup(const std::wstring& exe_name) {
    std::array<wchar_t, MAX_PATH> buffer{};
    const DWORD length = SearchPathW(nullptr, exe_name.c_str(), nullptr, static_cast<DWORD>(buffer.size()), buffer.data(), nullptr);
    if (length == 0U || length >= buffer.size()) {
        return L"";
    }
    return buffer.data();
}

std::wstring RunProbe(const std::wstring& command) {
    FILE* pipe = _wpopen(command.c_str(), L"rt");
    if (pipe == nullptr) {
        return L"";
    }
    std::wstring output;
    wchar_t buffer[256]{};
    while (fgetws(buffer, 256, pipe) != nullptr) {
        output += buffer;
        if (output.size() > 300U) {
            break;
        }
    }
    const int code = _pclose(pipe);
    if (code != 0) {
        return L"";
    }
    while (!output.empty() && (output.back() == L'\n' || output.back() == L'\r')) {
        output.pop_back();
    }
    return output;
}

std::wstring GitTip(const std::filesystem::path& workspace_root) {
    const std::filesystem::path head_path = workspace_root / ".git" / "HEAD";
    if (!std::filesystem::exists(head_path)) {
        return L"";
    }
    return L".git/HEAD readable";
}

}  // namespace

void SgfxDiagnosticOverlay::refresh(const std::filesystem::path& workspace_root) {
    rows_.clear();
    const std::filesystem::path bmw_git = L"C:\\3D Car git\\digital-3d-car-models";
    const std::filesystem::path svn_stage = L"C:\\repositories\\trunk\\Playground\\SGFX_QA_Preflight";
    const std::filesystem::path bmw_cars = bmw_git / "cars";

    rows_.push_back({L"BMW Git mirror", DirectoryEnumerable(bmw_cars) ? L"available" : StateForPath(bmw_git), PathDetail(bmw_cars)});
    rows_.push_back({L"SVN staging", StateForPath(svn_stage), PathDetail(svn_stage)});
    const std::wstring python_version = RunProbe(L"python --version");
    rows_.push_back({L"Python runtime", python_version.empty() ? L"missing" : L"available", python_version.empty() ? L"python not found on PATH" : python_version});
    const std::wstring module_probe = RunProbe(L"python -B -c \"import openpyxl, requests; print('openpyxl requests')\"");
    rows_.push_back({L"Python modules", module_probe.empty() ? L"missing" : L"available", module_probe.empty() ? L"openpyxl or requests missing" : module_probe});
    rows_.push_back({L"workspace", StateForPath(workspace_root), PathDetail(workspace_root)});
    const std::wstring raco_headless = ToolLookup(L"raco_headless.exe");
    const std::wstring raco = ToolLookup(L"raco.exe");
    const std::wstring ramses = ToolLookup(L"ramses_viewer.exe");
    rows_.push_back({L"raco_headless", raco_headless.empty() ? L"missing" : L"available", raco_headless.empty() ? L"path lookup only" : raco_headless});
    rows_.push_back({L"raco", raco.empty() ? L"missing" : L"available", raco.empty() ? L"path lookup only" : raco});
    rows_.push_back({L"ramses_viewer", ramses.empty() ? L"missing" : L"available", ramses.empty() ? L"path lookup only" : ramses});
    const std::wstring blender = ToolLookup(L"blender.exe");
    rows_.push_back({L"blender", blender.empty() ? L"missing" : L"available", blender.empty() ? L"path lookup only" : blender});
    const std::wstring git_tip = GitTip(workspace_root);
    rows_.push_back({L"Alpha Git tip", git_tip.empty() ? L"unknown" : L"available", git_tip.empty() ? L"not a Git checkout" : git_tip});
    rows_.push_back({L"Confluence anchor", L"unknown", L"surface-specific anchors reported in handoff"});

    ULARGE_INTEGER free_bytes{};
    if (GetDiskFreeSpaceExW(workspace_root.wstring().c_str(), &free_bytes, nullptr, nullptr) != 0) {
        rows_.push_back({L"Free disk", L"available", std::to_wstring(free_bytes.QuadPart / (1024ULL * 1024ULL)) + L" MB"});
    } else {
        rows_.push_back({L"Free disk", L"unknown", L"could not read workspace volume"});
    }
}

const std::vector<SgfxDiagnosticRow>& SgfxDiagnosticOverlay::rows() const {
    return rows_;
}

bool SgfxDiagnosticOverlay::visible() const {
    return visible_;
}

void SgfxDiagnosticOverlay::set_visible(bool visible) {
    visible_ = visible;
}

void SgfxDiagnosticOverlay::toggle() {
    visible_ = !visible_;
}

}  // namespace sg_preflight::sgfx_shell
