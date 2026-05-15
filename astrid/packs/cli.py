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
from typing import Any, Optional

import yaml

from astrid.core.pack import pack_manifest_path
from astrid.packs.agent_index import build_agent_index
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
What problems does it solve? What triggers its use?

## Entrypoints

List the orchestrators agents should start with for common tasks.
These are the high-level, safe entry points designed for agent consumption.
(Synced from the `agent.normal_entrypoints` and `agent.entrypoints` fields in pack.yaml.)

## Low-Level Executors

Describe executors that are building blocks, not primary entrypoints.
Agents should prefer orchestrators unless they know exactly which executor they need.

## Required Context

What inputs, environment variables, or prior knowledge does this pack assume?
(Synced from `agent.required_context` in pack.yaml.)

## Do Not Use For

Scenarios where this pack should NOT be used.
(Synced from `agent.do_not_use_for` in pack.yaml.)

## Secrets and Dependencies

List required and optional secrets, plus any Python, npm, or system dependencies.
(Synced from `secrets` and `dependencies` in pack.yaml.)
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
# astrid_version: "1.0.0"
# keywords:
#   - example
#   - template
# capabilities:
#   - file_io
#   - network
content:
  executors: executors
  orchestrators: orchestrators
  elements: elements
agent:
  purpose: "TODO: describe what this pack is for"
  # normal_entrypoints:
  #   - my_orchestrator
  # entrypoints:
  #   - legacy_entrypoint
  # do_not_use_for: "Destructive operations that cannot be undone"
  # required_context:
  #   - "API key for external service"
# secrets:
#   - name: API_KEY
#     required: true
#     description: "API key for the external service"
#   - name: OPTIONAL_FLAG
#     required: false
#     description: "Optional feature flag"
# dependencies:
#   python:
#     - requests>=2.28
#   npm:
#     - chalk@5
#   system:
#     - git
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
    full_data = _build_full_inspect(record, manifest, trust_summary, rev_dir=rev_dir)
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
    secrets_section = manifest.get("secrets")

    view: dict = {}

    # Purpose
    purpose = agent_section.get("purpose")
    if purpose:
        view["purpose"] = str(purpose)

    # Entrypoints — prefer normal_entrypoints, fall back to entrypoints
    normal_entrypoints = trust_summary.get("normal_entrypoints", [])
    if not normal_entrypoints and isinstance(agent_section.get("normal_entrypoints"), list):
        normal_entrypoints = [str(ep) for ep in agent_section["normal_entrypoints"] if ep]
    entrypoints = trust_summary.get("entrypoints", [])
    if not entrypoints and isinstance(agent_section.get("entrypoints"), list):
        entrypoints = [str(ep) for ep in agent_section["entrypoints"] if ep]
    display_entrypoints = normal_entrypoints if normal_entrypoints else entrypoints
    if display_entrypoints:
        view["normal_entrypoints"] = normal_entrypoints if normal_entrypoints else None
        view["entrypoints"] = display_entrypoints

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

    # do_not_use_for and required_context from agent section
    do_not_use_for = agent_section.get("do_not_use_for")
    if do_not_use_for:
        view["do_not_use_for"] = str(do_not_use_for)

    required_context = agent_section.get("required_context")
    if isinstance(required_context, list):
        view["required_context"] = [str(rc) for rc in required_context if rc]

    # Secrets — handle both new and old formats
    if isinstance(secrets_section, list):
        # New format: list of {name, required, description}
        structured_secrets = []
        for s_obj in secrets_section:
            if isinstance(s_obj, dict) and s_obj.get("name"):
                structured_secrets.append({
                    "name": str(s_obj["name"]),
                    "required": bool(s_obj.get("required", False)),
                    "description": str(s_obj.get("description", "")),
                })
        view["secrets"] = structured_secrets
    elif isinstance(secrets_section, dict):
        # Old format: dict with 'required' list
        secrets_list = trust_summary.get("declared_secrets", [])
        if not secrets_list and isinstance(secrets_section.get("required"), list):
            secrets_list = [str(s) for s in secrets_section["required"] if s]
        if secrets_list:
            view["secrets"] = secrets_list

    # Keywords and capabilities from manifest
    keywords_raw = manifest.get("keywords")
    if isinstance(keywords_raw, list):
        view["keywords"] = [str(k) for k in keywords_raw if k]

    capabilities_raw = manifest.get("capabilities")
    if isinstance(capabilities_raw, list):
        view["capabilities"] = [str(c) for c in capabilities_raw if c]

    return view


