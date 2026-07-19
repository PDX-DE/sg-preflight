"""Local Lua override snippets and status sentinels used to drive battery test scenarios and screenshot capture for the daily snapshot."""

from __future__ import annotations

import re


_BATTERY_SCENARIO_SELECTORS: dict[str, tuple[str, ...]] = {
    "default": ("default_rear", "default"),
    "openAllDoors_": ("openAllDoors_rightView", "openAllDoors_leftView"),
    "lights_drl_front": ("lights_drl_front",),
    "lights_LowBeam": ("lights_LowBeam",),
    "lights_HighBeam": ("lights_HighBeam",),
    "lights_OnlyCones": ("lights_OnlyCones",),
    "welcome_animation_": ("welcome_animation_casual", "welcome_animation_stealth"),
    "automatic_Doors_": (
        "automatic_Doors_Full_Angles",
        "automatic_Doors_Colors",
        "automatic_Doors_Opacities",
        "automatic_Doors_Unavailable_Angles",
    ),
    "highlighting_Doors": ("highlighting_Doors",),
}


_LUA_TEST_STATUS_SENTINEL = "SGPREFLIGHT_LUA_TEST_STATUS="


_LUA_SCREENSHOT_STATUS_SENTINEL = "SGPREFLIGHT_LUA_SCREENSHOT_STATUS="


_LOCAL_BATTERY_TEST_OVERRIDES = {
    "lights_LowBeam": (
        'if testViews["lights_LowBeam"] ~= nil then\n'
        '    testViews["lights_LowBeam"].enabled = true\n'
        '    testViews["lights_LowBeam"].update = function(time_ms)\n'
        '        reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); '
        'lights_beam(false, true); waitOnRendering(1000)\n'
        "    end\n"
        "end"
    ),
    "lights_HighBeam": (
        'if testViews["lights_HighBeam"] ~= nil then\n'
        '    testViews["lights_HighBeam"].enabled = true\n'
        '    testViews["lights_HighBeam"].update = function(time_ms)\n'
        '        reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); '
        'lights_beam(true, false); waitOnRendering(1000)\n'
        "    end\n"
        "end"
    ),
    "lights_OnlyCones": (
        'if testViews["lights_OnlyCones"] ~= nil then\n'
        '    testViews["lights_OnlyCones"].enabled = true\n'
        '    testViews["lights_OnlyCones"].update = function(time_ms)\n'
        '        reset(); forceUpdateScreen(); cameraView(7.0, 0.0, 45.0); '
        'lights_beam(false, false); road(true, 9.0, 12.0, 3.2, {1.0, 1.0, 1.0, 0.1}, true, {0.0, 0.0, 0.0, 0.5}, true); waitOnRendering(1000)\n'
        "    end\n"
        "end"
    ),
}


_LOCAL_DIRECT_SCREENSHOT_LUA_BY_TEST = {
    "lights_LowBeam": (
        "reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); "
        'R.logic().interfaces["Interface_Lights"]["IN"]["HighBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LowBeam_isActive"].value = true; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LightCones_isVisible"].value = true; '
        "waitOnRendering(1000); "
        'R.screenshot("__SGPREFLIGHT_SCREENSHOT_PATH__")'
    ),
    "lights_HighBeam": (
        "reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); "
        'R.logic().interfaces["Interface_Lights"]["IN"]["HighBeam_isActive"].value = true; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LowBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LightCones_isVisible"].value = true; '
        "waitOnRendering(1000); "
        'R.screenshot("__SGPREFLIGHT_SCREENSHOT_PATH__")'
    ),
    "lights_OnlyCones": (
        "reset(); forceUpdateScreen(); cameraView(7.0, 0.0, 45.0); "
        'R.logic().interfaces["Interface_Lights"]["IN"]["HighBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LowBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LightCones_isVisible"].value = true; '
        'road(true, 9.0, 12.0, 3.2, {1.0, 1.0, 1.0, 0.1}, true, {0.0, 0.0, 0.0, 0.5}, true); '
        "waitOnRendering(1000); "
        'R.screenshot("__SGPREFLIGHT_SCREENSHOT_PATH__")'
    ),
}


