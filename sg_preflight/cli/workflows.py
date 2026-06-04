from __future__ import annotations

import argparse
from importlib import import_module
import json
import sys
from pathlib import Path

common = import_module("sg_preflight.cli")


def _console_workflow_status(items: list[dict[str, object]], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(items, indent=2, ensure_ascii=False))
        return

    print("Workflow status:")
    for item in items:
        print(f"- {item['label']}: state={item['state']}")
        print(f"  {item['summary']}")
        blockers = item.get("blockers", [])
        if blockers:
            print("  blockers:")
            for blocker in blockers:
                print(f"    - {blocker}")


def handle_workflow_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "workflow-status":
        items = common.qa_workflow_status(common.root)
        output_format = common._resolve_render_format(args, parser, formats=("text", "json"))
        common._emit_console(lambda: common._console_workflow_status(items, as_json=output_format == "json"), args)
        return 0

    if args.command == "list-workflows":
        from sg_preflight import qa_workflows as qw

        summaries = [s.to_dict() for s in qw.list_workflows(workspace_root=common.root)]
        if args.json:
            print(json.dumps(summaries, indent=2))
        else:
            if not summaries:
                print("(no workflows found in qa_workflows/)")
            for summary in summaries:
                print(f"- {summary['id']:<40} {summary['name']}")
                print(
                    f"    scope: {','.join(summary['scope_kinds'])}  "
                    f"profiles: {','.join(summary['profiles']) or '-'}"
                )
                print(
                    f"    dod: {summary['dod_count']}  "
                    f"checks: {summary['check_count']}  status: {summary['last_status']}"
                )
        return 0

    if args.command == "validate-workflow":
        from sg_preflight import qa_workflows as qw

        target = (args.id_or_path or "").strip()
        candidates: list[Path] = []
        if not target:
            candidates = list(qw.discover(workspace_root=common.root))
        elif Path(target).is_file():
            candidates = [Path(target).resolve()]
        else:
            for path in qw.discover(workspace_root=common.root):
                try:
                    doc = json.loads(path.read_text(encoding="utf-8-sig"))
                except Exception:
                    continue
                if doc.get("id") == target:
                    candidates = [path]
                    break
        if not candidates:
            msg = f"workflow not found: {target!r}"
            print(json.dumps({"ok": False, "errors": [msg]})) if args.json else print(msg, file=sys.stderr)
            return 2
        all_ok = True
        results = []
        for path in candidates:
            try:
                doc = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                results.append({"path": str(path), "ok": False, "errors": [f"JSON parse: {exc}"], "warnings": []})
                all_ok = False
                continue
            result = qw.validate_doc(doc, path)
            results.append({"path": str(path), "ok": result.ok, "errors": result.errors, "warnings": result.warnings})
            if not result.ok:
                all_ok = False
        if args.json:
            print(json.dumps({"ok": all_ok, "results": results}, indent=2))
        else:
            for result in results:
                tag = "OK" if result["ok"] else "FAIL"
                print(f"[{tag}] {result['path']}")
                for error in result["errors"]:
                    print(f"  ERROR: {error}")
                for warning in result["warnings"]:
                    print(f"  warn:  {warning}")
        return 0 if all_ok else 1

    if args.command == "run-workflow":
        from sg_preflight import qa_workflows as qw

        out_root = Path(args.output_root).resolve() if args.output_root else None
        try:
            summary = qw.run_workflow(
                args.workflow_id,
                profile=args.profile or None,
                ticket_id=args.ticket_id or None,
                output_root=out_root,
                workspace_root=common.root,
            )
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"workflow:  {summary['id']}")
            print(f"profile:   {summary.get('profile') or '(workspace-scoped)'}")
            print(f"status:    {summary['status']}")
            print(f"checks:    {len(summary.get('checks', []))}")
            for check in summary.get("checks", []):
                req = "[req]" if check.get("required") else "[opt]"
                print(f"  {req} {check['id']:<30} {check['status']}")
        return 0 if summary["status"] in ("ready_for_review", "in_progress", "not_started", "covered") else 1

    parser.error(f"Unhandled workflow command: {args.command}")
    return 1
