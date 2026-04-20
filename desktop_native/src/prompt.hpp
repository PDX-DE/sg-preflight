#pragma once

#include "shell_types.hpp"

#include <string>
#include <string_view>

namespace sg_preflight::native_shell {

std::string ShortActionLabel(const std::string& action_id);
std::string FriendlyActionDescription(std::string_view action_id);
std::string BuildHelpPromptMessage(ShellScreen screen);

}  // namespace sg_preflight::native_shell
