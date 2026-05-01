"""Stdlib schema and validation for ArtAgents executable performers."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from artagents.contracts.schema import (
    CACHE_MODES,
    ISOLATION_MODES,
    OUTPUT_MODES,
    PORT_REQUIRED_TYPES,
    CachePolicy,
    CommandSpec,
    IsolationMetadata,
    Output as PerformerOutput,
    Port as PerformerPort,
)

PERFORMER_KINDS = {"built_in", "external"}
CONDITION_KINDS = {"requires_input", "requires_file", "skip_if_input", "always"}

KNOWN_RUNTIME_PLACEHOLDERS = {
    "asset_pairs",
    "audio",
    "brief",
    "brief_copy",
    "brief_out",
    "brief_slug",
    "cache_dir",
    "drift",
    "env_file",
    "extra_args",
    "keep_downloads",
    "no_prefetch",
    "out",
    "primary_asset",
    "python_exec",
    "render",
    "skip",
    "source_slug",
    "target_duration",
    "theme",
    "theme_explicit",
    "verbose",
    "video",
}

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class PerformerValidationError(ValueError):
    """Raised when a performer manifest or definition is structurally invalid."""


@dataclass(frozen=True)
class ConditionSpec:
    kind: str
    input: str | None = None
    path: str | None = None
    value: Any = None


@dataclass(frozen=True)
class GraphMetadata:
    depends_on: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PerformerDefinition:
    id: str
    name: str
    kind: str
    version: str
    description: str = ""
    inputs: tuple[PerformerPort, ...] = ()
    outputs: tuple[PerformerOutput, ...] = ()
    command: CommandSpec | None = None
    cache: CachePolicy = field(default_factory=CachePolicy)
    conditions: tuple[ConditionSpec, ...] = ()
    graph: GraphMetadata = field(default_factory=GraphMetadata)
    isolation: IsolationMetadata = field(default_factory=IsolationMetadata)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _drop_none(asdict(self))

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def validate_performer_definition(raw: Any) -> PerformerDefinition:
    if isinstance(raw, PerformerDefinition):
        performer = raw
    else:
        performer = _parse_performer(raw)
    _validate_performer(performer)
    return performer


def load_performer_manifest(path: str | Path) -> PerformerDefinition:
    manifest_path = Path(path)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PerformerValidationError(f"performer manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise PerformerValidationError(f"invalid JSON performer manifest {manifest_path}: {exc.msg}") from exc
    try:
        return validate_performer_definition(raw)
    except PerformerValidationError as exc:
        raise PerformerValidationError(f"{manifest_path}: {exc}") from exc


def _parse_performer(raw: Any) -> PerformerDefinition:
    data = _require_mapping(raw, "performer")
    for field_name in ("id", "name", "kind", "version"):
        _require_string(data, field_name, f"performer.{field_name}")

    inputs = tuple(_parse_port(item, f"performer.inputs[{index}]") for index, item in enumerate(_optional_list(data, "inputs", "performer.inputs")))
    outputs = tuple(_parse_output(item, f"performer.outputs[{index}]") for index, item in enumerate(_optional_list(data, "outputs", "performer.outputs")))
    command = _parse_command(data.get("command"), "performer.command")
    cache = _parse_cache(data.get("cache", {}), "performer.cache")
    conditions = tuple(
        _parse_condition(item, f"performer.conditions[{index}]")
        for index, item in enumerate(_optional_list(data, "conditions", "performer.conditions"))
    )
    graph = _parse_graph(data.get("graph", {}), "performer.graph")
    isolation = _parse_isolation(data.get("isolation", {}), "performer.isolation")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise PerformerValidationError("performer.metadata must be an object")

    return PerformerDefinition(
        id=data["id"],
        name=data["name"],
        kind=data["kind"],
        version=data["version"],
        description=_optional_string(data, "description", "performer.description"),
        inputs=inputs,
        outputs=outputs,
        command=command,
        cache=cache,
        conditions=conditions,
        graph=graph,
        isolation=isolation,
        metadata=dict(metadata),
    )


def _parse_port(raw: Any, path: str) -> PerformerPort:
    data = _require_mapping(raw, path)
    name = _require_string(data, "name", f"{path}.name")
    return PerformerPort(
        name=name,
        type=_optional_string(data, "type", f"{path}.type", default="path"),
        required=_optional_bool(data, "required", f"{path}.required", default=True),
        description=_optional_string(data, "description", f"{path}.description"),
        default=data.get("default"),
        placeholder=_optional_nullable_string(data, "placeholder", f"{path}.placeholder"),
    )


def _parse_output(raw: Any, path: str) -> PerformerOutput:
    data = _require_mapping(raw, path)
    name = _require_string(data, "name", f"{path}.name")
    return PerformerOutput(
        name=name,
        type=_optional_string(data, "type", f"{path}.type", default="path"),
        mode=_optional_string(data, "mode", f"{path}.mode", default="create_or_replace"),
        description=_optional_string(data, "description", f"{path}.description"),
        placeholder=_optional_nullable_string(data, "placeholder", f"{path}.placeholder"),
        path_template=_optional_nullable_string(data, "path_template", f"{path}.path_template"),
    )


def _parse_command(raw: Any, path: str) -> CommandSpec | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        argv = tuple(_string_list(raw, f"{path}.argv"))
        return CommandSpec(argv=argv)
    data = _require_mapping(raw, path)
    argv = tuple(_string_list(data.get("argv"), f"{path}.argv"))
    cwd = _optional_nullable_string(data, "cwd", f"{path}.cwd")
    env_raw = data.get("env", {})
    if not isinstance(env_raw, dict):
        raise PerformerValidationError(f"{path}.env must be an object")
    env: dict[str, str] = {}
    for key, value in env_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise PerformerValidationError(f"{path}.env keys and values must be strings")
        env[key] = value
    return CommandSpec(argv=argv, cwd=cwd, env=env)


def _parse_cache(raw: Any, path: str) -> CachePolicy:
    data = _require_mapping(raw, path)
    return CachePolicy(
        mode=_optional_string(data, "mode", f"{path}.mode", default="sentinel"),
        sentinels=tuple(_optional_string_list(data, "sentinels", f"{path}.sentinels")),
        always_run=_optional_bool(data, "always_run", f"{path}.always_run", default=False),
        per_brief=_optional_bool(data, "per_brief", f"{path}.per_brief", default=False),
    )


def _parse_condition(raw: Any, path: str) -> ConditionSpec:
    data = _require_mapping(raw, path)
    return ConditionSpec(
        kind=_require_string(data, "kind", f"{path}.kind"),
        input=_optional_nullable_string(data, "input", f"{path}.input"),
        path=_optional_nullable_string(data, "path", f"{path}.path"),
        value=data.get("value"),
    )


def _parse_graph(raw: Any, path: str) -> GraphMetadata:
    data = _require_mapping(raw, path)
    return GraphMetadata(
        depends_on=tuple(_optional_string_list(data, "depends_on", f"{path}.depends_on")),
        provides=tuple(_optional_string_list(data, "provides", f"{path}.provides")),
        consumes=tuple(_optional_string_list(data, "consumes", f"{path}.consumes")),
    )


def _parse_isolation(raw: Any, path: str) -> IsolationMetadata:
    data = _require_mapping(raw, path)
    return IsolationMetadata(
        mode=_optional_string(data, "mode", f"{path}.mode", default="subprocess"),
        requirements=tuple(_optional_string_list(data, "requirements", f"{path}.requirements")),
        binaries=tuple(_optional_string_list(data, "binaries", f"{path}.binaries")),
        network=_optional_bool(data, "network", f"{path}.network", default=False),
    )


def _validate_performer(performer: PerformerDefinition) -> None:
    _validate_non_empty_identifier(performer.id, "performer.id")
    _validate_non_empty_string(performer.name, "performer.name")
    if performer.kind not in PERFORMER_KINDS:
        raise PerformerValidationError(f"performer.kind must be one of {sorted(PERFORMER_KINDS)}")
    _validate_non_empty_string(performer.version, "performer.version")

    input_names = _validate_unique_named(performer.inputs, "input")
    output_names = _validate_unique_named(performer.outputs, "output")
    placeholders: set[str] = set(KNOWN_RUNTIME_PLACEHOLDERS)
    placeholders.update(input_names)
    placeholders.update(output_names)

    for port in performer.inputs:
        _validate_port(port)
        if port.placeholder:
            _validate_non_empty_identifier(port.placeholder, f"input {port.name!r}.placeholder")
            placeholders.add(port.placeholder)

    for output in performer.outputs:
        _validate_output(output)
        if output.placeholder:
            _validate_non_empty_identifier(output.placeholder, f"output {output.name!r}.placeholder")
            placeholders.add(output.placeholder)
        if output.path_template:
            _validate_placeholders(output.path_template, placeholders, f"output {output.name!r}.path_template")

    _validate_cache(performer.cache)
    _validate_conditions(performer.conditions, input_names)
    _validate_graph(performer.graph)
    _validate_isolation(performer.isolation)
    if performer.command is not None:
        _validate_command(performer.command, placeholders)


def _validate_port(port: PerformerPort) -> None:
    _validate_non_empty_identifier(port.name, "input.name")
    if port.type not in PORT_REQUIRED_TYPES:
        raise PerformerValidationError(f"input {port.name!r}.type must be one of {sorted(PORT_REQUIRED_TYPES)}")
    if port.required and port.default is not None:
        raise PerformerValidationError(f"input {port.name!r} cannot be both required and have a default")


def _validate_output(output: PerformerOutput) -> None:
    _validate_non_empty_identifier(output.name, "output.name")
    if output.type not in PORT_REQUIRED_TYPES:
        raise PerformerValidationError(f"output {output.name!r}.type must be one of {sorted(PORT_REQUIRED_TYPES)}")
    if output.mode not in OUTPUT_MODES:
        raise PerformerValidationError(f"output {output.name!r}.mode must be one of {sorted(OUTPUT_MODES)}")


def _validate_cache(cache: CachePolicy) -> None:
    if cache.mode not in CACHE_MODES:
        raise PerformerValidationError(f"cache.mode must be one of {sorted(CACHE_MODES)}")
    if cache.always_run and cache.sentinels:
        raise PerformerValidationError("cache.always_run cannot be combined with cache.sentinels")
    if cache.mode == "none" and (cache.sentinels or cache.always_run or cache.per_brief):
        raise PerformerValidationError("cache.mode 'none' cannot include sentinels, always_run, or per_brief")
    if cache.mode == "always_run" and not cache.always_run:
        raise PerformerValidationError("cache.mode 'always_run' requires cache.always_run=true")


def _validate_conditions(conditions: tuple[ConditionSpec, ...], input_names: set[str]) -> None:
    for index, condition in enumerate(conditions):
        if condition.kind not in CONDITION_KINDS:
            raise PerformerValidationError(f"condition[{index}].kind must be one of {sorted(CONDITION_KINDS)}")
        if condition.input is not None and condition.input not in input_names:
            raise PerformerValidationError(f"condition[{index}].input references unknown input {condition.input!r}")
        if condition.kind == "requires_input" and not condition.input:
            raise PerformerValidationError(f"condition[{index}] requires an input")
        if condition.kind == "requires_file" and not (condition.input or condition.path):
            raise PerformerValidationError(f"condition[{index}] requires an input or path")


def _validate_graph(graph: GraphMetadata) -> None:
    for label, values in (("depends_on", graph.depends_on), ("provides", graph.provides), ("consumes", graph.consumes)):
        for value in values:
            _validate_non_empty_string(value, f"graph.{label}[]")


def _validate_isolation(isolation: IsolationMetadata) -> None:
    if isolation.mode not in ISOLATION_MODES:
        raise PerformerValidationError(f"isolation.mode must be one of {sorted(ISOLATION_MODES)}")


def _validate_command(command: CommandSpec, placeholders: set[str]) -> None:
    if not command.argv:
        raise PerformerValidationError("command.argv must contain at least one argument")
    for index, part in enumerate(command.argv):
        _validate_non_empty_string(part, f"command.argv[{index}]")
        _validate_placeholders(part, placeholders, f"command.argv[{index}]")
    if command.cwd:
        _validate_placeholders(command.cwd, placeholders, "command.cwd")
    for key, value in command.env.items():
        _validate_non_empty_string(key, "command.env key")
        _validate_placeholders(value, placeholders, f"command.env[{key!r}]")


def _validate_placeholders(value: str, allowed: set[str], path: str) -> None:
    for placeholder in _PLACEHOLDER_RE.findall(value):
        if placeholder not in allowed:
            raise PerformerValidationError(f"{path} uses unknown placeholder {{{placeholder}}}")


def _validate_unique_named(values: tuple[PerformerPort, ...] | tuple[PerformerOutput, ...], label: str) -> set[str]:
    names: set[str] = set()
    for value in values:
        if value.name in names:
            raise PerformerValidationError(f"duplicate {label} name {value.name!r}")
        names.add(value.name)
    return names


def _validate_non_empty_identifier(value: str, path: str) -> None:
    _validate_non_empty_string(value, path)
    if not re.match(r"^[A-Za-z][A-Za-z0-9_.-]*$", value):
        raise PerformerValidationError(f"{path} must start with a letter and contain only letters, numbers, '.', '_' or '-'")


def _validate_non_empty_string(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PerformerValidationError(f"{path} must be a non-empty string")


def _require_mapping(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PerformerValidationError(f"{path} must be an object")
    return raw


def _require_string(data: dict[str, Any], key: str, path: str) -> str:
    if key not in data:
        raise PerformerValidationError(f"missing required field {path}")
    value = data[key]
    _validate_non_empty_string(value, path)
    return value


def _optional_string(data: dict[str, Any], key: str, path: str, *, default: str = "") -> str:
    if key not in data:
        return default
    value = data[key]
    _validate_non_empty_string(value, path)
    return value


def _optional_nullable_string(data: dict[str, Any], key: str, path: str) -> str | None:
    if key not in data or data[key] is None:
        return None
    value = data[key]
    _validate_non_empty_string(value, path)
    return value


def _optional_bool(data: dict[str, Any], key: str, path: str, *, default: bool) -> bool:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise PerformerValidationError(f"{path} must be a boolean")
    return value


def _optional_list(data: dict[str, Any], key: str, path: str) -> list[Any]:
    if key not in data:
        return []
    value = data[key]
    if not isinstance(value, list):
        raise PerformerValidationError(f"{path} must be a list")
    return value


def _string_list(raw: Any, path: str) -> list[str]:
    if not isinstance(raw, list):
        raise PerformerValidationError(f"{path} must be a list")
    result: list[str] = []
    for index, value in enumerate(raw):
        if not isinstance(value, str) or not value.strip():
            raise PerformerValidationError(f"{path}[{index}] must be a non-empty string")
        result.append(value)
    return result


def _optional_string_list(data: dict[str, Any], key: str, path: str) -> list[str]:
    if key not in data:
        return []
    return _string_list(data[key], path)


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, tuple):
        return [_drop_none(item) for item in value]
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


__all__ = [
    "CACHE_MODES",
    "CONDITION_KINDS",
    "ISOLATION_MODES",
    "KNOWN_RUNTIME_PLACEHOLDERS",
    "PERFORMER_KINDS",
    "OUTPUT_MODES",
    "PORT_REQUIRED_TYPES",
    "CachePolicy",
    "CommandSpec",
    "ConditionSpec",
    "GraphMetadata",
    "IsolationMetadata",
    "PerformerDefinition",
    "PerformerOutput",
    "PerformerPort",
    "PerformerValidationError",
    "load_performer_manifest",
    "validate_performer_definition",
]
