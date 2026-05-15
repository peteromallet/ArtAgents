"""`astrid packs` CLI: validate, new, list, inspect subcommands.

``packs validate <path>`` statically validates a pack root directory.
``packs new <id>`` scaffolds a minimal pack skeleton in the CWD.
``packs list`` lists installed external packs.
``packs inspect <id>`` shows details for an installed pack.

None of these commands load the built-in registry, import pack code, or
require a bound session.
"""

from __future__ import annotations

import argparse
import json as _json
import re
import sys
from pathlib import Path
from typing import Optional

import yaml

from astrid.core.pack import pack_manifest_path
from astrid.packs.validate import extract_trust_summary, validate_pack

# Must match the pack_id pattern in _defs.json: lowercase, digits, underscore
_PACK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_STAGE_MD_STUB = """# {pack_name}

## Purpose

What this pack does and when to use it.

## Components

- Executors: ...
- Orchestrators: ...
"""

_README_MD_STUB = """# {pack_name}

{description}

## Getting Started

1. Install Astrid
2. Run `python3 -m astrid packs validate .`
3. Start building executors and orchestrators
"""

_AGENTS_MD_STUB = """# {pack_name} — Agent Guide

## When to Use This Pack

Explain in 1-2 sentences when an agent should choose this pack.

## Entrypoints

List the orchestrators agents should start with for common tasks.

## Executors

Briefly describe each executor and its purpose.
"""


def _pack_id_is_valid(pack_id: str) -> bool:
    """Check that a pack id matches the v1 schema pattern."""
    return bool(_PACK_ID_RE.fullmatch(pack_id))


def _validate_pack_path(path: Path, must_exist: bool = True) -> Path:
    """Resolve and validate a pack root directory path.

    Args:
        path: The path to resolve.
        must_exist: If True, require the directory to exist.

    Returns:
        The resolved Path.

    Raises:
        SystemExit(2) on invalid paths.
    """
    resolved = path.resolve()
    if must_exist and not resolved.is_dir():
        print(
            f"packs validate: {path} is not a directory or does not exist",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return resolved


def cmd_validate(argv: list[str]) -> int:
    """Run static validation on a pack root directory.

    Usage: python3 -m astrid packs validate <path>
    """
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid packs validate",
        description="Statically validate a pack directory.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to the pack root directory (default: current directory).",
    )
    parser.add_argument(
        "--warnings",
        action="store_true",
        help="Also print non-fatal warnings.",
    )
    args = parser.parse_args(argv)

    pack_root = _validate_pack_path(Path(args.path))

    errors, warnings = validate_pack(pack_root)

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1

    if args.warnings and warnings:
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)

    resolved = pack_root.resolve()
    print(f"valid: {resolved}")
    return 0


def cmd_new(argv: list[str]) -> int:
    """Scaffold a minimal pack directory in the CWD.

    Usage: python3 -m astrid packs new <id>
    """
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid packs new",
        description="Create a new pack skeleton in the current directory.",
    )
    parser.add_argument(
        "pack_id",
        help="Pack identifier (lowercase, digits, underscore; e.g., my_project).",
    )
    args = parser.parse_args(argv)

    pack_id: str = args.pack_id

    # Validate the pack id
    if not _pack_id_is_valid(pack_id):
        print(
            f"packs new: invalid pack id {pack_id!r}. "
            f"Must match pattern: ^[a-z][a-z0-9_]*$",
            file=sys.stderr,
        )
        return 2

    # Target directory in CWD
    target = Path.cwd() / pack_id
    if target.exists():
        print(
            f"packs new: directory {target} already exists; "
            f"refusing to overwrite",
            file=sys.stderr,
        )
        return 1

    # Ensure parent (CWD) exists
    if not target.parent.is_dir():
        print(
            f"packs new: parent directory {target.parent} does not exist",
            file=sys.stderr,
        )
        return 1

    # Create the pack skeleton
    pack_name = pack_id.replace("_", " ").title()
    description = f"A pack for {pack_name}."

    target.mkdir(parents=False)

    # pack.yaml
    pack_yaml = target / "pack.yaml"
    pack_yaml.write_text(
        f"""schema_version: 1
id: {pack_id}
name: {pack_name}
version: 0.1.0
description: {description}
content:
  executors: executors
  orchestrators: orchestrators
  elements: elements
agent:
  purpose: "TODO: describe what this pack is for"
""",
        encoding="utf-8",
    )

    # AGENTS.md
    agents_md = target / "AGENTS.md"
    agents_md.write_text(
        _AGENTS_MD_STUB.format(pack_name=pack_name),
        encoding="utf-8",
    )

    # README.md
    readme_md = target / "README.md"
    readme_md.write_text(
        _README_MD_STUB.format(pack_name=pack_name, description=description),
        encoding="utf-8",
    )

    # STAGE.md at pack root
    stage_md = target / "STAGE.md"
    stage_md.write_text(
        _STAGE_MD_STUB.format(pack_name=pack_name),
        encoding="utf-8",
    )

    # Create content root directories
    for subdir in ("executors", "orchestrators", "elements"):
        (target / subdir).mkdir(parents=False)

    # Report what was created
    created = [
        "pack.yaml",
        "AGENTS.md",
        "README.md",
        "STAGE.md",
        "executors/",
        "orchestrators/",
        "elements/",
    ]
    for rel in created:
        print(f"created {target.name}/{rel}")

    # Validate the new pack before declaring success
    errors, warnings = validate_pack(target)
    if errors:
        print(
            f"packs new: scaffolded pack fails validation ({len(errors)} error(s))",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    if warnings:
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)

    print(f"pack {pack_id!r} created and validated: {target}")
    return 0


