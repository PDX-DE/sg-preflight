#include "sgfx/cine/ramses_probe.h"

#include <exception>
#include <iostream>

int main()
{
    try
    {
        std::cout << sgfx::cine::ramses_link_probe_message() << '\n';
    }
    catch (const std::exception& exc)
    {
        std::cerr << "Ramses link probe failed: " << exc.what() << '\n';
        return 1;
    }

    return 0;
}
