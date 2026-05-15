"""Canonical command-line interface for Astrid orchestrators."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from astrid.core._search import (
    SearchRecord,
    search as run_search,
    short_description_or_truncated,
)
from astrid.core.executor.banodoco_catalog import BanodocoCatalogConfig
from astrid.core.project.run import ProjectRunError

from .registry import OrchestratorRegistry, load_default_registry
from .schema import OrchestratorDefinition, OrchestratorValidationError


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parse_argv, passthrough = _split_run_passthrough(list(argv) if argv is not None else sys.argv[1:])
    args = parser.parse_args(parse_argv)
    if getattr(args, "command", None) == "run":
        args.orchestrator_args = passthrough
    # FLAG-S1-002: 'new' short-circuits BEFORE load_default_registry() so
    # scaffold commands never load the built-in registry or import pack code.
    if getattr(args, "command", None) == "new":
        return int(args.handler(args, registry=None))
    try:
        registry = load_default_registry(
            banodoco_config=_banodoco_config_from_args(args),
            extra_pack_roots=tuple(args.pack_root),
        )
        return int(args.handler(args, registry))
    except (KeyError, OrchestratorValidationError, ProjectRunError, ValueError) as exc:
        print(f"orchestrators: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid orchestrators",
        description="List, inspect, validate, and run Astrid orchestrators.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--pack-root", action="append", default=[], metavar="PATH", help="Extra pack root directory to discover orchestrators from; may be repeated.")
    parser.add_argument("--banodoco-agent-orchestrators", action="store_true", help="Opt in to loading orchestrators from the Banodoco website catalog.")
    parser.add_argument("--banodoco-catalog-url", help="Banodoco website catalog Edge Function URL.")
    parser.add_argument("--banodoco-cache-dir", help="Cache directory for git-backed Banodoco orchestrators.")
    parser.add_argument("--banodoco-refresh", action="store_true", help="Refresh cached git checkouts before loading Banodoco orchestrators.")
    parser.add_argument("--no-banodoco-defaults", action="store_true", help="Skip Banodoco catalog orchestrators marked default.")
    parser.add_argument("--no-banodoco-mandatory", action="store_true", help="Skip Banodoco catalog orchestrators marked mandatory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List available orchestrators.")
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    list_parser.add_argument("--kind", choices=("built_in", "external"), help="Filter orchestrators by kind.")
    list_parser.add_argument("--no-describe", action="store_true", help="Omit the short_description column for legacy parsers.")
    list_parser.set_defaults(handler=_cmd_list)

    search_parser = subparsers.add_parser("search", help="Search orchestrators by id, keywords, and descriptions.")
    search_parser.add_argument("terms", nargs="+", help="One or more search terms.")
    search_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    search_parser.add_argument("--limit", type=int, default=25, help="Maximum number of hits (default 25).")
    search_parser.set_defaults(handler=_cmd_search)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one orchestrator.")
    inspect_parser.add_argument("orchestrator_id")
    inspect_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    inspect_parser.set_defaults(handler=_cmd_inspect)

    validate_parser = subparsers.add_parser("validate", help="Validate orchestrator metadata.")
    validate_parser.add_argument("orchestrator_id", nargs="?")
    validate_parser.set_defaults(handler=_cmd_validate)

    run_parser = subparsers.add_parser("run", help="Run or dry-run one orchestrator.")
    run_parser.add_argument("orchestrator_id")
    run_parser.add_argument("--out", help="Output directory for runtime placeholders.")
    run_parser.add_argument("--project", help="Project slug for a persistent project run.")
    run_parser.add_argument("--brief", help="Brief path for runtime placeholders.")
    run_parser.add_argument("--input", action="append", default=[], metavar="NAME=VALUE", help="Orchestrator input value; may be repeated.")
    run_parser.add_argument("--dry-run", action="store_true", help="Plan commands without executing command runtimes.")
    run_parser.add_argument("--python-exec", help="Python executable for {python_exec} placeholders.")
    run_parser.add_argument("--verbose", action="store_true", help="Set verbose runtime context.")
    run_parser.add_argument("--thread", help="Thread id, @new, or @none for this run.")
    run_parser.add_argument("--variants", type=int, help="Request a sibling variant count for variant-aware producers.")
    run_parser.add_argument("--from", dest="from_ref", help="Consume a specific prior run or variant, e.g. <run-id>:<n>.")
    run_parser.set_defaults(handler=_cmd_run)

    new_parser = subparsers.add_parser("new", help="Scaffold a new orchestrator in an existing pack.")
    new_parser.add_argument(
        "qualified_id",
        help="Qualified orchestrator id: <pack>.<slug> (e.g., my_pack.make_trailer).",
    )
    new_parser.set_defaults(handler=_cmd_new)

    return parser


def _cmd_new(args: argparse.Namespace, registry: Any) -> int:
    """Scaffold a new orchestrator component into an existing pack (CWD-relative).

    Short-circuits before ``load_default_registry()`` — never imports pack code.
    """
    from astrid.core.executor.cli import (
        _QID_RE,
        _TEST_RUN_PY_TEMPLATE,
        _scaffold_component,
    )

    qualified_id: str = args.qualified_id

    # Validate early so we can safely split for the plan-template format.
    if not _QID_RE.fullmatch(qualified_id):
        print(
            f"orchestrators new: qualified id {qualified_id!r} must be "
            f"'<pack>.<slug>' with letters/digits/underscore",
            file=sys.stderr,
        )
        return 2

    pack, slug = qualified_id.split(".", 1)

    return _scaffold_component(
        qualified_id=qualified_id,
        component_type="orchestrator",
        yaml_template=_ORCHESTRATOR_YAML_TEMPLATE,
        run_py_template=_RUN_PY_TEMPLATE,
        extra_files={
            "plan_template.py": _ORCHESTRATOR_PLAN_TEMPLATE.format(
                qualified_id=qualified_id,
                pack=pack,
                slug=slug,
            ),
            "tests/__init__.py": "",
            "tests/test_run.py": _TEST_RUN_PY_TEMPLATE.format(
                qualified_id=qualified_id,
                component_type="orchestrator",
            ),
        },
    )


# ---------------------------------------------------------------------------
# Orchestrator-specific scaffold templates
# ---------------------------------------------------------------------------

_ORCHESTRATOR_YAML_TEMPLATE = """\
schema_version: 1
id: {qualified_id}
name: {slug}
kind: external
version: 0.1.0
description: \"TODO: describe what this orchestrator does.\"

