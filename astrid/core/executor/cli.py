"""Canonical command-line interface for Astrid executors."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from astrid.core.project.run import ProjectRunError

from astrid.core._search import (
    SearchRecord,
    search as run_search,
    short_description_or_truncated,
)

from .banodoco_catalog import BanodocoCatalogConfig
from .registry import ExecutorRegistry, load_default_registry
from .schema import ExecutorDefinition, ExecutorValidationError


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # FLAG-S1-002: 'new' short-circuits BEFORE load_default_registry() so
    # scaffold commands never load the built-in registry or import pack code.
    if getattr(args, "command", None) == "new":
        return int(args.handler(args, registry=None))
    try:
        registry = load_default_registry(_banodoco_config_from_args(args))
        return int(args.handler(args, registry))
    except (KeyError, ExecutorValidationError, ProjectRunError, ValueError) as exc:
        print(f"executors: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid executors",
        description="List, inspect, validate, install, and run Astrid executors.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--banodoco-agent-executors", action="store_true", help="Opt in to loading executors from the Banodoco website catalog.")
    parser.add_argument("--banodoco-catalog-url", help="Banodoco website agent-executor catalog Edge Function URL.")
    parser.add_argument("--banodoco-cache-dir", help="Cache directory for git-backed Banodoco executors.")
    parser.add_argument("--banodoco-refresh", action="store_true", help="Refresh cached git checkouts before loading Banodoco executors.")
    parser.add_argument("--no-banodoco-defaults", action="store_true", help="Skip Banodoco catalog executors marked default.")
    parser.add_argument("--no-banodoco-mandatory", action="store_true", help="Skip Banodoco catalog executors marked mandatory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List available executors.")
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    list_parser.add_argument("--kind", choices=("built_in", "external"), help="Filter executors by kind.")
    list_parser.add_argument("--no-describe", action="store_true", help="Omit the short_description column for legacy parsers.")
    list_parser.set_defaults(handler=_cmd_list)

    search_parser = subparsers.add_parser("search", help="Search executors by id, keywords, descriptions, and binaries.")
    search_parser.add_argument("terms", nargs="+", help="One or more search terms.")
    search_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    search_parser.add_argument("--limit", type=int, default=25, help="Maximum number of hits (default 25).")
    search_parser.set_defaults(handler=_cmd_search)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect one executor.")
    inspect_parser.add_argument("executor_id")
    inspect_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    inspect_parser.set_defaults(handler=_cmd_inspect)

    validate_parser = subparsers.add_parser("validate", help="Validate executor metadata.")
    validate_parser.add_argument("executor_id", nargs="?")
    validate_parser.add_argument("--check-binaries", action="store_true", help="Also require declared external binaries to be on PATH.")
    validate_parser.set_defaults(handler=_cmd_validate)

    install_parser = subparsers.add_parser("install", help="Install dependencies for one executor.")
    install_parser.add_argument("executor_id")
    install_parser.add_argument("--dry-run", action="store_true", help="Print install commands without executing them.")
    install_parser.set_defaults(handler=_cmd_install)

    run_parser = subparsers.add_parser("run", help="Run or dry-run one executor.")
    run_parser.add_argument("executor_id")
    run_parser.add_argument("--out", help="Output directory for runtime placeholders.")
    run_parser.add_argument(
        "--project",
        help=(
            "Project identifier. A project slug runs in cache-only/offline mode "
            "(local sources/ + runs/ provenance). A reigh-app project UUID "
            "(8-4-4-4-12 hex) routes the post-run timeline through "
            "SupabaseDataProvider; pair with --timeline-id."
        ),
    )
    run_parser.add_argument(
        "--timeline-id",
        dest="timeline_id",
        help="reigh-app timeline UUID; required when --project is a reigh-app UUID.",
    )
    run_parser.add_argument(
        "--service-role",
        action="store_true",
        help="Worker-only escape hatch when pushing back via SupabaseDataProvider.",
    )
    run_parser.add_argument("--input", action="append", default=[], metavar="NAME=VALUE", help="Executor input value; may be repeated.")
    run_parser.add_argument("--brief", help="Brief path for built-in pipeline context synthesis.")
    run_parser.add_argument("--dry-run", action="store_true", help="Build and print the command without executing it.")
    run_parser.add_argument("--check-binaries", action="store_true", help="Also require declared external binaries to be on PATH.")
    run_parser.add_argument("--python-exec", help="Python executable for {python_exec} placeholders.")
    run_parser.add_argument("--verbose", action="store_true", help="Stream subprocess output for built-in pipeline steps.")
    run_parser.add_argument("--thread", help="Thread id, @new, or @none for this run.")
    run_parser.add_argument("--variants", type=int, help="Request a sibling variant count for variant-aware producers.")
    run_parser.add_argument("--from", dest="from_ref", help="Consume a specific prior run or variant, e.g. <run-id>:<n>.")
    run_parser.add_argument("--video-url", "--video", dest="video_url", help="Reachable http(s) video URL.")
    run_parser.add_argument("--title", help="YouTube video title.")
    run_parser.add_argument("--description", help="YouTube video description.")
    run_parser.add_argument("--tag", action="append", default=[], help="YouTube tag. May be repeated.")
    run_parser.add_argument("--tags", action="append", default=[], help="Comma-separated YouTube tags.")
    run_parser.add_argument("--privacy-status", default=None, help="YouTube privacy status: private, unlisted, or public.")
    run_parser.add_argument("--playlist-id", help="Optional YouTube playlist ID.")
    run_parser.add_argument("--made-for-kids", action="store_true", help="Mark the video as made for kids.")
    run_parser.set_defaults(handler=_cmd_run)

    new_parser = subparsers.add_parser("new", help="Scaffold a new executor in an existing pack.")
    new_parser.add_argument(
        "qualified_id",
        help="Qualified executor id: <pack>.<slug> (e.g., my_pack.ingest_assets).",
    )
    new_parser.set_defaults(handler=_cmd_new)

    return parser


def _cmd_new(args: argparse.Namespace, registry: Any) -> int:
    """Scaffold a new executor component into an existing pack (CWD-relative).

    Short-circuits before ``load_default_registry()`` — never imports pack code.
    """
    return _scaffold_component(
        qualified_id=args.qualified_id,
        component_type="executor",
        yaml_template=_EXECUTOR_YAML_TEMPLATE,
        run_py_template=_RUN_PY_TEMPLATE,
    )


def _scaffold_component(
    qualified_id: str,
    component_type: str,
    yaml_template: str,
    run_py_template: str,
) -> int:
    """Shared scaffolding logic for executors new / orchestrators new.

    Args:
        qualified_id: ``<pack>.<slug>`` identifier.
        component_type: ``'executor'`` or ``'orchestrator'``.
        yaml_template: str.format template for the component manifest.
        run_py_template: str.format template for run.py stub.

    Returns:
        Exit code (0 on success, non-zero on failure).
    """
    from astrid.packs.validate import validate_pack

    # Derive the correct CLI prefix for error messages.
    _cli_prefix = f"{component_type}s new"

    # --- 1. Validate the qualified id ------------------------------------------
    if not _QID_RE.fullmatch(qualified_id):
        print(
            f"{_cli_prefix}: qualified id {qualified_id!r} must be "
            f"'<pack>.<slug>' with letters/digits/underscore",
            file=sys.stderr,
        )
        return 2

    pack, slug = qualified_id.split(".", 1)

    # --- 2. Find the target pack root (CWD-relative) ---------------------------
    pack_root = Path.cwd().resolve()
    pack_yaml = pack_root / "pack.yaml"
    if not pack_yaml.is_file():
        print(
            f"{_cli_prefix}: pack.yaml not found at {pack_root}. "
            f"Scaffold the pack first with: python3 -m astrid packs new {pack}",
            file=sys.stderr,
        )
        return 1

    # Verify the pack id in pack.yaml matches
    import yaml as _yaml_module
    try:
        with open(pack_yaml, "r", encoding="utf-8") as fh:
            doc = _yaml_module.safe_load(fh)
    except Exception as exc:
        print(f"{_cli_prefix}: cannot read {pack_yaml}: {exc}", file=sys.stderr)
        return 1

    if isinstance(doc, dict) and doc.get("id") != pack:
        print(
            f"{_cli_prefix}: pack id mismatch — {qualified_id!r} expects "
            f"pack id {pack!r} but {pack_yaml} has id {doc.get('id')!r}",
            file=sys.stderr,
        )
        return 1

    # --- 3. Determine the content root for this component type -----------------
    content = doc.get("content", {}) if isinstance(doc, dict) else {}
    rel_dir = content.get(f"{component_type}s", f"{component_type}s")
    components_root = pack_root / rel_dir
    component_dir = components_root / slug

    # --- 4. Reject overwrite collisions ----------------------------------------
    if component_dir.exists():
        print(
            f"{_cli_prefix}: {component_dir} already exists; refusing to overwrite",
            file=sys.stderr,
        )
        return 1

    # --- 5. Create the scaffold ------------------------------------------------
    component_dir.mkdir(parents=True)
    created: list[str] = []

    # Component manifest (executor.yaml / orchestrator.yaml)
    manifest_path = component_dir / f"{component_type}.yaml"
    manifest_text = yaml_template.format(pack=pack, slug=slug, qualified_id=qualified_id)
    manifest_path.write_text(manifest_text, encoding="utf-8")
    created.append(str(manifest_path.relative_to(pack_root)))

    # run.py stub
    run_py_path = component_dir / "run.py"
    run_py_text = run_py_template.format(qualified_id=qualified_id, component_type=component_type)
    run_py_path.write_text(run_py_text, encoding="utf-8")
    created.append(str(run_py_path.relative_to(pack_root)))

    # STAGE.md stub
    stage_md_path = component_dir / "STAGE.md"
    stage_md_text = _STAGE_MD_TEMPLATE.format(
        qualified_id=qualified_id, component_type=component_type.title()
    )
    stage_md_path.write_text(stage_md_text, encoding="utf-8")
    created.append(str(stage_md_path.relative_to(pack_root)))

    # --- 6. Validate the pack after scaffolding --------------------------------
    errors, warnings = validate_pack(pack_root)
    if errors:
        print(
            f"{_cli_prefix}: scaffolded {component_type} fails validation "
            f"({len(errors)} error(s))",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    # --- 7. Report ------------------------------------------------------------
    for rel in created:
        print(f"created {rel}")
    if warnings:
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)
    print(f"{component_type} {qualified_id!r} created and validated")
    return 0


# ---------------------------------------------------------------------------
# Qualified-id validation (matches the v1 _defs.json qualified_id pattern)
# ---------------------------------------------------------------------------

import re as _re

_QID_RE = _re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

# ---------------------------------------------------------------------------
# Scaffold templates
# ---------------------------------------------------------------------------

_EXECUTOR_YAML_TEMPLATE = """\
schema_version: 1
id: {qualified_id}
name: {slug}
version: 0.1.0
description: \"TODO: describe what this executor does.\"

