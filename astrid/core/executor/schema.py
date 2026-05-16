"""Stdlib schema and validation for Astrid executable executors."""

from __future__ import annotations

import json
import keyword
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from astrid.contracts.schema import (
    CACHE_MODES,
    ISOLATION_MODES,
    OUTPUT_MODES,
    PORT_REQUIRED_TYPES,
    CachePolicy,
    CommandSpec,
    IsolationMetadata,
    Output as ExecutorOutput,
    Port as ExecutorPort,
)
from astrid.timeline import ClipClassifiedKind

EXECUTOR_KINDS = {"built_in", "external"}
EXTERNAL_RUNTIME_MODES = {"api", "package"}
EXTERNAL_RUNTIME_SOURCE_KINDS = {"git", "path", "pypi"}
EXTERNAL_RUNTIME_INSTALL_STRATEGIES = {"pip_args", "pyproject", "requirements"}
CONDITION_KINDS = {"requires_input", "requires_file", "skip_if_input", "always"}
CLIP_KIND_VALUES = tuple(kind.value for kind in ClipClassifiedKind)
PIPELINE_REQUIREMENT_FACTS = {
    "arrangement",
    "assets",
    "audio",
    "brief",
    "generative_visuals_enabled",
    "metadata",
    "pool",
    "quality_zones",
    "quote_candidates",
    "rendered_video",
    "scene_descriptions",
    "scene_triage",
    "scenes",
    "shots",
    "source_audio",
    "source_media",
    "source_video",
    "target_duration",
    "theme",
    "timeline",
    "transcript",
    "video",
}

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


class ExecutorValidationError(ValueError):
    """Raised when a executor manifest or definition is structurally invalid."""


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
class ExternalRuntimeSource:
    kind: str
    url: str | None = None
    ref: str | None = None
    path: str | None = None
    package: str | None = None


@dataclass(frozen=True)
class ExternalRuntimeInstall:
    strategy: str
    target: str


@dataclass(frozen=True)
class ExternalRuntimeMetadata:
    mode: str = "package"
    source: ExternalRuntimeSource | None = None
    install: ExternalRuntimeInstall | None = None
    import_check: str | None = None
    binary_check: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutorDefinition:
    id: str
    name: str
    kind: str
    version: str
    description: str = ""
    short_description: str = ""
    keywords: tuple[str, ...] = ()
    inputs: tuple[ExecutorPort, ...] = ()
    outputs: tuple[ExecutorOutput, ...] = ()
    command: CommandSpec | None = None
    cache: CachePolicy = field(default_factory=CachePolicy)
    conditions: tuple[ConditionSpec, ...] = ()
    graph: GraphMetadata = field(default_factory=GraphMetadata)
    clip_kinds_supported: tuple[str, ...] = ()
    pipeline_requirements: tuple[str, ...] = ()
    isolation: IsolationMetadata = field(default_factory=IsolationMetadata)
    metadata: dict[str, Any] = field(default_factory=dict)
    external_runtime: ExternalRuntimeMetadata | None = None

    def to_dict(self) -> dict[str, Any]:
        data = _drop_none(asdict(self))
        data.pop("external_runtime", None)
        # Derive pack_id from qualified id
        try:
            from astrid.core.pack import qualified_id_pack_id
            data["pack_id"] = qualified_id_pack_id(self.id)
        except Exception:
            pass
        return data

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def validate_executor_definition(raw: Any) -> ExecutorDefinition:
    if isinstance(raw, ExecutorDefinition):
        executor = raw
    else:
        executor = _parse_executor(raw)
    _validate_executor(executor)
    return executor


def load_executor_manifest(path: str | Path) -> ExecutorDefinition:
    definitions = load_executor_manifest_definitions(path)
    if len(definitions) != 1:
        raise ExecutorValidationError(f"executor manifest must define exactly one executor: {Path(path)}")
    return definitions[0]