def _print_agent_view(view: dict) -> None:
    """Pretty-print an agent-focused pack view."""
    print(f"━━━ Agent View: {view.get('pack_id', '?')} ━━━")
    if "purpose" in view:
        print(f"Purpose:        {view['purpose']}")
    if "entrypoints" in view:
        eps = view["entrypoints"]
        if isinstance(eps, list):
            print(f"Entrypoints:    {', '.join(eps)}")
    if "normal_entrypoints" in view and view.get("normal_entrypoints"):
        print(f"Normal EPts:    {', '.join(view['normal_entrypoints'])}")
    if "constraints" in view:
        print(f"Constraints:    {view['constraints']}")
    if "context" in view:
        print(f"Context:        {view['context']}")
    if "do_not_use_for" in view:
        print(f"Do Not Use For: {view['do_not_use_for']}")
    if "required_context" in view:
        print(f"Req. Context:   {', '.join(view['required_context'])}")
    if "secrets" in view:
        secrets = view["secrets"]
        if isinstance(secrets, list) and secrets and isinstance(secrets[0], dict):
            for s_obj in secrets:
                req = " (required)" if s_obj.get("required") else ""
                print(f"Secret:         {s_obj['name']}{req}: {s_obj.get('description', '')}")
        else:
            print(f"Secrets:        {', '.join(secrets)}")
    if "keywords" in view:
        print(f"Keywords:       {', '.join(view['keywords'])}")
    if "capabilities" in view:
        print(f"Capabilities:   {', '.join(view['capabilities'])}")


# ---------------------------------------------------------------------------
# Full inspect helpers
# ---------------------------------------------------------------------------

# Recognised component manifest filenames keyed by kind.
_INSPECT_COMPONENT_MANIFEST_NAMES: dict[str, tuple[str, ...]] = {
    "executor": ("executor.yaml", "executor.yml", "executor.json"),
    "orchestrator": ("orchestrator.yaml", "orchestrator.yml", "orchestrator.json"),
}


def _find_component_manifest(comp_dir: Path, kind: str) -> Path | None:
    """Return the first manifest file found in *comp_dir* for *kind*."""
    names = _INSPECT_COMPONENT_MANIFEST_NAMES.get(kind, ())
    for name in sorted(names):
        candidate = comp_dir / name
        if candidate.is_file():
            return candidate
    return None


def _read_stage_excerpt(stage_path: Path, *, max_lines: int = 30) -> str | None:
    """Return a bounded excerpt from a STAGE.md file.

    Reads at most *max_lines* lines, stopping early at the first ``##``
    heading (ATX level-2).  Returns ``None`` when the file cannot be read.
    """
    if not stage_path.is_file():
        return None
    try:
        text = stage_path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    excerpt_lines: list[str] = []
    for i, line in enumerate(lines):
        if i >= max_lines:
            break
        if line.startswith("##") and i > 0:
            break
        excerpt_lines.append(line)
    return "\n".join(excerpt_lines).strip() or None