runtime:
  type: python-cli
  entrypoint: run.py
  callable: main
"""

_RUN_PY_TEMPLATE = """\
\"\"\"{qualified_id} — {component_type} runtime entrypoint.

Implement your {component_type} logic here. The function named ``main`` (or
whatever you set for ``runtime.callable`` in the manifest) is the entrypoint.
\"\"\"


def main(*, inputs: dict, outputs: dict, **kwargs) -> int:
    \"\"\"Entrypoint for {qualified_id}.

    Args:
        inputs: Dict of resolved input values (name → path/value).
        outputs: Dict to populate with output values (name → path/value).
        **kwargs: Runtime context (project, brief, etc.).

    Returns:
        Exit code (0 on success, non-zero on failure).
    \"\"\"
    # TODO: implement your logic here
    return 0
"""

_STAGE_MD_TEMPLATE = """\
# {qualified_id}

## Purpose

TODO: describe what this {component_type} does and when to use it.

## Inputs

TODO: list the inputs this {component_type} expects.

## Outputs

TODO: list the outputs this {component_type} produces.

## Dependencies

TODO: any Python, npm, or system dependencies.
"""


def _banodoco_config_from_args(args: argparse.Namespace) -> BanodocoCatalogConfig:
    env_config = BanodocoCatalogConfig.from_env()
    enabled = bool(args.banodoco_agent_executors or env_config.enabled)
    return BanodocoCatalogConfig(
        enabled=enabled,
        catalog_url=args.banodoco_catalog_url or env_config.catalog_url,
        include_defaults=False if args.no_banodoco_defaults else env_config.include_defaults,
        include_mandatory=False if args.no_banodoco_mandatory else env_config.include_mandatory,
        cache_dir=Path(args.banodoco_cache_dir).expanduser() if args.banodoco_cache_dir else env_config.cache_dir,
        refresh=bool(args.banodoco_refresh or env_config.refresh),
        timeout_seconds=env_config.timeout_seconds,
    )


def _cmd_list(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    executors = registry.list(kind=args.kind)
    if args.json:
        print(json.dumps({"executors": [executor.to_dict() for executor in executors]}, indent=2, sort_keys=True))
        return 0
    no_describe = bool(getattr(args, "no_describe", False))
    for executor in executors:
        if no_describe:
            print(f"{executor.id}\t{executor.kind}\t{executor.name}")
        else:
            short = short_description_or_truncated(executor.short_description, executor.description)
            print(f"{executor.id}\t{executor.kind}\t{executor.name}\t{short}")
    return 0


def _cmd_search(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    records = [_executor_search_record(executor) for executor in registry.list()]
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


def _executor_search_record(executor: ExecutorDefinition) -> SearchRecord:
    short = short_description_or_truncated(executor.short_description, executor.description)
    fields = {
        "id": executor.id,
        "name": executor.name,
        "short_description": executor.short_description,
        "description": executor.description,
        "keywords": " ".join(executor.keywords),
        "binaries": " ".join(executor.isolation.binaries),
    }
    return SearchRecord(id=executor.id, kind=executor.kind, short_description=short, fields=fields)


def _cmd_inspect(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    _require_qualified_id(args.executor_id, "executor id")
    executor = registry.get(args.executor_id)
    if args.json:
        print(executor.to_json())
        return 0
    print(f"id: {executor.id}")
    print(f"name: {executor.name}")
    print(f"kind: {executor.kind}")
    print(f"version: {executor.version}")
    if executor.short_description:
        print(f"short_description: {executor.short_description}")
    if executor.description:
        print(f"description: {executor.description}")
    if executor.keywords:
        print(f"keywords: {', '.join(executor.keywords)}")
    _print_ports("inputs", executor.inputs)
    _print_outputs(executor)
    if executor.command is not None:
        print(f"command: {shlex.join(executor.command.argv)}")
    print(f"cache: {executor.cache.mode}")
    if executor.cache.sentinels:
        print(f"cache_sentinels: {', '.join(executor.cache.sentinels)}")
    if executor.isolation.binaries:
        print(f"binaries: {', '.join(executor.isolation.binaries)}")
    _print_active_thread_footer()
    return 0


def _cmd_validate(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    registry.validate_all()
    if args.executor_id:
        _require_qualified_id(args.executor_id, "executor id")
    executors = [registry.get(args.executor_id)] if args.executor_id else registry.list()
    missing_by_executor: dict[str, tuple[str, ...]] = {}
    if args.check_binaries:
        from .runner import check_executor_binaries

        for executor in executors:
            missing = check_executor_binaries(executor)
            if missing:
                missing_by_executor[executor.id] = missing
    if missing_by_executor:
        for executor_id, missing in missing_by_executor.items():
            print(f"{executor_id}: missing binaries: {', '.join(missing)}", file=sys.stderr)
        return 1
    if args.executor_id:
        print(f"{args.executor_id}: ok")
    else:
        print(f"{len(executors)} executor(s): ok")
    return 0


def _cmd_install(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    from .install import install_executor

    _require_qualified_id(args.executor_id, "executor id")
    executor = registry.get(args.executor_id)
    result = install_executor(executor, dry_run=bool(args.dry_run))
    plan = result.plan
    if plan.noop_reason:
        print(f"{executor.id}: no install needed: {plan.noop_reason}")
        return result.returncode
    if plan.environment_path is not None:
        print(f"env: {plan.environment_path}")
    if plan.python_path is not None:
        print(f"python: {plan.python_path}")
    for command in plan.commands:
        print(shlex.join(command))
    return result.returncode


def _cmd_run(args: argparse.Namespace, registry: ExecutorRegistry) -> int:
    from .runner import ExecutorRunRequest, run_executor

    _require_qualified_id(args.executor_id, "executor id")
    executor = registry.get(args.executor_id)
    project_uuid = _project_uuid_or_none(args.project)
    if project_uuid is not None:
        # UUID mode: --project is a reigh-app UUID, runs need an --out for
        # local placeholders + a --timeline-id to address the row.
        if not getattr(args, "timeline_id", None):
            raise ValueError("--timeline-id is required when --project is a reigh-app UUID")
        if not args.out:
            raise ValueError("--out is required when --project is a reigh-app UUID")
        local_project: str | None = None
    else:
        local_project = args.project
        if local_project and args.out:
            raise ValueError("--project cannot be combined with --out; project runs own their output directory")
    if not args.out and local_project is None and project_uuid is None and _executor_needs_out(executor):
        raise ValueError("--out is required for this executor")
    request = ExecutorRunRequest(
        executor_id=args.executor_id,
        out=Path(args.out) if args.out else "",
        project=local_project,
        inputs=_run_inputs(args),
        brief=Path(args.brief) if args.brief else None,
        dry_run=bool(args.dry_run),
        check_binaries=bool(args.check_binaries),
        python_exec=args.python_exec,
        verbose=bool(args.verbose),
        thread=args.thread,
        variants=args.variants,
        from_ref=args.from_ref,
    )
    result = run_executor(request, registry)
    if result.missing_binaries:
        print(f"{args.executor_id}: missing binaries: {', '.join(result.missing_binaries)}", file=sys.stderr)
        return 1
    if result.skipped:
        print(f"{args.executor_id}: skipped: {result.skipped_reason}")
        return 0
    if result.command:
        print(shlex.join(result.command))
    if result.payload:
        print(json.dumps(dict(result.payload), separators=(",", ":"), sort_keys=True))
    rc = int(result.returncode or 0)
    if rc == 0 and project_uuid is not None and not args.dry_run:
        rc = _push_run_to_supabase(
            project_id=project_uuid,
            timeline_id=args.timeline_id,
            out_dir=Path(args.out),
            service_role=bool(getattr(args, "service_role", False)),
        )
    return rc


_UUID_RE = __import__("re").compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _project_uuid_or_none(value: str | None) -> str | None:
    if not value:
        return None
    return value if _UUID_RE.match(value) else None


def _push_run_to_supabase(
    *,
    project_id: str,
    timeline_id: str,
    out_dir: Path,
    service_role: bool,
) -> int:
    """Push the run's hype.timeline.json (if produced) via SupabaseDataProvider."""

    timeline_path = out_dir / "hype.timeline.json"
    if not timeline_path.is_file():
        print(
            f"executors: --project {project_id} requested but {timeline_path} not produced by run; skipping push",
            file=sys.stderr,
        )
        return 0

    from astrid.core.reigh import env as reigh_env
    from astrid.core.reigh.data_provider import SupabaseDataProvider
    from astrid.timeline import Timeline

    timeline_blob = Timeline.load(timeline_path).to_json_data()
    provider = SupabaseDataProvider.from_env()
    if service_role:
        auth = ("service_role", reigh_env.resolve_service_role_key())
    else:
        auth = ("pat", reigh_env.resolve_pat())
    _, current_version = provider.load_timeline(project_id, timeline_id)

    def _mutator(_config, _version):
        return timeline_blob

    result = provider.save_timeline(
        timeline_id,
        _mutator,
        project_id=project_id,
        auth=auth,
        expected_version=current_version,
        retries=3,
        force=False,
    )
    print(
        f"pushed timeline {timeline_id} project_id={project_id} "
        f"new_version={result.new_version} attempts={result.attempts}"
    )
    return 0


