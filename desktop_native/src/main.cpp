#include "sgfx_shell/sgfx_shell_app.hpp"

#include <windows.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR command_line, int show_command) {
    return sg_preflight::sgfx_shell::RunShell(instance, command_line, show_command);
}
