"""CLI handlers for review-board, review-priority, daily-delta, and review-decisions commands."""

from __future__ import annotations

import argparse
from importlib import import_module
import sys
from pathlib import Path

common = import_module("sg_preflight.cli")


def handle_reviews_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "review-board":
        review_root = common._resolve_workspace(args)
        try:
            if args.review_board_command == "list":
                payload = common.list_review_packages(review_root)
            elif args.review_board_command == "latest":
                payload = common.build_review_board_state(args.ticket_id, review_root)
            elif args.review_board_command == "copy-update":
                state = common.build_review_board_state(args.ticket_id, review_root)
                payload = {
                    "ticket_id": state["ticket_id"],
                    "scope": state["scope"],
                    "generated_at": state["generated_at"],
                    "package_path": state["package_path"],
                    "text": common.build_review_owner_update(state),
                }
            elif args.review_board_command == "verify":
                if args.latest:
                    latest = common.build_review_board_state(args.ticket_id, review_root)
                    payload = common.verify_sendable_package(
                        latest["package_zip_path"] or latest["package_path"],
                        review_root,
                    )
                else:
                    payload = common.verify_sendable_package(args.path, review_root)
            else:
                parser.error(f"Unhandled review-board command: {args.review_board_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"review-board failed: {exc}"), file=sys.stderr)
            return 1
        if args.review_board_command == "copy-update" and not args.json:
            print(common._console_safe(str(payload["text"])))
        else:
            common._console_desktop_payload(payload)
        return 0

    if args.command == "review-priority":
        review_root = common._resolve_workspace(args)
        try:
            if args.review_priority_command == "latest":
                payload = common.load_review_priority(args.ticket_id, review_root)
            else:
                parser.error(f"Unhandled review-priority command: {args.review_priority_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"review-priority failed: {exc}"), file=sys.stderr)
            return 1
        common._console_desktop_payload(payload)
        return 0

    if args.command == "daily-delta":
        delta_root = common._resolve_workspace(args)
        try:
            if args.daily_delta_command == "latest":
                payload = common.load_daily_delta(args.ticket_id, delta_root)
            else:
                parser.error(f"Unhandled daily-delta command: {args.daily_delta_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"daily-delta failed: {exc}"), file=sys.stderr)
            return 1
        common._console_desktop_payload(payload)
        return 0

    if args.command == "review-decisions":
        tracking_root = common._resolve_workspace(args)
        try:
            if args.review_decisions_command == "latest":
                package = common.load_latest_review_package(args.ticket_id, tracking_root)
                fallback_path = (
                    Path(package["review_owner_decisions"]["absolute_path"])
                    if package["review_owner_decisions"]["absolute_path"]
                    else None
                )
                payload = common.load_review_decisions(
                    args.ticket_id,
                    tracking_root,
                    fallback_markdown_path=fallback_path,
                )
            elif args.review_decisions_command == "set":
                package = common.load_latest_review_package(args.ticket_id, tracking_root)
                fallback_path = (
                    Path(package["review_owner_decisions"]["absolute_path"])
                    if package["review_owner_decisions"]["absolute_path"]
                    else None
                )
                payload = common.set_review_decision(
                    args.ticket_id,
                    args.decision_key,
                    status=args.status,
                    owner=args.owner,
                    note=args.note,
                    date=args.date,
                    title=args.title,
                    workspace=tracking_root,
                    fallback_markdown_path=fallback_path,
                )
            else:
                parser.error(f"Unhandled review-decisions command: {args.review_decisions_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"review-decisions failed: {exc}"), file=sys.stderr)
            return 1
        common._console_desktop_payload(payload)
        return 0

    if args.command == "external-findings":
        tracking_root = common._resolve_workspace(args)
        try:
            if args.external_findings_command == "latest":
                payload = common.load_external_findings(args.ticket_id, tracking_root)
            elif args.external_findings_command == "add":
                scopes: list[str] = []
                for item in args.scope:
                    scopes.extend(part.strip() for part in str(item).split(",") if part.strip())
                payload = common.add_external_finding(
                    args.ticket_id,
                    source=args.source,
                    reported_by=args.reported_by,
                    category=args.category,
                    scope=scopes,
                    finding=args.finding,
                    owner=args.owner,
                    status=args.status,
                    note=args.note,
                    finding_type=args.finding_type,
                    related_investigation_surfaces=args.related_surface,
                    workspace=tracking_root,
                )
            else:
                parser.error(f"Unhandled external-findings command: {args.external_findings_command}")
                return 1
        except Exception as exc:
            print(common._console_safe(f"external-findings failed: {exc}"), file=sys.stderr)
            return 1
        common._console_desktop_payload(payload)
        return 0

    parser.error(f"Unhandled reviews command: {args.command}")
    return 1