def load_executor_manifest_definitions(path: str | Path) -> tuple[ExecutorDefinition, ...]:
    manifest_path = Path(path)
    try:
        raw = _load_manifest_payload(manifest_path)
    except FileNotFoundError as exc:
        raise ExecutorValidationError(f"executor manifest not found: {manifest_path}") from exc
    except ValueError as exc:
        raise ExecutorValidationError(f"invalid executor manifest {manifest_path}: {exc}") from exc
    try:
        return _validate_manifest_payload(raw)
    except ExecutorValidationError as exc:
        raise ExecutorValidationError(f"{manifest_path}: {exc}") from exc


def _load_manifest_payload(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as json_exc:
        if path.suffix.lower() not in {".yaml", ".yml"}:
            raise ValueError(f"invalid JSON: {json_exc.msg}") from json_exc
    return _parse_yaml_subset(text)


def _validate_manifest_payload(raw: Any) -> tuple[ExecutorDefinition, ...]:
    if isinstance(raw, dict) and "executors" in raw:
        raw_executors = raw["executors"]
        if not isinstance(raw_executors, list):
            raise ExecutorValidationError("executor manifest field executors must be a list")
        return tuple(validate_executor_definition(item) for item in raw_executors)
    return (validate_executor_definition(raw),)


def _parse_executor(raw: Any) -> ExecutorDefinition:
    data = _require_mapping(raw, "executor")
    for field_name in ("id", "name", "kind", "version"):
        _require_string(data, field_name, f"executor.{field_name}")

    inputs = tuple(_parse_port(item, f"executor.inputs[{index}]") for index, item in enumerate(_optional_list(data, "inputs", "executor.inputs")))
    outputs = tuple(_parse_output(item, f"executor.outputs[{index}]") for index, item in enumerate(_optional_list(data, "outputs", "executor.outputs")))
    # v1 manifests place argv under runtime.command when
    # runtime.type == "command".  The legacy top-level executor.command
    # fallback was removed in Sprint 9 Wave 3 once all shipped packs migrated.
    runtime_raw = data.get("runtime")
    runtime_command: Any = None
    if isinstance(runtime_raw, dict) and runtime_raw.get("type") == "command":
        runtime_command = runtime_raw.get("command")
    command = _parse_command(runtime_command, "executor.runtime.command")
    cache = _parse_cache(data.get("cache", {}), "executor.cache")
    conditions = tuple(
        _parse_condition(item, f"executor.conditions[{index}]")
        for index, item in enumerate(_optional_list(data, "conditions", "executor.conditions"))
    )
    graph = _parse_graph(data.get("graph", {}), "executor.graph")
    clip_kinds_supported = tuple(_parse_clip_kinds_supported(data))
    pipeline_requirements = tuple(_optional_string_list(data, "pipeline_requirements", "executor.pipeline_requirements"))
    isolation = _parse_isolation(data.get("isolation", {}), "executor.isolation")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ExecutorValidationError("executor.metadata must be an object")
    external_runtime = _parse_external_runtime(metadata.get("external_runtime"), "executor.metadata.external_runtime")

    return ExecutorDefinition(
        id=data["id"],
        name=data["name"],
        kind=data["kind"],
        version=data["version"],
        description=_optional_string(data, "description", "executor.description"),
        short_description=_optional_string(data, "short_description", "executor.short_description"),
        keywords=tuple(_optional_string_list(data, "keywords", "executor.keywords")),
        inputs=inputs,
        outputs=outputs,
        command=command,
        cache=cache,
        conditions=conditions,
        graph=graph,
        clip_kinds_supported=clip_kinds_supported,
        pipeline_requirements=pipeline_requirements,
        isolation=isolation,
        metadata=dict(metadata),
        external_runtime=external_runtime,
    )


def _parse_port(raw: Any, path: str) -> ExecutorPort:
    data = _require_mapping(raw, path)
    name = _require_string(data, "name", f"{path}.name")
    return ExecutorPort(
        name=name,
        type=_optional_string(data, "type", f"{path}.type", default="path"),
        required=_optional_bool(data, "required", f"{path}.required", default=True),
        description=_optional_string(data, "description", f"{path}.description"),
        default=data.get("default"),
        placeholder=_optional_nullable_string(data, "placeholder", f"{path}.placeholder"),
    )


def _parse_output(raw: Any, path: str) -> ExecutorOutput:
    data = _require_mapping(raw, path)
    name = _require_string(data, "name", f"{path}.name")
    return ExecutorOutput(
        name=name,
        type=_optional_string(data, "type", f"{path}.type", default="path"),
        mode=_optional_string(data, "mode", f"{path}.mode", default="create_or_replace"),
        description=_optional_string(data, "description", f"{path}.description"),
        placeholder=_optional_nullable_string(data, "placeholder", f"{path}.placeholder"),
        path_template=_optional_nullable_string(data, "path_template", f"{path}.path_template"),
        extension=_optional_nullable_string(data, "extension", f"{path}.extension"),
    )


def _parse_external_runtime(raw: Any, path: str) -> ExternalRuntimeMetadata | None:
    if raw is None:
        return None
    data = _require_mapping(raw, path)
    source = _parse_external_runtime_source(data.get("source"), f"{path}.source")
    install = _parse_external_runtime_install(data.get("install"), f"{path}.install")
    binary_check_raw = data.get("binary_check", [])
    if binary_check_raw is None:
        binary_check: tuple[str, ...] = ()
    else:
        binary_check = tuple(_string_list(binary_check_raw, f"{path}.binary_check"))
    return ExternalRuntimeMetadata(
        mode=_optional_string(data, "mode", f"{path}.mode", default="package"),
        source=source,
        install=install,
        import_check=_optional_nullable_string(data, "import_check", f"{path}.import_check"),
        binary_check=binary_check,
    )


def _parse_external_runtime_source(raw: Any, path: str) -> ExternalRuntimeSource | None:
    if raw is None:
        return None
    data = _require_mapping(raw, path)
    kind = _require_string(data, "kind", f"{path}.kind")
    ref = _optional_nullable_string(data, "ref", f"{path}.ref")
    return ExternalRuntimeSource(
        kind=kind,
        url=_optional_nullable_string(data, "url", f"{path}.url"),
        ref=ref or "main" if kind == "git" else ref,
        path=_optional_nullable_string(data, "path", f"{path}.path"),
        package=_optional_nullable_string(data, "package", f"{path}.package"),
    )


def _parse_external_runtime_install(raw: Any, path: str) -> ExternalRuntimeInstall | None:
    if raw is None:
        return None
    data = _require_mapping(raw, path)
    return ExternalRuntimeInstall(
        strategy=_require_string(data, "strategy", f"{path}.strategy"),
        target=_require_string(data, "target", f"{path}.target"),
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
        raise ExecutorValidationError(f"{path}.env must be an object")
    env: dict[str, str] = {}
    for key, value in env_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ExecutorValidationError(f"{path}.env keys and values must be strings")
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


def _validate_executor(executor: ExecutorDefinition) -> None:
    _validate_qualified_identifier(executor.id, "executor.id")
    _validate_non_empty_string(executor.name, "executor.name")
    if executor.kind not in EXECUTOR_KINDS:
        raise ExecutorValidationError(f"executor.kind must be one of {sorted(EXECUTOR_KINDS)}")
    _validate_non_empty_string(executor.version, "executor.version")
    _validate_capability_text(
        executor.description,
        executor.short_description,
        executor.keywords,
        manifest_id=executor.id,
        error_cls=ExecutorValidationError,
    )

    input_names = _validate_unique_named(executor.inputs, "input")
    output_names = _validate_unique_named(executor.outputs, "output")
    placeholders: set[str] = set(KNOWN_RUNTIME_PLACEHOLDERS)
    placeholders.update(input_names)
    placeholders.update(output_names)

    for port in executor.inputs:
        _validate_port(port)
        if port.placeholder:
            _validate_non_empty_identifier(port.placeholder, f"input {port.name!r}.placeholder")
            placeholders.add(port.placeholder)

    for output in executor.outputs:
        _validate_output(output)
        if output.placeholder:
            _validate_non_empty_identifier(output.placeholder, f"output {output.name!r}.placeholder")
            placeholders.add(output.placeholder)
        if output.path_template:
            _validate_placeholders(output.path_template, placeholders, f"output {output.name!r}.path_template")

    _validate_cache(executor.cache)
    _validate_conditions(executor.conditions, input_names)
    _validate_graph(executor.graph)
    _validate_clip_kinds_supported(executor.clip_kinds_supported)
    _validate_pipeline_requirements(executor.pipeline_requirements)
    _validate_isolation(executor.isolation)
    _validate_external_runtime(executor)
    if executor.command is not None:
        _validate_command(executor.command, placeholders)


def _validate_port(port: ExecutorPort) -> None:
    _validate_non_empty_identifier(port.name, "input.name")
    if port.type not in PORT_REQUIRED_TYPES:
        raise ExecutorValidationError(f"input {port.name!r}.type must be one of {sorted(PORT_REQUIRED_TYPES)}")
    if port.required and port.default is not None:
        raise ExecutorValidationError(f"input {port.name!r} cannot be both required and have a default")


def _validate_output(output: ExecutorOutput) -> None:
    _validate_non_empty_identifier(output.name, "output.name")
    if output.type not in PORT_REQUIRED_TYPES:
        raise ExecutorValidationError(f"output {output.name!r}.type must be one of {sorted(PORT_REQUIRED_TYPES)}")
    if output.mode not in OUTPUT_MODES:
        raise ExecutorValidationError(f"output {output.name!r}.mode must be one of {sorted(OUTPUT_MODES)}")
    if output.extension is not None:
        if not output.extension.startswith("."):
            raise ExecutorValidationError(f"output {output.name!r}.extension must start with '.'")
        if len(output.extension) > 16:
            raise ExecutorValidationError(f"output {output.name!r}.extension must be 16 characters or fewer")
        if any(char in output.extension for char in ("/", "\\")):
            raise ExecutorValidationError(f"output {output.name!r}.extension must not contain path separators")


def _validate_cache(cache: CachePolicy) -> None:
    if cache.mode not in CACHE_MODES:
        raise ExecutorValidationError(f"cache.mode must be one of {sorted(CACHE_MODES)}")
    if cache.always_run and cache.sentinels:
        raise ExecutorValidationError("cache.always_run cannot be combined with cache.sentinels")
    if cache.mode == "none" and (cache.sentinels or cache.always_run or cache.per_brief):
        raise ExecutorValidationError("cache.mode 'none' cannot include sentinels, always_run, or per_brief")
    if cache.mode == "always_run" and not cache.always_run:
        raise ExecutorValidationError("cache.mode 'always_run' requires cache.always_run=true")


def _validate_conditions(conditions: tuple[ConditionSpec, ...], input_names: set[str]) -> None:
    for index, condition in enumerate(conditions):
        if condition.kind not in CONDITION_KINDS:
            raise ExecutorValidationError(f"condition[{index}].kind must be one of {sorted(CONDITION_KINDS)}")
        if condition.input is not None and condition.input not in input_names:
            raise ExecutorValidationError(f"condition[{index}].input references unknown input {condition.input!r}")
        if condition.kind == "requires_input" and not condition.input:
            raise ExecutorValidationError(f"condition[{index}] requires an input")
        if condition.kind == "requires_file" and not (condition.input or condition.path):
            raise ExecutorValidationError(f"condition[{index}] requires an input or path")


def _validate_graph(graph: GraphMetadata) -> None:
    for label, values in (("depends_on", graph.depends_on), ("provides", graph.provides), ("consumes", graph.consumes)):
        for value in values:
            if label == "depends_on":
                _validate_qualified_identifier(value, f"graph.{label}[]")
            else:
                _validate_non_empty_string(value, f"graph.{label}[]")


def _validate_clip_kinds_supported(values: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for index, value in enumerate(values):
        if value not in CLIP_KIND_VALUES:
            raise ExecutorValidationError(
                f"clip_kinds_supported[{index}] must be one of {sorted(CLIP_KIND_VALUES)}"
            )
        if value in seen:
            raise ExecutorValidationError(f"clip_kinds_supported contains duplicate kind {value!r}")
        seen.add(value)


def _validate_pipeline_requirements(values: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for index, value in enumerate(values):
        if value not in PIPELINE_REQUIREMENT_FACTS:
            raise ExecutorValidationError(
                f"pipeline_requirements[{index}] must be one of {sorted(PIPELINE_REQUIREMENT_FACTS)}"
            )
        if value in seen:
            raise ExecutorValidationError(f"pipeline_requirements contains duplicate fact {value!r}")
        seen.add(value)


def _validate_isolation(isolation: IsolationMetadata) -> None:
    if isolation.mode not in ISOLATION_MODES:
        raise ExecutorValidationError(f"isolation.mode must be one of {sorted(ISOLATION_MODES)}")


def _validate_external_runtime(executor: ExecutorDefinition) -> None:
    runtime = executor.external_runtime
    if runtime is None:
        return
    if executor.kind != "external":
        raise ExecutorValidationError("executor.metadata.external_runtime is only valid for external executors")
    if runtime.mode not in EXTERNAL_RUNTIME_MODES:
        raise ExecutorValidationError(f"executor.metadata.external_runtime.mode must be one of {sorted(EXTERNAL_RUNTIME_MODES)}")
    if runtime.mode == "package":
        if runtime.source is None:
            raise ExecutorValidationError("executor.metadata.external_runtime.source is required when mode is 'package'")
        if runtime.install is None:
            raise ExecutorValidationError("executor.metadata.external_runtime.install is required when mode is 'package'")
    if runtime.mode == "api" and (runtime.source is not None or runtime.install is not None):
        raise ExecutorValidationError("executor.metadata.external_runtime mode 'api' must not declare source or install")
    if runtime.source is not None:
        _validate_external_runtime_source(runtime.source)
    if runtime.install is not None:
        _validate_external_runtime_install(runtime.install)
    if runtime.import_check is not None:
        _validate_python_import_target(runtime.import_check, "executor.metadata.external_runtime.import_check")
    for index, binary in enumerate(runtime.binary_check):
        _validate_non_empty_string(binary, f"executor.metadata.external_runtime.binary_check[{index}]")


def _validate_external_runtime_source(source: ExternalRuntimeSource) -> None:
    path = "executor.metadata.external_runtime.source"
    if source.kind not in EXTERNAL_RUNTIME_SOURCE_KINDS:
        raise ExecutorValidationError(f"{path}.kind must be one of {sorted(EXTERNAL_RUNTIME_SOURCE_KINDS)}")
    if source.kind == "git":
        _validate_non_empty_string(source.url, f"{path}.url")
        _validate_non_empty_string(source.ref, f"{path}.ref")
        _validate_absent(source.path, f"{path}.path", "git")
        _validate_absent(source.package, f"{path}.package", "git")
    elif source.kind == "path":
        _validate_non_empty_string(source.path, f"{path}.path")
        _validate_absent(source.url, f"{path}.url", "path")
        _validate_absent(source.ref, f"{path}.ref", "path")
        _validate_absent(source.package, f"{path}.package", "path")
    elif source.kind == "pypi":
        _validate_non_empty_string(source.package, f"{path}.package")
        _validate_absent(source.url, f"{path}.url", "pypi")
        _validate_absent(source.ref, f"{path}.ref", "pypi")
        _validate_absent(source.path, f"{path}.path", "pypi")


def _validate_external_runtime_install(install: ExternalRuntimeInstall) -> None:
    path = "executor.metadata.external_runtime.install"
    if install.strategy not in EXTERNAL_RUNTIME_INSTALL_STRATEGIES:
        raise ExecutorValidationError(f"{path}.strategy must be one of {sorted(EXTERNAL_RUNTIME_INSTALL_STRATEGIES)}")
    _validate_non_empty_string(install.target, f"{path}.target")


def _validate_python_import_target(value: str, path: str) -> None:
    _validate_non_empty_string(value, path)
    for part in value.split("."):
        if not part or not part.isidentifier() or keyword.iskeyword(part):
            raise ExecutorValidationError(f"{path} must be a valid Python import path")


def _validate_absent(value: Any, path: str, kind: str) -> None:
    if value is not None:
        raise ExecutorValidationError(f"{path} must not be set for source kind {kind!r}")


def _validate_command(command: CommandSpec, placeholders: set[str]) -> None:
    if not command.argv:
        raise ExecutorValidationError("command.argv must contain at least one argument")
    for index, part in enumerate(command.argv):
        _validate_non_empty_string(part, f"command.argv[{index}]")
        _validate_placeholders(part, placeholders, f"command.argv[{index}]")
    if command.cwd:
        _validate_placeholders(command.cwd, placeholders, "command.cwd")
    for key, value in command.env.items():
        _validate_non_empty_string(key, "command.env key")
        _validate_placeholders(value, placeholders, f"command.env[{key!r}]")


SHORT_DESCRIPTION_MAX_LEN = 120
DESCRIPTION_MAX_LEN = 500
KEYWORD_MAX_LEN = 32
KEYWORDS_MAX_COUNT = 12


def _validate_capability_text(
    description: str,
    short_description: str,
    keywords: tuple[str, ...],
    *,
    manifest_id: str,
    error_cls: type[Exception],
) -> None:
    if len(description) > DESCRIPTION_MAX_LEN:
        raise error_cls(
            f"{manifest_id}: description is {len(description)} chars; max is {DESCRIPTION_MAX_LEN}"
        )
    if len(short_description) > SHORT_DESCRIPTION_MAX_LEN:
        raise error_cls(
            f"{manifest_id}: short_description is {len(short_description)} chars; max is {SHORT_DESCRIPTION_MAX_LEN}"
        )
    if len(keywords) > KEYWORDS_MAX_COUNT:
        raise error_cls(
            f"{manifest_id}: keywords has {len(keywords)} entries; max is {KEYWORDS_MAX_COUNT}"
        )
    seen: set[str] = set()
    for index, keyword in enumerate(keywords):
        if len(keyword) > KEYWORD_MAX_LEN:
            raise error_cls(
                f"{manifest_id}: keywords[{index}] is {len(keyword)} chars; max is {KEYWORD_MAX_LEN}"
            )
        if any(ch.isspace() for ch in keyword):
            raise error_cls(
                f"{manifest_id}: keywords[{index}] {keyword!r} must not contain whitespace"
            )
        if keyword.lower() != keyword:
            raise error_cls(
                f"{manifest_id}: keywords[{index}] {keyword!r} must be lowercase"
            )
        if keyword in seen:
            raise error_cls(
                f"{manifest_id}: keywords[{index}] {keyword!r} is a duplicate"
            )
        seen.add(keyword)


def _validate_placeholders(value: str, allowed: set[str], path: str) -> None:
    for placeholder in _PLACEHOLDER_RE.findall(value):
        if placeholder not in allowed:
            raise ExecutorValidationError(f"{path} uses unknown placeholder {{{placeholder}}}")


def _validate_unique_named(values: tuple[ExecutorPort, ...] | tuple[ExecutorOutput, ...], label: str) -> set[str]:
    names: set[str] = set()
    for value in values:
        if value.name in names:
            raise ExecutorValidationError(f"duplicate {label} name {value.name!r}")
        names.add(value.name)
    return names


def _validate_non_empty_identifier(value: str, path: str) -> None:
    _validate_non_empty_string(value, path)
    if not re.match(r"^[A-Za-z][A-Za-z0-9_.-]*$", value):
        raise ExecutorValidationError(f"{path} must start with a letter and contain only letters, numbers, '.', '_' or '-'")


def _validate_qualified_identifier(value: str, path: str) -> None:
    _validate_non_empty_identifier(value, path)
    if "." not in value or any(not part for part in value.split(".")):
        raise ExecutorValidationError(f"{path} must be qualified as <pack>.<name>")


def _validate_non_empty_string(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ExecutorValidationError(f"{path} must be a non-empty string")


def _require_mapping(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ExecutorValidationError(f"{path} must be an object")
    return raw


def _require_string(data: dict[str, Any], key: str, path: str) -> str:
    if key not in data:
        raise ExecutorValidationError(f"missing required field {path}")
    value = data[key]
    _validate_non_empty_string(value, path)
    return value


def _optional_string(data: dict[str, Any], key: str, path: str, *, default: str = "") -> str:
    if key not in data:
        return default
    value = data[key]
    if value == "":
        return default
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
        raise ExecutorValidationError(f"{path} must be a boolean")
    return value


def _optional_list(data: dict[str, Any], key: str, path: str) -> list[Any]:
    if key not in data:
        return []
    value = data[key]
    if not isinstance(value, list):
        raise ExecutorValidationError(f"{path} must be a list")
    return value


def _string_list(raw: Any, path: str) -> list[str]:
    if not isinstance(raw, list):
        raise ExecutorValidationError(f"{path} must be a list")
    result: list[str] = []
    for index, value in enumerate(raw):
        if not isinstance(value, str) or not value.strip():
            raise ExecutorValidationError(f"{path}[{index}] must be a non-empty string")
        result.append(value)
    return result


def _optional_string_list(data: dict[str, Any], key: str, path: str) -> list[str]:
    if key not in data:
        return []
    return _string_list(data[key], path)


def _parse_clip_kinds_supported(data: dict[str, Any]) -> list[str]:
    has_canonical = "clip_kinds_supported" in data
    has_alias = "produces_for" in data
    if not has_canonical and not has_alias:
        return []
    key = "clip_kinds_supported" if has_canonical else "produces_for"
    path = f"executor.{key}"
    values = _string_list(data[key], path)
    normalized: list[str] = []
    for index, value in enumerate(values):
        candidate = value.strip()
        try:
            kind = ClipClassifiedKind(candidate.lower())
        except ValueError:
            try:
                kind = ClipClassifiedKind[candidate.upper()]
            except KeyError as exc:
                raise ExecutorValidationError(
                    f"{path}[{index}] must be one of {sorted(CLIP_KIND_VALUES)}"
                ) from exc
        normalized.append(kind.value)
    return normalized


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, tuple):
        return [_drop_none(item) for item in value]
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def _parse_yaml_subset(text: str) -> Any:
    lines = _yaml_lines(text)
    if not lines:
        raise ValueError("empty YAML manifest")
    value, index = _parse_yaml_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise ValueError(f"unexpected indentation near line {lines[index][2]}")
    return value


def _yaml_lines(text: str) -> list[tuple[int, str, int]]:
    result: list[tuple[int, str, int]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip())]:
            raise ValueError(f"tabs are not supported in YAML indentation at line {line_number}")
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        result.append((len(raw_line) - len(raw_line.lstrip(" ")), _strip_yaml_comment(stripped), line_number))
    return result


def _strip_yaml_comment(value: str) -> str:
    in_quote: str | None = None
    for index, char in enumerate(value):
        if char in {"'", '"'} and (index == 0 or value[index - 1] != "\\"):
            in_quote = None if in_quote == char else char if in_quote is None else in_quote
        if char == "#" and in_quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value


def _parse_yaml_block(lines: list[tuple[int, str, int]], index: int, indent: int) -> tuple[Any, int]:
    if lines[index][0] < indent:
        raise ValueError(f"unexpected indentation near line {lines[index][2]}")
    if lines[index][1].startswith("- "):
        return _parse_yaml_list(lines, index, indent)
    return _parse_yaml_mapping(lines, index, indent)


def _parse_yaml_mapping(lines: list[tuple[int, str, int]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        line_indent, content, line_number = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError(f"unexpected nested mapping at line {line_number}")
        if content.startswith("- "):
            break
        key, value_text = _split_yaml_key_value(content, line_number)
        if value_text == "":
            if index + 1 >= len(lines) or lines[index + 1][0] <= indent:
                result[key] = {}
                index += 1
            else:
                result[key], index = _parse_yaml_block(lines, index + 1, lines[index + 1][0])
        else:
            result[key] = _parse_yaml_scalar(value_text, line_number)
            index += 1
    return result, index


def _parse_yaml_list(lines: list[tuple[int, str, int]], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        line_indent, content, line_number = lines[index]
        if line_indent < indent:
            break
        if line_indent != indent or not content.startswith("- "):
            break
        item_text = content[2:].strip()
        if item_text == "":
            if index + 1 >= len(lines) or lines[index + 1][0] <= indent:
                result.append(None)
                index += 1
            else:
                item, index = _parse_yaml_block(lines, index + 1, lines[index + 1][0])
                result.append(item)
            continue
        if ":" in item_text and not item_text.startswith(("'", '"')):
            key, value_text = _split_yaml_key_value(item_text, line_number)
            item: dict[str, Any] = {}
            if value_text == "":
                if index + 1 >= len(lines) or lines[index + 1][0] <= indent:
                    item[key] = {}
                    index += 1
                else:
                    item[key], index = _parse_yaml_block(lines, index + 1, lines[index + 1][0])
            else:
                item[key] = _parse_yaml_scalar(value_text, line_number)
                index += 1
            while index < len(lines) and lines[index][0] > indent and not lines[index][1].startswith("- "):
                nested_indent = lines[index][0]
                nested, index = _parse_yaml_mapping(lines, index, nested_indent)
                item.update(nested)
            result.append(item)
        else:
            result.append(_parse_yaml_scalar(item_text, line_number))
            index += 1
    return result, index


def _split_yaml_key_value(content: str, line_number: int) -> tuple[str, str]:
    if ":" not in content:
        raise ValueError(f"expected key: value at line {line_number}")
    key, value = content.split(":", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"empty key at line {line_number}")
    return key, value.strip()


def _parse_yaml_scalar(value: str, line_number: int) -> Any:
    if value in {"[]", "{}"} or value.startswith(("[", "{", '"')):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON-compatible scalar at line {line_number}: {exc.msg}") from exc
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


__all__ = [
    "CACHE_MODES",
    "CONDITION_KINDS",
    "DESCRIPTION_MAX_LEN",
    "EXTERNAL_RUNTIME_INSTALL_STRATEGIES",
    "EXTERNAL_RUNTIME_MODES",
    "EXTERNAL_RUNTIME_SOURCE_KINDS",
    "ISOLATION_MODES",
    "KEYWORDS_MAX_COUNT",
    "KEYWORD_MAX_LEN",
    "KNOWN_RUNTIME_PLACEHOLDERS",
    "CLIP_KIND_VALUES",
    "EXECUTOR_KINDS",
    "OUTPUT_MODES",
    "PIPELINE_REQUIREMENT_FACTS",
    "PORT_REQUIRED_TYPES",
    "SHORT_DESCRIPTION_MAX_LEN",
    "CachePolicy",
    "CommandSpec",
    "ConditionSpec",
    "GraphMetadata",
    "IsolationMetadata",
    "ExecutorDefinition",
    "ExecutorOutput",
    "ExecutorPort",
    "ExecutorValidationError",
    "ExternalRuntimeInstall",
    "ExternalRuntimeMetadata",
    "ExternalRuntimeSource",
    "load_executor_manifest",
    "load_executor_manifest_definitions",
    "validate_executor_definition",
]
