from __future__ import annotations

import argparse
import sys

from sg_preflight.cli._common import (
    TEMPLATE_BANNER,
    TemplateStoreError,
    _console_safe,
    _emit_json,
    _emit_text,
    _render_template_list,
    _render_template_result,
    _resolve_workspace,
    delete_template,
    list_templates,
    load_template,
    main,
    parse_template_args,
    record_template_run,
    save_template,
    template_cli_args,
    template_path,
)


def handle_template_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    template_root = _resolve_workspace(args)
    try:
        if args.template_command == "save":
            template_args = parse_template_args(args.args)
            payload = save_template(
                template_root,
                args.name,
                command=args.template_cli_command,
                args=template_args,
                description=args.description,
                replace=args.replace,
            )
            result = {
                "status": "saved",
                "note": TEMPLATE_BANNER,
                "template": payload,
                "path": str(template_path(template_root, args.name)),
            }
            if args.json:
                _emit_json(result, args)
            else:
                _emit_text(_render_template_result(result), args)
            return 0
        if args.template_command == "list":
            payload = {"note": TEMPLATE_BANNER, "templates": list_templates(template_root)}
            if args.json:
                _emit_json(payload, args)
            else:
                _emit_text(_render_template_list(payload), args)
            return 0
        if args.template_command == "show":
            payload = {"note": TEMPLATE_BANNER, "template": load_template(template_root, args.name)}
            if args.json:
                _emit_json(payload, args)
            else:
                _emit_text(_render_template_result({"status": "template", **payload}), args)
            return 0
        if args.template_command == "delete":
            deleted = delete_template(template_root, args.name)
            payload = {"status": "deleted", "note": TEMPLATE_BANNER, "template": deleted}
            if args.json:
                _emit_json(payload, args)
            else:
                _emit_text(_render_template_result(payload), args)
            return 0
        if args.template_command == "run":
            template_payload = load_template(template_root, args.name)
            run_args = template_cli_args(template_payload, args_override=args.args_override)
            print(_console_safe(TEMPLATE_BANNER))
            print(_console_safe(f"Running template '{template_payload['name']}': sg-preflight {' '.join(run_args)}"))
            outcome = "error"
            try:
                exit_code = main(run_args)
                outcome = "ok" if exit_code == 0 else "error"
                return exit_code
            except SystemExit as exc:
                exit_code = int(exc.code or 0)
                outcome = "ok" if exit_code == 0 else "error"
                return exit_code
            finally:
                record_template_run(template_root, args.name, outcome=outcome)
        parser.error(f"Unhandled template command: {args.template_command}")
        return 1
    except TemplateStoreError as exc:
        print(_console_safe(f"template failed: {exc}"), file=sys.stderr)
        return 1