# ---------------------------------------------------------------------------
# pack list
# ---------------------------------------------------------------------------


def cmd_list(argv: list[str]) -> int:
    """List installed external packs.

    Usage: python3 -m astrid packs list
    """
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid packs list",
        description="List installed external packs.",
    )
    parser.parse_args(argv)  # no arguments, just parses --help

    # Lazy import — InstalledPackStore touches filesystem only when called
    from astrid.core.pack_store import InstalledPackStore

    store = InstalledPackStore()
    records = store.list_installed()

    if not records:
        print("No packs installed.")
        return 0

    # Column widths (minimums, will expand for longer values)
    col_id = max(max(len(r.pack_id) for r in records), 2)
    col_name = max(max(len(r.name) for r in records), 4)
    col_version = max(max(len(r.version) for r in records), 7)
    col_status = 6  # "active" = 6 chars
    col_installed = 19  # ISO-8601 "YYYY-MM-DDTHH:MM:SS"

    header = (
        f"{'ID':<{col_id}}  {'NAME':<{col_name}}  "
        f"{'VERSION':<{col_version}}  {'STATUS':<{col_status}}  "
        f"{'INSTALLED':<{col_installed}}"
    )
    print(header)
    print("-" * len(header))

    for r in records:
        status = "active" if r.active else "inactive"
        print(
            f"{r.pack_id:<{col_id}}  {r.name:<{col_name}}  "
            f"{r.version:<{col_version}}  {status:<{col_status}}  "
            f"{r.installed_at:<{col_installed}}"
        )

    return 0


# ---------------------------------------------------------------------------
# pack inspect
# ---------------------------------------------------------------------------


def cmd_inspect(argv: list[str]) -> int:
    """Show details for an installed pack.

    Usage: python3 -m astrid packs inspect <pack_id> [--agent] [--json]
    """
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid packs inspect",
        description="Show details for an installed pack.",
    )
    parser.add_argument(
        "pack_id",
        help="Pack identifier to inspect.",
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Emit agent-focused subset (purpose, entrypoints, constraints, "
        "context, secrets).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output as JSON.",
    )
    args = parser.parse_args(argv)

    from astrid.core.pack_store import InstalledPackStore

    store = InstalledPackStore()
    record = store.get_active(args.pack_id)

    if record is None:
        print(
            f"inspect: pack {args.pack_id!r} is not installed.",
            file=sys.stderr,
        )
        return 1

    # Resolve the active revision directory
    rev_dir = store.active_revision_path(args.pack_id)
    if rev_dir is None:
        print(
            f"inspect: cannot resolve active revision for {args.pack_id!r}.",
            file=sys.stderr,
        )
        return 1

    # Read pack manifest from active revision for fresh data
    manifest_path = pack_manifest_path(rev_dir)
    if manifest_path is None:
        print(
            f"inspect: no pack manifest found in installed revision {rev_dir}.",
            file=sys.stderr,
        )
        return 1

    try:
        if manifest_path.suffix == ".json":
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"inspect: failed to parse pack manifest: {e}", file=sys.stderr)
        return 1

    if not isinstance(manifest, dict):
        print("inspect: pack manifest is not a mapping", file=sys.stderr)
        return 1

    # Also get the trust summary for component counts
    try:
        trust_summary = extract_trust_summary(rev_dir)
    except Exception:
        trust_summary = {}

    # ── Agent-focused output ──
    if args.agent:
        agent_data = _build_agent_view(manifest, trust_summary)
        if args.json_output:
            print(_json.dumps(agent_data, indent=2, default=str))
        else:
            _print_agent_view(agent_data)
        return 0

    # ── Full inspect output ──
    full_data = _build_full_inspect(record, manifest, trust_summary)
    if args.json_output:
        print(_json.dumps(full_data, indent=2, default=str))
    else:
        _print_full_inspect(full_data)

    return 0


