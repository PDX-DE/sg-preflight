#include "sgfx_shell/sgfx_menu_background.hpp"

namespace sg_preflight::sgfx_shell {

namespace {

void Fill(HDC dc, const RECT& rect, COLORREF color) {
    HBRUSH brush = CreateSolidBrush(color);
    FillRect(dc, &rect, brush);
    DeleteObject(brush);
}

}  // namespace

void SgfxMenuBackground::draw(HDC dc, const RECT& bounds, SgfxUiMode mode) const {
    const COLORREF background = mode == SgfxUiMode::Clean ? RGB(15, 17, 19) : RGB(18, 22, 32);
    Fill(dc, bounds, background);

    RECT band = bounds;
    band.bottom = band.top + 96;
    Fill(dc, band, mode == SgfxUiMode::Clean ? RGB(24, 27, 30) : RGB(32, 41, 64));

    RECT footer = bounds;
    footer.top = footer.bottom - 54;
    Fill(dc, footer, mode == SgfxUiMode::Clean ? RGB(21, 23, 25) : RGB(26, 31, 44));
}

}  // namespace sg_preflight::sgfx_shell
