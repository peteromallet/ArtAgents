"""Python DSL for authoring ArtAgents task-mode orchestrators (Phase 4).

Authors write `<pack>/<orch>.py` using the helpers exported here. The DSL
emits a JSON manifest that is byte-shape-equivalent to the schema accepted
by `artagents.core.task.plan.load_plan`.
"""

from __future__ import annotations

from artagents.verify import (
    all_of,
    audio_duration_min,
    file_nonempty,
    image_dimensions,
    json_file,
    json_schema,
)

from .dsl import (
    OrchestrateDefinitionError,
    attested,
    code,
    nested,
    orchestrator,
    plan,
    repeat_for_each,
    repeat_until,
)

__all__ = [
    "OrchestrateDefinitionError",
    "all_of",
    "attested",
    "audio_duration_min",
    "code",
    "file_nonempty",
    "image_dimensions",
    "json_file",
    "json_schema",
    "nested",
    "orchestrator",
    "plan",
    "repeat_for_each",
    "repeat_until",
]