runtime:
  type: python-cli
  entrypoint: run.py
  callable: main
"""

_RUN_PY_TEMPLATE = """\
\"""\{qualified_id} — orchestrator runtime entrypoint.

Implement your orchestrator logic here. The function named ``main`` (or
whatever you set for ``runtime.callable`` in the manifest) is the entrypoint.

Example invocation::

    python3 -m astrid orchestrators run {qualified_id} -- --my-flag
\"""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    \"""Entrypoint for {qualified_id}.

    Parses CLI arguments and runs the orchestrator logic.  In dry-run mode
    the command is printed but not executed.

    Use ``--`` to pass orchestrator-specific args through the runner, e.g.::

        python3 -m astrid orchestrators run {qualified_id} -- --my-flag
    \"""
    parser = argparse.ArgumentParser(
        prog="{qualified_id}",
        description="TODO: describe what this orchestrator does.",
    )
    parser.add_argument("--input", nargs="*", default=[],
                        help="Input values as NAME=VALUE pairs.")
    parser.add_argument("--out", default=None,
                        help="Output directory for artifacts.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the command without executing it.")
    # --- Add your own orchestrator-specific flags here ---
    parser.add_argument("--my-flag", action="store_true",
                        help="Example orchestrator-specific flag.")

    args = parser.parse_args(argv)

    if args.dry_run:
        print(f"[dry-run] {qualified_id} would run with out={{args.out}}")
        return 0

    # TODO: implement your orchestration logic here
    print(f"{qualified_id}: running with out={{args.out}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


_ORCHESTRATOR_PLAN_TEMPLATE = """\
# {qualified_id} — plan v2 template
#
# This file defines ``build_plan_v2``, the function that produces the plan
# dict emitted by the orchestrator runner.  Import helpers from
# ``astrid.core.orchestrator.plan_v2`` so you don't need to copy-paste the
# emit / step-command / produces boilerplate into your pack.

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from astrid.core.orchestrator.plan_v2 import (
    emit_plan_json,
    build_step_command,
    make_produces,
)


