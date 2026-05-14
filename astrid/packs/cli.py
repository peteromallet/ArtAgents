"""`astrid packs` CLI: validate and new subcommands.

``packs validate <path>`` statically validates a pack root directory.
``packs new <id>`` scaffolds a minimal pack skeleton in the CWD.

Neither command loads the built-in registry, imports pack code, or
requires a bound session.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

from astrid.packs.validate import validate_pack

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

    return parser


def _handle_validate(args: argparse.Namespace) -> int:
    """Handler for ``packs validate``."""
    return cmd_validate([args.path] + (["--warnings"] if args.warnings else []))


def _handle_new(args: argparse.Namespace) -> int:
    """Handler for ``packs new``."""
    return cmd_new([args.pack_id])


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