_LOCAL_PROXY_SCREENSHOT_LUA_BY_TEST = {
    "lights_LowBeam": (
        "reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); "
        'R.logic().interfaces["Interface_Lights"]["IN"]["HighBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LowBeam_isActive"].value = true; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LightCones_isVisible"].value = false; '
        "waitOnRendering(1000); "
        'R.screenshot("__SGPREFLIGHT_SCREENSHOT_PATH__")'
    ),
    "lights_HighBeam": (
        "reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); "
        'R.logic().interfaces["Interface_Lights"]["IN"]["HighBeam_isActive"].value = true; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LowBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LightCones_isVisible"].value = false; '
        "waitOnRendering(1000); "
        'R.screenshot("__SGPREFLIGHT_SCREENSHOT_PATH__")'
    ),
}


def _sanitize_filter_slug(filter_name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", filter_name.strip().lower())
    return cleaned.strip("_") or "all_tests"


def _resolve_battery_selected_tests(filter_name: str, all_tests: list[str] | tuple[str, ...]) -> list[str]:
    exact = _BATTERY_SCENARIO_SELECTORS.get(filter_name)
    if exact:
        available = set(all_tests)
        return [name for name in exact if name in available]
    return [test for test in all_tests if filter_name in test]


def _render_local_battery_override_lua(selected_tests: tuple[str, ...] | list[str]) -> str:
    lines: list[str] = []
    for test_name in selected_tests:
        override = _LOCAL_BATTERY_TEST_OVERRIDES.get(test_name)
        if override:
            if lines:
                lines.append("")
            lines.append("-- Local SG preflight override: wait for beam-light resources before screenshot.")
            lines.append(override)
    return "\n".join(lines).strip()


def _render_local_call_screenshot_override_lua(selected_tests: tuple[str, ...] | list[str]) -> str:
    if not selected_tests:
        return ""
    return "\n".join(
        [
            "-- Local SG preflight override: instrument per-test screenshot execution.",
            "function callSingleScreenshotTest(name, path)",
            "    local test = testViews[name]",
            "    if test == nil then",
            f'        print("{_LUA_TEST_STATUS_SENTINEL}" .. tostring(name) .. "|false|missing_test")',
            "        return",
            "    end",
            "    if not test.enabled then",
            f'        print("{_LUA_TEST_STATUS_SENTINEL}" .. tostring(name) .. "|false|disabled_test")',
            "        return",
            "    end",
            "    local ok, err = pcall(function() test.update(0) end)",
            f'    print("{_LUA_TEST_STATUS_SENTINEL}" .. tostring(name) .. "|" .. tostring(ok) .. "|" .. tostring(err))',
            "    if ok then",
            "        waitOnRendering(1000)",
            '        local screenshotPath = path .. "/" .. tostring(name) .. ".png"',
            "        local shotOk, shotErr = pcall(function() R.screenshot(screenshotPath) end)",
            f'        print("{_LUA_SCREENSHOT_STATUS_SENTINEL}" .. tostring(name) .. "|" .. tostring(shotOk) .. "|" .. tostring(shotErr))',
            "    end",
            "end",
            "",
            "function callScreenshotTests(path)",
            "    for name, test in pairs(testViews) do",
            "        if test.enabled then",
            "            callSingleScreenshotTest(name, path)",
            "        end",
            "    end",
            "end",
        ]
    ).strip()


def _render_local_direct_screenshot_templates(selected_tests: tuple[str, ...] | list[str]) -> dict[str, str]:
    return {
        test_name: template
        for test_name in selected_tests
        if (template := _LOCAL_DIRECT_SCREENSHOT_LUA_BY_TEST.get(test_name))
    }


def _render_local_proxy_screenshot_templates(selected_tests: tuple[str, ...] | list[str]) -> dict[str, str]:
    return {
        test_name: template
        for test_name in selected_tests
        if (template := _LOCAL_PROXY_SCREENSHOT_LUA_BY_TEST.get(test_name))
    }
