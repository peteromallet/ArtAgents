"""Neutral shared schema primitives for ArtAgents executable contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PORT_REQUIRED_TYPES = {"string", "path", "file", "directory", "json", "boolean", "number", "integer"}
OUTPUT_MODES = {"mutate", "create", "create_or_replace"}
CACHE_MODES = {"none", "sentinel", "always_run"}
ISOLATION_MODES = {"in_process", "subprocess"}


@dataclass(frozen=True)
class Port:
    name: str
    type: str = "path"
    required: bool = True
    description: str = ""
    default: Any = None
    placeholder: str | None = None


@dataclass(frozen=True)
class Output:
    name: str
    type: str = "path"
    mode: str = "create_or_replace"
    description: str = ""
    placeholder: str | None = None
    path_template: str | None = None


PerformerPort = Port
PerformerOutput = Output


@dataclass(frozen=True)
class CommandSpec:
    argv: tuple[str, ...]
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CachePolicy:
    mode: str = "sentinel"
    sentinels: tuple[str, ...] = ()
    always_run: bool = False
    per_brief: bool = False


@dataclass(frozen=True)
class IsolationMetadata:
    mode: str = "subprocess"
    requirements: tuple[str, ...] = ()
    binaries: tuple[str, ...] = ()
    network: bool = False


__all__ = [
    "CACHE_MODES",
    "ISOLATION_MODES",
    "OUTPUT_MODES",
    "PORT_REQUIRED_TYPES",
    "CachePolicy",
    "CommandSpec",
    "IsolationMetadata",
    "Output",
    "Port",
    "PerformerOutput",
    "PerformerPort",
]
