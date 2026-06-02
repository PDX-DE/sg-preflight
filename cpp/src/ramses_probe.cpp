#include "sgfx/cine/ramses_probe.h"

#include <ramses/framework/EFeatureLevel.h>
#include <ramses/framework/RamsesFramework.h>
#include <ramses/framework/RamsesFrameworkConfig.h>
#include <ramses/framework/RamsesVersion.h>

#include <sstream>

namespace sgfx::cine
{
std::string ramses_link_probe_message()
{
    const auto version = ramses::GetRamsesVersion();

    ramses::RamsesFrameworkConfig config{ramses::EFeatureLevel_01};
    ramses::RamsesFramework framework{config};

    std::ostringstream out;
    out << "Ramses version: " << version.string << " ("
        << version.major << '.' << version.minor << '.' << version.patch << ")\n"
        << "Ramses feature level: " << static_cast<unsigned>(framework.getFeatureLevel()) << '\n'
        << "Ramses linked OK";
    return out.str();
}
}
