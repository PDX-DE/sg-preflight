# Tests

C-1 uses a CTest smoke probe wired from `cpp/CMakeLists.txt` because the only behavior under test is successful Ramses runtime linking. Unit test targets should live here once `sgfx_cine` has logic independent of the link probe.
