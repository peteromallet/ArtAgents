#!/usr/bin/env python3
"""Generate the Remotion effect registry from workspace and active-theme plugins."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

TOOLS_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = TOOLS_DIR.parent
THEMES_ROOT = WORKSPACE_ROOT / "themes"
REMOTION_SRC = TOOLS_DIR / "remotion" / "src"
# Sprint 5: composition source moved into
# packages/timeline-composition. The codegen now writes the generated
# registries directly into the package source so the package is the
# single owner of its own runtime tables. The in-tree shell at
# tools/remotion/ keeps a re-export shim (effects.generated.ts) for
# back-compat with tests that imported from the old location.
PACKAGE_SRC = WORKSPACE_ROOT / "packages" / "timeline-composition" / "typescript" / "src"
OUTPUT = PACKAGE_SRC / "effects.generated.ts"
OUTPUTS = {
    "effects": PACKAGE_SRC / "effects.generated.ts",
    "animations": PACKAGE_SRC / "animations.generated.ts",
    "transitions": PACKAGE_SRC / "transitions.generated.ts",
}
# Shim files in the in-tree shell that re-export from the package, so
# any pre-Sprint-5 callers that still imported the in-tree path resolve.
SHIM_OUTPUTS = {
    "effects": REMOTION_SRC / "effects.generated.ts",
    "animations": REMOTION_SRC / "animations.generated.ts",
    "transitions": REMOTION_SRC / "transitions.generated.ts",
}
ACTIVE_THEME_LINK = TOOLS_DIR / "remotion" / "_active_theme"
ACTIVE_THEME_POINTER = TOOLS_DIR / "remotion" / "_active_theme.txt"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

PrimitiveKind = Literal["effects", "animations", "transitions"]
REQUIRED_PLUGIN_FILES = ("component.tsx", "schema.json", "defaults.json", "meta.json")


@dataclass(frozen=True)
class PluginRecord:
    plugin_id: str
    kind: PrimitiveKind
    scope: str
    root: Path
    meta: dict[str, Any]


EffectRecord = PluginRecord


def _component_name(plugin_id: str) -> str:
    return "".join(part.capitalize() for part in plugin_id.split("-"))


def _resolve_theme_dir(theme: str | None) -> Path | None:
    if theme is None:
        return None
    candidate = Path(theme)
    if candidate.name == "theme.json":
        return candidate.parent.resolve()
    if candidate.exists():
        return (candidate if candidate.is_dir() else candidate.parent).resolve()
    return (THEMES_ROOT / theme).resolve()


def _theme_id(theme_dir: Path | None) -> str | None:
    return theme_dir.name if theme_dir is not None else None


def _validate_kind(kind: str) -> None:
    if kind not in {"effects", "animations", "transitions"}:
        raise ValueError(f"Invalid primitive kind {kind!r}")


def _singular(kind: PrimitiveKind) -> str:
    return kind[:-1]


def _constant_prefix(kind: PrimitiveKind) -> str:
    return _singular(kind).upper()


def _type_name(kind: PrimitiveKind) -> str:
    return f"{_singular(kind).capitalize()}Id"


def _registry_name(kind: PrimitiveKind) -> str:
    return f"{_constant_prefix(kind)}_REGISTRY"


def _ids_name(kind: PrimitiveKind) -> str:
    return f"{_constant_prefix(kind)}_IDS"


def _workspace_root(kind: PrimitiveKind) -> Path:
    _validate_kind(kind)
    return WORKSPACE_ROOT / kind


def _missing_required_files(root: Path) -> list[str]:
    return [filename for filename in REQUIRED_PLUGIN_FILES if not (root / filename).is_file()]


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _load_plugin(
    root: Path,
    plugin_id: str,
    *,
    kind: PrimitiveKind,
    scope: str,
) -> PluginRecord | None:
    missing = _missing_required_files(root)
    if missing:
        missing_text = ", ".join(missing)
        print(f"WARN skipping {root}: missing {missing_text}", file=sys.stderr)
        return None
    meta_path = root / "meta.json"
    meta = _load_json(meta_path)
    if meta.get("id") not in (None, plugin_id):
        raise ValueError(f"{meta_path} must contain matching id {plugin_id!r}")
    return PluginRecord(plugin_id=plugin_id, kind=kind, scope=scope, root=root, meta=meta)


def _scan_plugins(root: Path, *, kind: PrimitiveKind, scope: str) -> dict[str, PluginRecord]:
    if not root.is_dir():
        return {}
    plugins: dict[str, PluginRecord] = {}
    singular = _singular(kind)
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not child.is_dir():
            continue
        if not ID_RE.fullmatch(child.name):
            print(f"WARN skipping {child}: invalid {singular} id", file=sys.stderr)
            continue
        plugin = _load_plugin(child, child.name, kind=kind, scope=scope)
        if plugin is not None:
            plugins[child.name] = plugin
    return plugins


def discover_plugins(kind: PrimitiveKind, theme_dir: Path | None = None) -> dict[str, PluginRecord]:
    _validate_kind(kind)
    plugins = _scan_plugins(_workspace_root(kind), kind=kind, scope="workspace")
    if theme_dir is None:
        return plugins
    theme_plugins = _scan_plugins(theme_dir / kind, kind=kind, scope="theme")
    theme_name = _theme_id(theme_dir) or "unknown"
    singular = _singular(kind)
    for plugin_id, plugin in theme_plugins.items():
        if plugin_id in plugins:
            print(
                f"WARN theme '{theme_name}' overrides workspace {singular} '{plugin_id}'",
                file=sys.stderr,
            )
        plugins[plugin_id] = plugin
    return plugins


def discover_effects(theme_dir: Path | None = None) -> dict[str, EffectRecord]:
    return discover_plugins("effects", theme_dir)


def discover_animations(theme_dir: Path | None = None) -> dict[str, PluginRecord]:
    return discover_plugins("animations", theme_dir)


def discover_transitions(theme_dir: Path | None = None) -> dict[str, PluginRecord]:
    return discover_plugins("transitions", theme_dir)


def _import_path(plugin: PluginRecord) -> str:
    if plugin.scope == "theme":
        return f"@theme-{plugin.kind}/{plugin.plugin_id}/component"
    return f"@workspace-{plugin.kind}/{plugin.plugin_id}/component"


def _clip_type_aliases(effects: dict[str, EffectRecord]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    if "text-card" in effects:
        aliases["text"] = "text-card"
    for effect_id, effect in effects.items():
        raw_aliases = effect.meta.get("clipTypeAliases")
        if isinstance(raw_aliases, list):
            for alias in raw_aliases:
                if isinstance(alias, str) and alias:
                    aliases[alias] = effect_id
    return dict(sorted(aliases.items()))


def _ts_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _ts_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _ts_property_key(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", value) else _ts_string(value)


def _write_active_theme_pointer(theme_dir: Path | None) -> None:
    if theme_dir is None:
        if ACTIVE_THEME_LINK.is_symlink() or ACTIVE_THEME_LINK.is_file():
            ACTIVE_THEME_LINK.unlink()
        if ACTIVE_THEME_POINTER.exists():
            ACTIVE_THEME_POINTER.unlink()
        return

    if os.name == "nt":
        ACTIVE_THEME_POINTER.write_text(str(theme_dir.resolve()) + "\n", encoding="utf-8")
        return

    if ACTIVE_THEME_POINTER.exists():
        ACTIVE_THEME_POINTER.unlink()
    if ACTIVE_THEME_LINK.is_symlink() or ACTIVE_THEME_LINK.is_file():
        ACTIVE_THEME_LINK.unlink()
    elif ACTIVE_THEME_LINK.exists():
        raise RuntimeError(f"{ACTIVE_THEME_LINK} exists and is not a symlink")
    ACTIVE_THEME_LINK.symlink_to(theme_dir.resolve(), target_is_directory=True)


def generate(*, theme_dir: Path | None = None) -> str:
    return generate_primitive_registry("effects", theme_dir=theme_dir)


def generate_primitive_registry(kind: PrimitiveKind, *, theme_dir: Path | None = None) -> str:
    _validate_kind(kind)
    if kind == "effects":
        return _generate_effect_registry(theme_dir=theme_dir)

    component_type = "AnimationComponent" if kind == "animations" else "TransitionComponent"
    meta_type = "AnimationMeta" if kind == "animations" else "Record<string, unknown>"
    plugins = discover_plugins(kind, theme_dir)
    plugin_ids = sorted(plugins)
    imports = [
        f"import {_component_name(plugin_id)} from '{_import_path(plugins[plugin_id])}';"
        for plugin_id in plugin_ids
    ]
    registry_entries = [
        f"  '{plugin_id}': {_component_name(plugin_id)},"
        for plugin_id in plugin_ids
    ]
    defaults_entries = [
        f"  '{plugin_id}': {_ts_json(_load_json(plugins[plugin_id].root / 'defaults.json'))},"
        for plugin_id in plugin_ids
    ]
    meta_entries = [
        f"  '{plugin_id}': {_ts_json(plugins[plugin_id].meta)},"
        for plugin_id in plugin_ids
    ]
    ids = ", ".join(_ts_string(plugin_id) for plugin_id in plugin_ids)
    active_theme = f"{json.dumps(_theme_id(theme_dir))} as const" if theme_dir is not None else "null"
    ids_name = _ids_name(kind)
    type_name = _type_name(kind)
    registry_name = _registry_name(kind)
    defaults_name = f"{_constant_prefix(kind)}_DEFAULTS"
    meta_name = f"{_constant_prefix(kind)}_META"
    blocks = [
        "// DO NOT EDIT - generated by tools/scripts/gen_effect_registry.py",
        f"import type {{{component_type}, {meta_type}}} from './effects-types';"
        if kind == "animations"
        else f"import type {{{component_type}}} from './effects-types';",
        *imports,
        "",
        f"export const ACTIVE_THEME_ID = {active_theme};",
        f"export const {ids_name} = [{ids}] as const;",
        f"export type {type_name} = typeof {ids_name}[number];",
        f"export const {registry_name}: Record<{type_name}, {component_type}> = {{",
        *registry_entries,
        "};",
        f"export const {defaults_name}: Record<{type_name}, Record<string, unknown>> = {{",
        *defaults_entries,
        "};",
        f"export const {meta_name}: Record<{type_name}, {meta_type}> = {{",
        *meta_entries,
        "};",
        "",
    ]
    return "\n".join(blocks)


def _generate_effect_registry(*, theme_dir: Path | None = None) -> str:
    effects = discover_effects(theme_dir)
    effect_ids = sorted(effects)
    imports = [
        f"import {_component_name(effect_id)} from '{_import_path(effects[effect_id])}';"
        for effect_id in effect_ids
    ]
    registry_entries = [
        f"  '{effect_id}': {_component_name(effect_id)},"
        for effect_id in effect_ids
    ]
    ids = ", ".join(_ts_string(effect_id) for effect_id in effect_ids)
    aliases = _clip_type_aliases(effects)
    alias_entries = [
        f"  {_ts_property_key(alias)}: {_ts_string(effect_id)},"
        for alias, effect_id in aliases.items()
    ]
    active_theme = f"{json.dumps(_theme_id(theme_dir))} as const" if theme_dir is not None else "null"
    blocks = [
        "// DO NOT EDIT - generated by tools/scripts/gen_effect_registry.py",
        "import type {EffectComponent} from './effects-types';",
        *imports,
        "",
        f"export const ACTIVE_THEME_ID = {active_theme};",
        f"export const EFFECT_IDS = [{ids}] as const;",
        "export type EffectId = typeof EFFECT_IDS[number];",
        "export const EFFECT_REGISTRY: Record<EffectId, EffectComponent> = {",
        *registry_entries,
        "};",
        "export const CLIP_TYPE_ALIASES: Record<string, EffectId> = {",
        *alias_entries,
        "};",
        "",
    ]
    return "\n".join(blocks)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Remotion effect registry.")
    parser.add_argument("--theme", help="Theme id, theme directory, or path to theme.json.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    theme_dir = _resolve_theme_dir(args.theme)
    _write_active_theme_pointer(theme_dir)
    for kind, output in OUTPUTS.items():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(generate_primitive_registry(kind, theme_dir=theme_dir), encoding="utf-8")
    # Sprint 5: in-tree shim re-exports for back-compat. Anything that
    # still imports from `tools/remotion/src/{effects,animations,
    # transitions}.generated` resolves through the package.
    for kind, shim in SHIM_OUTPUTS.items():
        shim.parent.mkdir(parents=True, exist_ok=True)
        shim.write_text(
            "// DO NOT EDIT - generated shim by tools/scripts/gen_effect_registry.py\n"
            "// Re-exports the package's registry from\n"
            "// `@banodoco/timeline-composition/typescript/src/<kind>.generated`.\n"
            f"export * from '@banodoco/timeline-composition/typescript/src/{kind}.generated';\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