def _executor_needs_out(executor: ExecutorDefinition) -> bool:
    if executor.id == "upload.youtube":
        return False
    if executor.kind == "built_in" and "pipeline_step" in executor.metadata:
        return True
    if executor.command is not None:
        parts = [*executor.command.argv]
        if executor.command.cwd:
            parts.append(executor.command.cwd)
        parts.extend(executor.command.env.values())
        if any("{out}" in part for part in parts):
            return True
    return any((output.path_template and "{out}" in output.path_template) for output in executor.outputs)


def _run_inputs(args: argparse.Namespace) -> dict[str, Any]:
    inputs = _parse_input_values(args.input)
    for key in ("video_url", "title", "description", "privacy_status", "playlist_id"):
        value = getattr(args, key)
        if value not in (None, ""):
            inputs[key] = value
    tags = [*getattr(args, "tag", []), *getattr(args, "tags", [])]
    if tags:
        inputs["tags"] = tags
    if getattr(args, "made_for_kids", False):
        inputs["made_for_kids"] = True
    return inputs


def _parse_input_values(raw_values: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in raw_values:
        if "=" not in raw:
            raise ValueError(f"invalid --input value {raw!r}; expected NAME=VALUE")
        key, value = raw.split("=", 1)
        key = key.strip().replace("-", "_")
        if not key:
            raise ValueError(f"invalid --input value {raw!r}; expected NAME=VALUE")
        if key in values:
            values[key] = f"{values[key]},{value}"
        else:
            values[key] = value
    return values


def _require_qualified_id(value: str, label: str) -> None:
    if "." not in value or any(not part for part in value.split(".")):
        raise ValueError(f"{label} must be qualified as <pack>.<name>")


def _print_ports(label: str, ports: tuple[Any, ...]) -> None:
    if not ports:
        return
    print(f"{label}:")
    for port in ports:
        required = "required" if port.required else "optional"
        print(f"  - {port.name} ({port.type}, {required})")


def _print_outputs(executor: ExecutorDefinition) -> None:
    if not executor.outputs:
        return
    print("outputs:")
    for output in executor.outputs:
        placeholder = f", placeholder={output.placeholder}" if output.placeholder else ""
        print(f"  - {output.name} ({output.type}, {output.mode}{placeholder})")


def _print_active_thread_footer() -> None:
    try:
        import os

        from astrid._paths import REPO_ROOT
        from astrid.threads.index import ThreadIndexStore

        index = ThreadIndexStore(Path(os.environ.get("ASTRID_REPO_ROOT", REPO_ROOT))).read()
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
