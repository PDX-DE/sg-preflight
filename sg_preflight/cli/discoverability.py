"""CLI discoverability surface for argparse.

Owns the daily-use action map, per-command example epilogs, the custom
argparse parser/version action, and the build/version-stamp helpers they use.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sg_preflight import __version__

root = Path(__file__).resolve().parents[2]


def _is_frozen_exe() -> bool:
    return bool(getattr(sys, "frozen", False))


class _SgfxArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)


class _VersionAction(argparse.Action):
    def __init__(self, option_strings: list[str], dest: str = argparse.SUPPRESS, **kwargs: object) -> None:
        super().__init__(option_strings=option_strings, dest=dest, nargs=0, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        parser._print_message(f"{_version_text()}\n", sys.stdout)
        parser.exit(0)


_MAIN_ACTION_MAP: tuple[tuple[str, str, str], ...] = (
    (
        "full-qa-pass",
        "Run the local QA pass sequence for one car.",
        r"sgfx-preflight.exe full-qa-pass run --profile G65 --workspace C:\repositories\trunk --format json",
    ),
    (
        "dashboard",
        "Open the Clean or Grafiks operator dashboard.",
        r"sgfx-preflight.exe dashboard run --workspace C:\repositories\trunk --ui-mode clean",
    ),
    (
        "screenshot-test-state",
        "Read local screenshot expected/actual/diff state.",
        "sgfx-preflight.exe screenshot-test-state read --profile G65 --format json",
    ),
    (
        "screenshot-review-viewer",
        "Build the side-by-side expected/actual/diff viewer.",
        r"sgfx-preflight.exe screenshot-review-viewer build --profile F70 --workspace C:\repositories\trunk",
    ),
    (
        "delivery-workbook",
        "Inspect the delivery workbook generation trigger.",
        r"sgfx-preflight.exe delivery-workbook trigger --profile F70 --workspace C:\repositories\trunk --format json",
    ),
    (
        "delivery-documentation",
        "Read operator-local delivery workbook evidence.",
        r"sgfx-preflight.exe delivery-documentation read --profile G65 --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "export-size-analysis",
        "Read the operator-local size-analysis workbook.",
        r"sgfx-preflight.exe export-size-analysis read --profile G65 --workspace C:\repositories\trunk --latest --format markdown",
    ),
    (
        "quality-hero-report",
        "Generate Markdown or HTML review reports from local evidence.",
        r"sgfx-preflight.exe quality-hero-report generate --profile G70 --workspace C:\repositories\trunk --format html",
    ),
    (
        "daily-digest",
        "Build the latest copy-ready local daily digest.",
        r"sgfx-preflight.exe daily-digest latest --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "team-digest-board",
        "Build the local team digest board snapshot.",
        r"sgfx-preflight.exe team-digest-board snapshot --profile G70 --profile G65 --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "risk-score",
        "Read per-car local risk score with review deltas.",
        r"sgfx-preflight.exe risk-score read --profile G65 --workspace C:\repositories\trunk --format json",
    ),
    (
        "cross-car-comparison",
        "Compare two profiles with the same local risk widget.",
        r"sgfx-preflight.exe cross-car-comparison snapshot --profile G70 --comparison-profile G65 --workspace C:\repositories\trunk --format json",
    ),
    (
        "profile-summary",
        "Build a shareable per-profile HTML or export the full evidence zip.",
        r"sgfx-preflight.exe profile-summary build --profile G70 --workspace C:\repositories\trunk --html-output G70_summary.html",
    ),
    (
        "operator-handoff",
        "Record or read an operator-local stopping point.",
        r"sgfx-preflight.exe operator-handoff latest --profile G65 --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "manual-review",
        "Create and update operator-recorded manual-review sessions.",
        r"sgfx-preflight.exe manual-review assist --profile G65 --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "bmw-git-readiness",
        "Read local BMW Git profile readiness without writing to it.",
        "sgfx-preflight.exe bmw-git-readiness read --profile G65 --format json",
    ),
    (
        "qa-hero-readiness",
        "Read local Quality Hero asset-readiness signals.",
        "sgfx-preflight.exe qa-hero-readiness read --profile G65 --format json",
    ),
    ("list-profiles", "List canonical live run profiles.", "sgfx-preflight.exe list-profiles --format json"),
    ("list-actions", "List one-click local actions.", "sgfx-preflight.exe list-actions --format json"),
    ("template", "Manage operator-local saved command templates.", "sgfx-preflight.exe template list --format json"),
    (
        "onboarding-guide",
        "Read setup guidance for one profile.",
        r"sgfx-preflight.exe onboarding-guide read --profile G65 --workspace C:\repositories\trunk --format markdown",
    ),
    (
        "desktop-notification",
        "Record or show a local desktop notification.",
        'sgfx-preflight.exe desktop-notification send --title "SGFX check complete" --message "F70 pass finished." --dry-run --format json',
    ),
    (
        "daily-qa-snapshot",
        "Run the local daily QA snapshot for selected profiles.",
        r"sgfx-preflight.exe daily-qa-snapshot --profile G70 --workspace C:\repositories\trunk --no-smoke --json",
    ),
    (
        "ticket-review",
        "Generate a ticket-centered local review package.",
        r"sgfx-preflight.exe ticket-review IDCEVODEV-1009239 --profile G70 --workspace C:\repositories\trunk --json",
    ),
    (
        "review-board",
        "Inspect local review-board packages.",
        r"sgfx-preflight.exe review-board latest --workspace C:\repositories\trunk --json",
    ),
    ("workflow-status", "List workflow coverage and known partial areas.", "sgfx-preflight.exe workflow-status --json"),
    (
        "activity-log",
        "Read or tail the operator-local activity log.",
        r"sgfx-preflight.exe activity-log read --workspace C:\repositories\trunk --tail",
    ),
    (
        "live-state",
        "Read or tail the operator-local dashboard live-state telemetry.",
        r"sgfx-preflight.exe live-state --workspace C:\repositories\trunk --tail",
    ),
    (
        "session-log",
        "Read or export the operator-local session diagnostic log.",
        r"sgfx-preflight.exe session-log latest --workspace C:\repositories\trunk",
    ),
    ("station", "Run the optional local OpenHTF station surface.", r"sgfx-preflight.exe station run --profile G65 --workspace C:\repositories\trunk --no-browser --once"),
    ("desktop-state", "Inspect desktop-shell state snapshots.", r"sgfx-preflight.exe desktop-state overview --profile-id G65 --workspace C:\repositories\trunk --json"),
    ("run-action", "Execute one registered local action.", r"sgfx-preflight.exe run-action qa_stack__g65 --workspace C:\repositories\trunk --json"),
    ("launch-action", "Queue one registered local action for polling clients.", r"sgfx-preflight.exe launch-action qa_stack__g65 --workspace C:\repositories\trunk --json"),
    ("review-priority", "Inspect latest screenshot review-priority artifact.", r"sgfx-preflight.exe review-priority latest --workspace C:\repositories\trunk --json"),
    ("daily-delta", "Inspect latest daily QA delta artifact.", r"sgfx-preflight.exe daily-delta latest --workspace C:\repositories\trunk --json"),
    ("review-decisions", "Record and inspect review-owner decisions.", r"sgfx-preflight.exe review-decisions latest IDCEVODEV-1009239 --workspace C:\repositories\trunk --json"),
    ("external-findings", "Record and inspect external review findings.", r"sgfx-preflight.exe external-findings latest IDCEVODEV-1009239 --workspace C:\repositories\trunk --json"),
    ("run-profile", "Materialize and validate one canonical profile.", r"sgfx-preflight.exe run-profile G65 --output-root out\run-profile-g65 --json"),
    ("run", "Run validation packs against an existing bundle.", r"sgfx-preflight.exe run --bundle out\bundle --config config\sg_rules.json --packs anchors --fail-on warning"),
    ("list-checkers", "List checker coverage and readiness.", "sgfx-preflight.exe list-checkers --format json"),
    (
        "bmw-pipeline-diagnostics",
        "Inspect missing-actual diagnostics with confirmation-gated refresh actions.",
        r"sgfx-preflight.exe bmw-pipeline-diagnostics missing-actuals --profile F70 --workspace C:\repositories\trunk --format json",
    ),
    ("screenshot-triage", "Run deterministic screenshot triage.", r"sgfx-preflight.exe screenshot-triage --profile F70 --workspace C:\repositories\trunk --json"),
    ("materialize", "Create a normalized validation bundle from SG-shaped inputs.", r"sgfx-preflight.exe materialize --output-bundle out\bundle --repo-root C:\repositories\trunk --project-root C:\repositories\trunk\Cars\BMW\G45"),
    ("probe", "Discover SG-style repository roots and likely inputs.", r"sgfx-preflight.exe probe --search-root C:\repositories\trunk"),
    # `demo-good`, `demo-broken`, `ui`, `retro-extract` subcommands stay
    # registered for backward compat but are hidden from the operator-facing
    # action map. They're dev / legacy entries that don't belong in the daily-
    # use list.
)


_MAIN_ACTION_EXAMPLES = {command: example for command, _description, example in _MAIN_ACTION_MAP}


_COMMAND_EXAMPLES: dict[str, tuple[str, ...]] = {
    "full-qa-pass": (_MAIN_ACTION_EXAMPLES["full-qa-pass"],),
    "full-qa-pass run": (_MAIN_ACTION_EXAMPLES["full-qa-pass"],),
    "delivery-workbook": (_MAIN_ACTION_EXAMPLES["delivery-workbook"],),
    "delivery-workbook trigger": (_MAIN_ACTION_EXAMPLES["delivery-workbook"],),
    "delivery-documentation": (_MAIN_ACTION_EXAMPLES["delivery-documentation"],),
    "delivery-documentation read": (_MAIN_ACTION_EXAMPLES["delivery-documentation"],),
    "integration": (
        "sgfx-preflight.exe integration jira status --format json",
    ),
    "integration jira": (
        "sgfx-preflight.exe integration jira status --format json",
    ),
    "integration jira weekly-tickets": (
        r"sgfx-preflight.exe integration jira weekly-tickets --workspace C:\repositories\trunk --format markdown",
    ),
    "integration jira post-comment": (
        'sgfx-preflight.exe integration jira post-comment --ticket IDCEVODEV-1009239 --body "Local QA evidence is ready for review." --format json',
    ),
    "integration jira status": (
        "sgfx-preflight.exe integration jira status --ticket IDCEVODEV-1009244 --format json",
    ),
    "integration jira register": (
        r"sgfx-preflight.exe integration jira register --jira-url https://jira.cc.bmwgroup.net --pat-file C:\secure\jira-pat.txt --confirm-local-write --format json",
    ),
    "integration jira update-issue": ('sgfx-preflight.exe integration jira update-issue --ticket IDCEVODEV-1009239 --fields "{""fields"":{""labels"":[""sgfx""]}}" --format json',),
    "integration jira attach-file": (r"sgfx-preflight.exe integration jira attach-file --ticket IDCEVODEV-1009239 --file out\review.md --format json",),
    "screenshot-review-viewer": (_MAIN_ACTION_EXAMPLES["screenshot-review-viewer"],),
    "screenshot-review-viewer build": (_MAIN_ACTION_EXAMPLES["screenshot-review-viewer"],),
    "dashboard": (_MAIN_ACTION_EXAMPLES["dashboard"], r"sgfx-preflight.exe dashboard run --workspace C:\repositories\trunk --ui-mode grafiks"),
    "dashboard run": (_MAIN_ACTION_EXAMPLES["dashboard"],),
    "desktop-state": (r"sgfx-preflight.exe desktop-state overview --profile-id G65 --workspace C:\repositories\trunk --json",),
    "desktop-state overview": (r"sgfx-preflight.exe desktop-state overview --profile-id G65 --workspace C:\repositories\trunk --json",),
    "quality-hero-report": (_MAIN_ACTION_EXAMPLES["quality-hero-report"],),
    "quality-hero-report generate": (_MAIN_ACTION_EXAMPLES["quality-hero-report"],),
    "bmw-pipeline-diagnostics": (
        r"sgfx-preflight.exe bmw-pipeline-diagnostics missing-actuals --profile F70 --workspace C:\repositories\trunk --format json",
    ),
    "bmw-pipeline-diagnostics missing-actuals": (
        r"sgfx-preflight.exe bmw-pipeline-diagnostics missing-actuals --profile F70 --workspace C:\repositories\trunk --format json",
    ),
    "template": (_MAIN_ACTION_EXAMPLES["template"],),
    "template save": ('sgfx-preflight.exe template save f70-pass --command full-qa-pass --args "run --profile F70 --workspace C:\\repositories\\trunk" --json',),
    "template run": ("sgfx-preflight.exe template run f70-pass",),
    "template list": (_MAIN_ACTION_EXAMPLES["template"],),
    "template show": ("sgfx-preflight.exe template show f70-pass --json",),
    "template delete": ("sgfx-preflight.exe template delete f70-pass --json",),
    "manual-review": (_MAIN_ACTION_EXAMPLES["manual-review"],),
    "manual-review session": (r"sgfx-preflight.exe manual-review session --profile G65 --ticket IDCEVODEV-1009239 --workspace C:\repositories\trunk --format json",),
    "manual-review assist": (_MAIN_ACTION_EXAMPLES["manual-review"],),
    "manual-review auto-checks": (r"sgfx-preflight.exe manual-review auto-checks --profile G65 --workspace C:\repositories\trunk --format markdown",),
    "manual-review templates": ("sgfx-preflight.exe manual-review templates --json",),
    "manual-review record-step": (r"sgfx-preflight.exe manual-review record-step out\session.json --step blender_visual_check --verdict incomplete --note ""Needs reviewer follow-up."" --json",),
    "manual-review summary": (r"sgfx-preflight.exe manual-review summary out\session.json --format markdown",),
    "manual-review open-raco": (r"sgfx-preflight.exe manual-review open-raco out\session.json --step blender_visual_check --json",),
    "manual-review open-blender": (r"sgfx-preflight.exe manual-review open-blender out\session.json --step blender_visual_check --json",),
    "desktop-notification": (_MAIN_ACTION_EXAMPLES["desktop-notification"],),
    "desktop-notification send": (_MAIN_ACTION_EXAMPLES["desktop-notification"],),
}


def _main_help_epilog() -> str:
    lines = [
        "Daily-use action map (frequency ordered):",
    ]
    for command, description, example in _MAIN_ACTION_MAP:
        lines.append(f"  {command:<26} {description}")
        lines.append(f"    example: {example}")
    lines.append("")
    lines.append("Use 'sgfx-preflight.exe <action> --help' for flags and command-specific examples.")
    return "\n".join(lines)


def _command_path_from_prog(prog: str) -> str:
    parts = prog.split()
    if parts and parts[0] in {"sg-preflight", "sgfx-preflight.exe"}:
        parts = parts[1:]
    return " ".join(parts)


def _default_example_for(prog: str) -> str:
    path = _command_path_from_prog(prog)
    return f"sgfx-preflight.exe {path} --help".strip()


def _examples_epilog(parser: argparse.ArgumentParser) -> str:
    path = _command_path_from_prog(parser.prog)
    examples = _COMMAND_EXAMPLES.get(path, (None,))
    lines = ["Examples:"]
    for example in examples:
        lines.append(f"  {example or _default_example_for(parser.prog)}")
    return "\n".join(lines)


def _subparser_actions(parser: argparse.ArgumentParser) -> list[argparse._SubParsersAction]:  # type: ignore[attr-defined]
    return [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]


def _install_cli_discoverability(parser: argparse.ArgumentParser) -> None:
    parser.description = (
        "Seriengrafik: Project Quality-Hero local command line. Commands read local evidence by default; Jira and SVN writes stay gated."
        f"\n\n{_main_help_epilog()}"
    )
    parser.epilog = None
    for action in _subparser_actions(parser):
        if action.dest == "command":
            action._choices_actions = []
    pending = [parser]
    while pending:
        current = pending.pop()
        for action in _subparser_actions(current):
            for child in action.choices.values():
                if child.epilog is None:
                    child.epilog = _examples_epilog(child)
                pending.append(child)


def _git_commit_short() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except Exception:
        return "unknown"
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else "unknown"


def _build_stamp() -> str:
    if _is_frozen_exe():
        try:
            timestamp = Path(sys.executable).stat().st_mtime
        except OSError:
            return "unknown"
        return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat()
    return "source"


def _version_text() -> str:
    return f"sg-preflight {__version__}; commit {_git_commit_short()}; build {_build_stamp()}; python {sys.version.split()[0]}"


def _default_prog() -> str:
    if _is_frozen_exe():
        return Path(sys.executable).name
    return "sg-preflight"
