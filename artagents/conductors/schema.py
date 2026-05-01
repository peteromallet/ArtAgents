"""Stdlib schema and validation for ArtAgents conductors."""

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
    CachePolicy,
    CommandSpec,
    IsolationMetadata,
    Output,
    Port,
)


CONDUCTOR_KINDS = {"built_in", "external"}
RUNTIME_KINDS = {"python", "command"}


class ConductorValidationError(ValueError):
    """Raised when a conductor manifest or definition is structurally invalid."""


@dataclass(frozen=True)
class RuntimeSpec:
    kind: str
    module: str | None = None
    function: str | None = None
    command: CommandSpec | None = None


@dataclass(frozen=True)
class ConductorDefinition:
    id: str
    name: str
    kind: str
    version: str
    runtime: RuntimeSpec
    description: str = ""
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Output, ...] = ()
    child_performers: tuple[str, ...] = ()
    child_conductors: tuple[str, ...] = ()
    cache: CachePolicy = field(default_factory=CachePolicy)
    isolation: IsolationMetadata = field(default_factory=IsolationMetadata)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _drop_none(asdict(self))

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

def validate_conductor_definition(raw: Any) -> ConductorDefinition:
    if isinstance(raw, ConductorDefinition):
        conductor = raw
    else:
        conductor = _parse_conductor(raw)
    _validate_conductor(conductor)
    return conductor