# ---------------------------------------------------------------------------
# Agent-view helpers
# ---------------------------------------------------------------------------


def _build_agent_view(manifest: dict, trust_summary: dict) -> dict:
    """Build an agent-focused subset of a pack manifest."""
    agent_section = manifest.get("agent", {}) if isinstance(manifest.get("agent"), dict) else {}
    secrets_section = manifest.get("secrets", {}) if isinstance(manifest.get("secrets"), dict) else {}

    view: dict = {}

    # Purpose
    purpose = agent_section.get("purpose")
    if purpose:
        view["purpose"] = str(purpose)

    # Entrypoints
    entrypoints = trust_summary.get("entrypoints", [])
    if not entrypoints and isinstance(agent_section.get("entrypoints"), list):
        entrypoints = [str(ep) for ep in agent_section["entrypoints"] if ep]
    if entrypoints:
        view["entrypoints"] = entrypoints

    # Constraints (from agent section or metadata)
    constraints = agent_section.get("constraints")
    if constraints is None:
        metadata = manifest.get("metadata", {}) if isinstance(manifest.get("metadata"), dict) else {}
        constraints = metadata.get("constraints")
    if constraints:
        view["constraints"] = constraints if isinstance(constraints, str) else str(constraints)

    # Context (from agent section or metadata)
    context = agent_section.get("context")
    if context is None:
        metadata = manifest.get("metadata", {}) if isinstance(manifest.get("metadata"), dict) else {}
        context = metadata.get("context")
    if context:
        view["context"] = context if isinstance(context, str) else str(context)

    # Secrets
    secrets_list = trust_summary.get("declared_secrets", [])
    if not secrets_list and isinstance(secrets_section.get("required"), list):
        secrets_list = [str(s) for s in secrets_section["required"] if s]
    if secrets_list:
        view["secrets"] = secrets_list

    return view


def _print_agent_view(view: dict) -> None:
    """Pretty-print an agent-focused pack view."""
    print(f"━━━ Agent View: {view.get('pack_id', '?')} ━━━")
    if "purpose" in view:
        print(f"Purpose:     {view['purpose']}")
    if "entrypoints" in view:
        print(f"Entrypoints: {', '.join(view['entrypoints'])}")
    if "constraints" in view:
        print(f"Constraints: {view['constraints']}")
    if "context" in view:
        print(f"Context:     {view['context']}")
    if "secrets" in view:
        print(f"Secrets:     {', '.join(view['secrets'])}")


# ---------------------------------------------------------------------------
# Full inspect helpers
# ---------------------------------------------------------------------------


def _build_full_inspect(
    record: "InstallRecord", manifest: dict, trust_summary: dict
) -> dict:
    """Build a full inspect dict for JSON or pretty-print output."""
    return {
        "pack_id": record.pack_id,
        "name": record.name,
        "version": record.version,
        "schema_version": record.schema_version,
        "description": manifest.get("description", ""),
        "source_path": record.source_path,
        "installed_at": record.installed_at,
        "status": "active" if record.active else "inactive",
        "component_counts": trust_summary.get("component_counts", {}),
        "entrypoints": trust_summary.get("entrypoints", []),
        "declared_secrets": trust_summary.get("declared_secrets", []),
        "dependencies": trust_summary.get("dependencies", []),
        "docs": trust_summary.get("docs", {}),
        "warnings": trust_summary.get("warnings", []),
        "agent": manifest.get("agent") if isinstance(manifest.get("agent"), dict) else None,
        # Git-enriched and trust fields
        "git_url": record.git_url,
        "commit_sha": record.commit_sha,
        "source_type": record.source_type,
        "requested_ref": record.requested_ref,
        "astrid_version": record.astrid_version,
        "trust_tier": record.trust_tier,
        "manifest_digest": record.manifest_digest,
        "previous_active_revision": record.previous_active_revision,
    }


