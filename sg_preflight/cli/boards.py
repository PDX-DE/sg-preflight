from __future__ import annotations

import argparse
from pathlib import Path

from sg_preflight.cli._common import (
    _console_api_version_coverage,
    _console_country_variant_coverage,
    _console_cross_domain_delivery,
    _console_disabled_tests,
    _console_export_size_trend,
    _console_perspectives_inventory,
    _emit_json,
    _resolve_workspace,
    build_api_version_coverage_board,
    build_country_variant_coverage_board,
    build_cross_domain_delivery_board,
    build_disabled_tests_board,
    build_export_size_trend_board,
    build_perspectives_inventory_board,
    write_api_version_coverage_board,
    write_country_variant_coverage_board,
    write_cross_domain_delivery_board,
    write_disabled_tests_board,
    write_export_size_trend_board,
    write_perspectives_inventory_board,
)


BOARD_COMMANDS = {
    "disabled-tests",
    "api-version-coverage",
    "country-variant-coverage",
    "cross-domain-delivery",
    "perspectives-inventory",
    "export-size-trend",
}


def handle_board_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "disabled-tests":
        disabled_root = _resolve_workspace(args)
        repo_root = Path(args.repo_root).resolve() if args.repo_root else None
        bmw_repo_root = Path(args.bmw_repo_root).resolve() if args.bmw_repo_root else None
        board = build_disabled_tests_board(repo_root, workspace_root=disabled_root, bmw_repo_root=bmw_repo_root)
        payload = board.to_dict()
        if args.output_root:
            payload["artifacts"] = write_disabled_tests_board(board, Path(args.output_root).resolve())
        if args.json:
            _emit_json(payload, args)
        else:
            _console_disabled_tests(payload)
        return 0

    if args.command == "api-version-coverage":
        api_root = _resolve_workspace(args)
        repo_root = Path(args.repo_root).resolve() if args.repo_root else None
        bmw_repo_root = Path(args.bmw_repo_root).resolve() if args.bmw_repo_root else None
        board = build_api_version_coverage_board(repo_root, workspace_root=api_root, bmw_repo_root=bmw_repo_root)
        payload = board.to_dict()
        if args.output_root:
            payload["artifacts"] = write_api_version_coverage_board(board, Path(args.output_root).resolve())
        if args.json:
            _emit_json(payload, args)
        else:
            _console_api_version_coverage(payload)
        return 0

    if args.command == "country-variant-coverage":
        variant_root = _resolve_workspace(args)
        repo_root = Path(args.repo_root).resolve() if args.repo_root else None
        bmw_repo_root = Path(args.bmw_repo_root).resolve() if args.bmw_repo_root else None
        board = build_country_variant_coverage_board(
            repo_root,
            workspace_root=variant_root,
            bmw_repo_root=bmw_repo_root,
        )
        payload = board.to_dict()
        if args.output_root:
            payload["artifacts"] = write_country_variant_coverage_board(board, Path(args.output_root).resolve())
        if args.json:
            _emit_json(payload, args)
        else:
            _console_country_variant_coverage(payload)
        return 0

    if args.command == "cross-domain-delivery":
        board_root = _resolve_workspace(args)
        repo_root = Path(args.repo_root).resolve() if args.repo_root else None
        bmw_repo_root = Path(args.bmw_repo_root).resolve() if args.bmw_repo_root else None
        board = build_cross_domain_delivery_board(
            repo_root,
            workspace_root=board_root,
            bmw_repo_root=bmw_repo_root,
        )
        payload = board.to_dict()
        if args.output_root:
            payload["artifacts"] = write_cross_domain_delivery_board(board, Path(args.output_root).resolve())
        if args.json:
            _emit_json(payload, args)
        else:
            _console_cross_domain_delivery(payload)
        return 0

    if args.command == "perspectives-inventory":
        board_root = _resolve_workspace(args)
        repo_root = Path(args.repo_root).resolve() if args.repo_root else None
        board = build_perspectives_inventory_board(
            repo_root,
            workspace_root=board_root,
        )
        payload = board.to_dict()
        if args.output_root:
            payload["artifacts"] = write_perspectives_inventory_board(board, Path(args.output_root).resolve())
        if args.json:
            _emit_json(payload, args)
        else:
            _console_perspectives_inventory(payload)
        return 0

    if args.command == "export-size-trend":
        trend_root = _resolve_workspace(args)
        repo_root = Path(args.repo_root).resolve() if args.repo_root else None
        board = build_export_size_trend_board(repo_root, workspace_root=trend_root)
        payload = board.to_dict()
        if args.output_root:
            payload["artifacts"] = write_export_size_trend_board(board, Path(args.output_root).resolve())
        if args.json:
            _emit_json(payload, args)
        else:
            _console_export_size_trend(payload)
        return 0

    parser.error(f"Unhandled board command: {args.command}")
    return 1
