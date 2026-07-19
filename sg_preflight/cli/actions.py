"""Handles the run-action, launch-action, run-action-worker, and dependency-setup-worker
CLI commands that execute or background-launch a single operator action."""

from __future__ import annotations

import argparse
from importlib import import_module
import json
import sys
from pathlib import Path

common = import_module("sg_preflight.cli")


def _console_action_record(record: object, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Action run ID: {record.run_id}")
    print(f"Action: {record.action_id} ({record.label})")
    print(f"Status: {record.status}")
    if record.profile_id:
        print(f"Profile: {record.profile_id}")
    if record.blocker_message:
        print(f"Blocker: {record.blocker_message}")
    if record.error_message:
        print(f"Error: {record.error_message}")
    print(f"Output root: {record.paths['output_root']}")
    print(f"Log: {record.paths['log']}")
    print(f"Summary JSON: {record.paths['summary_json']}")
    print(f"Summary Markdown: {record.paths['summary_md']}")
    if record.summary:
        for line in record.summary.get("lines", []):
            print(f"  - {line}")
    if record.artifacts:
        print("Artifacts:")
        for artifact in record.artifacts:
            print(f"  - {artifact.get('label', 'artifact')}: {artifact.get('path', '')}")


def handle_action_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "run-action":
        try:
            action_root = common._resolve_workspace(args)
            action = common.get_operator_action(args.action_id, action_root)
        except KeyError as exc:
            parser.error(str(exc))
            return 1

        try:
            record = common.execute_operator_action(action, action_root)
        except Exception as exc:
            print(common._console_safe(f"run-action failed: {exc}"), file=sys.stderr)
            return 1
        common._console_action_record(record, as_json=args.json)
        return 0 if record.status in {"completed", "blocked"} else 1

    if args.command == "launch-action":
        action_root = common._resolve_workspace(args)
        try:
            action = common.get_operator_action(args.action_id, action_root)
        except KeyError as exc:
            parser.error(str(exc))
            return 1

        record = common.build_action_record(action, action_root)
        common.save_action_record(record)
        worker_command = common.sgfx_cli_command(
            "run-action-worker",
            action.action_id,
            "--run-id",
            record.run_id,
            "--workspace",
            str(action_root),
            bytecode=False,
        )
        creationflags = getattr(common.subprocess, "CREATE_NO_WINDOW", 0)
        try:
            common.subprocess.Popen(
                worker_command,
                cwd=action_root,
                stdout=common.subprocess.DEVNULL,
                stderr=common.subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            print(common._console_safe(f"launch-action failed: {exc}"), file=sys.stderr)
            return 1
        common._console_action_record(record, as_json=args.json)
        return 0

    if args.command == "run-action-worker":
        action_root = Path(args.workspace).resolve()
        try:
            action = common.get_operator_action(args.action_id, action_root)
            record = common.load_action_record(args.run_id, action_root)
            result = common.execute_operator_action(action, action_root, record=record)
        except Exception as exc:
            print(common._console_safe(f"run-action-worker failed: {exc}"), file=sys.stderr)
            return 1
        return 0 if result.status in {"completed", "blocked"} else 1

    if args.command == "dependency-setup-worker":
        action_root = Path(args.workspace).resolve()
        try:
            from sg_preflight.dependency_onboarding import run_dependency_setup_action

            payload = run_dependency_setup_action(
                action_id=args.action_id,
                workspace=action_root,
                operator_confirmed=True,
                target_path=args.target_path or None,
                source_path=args.source_path or None,
                stream_output=True,
            )
        except Exception as exc:
            print(common._console_safe(f"dependency-setup-worker failed: {exc}"), file=sys.stderr)
            return 1
        print(json.dumps(common._json_ready(payload), ensure_ascii=False))
        return 1 if payload.get("status") == "failed" else 0

    parser.error(f"Unhandled action command: {args.command}")
    return 1
