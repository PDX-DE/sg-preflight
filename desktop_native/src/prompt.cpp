#include "prompt.hpp"

namespace sg_preflight::native_shell {

std::string ShortActionLabel(const std::string& action_id) {
    if (action_id == "daily_live_matrix") {
        return "DAILY";
    }
    if (action_id.find("qa_stack__") == 0) {
        return "STACK";
    }
    if (action_id.find("repo_checker_") == 0) {
        return "REPO";
    }
    if (action_id.find("scene_check__") == 0) {
        return "SCENE";
    }
    if (action_id.find("unused_resources__") == 0) {
        return "UNUSED";
    }
    if (action_id.find("delivery_checklist__") == 0) {
        return "DELIVERY";
    }
    return "ACTION";
}

std::string FriendlyActionDescription(std::string_view action_id) {
    const std::string short_label = ShortActionLabel(std::string(action_id));
    if (short_label == "DAILY") {
        return "Run the recommended local checks across every ready slice and collect one shared review surface.";
    }
    if (short_label == "STACK") {
        return "Run the standard per-slice SG preflight stack for the selected slice.";
    }
    if (short_label == "REPO") {
        return "Run the SG repository-wide checker pass to catch broader issues outside one slice.";
    }
    if (short_label == "SCENE") {
        return "Run the scene-specific check for the selected slice.";
    }
    if (short_label == "UNUSED") {
        return "Scan the selected slice for unused resources that should be cleaned up or reviewed.";
    }
    if (short_label == "DELIVERY") {
        return "Prepare the delivery-readiness view and show the follow-up items that still need attention.";
    }
    return {};
}

std::string BuildHelpPromptMessage(ShellScreen screen) {
    switch (screen) {
    case ShellScreen::Introduction:
        return "SGFX: Project Quality-Hero is the local desktop operator shell for SG-side 3D Car QA review.\n\nUse the workflow from left to right: choose a slice, choose a check, review it, run it, open the first files that need attention, then review reports, exports, and follow-up work.\n\nIt does not replace Blender visual review, RaCo / RaCoHeadless, rack sessions, or BMW screenshot smoke. Use it to get deterministic SG-side evidence first, keep blocked/manual work visible, and hand off a cleaner bug report surface.";
    case ShellScreen::Select:
        return "Choose one slice on the right, then choose the local check to run for that slice.\n\nDAILY: runs the recommended local check flow across every ready slice.\nSTACK: runs the standard per-slice QA stack.\nREPO: runs the broader repository checker pass.\nSCENE: runs the scene-specific local check.\nUNUSED: scans the selected slice for unused resources.\nDELIVERY: shows delivery-readiness follow-up for the selected slice.";
    case ShellScreen::Review:
        return "Review confirms what is about to run.\n\nCheck that the selected slice and the selected check are correct before you start the run.";
    case ShellScreen::Run:
        return "Run shows live status while the selected check is queued or running.\n\nStay here to watch progress, refresh the state, and open the raw log or linked result when they are available.";
    case ShellScreen::Evidence:
        return "Open First points to the first files that need attention.\n\nUse this page when you want the most important evidence first instead of searching through every output manually.";
    case ShellScreen::Files:
        return "Files collects generated outputs, reports, source files, and copy-ready exports.\n\nUse it when you need to open deliverables or copy material into Jira, QA Hero, or handoff notes.";
    case ShellScreen::Environment:
        return "Environment Doctor shows what this machine can actually do right now.\n\nUse it to confirm Python/backend readiness, mirrored SG checker coverage, local RaCo or Blender adapters, BMW blockers, and output write access before you overclaim later stages.";
    case ShellScreen::Stages:
        return "Stages keeps the remaining follow-up visible.\n\nUse it to review blocked BMW/manual items, open the BMW intake checklist, attach manual evidence into the active action bundle, and keep audio/settings honest before you loop back to the next slice.";
    case ShellScreen::ReviewBoard:
        return "SGFX QA Status Board is the operator summary for the latest packaged review state.\n\nUse it to check package verification, the DoD summary, smoke and battery counts, the top review-priority items, owner decisions, and the exact artifact links that should be opened first.";
    case ShellScreen::Language:
        return "Choose the language used by the shell interface.\n\nProject data, checker output, and generated files stay the same.";
    default:
        return "Use SGFX: Project Quality-Hero from left to right: choose a slice, choose the check, review it, run it, open the first results, then review files and follow-up.";
    }
}

}  // namespace sg_preflight::native_shell