def _scan_inspect_components(
    rev_dir: Path | None, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    """Scan component manifests under declared content roots in *rev_dir*.

    Returns a deterministic (sorted by id) list of component overview dicts.
    Each dict includes: id, name, kind, description, runtime, is_entrypoint,
    docs_paths, stage_excerpt.
    """
    if rev_dir is None:
        return []

    content = manifest.get("content", {}) if isinstance(manifest.get("content"), dict) else {}
    agent = manifest.get("agent", {}) if isinstance(manifest.get("agent"), dict) else {}
    normal_eps = set()
    if isinstance(agent.get("normal_entrypoints"), list):
        normal_eps = {str(ep) for ep in agent["normal_entrypoints"] if ep}
    if not normal_eps and isinstance(agent.get("entrypoints"), list):
        normal_eps = {str(ep) for ep in agent["entrypoints"] if ep}

    components: list[dict[str, Any]] = []

    for comp_kind in ("executors", "orchestrators"):
        comp_root_rel = content.get(comp_kind)
        if not isinstance(comp_root_rel, str) or not comp_root_rel.strip():
            continue
        comp_root = rev_dir / comp_root_rel
        if not comp_root.is_dir():
            continue

        manifest_kind = comp_kind.rstrip("s")  # "executors" -> "executor"

        for comp_dir in sorted(comp_root.iterdir()):
            if not comp_dir.is_dir() or comp_dir.name.startswith("."):
                continue
            if comp_dir.name == "__pycache__":
                continue

            mf_path = _find_component_manifest(comp_dir, manifest_kind)
            if mf_path is None:
                continue

            data: dict[str, Any] | None
            try:
                if mf_path.suffix == ".json":
                    import json as _json_inspect
                    data = _json_inspect.loads(mf_path.read_text(encoding="utf-8"))
                else:
                    data = yaml.safe_load(mf_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            if not isinstance(data, dict):
                continue

            comp_id = str(data.get("id", comp_dir.name))
            name = str(data.get("name", comp_id))
            description = str(data.get("description", ""))
            kind = str(data.get("kind", manifest_kind))

            # Runtime
            runtime_raw = data.get("runtime", {}) if isinstance(data.get("runtime"), dict) else {}
            runtime: dict[str, Any] | None = None
            if runtime_raw:
                runtime = {
                    "type": runtime_raw.get("type"),
                    "entrypoint": runtime_raw.get("entrypoint"),
                    "callable": runtime_raw.get("callable"),
                }

            # Is entrypoint?
            is_entrypoint = comp_id in normal_eps

            # Docs paths
            docs = data.get("docs", {}) if isinstance(data.get("docs"), dict) else {}
            stage_rel = docs.get("stage", "STAGE.md")
            stage_path = comp_dir / stage_rel
            docs_paths: dict[str, str] = {"stage": str(stage_path)}

            # Stage excerpt
            stage_excerpt = _read_stage_excerpt(stage_path)

            components.append({
                "id": comp_id,
                "name": name,
                "kind": kind,
                "description": description,
                "runtime": runtime,
                "is_entrypoint": is_entrypoint,
                "docs_paths": docs_paths,
                "stage_excerpt": stage_excerpt,
            })

    # Sort by id for determinism
    components.sort(key=lambda c: c["id"])
    return components


def _build_full_inspect(
    record: "InstallRecord", manifest: dict, trust_summary: dict,
    *, rev_dir: "Path | None" = None,
) -> dict:
    """Build a full inspect dict for JSON or pretty-print output.

    When *rev_dir* is provided, component manifests under declared content
    roots are scanned and STAGE.md excerpts are extracted for each component.
    """
    # ── Structured secrets ──────────────────────────────────────────
    secrets_raw = manifest.get("secrets")
    structured_secrets: list[dict[str, Any]] = []
    if isinstance(secrets_raw, list):
        for s_obj in secrets_raw:
            if isinstance(s_obj, dict) and s_obj.get("name"):
                structured_secrets.append({
                    "name": str(s_obj["name"]),
                    "required": bool(s_obj.get("required", False)),
                    "description": str(s_obj.get("description", "")),
                })
    elif isinstance(secrets_raw, dict):
        req_list = secrets_raw.get("required")
        if isinstance(req_list, list):
            for s in req_list:
                if s:
                    structured_secrets.append({
                        "name": str(s), "required": True, "description": "",
                    })

    # ── Structured dependencies ─────────────────────────────────────
    deps_raw = manifest.get("dependencies")
    structured_deps: dict[str, list[str]] = {}
    if isinstance(deps_raw, dict):
        for eco in ("python", "npm", "system"):
            eco_deps = deps_raw.get(eco)
            if isinstance(eco_deps, list):
                structured_deps[eco] = [str(d) for d in eco_deps if d]

    # ── Components scan ─────────────────────────────────────────────
    components = _scan_inspect_components(rev_dir, manifest) if rev_dir is not None else []

    result = {
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
        "secrets": structured_secrets,  # structured: [{name, required, description}]
        "dependencies": trust_summary.get("dependencies", []),
        "dependencies_struct": trust_summary.get("dependencies_struct", {}),
        "docs": trust_summary.get("docs", {}),
        "warnings": trust_summary.get("warnings", []),
        "agent": manifest.get("agent") if isinstance(manifest.get("agent"), dict) else None,
        # Git-enriched and trust fields
        "git_url": record.git_url,
        "commit_sha": record.commit_sha,
        "source_type": record.source_type,
        "requested_ref": record.requested_ref,
        "astrid_version": record.astrid_version if hasattr(record, 'astrid_version') else None,
        "trust_tier": record.trust_tier,
        "manifest_digest": record.manifest_digest if hasattr(record, 'manifest_digest') else None,
        "previous_active_revision": record.previous_active_revision if hasattr(record, 'previous_active_revision') else None,
        # New structured fields from trust_summary
        "normal_entrypoints": trust_summary.get("normal_entrypoints", []),
        "do_not_use_for": trust_summary.get("do_not_use_for"),
        "required_context": trust_summary.get("required_context", []),
        "keywords": trust_summary.get("keywords", []),
        "capabilities": trust_summary.get("capabilities", []),
        # Component details (scanned from disk)
        "components": components,
    }
    return result


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

    # Secrets (structured)
    secrets = data.get("secrets", [])
    if secrets:
        if isinstance(secrets, list) and secrets and isinstance(secrets[0], dict):
            for s_obj in secrets:
                req = " (required)" if s_obj.get("required") else ""
                desc = s_obj.get("description", "")
                print(f"  Secret:        {s_obj['name']}{req}{': ' + desc if desc else ''}")
        else:
            print(f"  Secrets:       {', '.join(str(s) for s in secrets)}")

    # Dependencies
    deps = data.get("dependencies", [])
    if deps:
        if isinstance(deps, list):
            print(f"  Dependencies:  {', '.join(deps)}")
        elif isinstance(deps, dict):
            dep_parts = []
            for eco, pkg_list in deps.items():
                if pkg_list:
                    dep_parts.append(f"{eco}:{','.join(pkg_list)}")
            if dep_parts:
                print(f"  Dependencies:  {'; '.join(dep_parts)}")

    # Structured dependencies
    deps_struct = data.get("dependencies_struct", {})
    if deps_struct:
        dep_parts = []
        for eco, pkg_list in deps_struct.items():
            if pkg_list:
                dep_parts.append(f"{eco}:{','.join(pkg_list)}")
        if dep_parts:
            print(f"  Deps Struct:   {'; '.join(dep_parts)}")

    # New structured fields
    normal_entrypoints = data.get("normal_entrypoints", [])
    if normal_entrypoints:
        print(f"  Normal EPts:   {', '.join(normal_entrypoints)}")

    do_not_use_for = data.get("do_not_use_for")
    if do_not_use_for:
        print(f"  DoNotUseFor:   {do_not_use_for}")

    required_context = data.get("required_context", [])
    if required_context:
        print(f"  Req. Context:  {', '.join(required_context)}")

    keywords = data.get("keywords", [])
    if keywords:
        print(f"  Keywords:      {', '.join(keywords)}")

    capabilities = data.get("capabilities", [])
    if capabilities:
        print(f"  Capabilities:  {', '.join(capabilities)}")

    # Components list
    components = data.get("components", [])
    if components:
        print(f"  Components:    ({len(components)} total)")
        for comp in components:
            ep_mark = " [ENTRYPOINT]" if comp.get("is_entrypoint") else ""
            print(f"    • {comp['id']} ({comp.get('kind', '?')}){ep_mark}: {comp.get('description', '')[:80]}")
            se = comp.get("stage_excerpt")
            if se:
                first_line = se.split("\n")[0][:120]
                print(f"      stage: {first_line}")

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

    # ── agent-index ──
    agent_index_parser = subparsers.add_parser(
        "agent-index",
        help="Emit a machine-readable pack index for agents.",
    )
    agent_index_parser.add_argument(
        "--pack-id",
        help="Limit output to a single pack (returns the pack dict or null).",
    )
    agent_index_parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output as JSON (default).",
    )
    agent_index_parser.add_argument(
        "--text", dest="text_output", action="store_true",
        help="Output as a human-readable text table.",
    )
    agent_index_parser.set_defaults(handler=_handle_agent_index)

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


def _handle_agent_index(args: argparse.Namespace) -> int:
    """Handler for ``packs agent-index``."""
    import json as _json

    from astrid.core.pack import PackResolver, packs_root
    from astrid.core.pack_store import InstalledPackStore

    resolver = PackResolver(packs_root())
    store = InstalledPackStore()

    pack_id = getattr(args, "pack_id", None)
    result = build_agent_index(resolver, store, pack_id=pack_id)

    if args.text_output:
        # Text table output
        if isinstance(result, dict) and "packs" in result:
            packs = result["packs"]
        elif isinstance(result, dict):
            packs = [result]  # single pack from --pack-id filter
        elif result is None:
            packs = []
        else:
            packs = [result]
        if not packs:
            print("(no packs found)")
            return 0
        for pack_entry in packs:
            pid = pack_entry.get("pack_id", "?")
            name = pack_entry.get("name", pid)
            version = pack_entry.get("version", "")
            purpose = pack_entry.get("purpose", "")
            source_type = pack_entry.get("source_type", "")
            normal_eps = pack_entry.get("normal_entrypoints", [])
            comp_counts = pack_entry.get("component_counts", {})
            secrets_cnt = len(pack_entry.get("secrets", []))

            print(f"━━━ {pid} ━━━")
            print(f"  Name:          {name}")
            if version:
                print(f"  Version:       {version}")
            print(f"  Source:        {source_type}")
            if purpose:
                print(f"  Purpose:       {purpose}")
            if normal_eps:
                print(f"  Entrypoints:   {', '.join(normal_eps)}")
            if comp_counts:
                parts = []
                for k in ("executors", "orchestrators", "elements"):
                    if comp_counts.get(k, 0):
                        parts.append(f"{comp_counts[k]} {k}")
                print(f"  Components:    {', '.join(parts)}")
            if secrets_cnt:
                print(f"  Secrets:       {secrets_cnt} declared")

            do_not = pack_entry.get("do_not_use_for")
            if do_not:
                print(f"  DoNotUseFor:   {do_not}")

            req_ctx = pack_entry.get("required_context", [])
            if req_ctx:
                print(f"  Req. Context:  {', '.join(req_ctx)}")

            keywords = pack_entry.get("keywords", [])
            if keywords:
                print(f"  Keywords:      {', '.join(keywords)}")

            capabilities = pack_entry.get("capabilities", [])
            if capabilities:
                print(f"  Capabilities:  {', '.join(capabilities)}")

            deps = pack_entry.get("dependencies", {})
            if deps:
                dep_parts = []
                for eco, pkg_list in deps.items():
                    if pkg_list:
                        dep_parts.append(f"{eco}:{','.join(pkg_list)}")
                if dep_parts:
                    print(f"  Dependencies:  {'; '.join(dep_parts)}")

            components = pack_entry.get("components", [])
            if components:
                print(f"  Components:    ({len(components)} total)")
                for comp in components:
                    ep_mark = " [ENTRYPOINT]" if comp.get("is_entrypoint") else ""
                    desc = comp.get("description", "")[:80]
                    print(f"    • {comp['id']} ({comp.get('kind', '?')}){ep_mark}: {desc}")

            warnings = pack_entry.get("warnings", [])
            if warnings:
                print("  ⚠ Warnings:")
                for w in warnings:
                    print(f"    • {w}")
            print()  # blank line between packs
    else:
        # JSON output (default)
        _json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")

    return 0


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