def _print_full_inspect(data: dict) -> None:
    """Pretty-print a full pack inspect result."""
    print(f"━━━ Pack: {data['pack_id']} ━━━")
    print(f"  Name:          {data['name']}")
    print(f"  Version:       {data['version']}")
    print(f"  Schema:        {data['schema_version']}")
    print(f"  Status:        {data['status']}")
    print(f"  Source:        {data['source_path']}")
    print(f"  Installed:     {data['installed_at']}")

    desc = data.get("description")
    if desc:
        print(f"  Description:   {desc}")

    # Git-enriched fields
    git_url = data.get("git_url", "")
    if git_url:
        print(f"  Git URL:       {git_url}")

    commit_sha = data.get("commit_sha", "")
    if commit_sha:
        print(f"  Commit SHA:    {commit_sha[:8]}")

    source_type = data.get("source_type", "")
    if source_type:
        print(f"  Source Type:   {source_type}")

    requested_ref = data.get("requested_ref", "")
    if requested_ref:
        print(f"  Requested Ref: {requested_ref}")

    astrid_version = data.get("astrid_version", "")
    if astrid_version:
        print(f"  Astrid Ver:    {astrid_version}")

    trust_tier = data.get("trust_tier", "")
    if trust_tier:
        print(f"  Trust Tier:    {trust_tier}")

    manifest_digest = data.get("manifest_digest", "")
    if manifest_digest:
        print(f"  Manifest Hash: {manifest_digest}")

    previous = data.get("previous_active_revision", "")
    if previous:
        print(f"  Prev Revision: {previous}")

    # Components
    counts = data.get("component_counts", {})
    if counts:
        parts = []
        for k in ("executors", "orchestrators", "elements"):
            if counts.get(k, 0):
                parts.append(f"{counts[k]} {k}")
        if parts:
            print(f"  Components:    {', '.join(parts)}")
        else:
            print("  Components:    (none)")
    else:
        print("  Components:    (none)")

    # Entrypoints
    entrypoints = data.get("entrypoints", [])
    if entrypoints:
        print(f"  Entrypoints:   {', '.join(entrypoints)}")

    # Secrets
    secrets = data.get("declared_secrets", [])
    if secrets:
        print(f"  Secrets:       {', '.join(secrets)}")

    # Dependencies
    deps = data.get("dependencies", [])
    if deps:
        print(f"  Dependencies:  {', '.join(deps)}")

    # Docs
    docs = data.get("docs", {})
    if docs:
        doc_parts = [f"{k}={v}" for k, v in docs.items() if v]
        if doc_parts:
            print(f"  Docs:          {', '.join(doc_parts)}")

    # Agent block
    agent = data.get("agent")
    if agent:
        purpose = agent.get("purpose") if isinstance(agent, dict) else None
        if purpose:
            print(f"  Purpose:       {purpose}")

    # Warnings
    warnings = data.get("warnings", [])
    if warnings:
        print("  ⚠ Warnings:")
        for w in warnings:
            print(f"    • {w}")