def build_plan_v2(
    *,
    python_exec: str,
    run_root: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    \"\"\"Return a minimal valid plan-v2 dict.

    This stub produces a single ``adapter: local`` step.  Replace the
    placeholder command and expand the step list to match your pipeline.
    \"\"\"
    run_root = Path(run_root)

    # TODO: replace this placeholder with your real step command.
    # Use ``build_step_command`` or construct the command string directly.
    step_id = \"hello\"
    command = f\"{{python_exec}} -c 'print(\\\"hello from {{qualified_id}}\\\")' --out {{run_root}}/steps/{{step_id}}/v1/produces\"

    plan: dict[str, Any] = {{
        \"plan_id\": \"{qualified_id}\",
        \"version\": 2,
        \"steps\": [
            {{
                \"id\": step_id,
                \"adapter\": \"local\",
                \"command\": command,
                \"produces\": {{
                    # TODO: replace with your real produces path(s).
                    \"hello_output\": {{
                        \"path\": \"hello.txt\",
                        \"check\": {{
                            \"check_id\": \"file_nonempty\",
                            \"params\": {{}},
                            \"sentinel\": False,
                        }},
                    }}
                }},
            }}
        ],
    }}
    return plan


if __name__ == \"__main__\":
    # Quick smoke-test: build a plan and emit it to a temp path.
    import tempfile

    run_root = Path(tempfile.mkdtemp(prefix=\"plan-test-\"))
    plan = build_plan_v2(python_exec=sys.executable, run_root=run_root)
    plan_path = run_root / \"plan.json\"
    emit_plan_json(plan, plan_path)
    print(f\"plan emitted to {{plan_path}}\")
"""


def _banodoco_config_from_args(args: argparse.Namespace) -> BanodocoCatalogConfig:
    env_config = BanodocoCatalogConfig.from_env()
    enabled = bool(args.banodoco_agent_orchestrators or env_config.enabled)
    return BanodocoCatalogConfig(
        enabled=enabled,
        catalog_url=args.banodoco_catalog_url or env_config.catalog_url,
        include_defaults=False if args.no_banodoco_defaults else env_config.include_defaults,
        include_mandatory=False if args.no_banodoco_mandatory else env_config.include_mandatory,
        cache_dir=Path(args.banodoco_cache_dir).expanduser() if args.banodoco_cache_dir else env_config.cache_dir,
        refresh=bool(args.banodoco_refresh or env_config.refresh),
        timeout_seconds=env_config.timeout_seconds,
    )


def _cmd_list(args: argparse.Namespace, registry: OrchestratorRegistry) -> int:
    orchestrators = registry.list(kind=args.kind)
    if args.json:
        print(json.dumps({"orchestrators": [item.to_dict() for item in orchestrators]}, indent=2, sort_keys=True))
        return 0
    no_describe = bool(getattr(args, "no_describe", False))
    for orchestrator in orchestrators:
        if no_describe:
            print(f"{orchestrator.id}\t{orchestrator.kind}\t{orchestrator.name}")
        else:
            short = short_description_or_truncated(orchestrator.short_description, orchestrator.description)
            print(f"{orchestrator.id}\t{orchestrator.kind}\t{orchestrator.name}\t{short}")
    return 0


def _cmd_search(args: argparse.Namespace, registry: OrchestratorRegistry) -> int:
    records = [_orchestrator_search_record(item) for item in registry.list()]
    hits = run_search(records, list(args.terms), limit=int(args.limit))
    if args.json:
        payload = [
            {
                "id": hit.record.id,
                "kind": hit.record.kind,
                "score": round(hit.score, 3),
                "short_description": hit.record.short_description,
            }
            for hit in hits
        ]
        print(json.dumps({"hits": payload}, indent=2, sort_keys=True))
        return 0
    for hit in hits:
        print(f"{hit.score:.2f}\t{hit.record.id}\t{hit.record.kind}\t{hit.record.short_description}")
    return 0


def _orchestrator_search_record(orchestrator: OrchestratorDefinition) -> SearchRecord:
    short = short_description_or_truncated(orchestrator.short_description, orchestrator.description)
    fields = {
        "id": orchestrator.id,
        "name": orchestrator.name,
        "short_description": orchestrator.short_description,
        "description": orchestrator.description,
        "keywords": " ".join(orchestrator.keywords),
    }
    return SearchRecord(id=orchestrator.id, kind=orchestrator.kind, short_description=short, fields=fields)


def _cmd_inspect(args: argparse.Namespace, registry: OrchestratorRegistry) -> int:
    _require_qualified_id(args.orchestrator_id, "orchestrator id")
    orchestrator = registry.get(args.orchestrator_id)
    if args.json:
        print(orchestrator.to_json())
        return 0
    print(f"id: {orchestrator.id}")
    print(f"name: {orchestrator.name}")
    print(f"kind: {orchestrator.kind}")
    print(f"version: {orchestrator.version}")
    print(f"runtime: {orchestrator.runtime.kind}")
    if orchestrator.short_description:
        print(f"short_description: {orchestrator.short_description}")
    if orchestrator.description:
        print(f"description: {orchestrator.description}")
    if orchestrator.keywords:
        print(f"keywords: {', '.join(orchestrator.keywords)}")
    _print_ports("inputs", orchestrator.inputs)
    _print_outputs(orchestrator)
    if orchestrator.child_executors:
        print(f"child_executors: {', '.join(orchestrator.child_executors)}")
    if orchestrator.child_orchestrators:
        print(f"child_orchestrators: {', '.join(orchestrator.child_orchestrators)}")
    if orchestrator.runtime.command is not None:
        print(f"command: {shlex.join(orchestrator.runtime.command.argv)}")
    _print_active_thread_footer()
    return 0


def _cmd_validate(args: argparse.Namespace, registry: OrchestratorRegistry) -> int:
    registry.validate_all()
    if args.orchestrator_id:
        _require_qualified_id(args.orchestrator_id, "orchestrator id")
    orchestrators = [registry.get(args.orchestrator_id)] if args.orchestrator_id else registry.list()
    if args.orchestrator_id:
        print(f"{args.orchestrator_id}: ok")
    else:
        print(f"{len(orchestrators)} orchestrator(s): ok")
    return 0


def _cmd_run(args: argparse.Namespace, registry: OrchestratorRegistry) -> int:
    from .runner import OrchestratorRunRequest, run_orchestrator

    _require_qualified_id(args.orchestrator_id, "orchestrator id")
    request = OrchestratorRunRequest(
        orchestrator_id=args.orchestrator_id,
        out=Path(args.out) if args.out else None,
        project=args.project,
        inputs=_parse_input_values(args.input),
        brief=Path(args.brief) if args.brief else None,
        orchestrator_args=tuple(args.orchestrator_args),
        dry_run=bool(args.dry_run),
        python_exec=args.python_exec,
        verbose=bool(args.verbose),
        thread=args.thread,
        variants=args.variants,
        from_ref=args.from_ref,
    )
    result = run_orchestrator(request, registry)
    _print_run_result(result)
    return int(result.returncode or 0)


def _parse_input_values(raw_values: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in raw_values:
        if "=" not in raw:
            raise ValueError(f"invalid --input value {raw!r}; expected NAME=VALUE")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"invalid --input value {raw!r}; expected NAME=VALUE")
        values[key] = value
    return values


def _require_qualified_id(value: str, label: str) -> None:
    if "." not in value or any(not part for part in value.split(".")):
        raise ValueError(f"{label} must be qualified as <pack>.<name>")


def _split_run_passthrough(argv: list[str]) -> tuple[list[str], list[str]]:
    if not argv or argv[0] != "run" or "--" not in argv:
        return argv, []
    separator_index = argv.index("--")
    return argv[:separator_index], argv[separator_index + 1 :]


def _print_run_result(result: Any) -> None:
    commands = result.planned_commands or ((result.command,) if result.command else ())
    for command in commands:
        if command:
            print(shlex.join(command))
    if result.errors:
        for error in result.errors:
            print(f"{error.kind}: {error.message}", file=sys.stderr)


def _print_ports(label: str, ports: tuple[Any, ...]) -> None:
    if not ports:
        return
    print(f"{label}:")
    for port in ports:
        required = "required" if port.required else "optional"
        print(f"  - {port.name} ({port.type}, {required})")


def _print_outputs(orchestrator: OrchestratorDefinition) -> None:
    if not orchestrator.outputs:
        return
    print("outputs:")
    for output in orchestrator.outputs:
        placeholder = f", placeholder={output.placeholder}" if output.placeholder else ""
        print(f"  - {output.name} ({output.type}, {output.mode}{placeholder})")


def _print_active_thread_footer() -> None:
    try:
        import os

        from astrid._paths import REPO_ROOT
        from astrid.threads.index import ThreadIndexStore

        index = ThreadIndexStore(Path(os.environ.get("ARTAGENTS_REPO_ROOT", REPO_ROOT))).read()
    except Exception:
        print("active_thread: unavailable")
        print("thread_details: python3 -m astrid thread show @active")
        return
    active = index.get("active_thread_id")
    thread = index.get("threads", {}).get(active) if isinstance(active, str) else None
    if isinstance(thread, dict):
        print(f"active_thread: {thread.get('label') or 'unlabeled'} ({active})")
    else:
        print("active_thread: none")
    print("thread_details: python3 -m astrid thread show @active")


if __name__ == "__main__":
    raise SystemExit(main())
