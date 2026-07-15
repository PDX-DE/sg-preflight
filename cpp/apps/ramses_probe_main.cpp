#include "sgfx/cine/ramses_probe.h"

#include <iostream>
#include <string>
#include <vector>

int main(int argc, char** argv)
{
    const std::vector<std::string> arguments(argv + 1, argv + argc);
    const auto parse = sgfx::cine::parse_probe_arguments(arguments);
    if (!parse.accepted)
    {
        std::cerr << "argument_rejected: " << parse.rejection << "\n";
        return sgfx::cine::kProbeExitUsage;
    }
    const auto outcome = sgfx::cine::execute_probe_request(parse.request);
    std::cerr << "probe " << outcome.classification << "\n";
    return outcome.exit_code;
}
