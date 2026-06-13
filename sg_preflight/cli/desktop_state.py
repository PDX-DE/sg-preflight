from __future__ import annotations

import argparse
from importlib import import_module
from pathlib import Path

common = import_module("sg_preflight.cli")


def handle_desktop_state_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "desktop-state":
        state_root = common._resolve_workspace(args)
        if args.desktop_state_command == "profiles":
            payload = common.desktop_profiles(state_root)
        elif args.desktop_state_command == "overview":
            payload = common.desktop_operator_overview(
                state_root,
                profile_id=args.profile_id or "",
            )
        elif args.desktop_state_command == "actions":
            payload = common.desktop_actions_for_profile(args.profile_id, state_root)
        elif args.desktop_state_command == "blockers":
            payload = common.desktop_blocker_items(args.profile_id, state_root)
        elif args.desktop_state_command == "manual":
            payload = common.desktop_manual_cards(args.profile_id, state_root)
        elif args.desktop_state_command == "surfaces":
            payload = common.desktop_surface_items(args.profile_id, state_root)
        elif args.desktop_state_command == "snapshot":
            payload = common.desktop_action_snapshot(args.run_id_or_path, state_root)
        elif args.desktop_state_command == "recent-actions":
            payload = common.desktop_recent_actions(
                state_root,
                profile_id=args.profile_id or "",
                limit=args.limit,
            )
        elif args.desktop_state_command == "recent-runs":
            payload = common.desktop_recent_runs(
                state_root,
                profile_id=args.profile_id or "",
                limit=args.limit,
            )
        elif args.desktop_state_command == "run-snapshot":
            payload = common.desktop_run_snapshot(args.run_id_or_path, state_root)
        elif args.desktop_state_command == "environment":
            payload = common.desktop_environment_doctor(state_root)
        elif args.desktop_state_command == "review-board":
            payload = common.build_review_board_state(args.ticket_id or None, state_root)
        elif args.desktop_state_command == "delivery-readiness":
            repo_root = Path(args.repo_root).resolve() if args.repo_root else None
            bmw_repo_root = Path(args.bmw_repo_root).resolve() if args.bmw_repo_root else None
            payload = common.build_delivery_readiness_board(
                repo_root,
                workspace_root=state_root,
                bmw_repo_root=bmw_repo_root,
            ).to_dict()
        elif args.desktop_state_command == "disabled-tests":
            repo_root = Path(args.repo_root).resolve() if args.repo_root else None
            bmw_repo_root = Path(args.bmw_repo_root).resolve() if args.bmw_repo_root else None
            payload = common.build_disabled_tests_board(
                repo_root,
                workspace_root=state_root,
                bmw_repo_root=bmw_repo_root,
            ).to_dict()
        elif args.desktop_state_command == "api-version-coverage":
            repo_root = Path(args.repo_root).resolve() if args.repo_root else None
            bmw_repo_root = Path(args.bmw_repo_root).resolve() if args.bmw_repo_root else None
            payload = common.build_api_version_coverage_board(
                repo_root,
                workspace_root=state_root,
                bmw_repo_root=bmw_repo_root,
            ).to_dict()
        elif args.desktop_state_command == "country-variant-coverage":
            repo_root = Path(args.repo_root).resolve() if args.repo_root else None
            bmw_repo_root = Path(args.bmw_repo_root).resolve() if args.bmw_repo_root else None
            payload = common.build_country_variant_coverage_board(
                repo_root,
                workspace_root=state_root,
                bmw_repo_root=bmw_repo_root,
            ).to_dict()
        elif args.desktop_state_command == "export-size-trend":
            repo_root = Path(args.repo_root).resolve() if args.repo_root else None
            payload = common.build_export_size_trend_board(
                repo_root,
                workspace_root=state_root,
            ).to_dict()
        elif args.desktop_state_command == "attach-manual-evidence":
            payload = common.attach_manual_evidence(
                args.run_id_or_path,
                state_root,
                kind=args.kind,
                label=args.label,
                source_path=args.source,
                note=args.note,
            )
        else:
            parser.error(f"Unhandled desktop-state command: {args.desktop_state_command}")
            return 1

        common._console_desktop_payload(payload)
        return 0

    parser.error(f"Unhandled desktop-state command: {args.command}")
    return 1