def build_parser() -> argparse.ArgumentParser:
    """Build the ``packs`` subcommand parser."""
    parser = argparse.ArgumentParser(
        prog="python3 -m astrid packs",
        description="Manage and validate Astrid packs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate", help="Statically validate a pack directory."
    )
    validate_parser.add_argument(
        "path", nargs="?", default=".", help="Path to pack root (default: .)"
    )
    validate_parser.add_argument(
        "--warnings", action="store_true", help="Also print non-fatal warnings."
    )
    validate_parser.set_defaults(handler=_handle_validate)

    new_parser = subparsers.add_parser(
        "new", help="Create a new pack skeleton in the current directory."
    )
    new_parser.add_argument("pack_id", help="Pack identifier (e.g., my_project).")
    new_parser.set_defaults(handler=_handle_new)

    list_parser = subparsers.add_parser(
        "list", help="List installed external packs."
    )
    list_parser.set_defaults(handler=_handle_list)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Show details for an installed pack."
    )
    inspect_parser.add_argument("pack_id", help="Pack identifier to inspect.")
    inspect_parser.add_argument(
        "--agent", action="store_true",
        help="Emit agent-focused subset (purpose, entrypoints, constraints, context, secrets)."
    )
    inspect_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output as JSON."
    )
    inspect_parser.set_defaults(handler=_handle_inspect)

    # ── install ──
    install_parser = subparsers.add_parser(
        "install", help="Install a pack from a local directory or Git URL."
    )
    install_parser.add_argument(
        "source", help="Path to the pack source directory or a Git URL."
    )
    install_parser.add_argument(
        "--dry-run", action="store_true",
        help="Print trust summary without installing."
    )
    install_parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt."
    )
    install_parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing install (preserve old revision)."
    )
    install_parser.set_defaults(handler=_handle_install)

    # ── update ──
    update_parser = subparsers.add_parser(
        "update", help="Update an installed pack from its source."
    )
    update_parser.add_argument(
        "pack_id", help="Pack identifier to update."
    )
    update_parser.add_argument(
        "--dry-run", action="store_true",
        help="Print diff summary without updating."
    )
    update_parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt."
    )
    update_parser.set_defaults(handler=_handle_update)

    # ── uninstall ──
    uninstall_parser = subparsers.add_parser(
        "uninstall", help="Remove an installed pack."
    )
    uninstall_parser.add_argument(
        "pack_id", help="Pack identifier to uninstall."
    )
    uninstall_parser.add_argument(
        "--keep-revisions", action="store_true",
        help="Keep revision directories on disk."
    )
    uninstall_parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt."
    )
    uninstall_parser.set_defaults(handler=_handle_uninstall)

    # ── rollback ──
    rollback_parser = subparsers.add_parser(
        "rollback", help="Rollback an installed pack to a previous revision."
    )
    rollback_parser.add_argument(
        "pack_id", help="Pack identifier to rollback."
    )
    rollback_parser.add_argument(
        "--revision",
        help="Specific revision directory name to activate. "
        "If omitted, shows an interactive numbered list.",
    )
    rollback_parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation prompt."
    )
    rollback_parser.set_defaults(handler=_handle_rollback)

    return parser


def _handle_validate(args: argparse.Namespace) -> int:
    """Handler for ``packs validate``."""
    return cmd_validate([args.path] + (["--warnings"] if args.warnings else []))


def _handle_new(args: argparse.Namespace) -> int:
    """Handler for ``packs new``."""
    return cmd_new([args.pack_id])


def _handle_list(args: argparse.Namespace) -> int:
    """Handler for ``packs list``."""
    return cmd_list([])


def _handle_inspect(args: argparse.Namespace) -> int:
    """Handler for ``packs inspect``."""
    argv = [args.pack_id]
    if args.agent:
        argv.append("--agent")
    if args.json_output:
        argv.append("--json")
    return cmd_inspect(argv)


def _handle_install(args: argparse.Namespace) -> int:
    """Handler for ``packs install``."""
    from astrid.packs.install import cmd_install

    argv = [args.source]
    if args.dry_run:
        argv.append("--dry-run")
    if args.yes:
        argv.append("--yes")
    if args.force:
        argv.append("--force")
    return cmd_install(argv)


def _handle_update(args: argparse.Namespace) -> int:
    """Handler for ``packs update``."""
    from astrid.packs.install import cmd_update

    argv = [args.pack_id]
    if args.dry_run:
        argv.append("--dry-run")
    if args.yes:
        argv.append("--yes")
    return cmd_update(argv)


def _handle_uninstall(args: argparse.Namespace) -> int:
    """Handler for ``packs uninstall``."""
    from astrid.packs.install import cmd_uninstall

    argv = [args.pack_id]
    if args.keep_revisions:
        argv.append("--keep-revisions")
    if args.yes:
        argv.append("--yes")
    return cmd_uninstall(argv)


def _handle_rollback(args: argparse.Namespace) -> int:
    """Handler for ``packs rollback``."""
    from astrid.packs.install import cmd_rollback

    argv = [args.pack_id]
    if args.revision:
        argv.extend(["--revision", args.revision])
    if args.yes:
        argv.append("--yes")
    return cmd_rollback(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for ``astrid packs`` CLI.

    Args:
        argv: Command-line arguments (excluding the ``packs`` verb).
              If None, reads from sys.argv[1:].

    Returns:
        Exit code (0 on success).
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits on --help or parse errors
        return int(exc.code) if exc.code is not None else 2

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_usage(file=sys.stderr)
        return 2

    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