def load_conductor_manifest(path: str | Path) -> ConductorDefinition:
    manifest_path = Path(path)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConductorValidationError(f"conductor manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConductorValidationError(f"invalid JSON conductor manifest {manifest_path}: {exc.msg}") from exc
    try:
        return validate_conductor_definition(raw)
    except ConductorValidationError as exc:
        raise ConductorValidationError(f"{manifest_path}: {exc}") from exc


def _parse_conductor(raw: Any) -> ConductorDefinition:
    data = _require_mapping(raw, "conductor")
    for field_name in ("id", "name", "kind", "version"):
        _require_string(data, field_name, f"conductor.{field_name}")
    if "runtime" not in data:
        raise ConductorValidationError("missing required field conductor.runtime")

    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ConductorValidationError("conductor.metadata must be an object")

    return ConductorDefinition(
        id=data["id"],
        name=data["name"],
        kind=data["kind"],
        version=data["version"],
        runtime=_parse_runtime(data["runtime"], "conductor.runtime"),
        description=_optional_string(data, "description", "conductor.description"),
        inputs=tuple(_parse_port(item, f"conductor.inputs[{index}]") for index, item in enumerate(_optional_list(data, "inputs", "conductor.inputs"))),
        outputs=tuple(_parse_output(item, f"conductor.outputs[{index}]") for index, item in enumerate(_optional_list(data, "outputs", "conductor.outputs"))),
        child_performers=tuple(_optional_string_list(data, "child_performers", "conductor.child_performers")),
        child_conductors=tuple(_optional_string_list(data, "child_conductors", "conductor.child_conductors")),
        cache=_parse_cache(data.get("cache", {}), "conductor.cache"),
        isolation=_parse_isolation(data.get("isolation", {}), "conductor.isolation"),
        metadata=dict(metadata),
    )


def _parse_runtime(raw: Any, path: str) -> RuntimeSpec:
    data = _require_mapping(raw, path)
    kind = _require_string(data, "kind", f"{path}.kind")
    if kind == "python":
        return RuntimeSpec(
            kind=kind,
            module=_optional_nullable_string(data, "module", f"{path}.module"),
            function=_optional_nullable_string(data, "function", f"{path}.function"),
        )
    if kind == "command":
        return RuntimeSpec(kind=kind, command=_parse_command(data.get("command"), f"{path}.command"))
    return RuntimeSpec(
        kind=kind,
        module=_optional_nullable_string(data, "module", f"{path}.module"),
        function=_optional_nullable_string(data, "function", f"{path}.function"),
        command=_parse_command(data.get("command"), f"{path}.command") if "command" in data else None,
    )


def _parse_port(raw: Any, path: str) -> Port:
    data = _require_mapping(raw, path)
    return Port(
        name=_require_string(data, "name", f"{path}.name"),
        type=_optional_string(data, "type", f"{path}.type", default="path"),
        required=_optional_bool(data, "required", f"{path}.required", default=True),
        description=_optional_string(data, "description", f"{path}.description"),
        default=data.get("default"),
        placeholder=_optional_nullable_string(data, "placeholder", f"{path}.placeholder"),
    )


def _parse_output(raw: Any, path: str) -> Output:
    data = _require_mapping(raw, path)
    return Output(
        name=_require_string(data, "name", f"{path}.name"),
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
        return CommandSpec(argv=tuple(_string_list(raw, f"{path}.argv")))
    data = _require_mapping(raw, path)
    env_raw = data.get("env", {})
    if not isinstance(env_raw, dict):
        raise ConductorValidationError(f"{path}.env must be an object")
    env: dict[str, str] = {}
    for key, value in env_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ConductorValidationError(f"{path}.env keys and values must be strings")
        env[key] = value
    return CommandSpec(
        argv=tuple(_string_list(data.get("argv"), f"{path}.argv")),
        cwd=_optional_nullable_string(data, "cwd", f"{path}.cwd"),
        env=env,
    )


def _parse_cache(raw: Any, path: str) -> CachePolicy:
    data = _require_mapping(raw, path)
    return CachePolicy(
        mode=_optional_string(data, "mode", f"{path}.mode", default="sentinel"),
        sentinels=tuple(_optional_string_list(data, "sentinels", f"{path}.sentinels")),
        always_run=_optional_bool(data, "always_run", f"{path}.always_run", default=False),
        per_brief=_optional_bool(data, "per_brief", f"{path}.per_brief", default=False),
    )


def _parse_isolation(raw: Any, path: str) -> IsolationMetadata:
    data = _require_mapping(raw, path)
    return IsolationMetadata(
        mode=_optional_string(data, "mode", f"{path}.mode", default="subprocess"),
        requirements=tuple(_optional_string_list(data, "requirements", f"{path}.requirements")),
        binaries=tuple(_optional_string_list(data, "binaries", f"{path}.binaries")),
        network=_optional_bool(data, "network", f"{path}.network", default=False),
    )


def _validate_conductor(conductor: ConductorDefinition) -> None:
    _validate_non_empty_identifier(conductor.id, "conductor.id")
    _validate_non_empty_string(conductor.name, "conductor.name")
    if conductor.kind not in CONDUCTOR_KINDS:
        raise ConductorValidationError(f"conductor.kind must be one of {sorted(CONDUCTOR_KINDS)}")
    _validate_non_empty_string(conductor.version, "conductor.version")
    _validate_runtime(conductor.runtime)

    input_names = _validate_unique_named(conductor.inputs, "input")
    output_names = _validate_unique_named(conductor.outputs, "output")
    placeholders = set(input_names) | set(output_names)
    placeholders.update({"out", "brief", "python_exec", "conductor_args", "verbose"})

    for port in conductor.inputs:
        _validate_port(port)
        if port.placeholder:
            _validate_non_empty_identifier(port.placeholder, f"input {port.name!r}.placeholder")
            placeholders.add(port.placeholder)
    for output in conductor.outputs:
        _validate_output(output)
        if output.placeholder:
            _validate_non_empty_identifier(output.placeholder, f"output {output.name!r}.placeholder")
            placeholders.add(output.placeholder)
        if output.path_template:
            _validate_placeholders(output.path_template, placeholders, f"output {output.name!r}.path_template")
    for index, child_performer in enumerate(conductor.child_performers):
        _validate_non_empty_identifier(child_performer, f"conductor.child_performers[{index}]")
    for index, child_conductor in enumerate(conductor.child_conductors):
        _validate_non_empty_identifier(child_conductor, f"conductor.child_conductors[{index}]")
    _validate_cache(conductor.cache)
    _validate_isolation(conductor.isolation)
    if conductor.runtime.command is not None:
        _validate_command(conductor.runtime.command, placeholders)


def _validate_runtime(runtime: RuntimeSpec) -> None:
    if runtime.kind not in RUNTIME_KINDS:
        raise ConductorValidationError(f"runtime.kind must be one of {sorted(RUNTIME_KINDS)}")
    if runtime.kind == "python":
        _validate_non_empty_string(runtime.module, "runtime.module")
        _validate_non_empty_string(runtime.function, "runtime.function")
        if runtime.command is not None:
            raise ConductorValidationError("python runtime cannot include runtime.command")
    if runtime.kind == "command":
        if runtime.command is None:
            raise ConductorValidationError("command runtime requires runtime.command")
        if runtime.module is not None or runtime.function is not None:
            raise ConductorValidationError("command runtime cannot include runtime.module or runtime.function")


def _validate_port(port: Port) -> None:
    _validate_non_empty_identifier(port.name, "input.name")
    if port.required and port.default is not None:
        raise ConductorValidationError(f"input {port.name!r} cannot be both required and have a default")


def _validate_output(output: Output) -> None:
    _validate_non_empty_identifier(output.name, "output.name")
    if output.mode not in OUTPUT_MODES:
        raise ConductorValidationError(f"output {output.name!r}.mode must be one of ['create', 'create_or_replace', 'mutate']")


def _validate_cache(cache: CachePolicy) -> None:
    if cache.mode not in CACHE_MODES:
        raise ConductorValidationError("cache.mode must be one of ['always_run', 'none', 'sentinel']")
    if cache.always_run and cache.sentinels:
        raise ConductorValidationError("cache.always_run cannot be combined with cache.sentinels")
    if cache.mode == "none" and (cache.sentinels or cache.always_run or cache.per_brief):
        raise ConductorValidationError("cache.mode 'none' cannot include sentinels, always_run, or per_brief")
    if cache.mode == "always_run" and not cache.always_run:
        raise ConductorValidationError("cache.mode 'always_run' requires cache.always_run=true")


def _validate_isolation(isolation: IsolationMetadata) -> None:
    if isolation.mode not in ISOLATION_MODES:
        raise ConductorValidationError("isolation.mode must be one of ['in_process', 'subprocess']")


def _validate_command(command: CommandSpec, placeholders: set[str]) -> None:
    if not command.argv:
        raise ConductorValidationError("runtime.command.argv must contain at least one argument")
    for index, part in enumerate(command.argv):
        _validate_non_empty_string(part, f"runtime.command.argv[{index}]")
        _validate_placeholders(part, placeholders, f"runtime.command.argv[{index}]")
    if command.cwd:
        _validate_placeholders(command.cwd, placeholders, "runtime.command.cwd")
    for key, value in command.env.items():
        _validate_non_empty_string(key, "runtime.command.env key")
        _validate_placeholders(value, placeholders, f"runtime.command.env[{key!r}]")


def _validate_placeholders(value: str, allowed: set[str], path: str) -> None:
    for placeholder in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", value):
        if placeholder not in allowed:
            raise ConductorValidationError(f"{path} uses unknown placeholder {{{placeholder}}}")


def _validate_unique_named(values: tuple[Port, ...] | tuple[Output, ...], label: str) -> set[str]:
    names: set[str] = set()
    for value in values:
        if value.name in names:
            raise ConductorValidationError(f"duplicate {label} name {value.name!r}")
        names.add(value.name)
    return names


def _validate_non_empty_identifier(value: Any, path: str) -> None:
    _validate_non_empty_string(value, path)
    if not re.match(r"^[A-Za-z][A-Za-z0-9_.-]*$", value):
        raise ConductorValidationError(f"{path} must start with a letter and contain only letters, numbers, '.', '_' or '-'")


def _validate_non_empty_string(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ConductorValidationError(f"{path} must be a non-empty string")


def _require_mapping(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConductorValidationError(f"{path} must be an object")
    return raw


def _require_string(data: dict[str, Any], key: str, path: str) -> str:
    if key not in data:
        raise ConductorValidationError(f"missing required field {path}")
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
        raise ConductorValidationError(f"{path} must be a boolean")
    return value


def _optional_list(data: dict[str, Any], key: str, path: str) -> list[Any]:
    if key not in data:
        return []
    value = data[key]
    if not isinstance(value, list):
        raise ConductorValidationError(f"{path} must be a list")
    return value


def _string_list(raw: Any, path: str) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        raise ConductorValidationError(f"{path} must be a list")
    result: list[str] = []
    for index, value in enumerate(raw):
        if not isinstance(value, str) or not value.strip():
            raise ConductorValidationError(f"{path}[{index}] must be a non-empty string")
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
    "ISOLATION_MODES",
    "OUTPUT_MODES",
    "CachePolicy",
    "CommandSpec",
    "ConductorDefinition",
    "ConductorValidationError",
    "IsolationMetadata",
    "Output",
    "Port",
    "RuntimeSpec",
    "load_conductor_manifest",
    "validate_conductor_definition",
]
