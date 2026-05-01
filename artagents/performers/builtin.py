"""Built-in performer metadata for legacy ArtAgents pipeline steps."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from artagents.pipeline import STEP_ORDER, Step, build_pool_steps

from .schema import (
    CachePolicy,
    ConditionSpec,
    GraphMetadata,
    IsolationMetadata,
    PerformerDefinition,
    PerformerOutput,
    PerformerPort,
    validate_performer_definition,
)


_INPUTS: Mapping[str, tuple[PerformerPort, ...]] = MappingProxyType(
    {
        "transcribe": (
            PerformerPort("audio", "file", description="Audio or video-derived audio to transcribe."),
            PerformerPort("env_file", "file", required=False, description="Optional environment file for API credentials."),
        ),
        "scenes": (PerformerPort("video", "file", description="Source video to segment into scenes."),),
        "quality_zones": (PerformerPort("video", "file", description="Source video to analyze for quality zones."),),
        "shots": (
            PerformerPort("video", "file", description="Source video to split into shots."),
            PerformerPort("scenes", "file", required=False, description="Existing scenes.json input."),
        ),
        "triage": (
            PerformerPort("scenes", "file", required=False),
            PerformerPort("shots", "file", required=False),
            PerformerPort("env_file", "file", required=False),
        ),
        "scene_describe": (
            PerformerPort("video", "file"),
            PerformerPort("scenes", "file", required=False),
            PerformerPort("triage", "file", required=False),
            PerformerPort("env_file", "file", required=False),
        ),
        "quote_scout": (
            PerformerPort("transcript", "file", required=False),
            PerformerPort("env_file", "file", required=False),
        ),
        "pool_build": (
            PerformerPort("triage", "file", required=False),
            PerformerPort("scene_descriptions", "file", required=False),
            PerformerPort("quote_candidates", "file", required=False),
            PerformerPort("transcript", "file", required=False),
            PerformerPort("scenes", "file", required=False),
        ),
        "pool_merge": (
            PerformerPort("pool", "file", required=False),
            PerformerPort("theme", "file", required=False),
        ),
        "arrange": (
            PerformerPort("pool", "file", required=False),
            PerformerPort("brief", "file"),
            PerformerPort("theme", "file", required=False),
            PerformerPort("target_duration", "number", required=False),
            PerformerPort("env_file", "file", required=False),
        ),
        "cut": (
            PerformerPort("pool", "file", required=False),
            PerformerPort("arrangement", "file", required=False),
            PerformerPort("brief", "file"),
            PerformerPort("video", "file", required=False),
            PerformerPort("audio", "file", required=False),
            PerformerPort("theme", "file", required=False),
        ),
        "refine": (
            PerformerPort("arrangement", "file", required=False),
            PerformerPort("pool", "file", required=False),
            PerformerPort("timeline", "file", required=False),
            PerformerPort("assets", "file", required=False),
            PerformerPort("metadata", "file", required=False),
            PerformerPort("transcript", "file", required=False),
            PerformerPort("env_file", "file", required=False),
        ),
        "render": (
            PerformerPort("timeline", "file", required=False),
            PerformerPort("assets", "file", required=False),
            PerformerPort("theme", "file", required=False),
        ),
        "editor_review": (
            PerformerPort("brief_dir", "directory", required=False),
            PerformerPort("run_dir", "directory", required=False),
            PerformerPort("env_file", "file", required=False),
        ),
        "validate": (
            PerformerPort("video", "file", required=False),
            PerformerPort("timeline", "file", required=False),
            PerformerPort("metadata", "file", required=False),
            PerformerPort("env_file", "file", required=False),
        ),
    }
)

_OUTPUTS: Mapping[str, tuple[PerformerOutput, ...]] = MappingProxyType(
    {
        "transcribe": (PerformerOutput("transcript", "file", path_template="{out}/transcript.json"),),
        "scenes": (PerformerOutput("scenes", "file", path_template="{out}/scenes.json"),),
        "quality_zones": (PerformerOutput("quality_zones", "file", path_template="{out}/quality_zones.json"),),
        "shots": (PerformerOutput("shots", "file", path_template="{out}/shots.json"),),
        "triage": (PerformerOutput("scene_triage", "file", path_template="{out}/scene_triage.json"),),
        "scene_describe": (PerformerOutput("scene_descriptions", "file", path_template="{out}/scene_descriptions.json"),),
        "quote_scout": (PerformerOutput("quote_candidates", "file", path_template="{out}/quote_candidates.json"),),
        "pool_build": (PerformerOutput("pool", "file", path_template="{out}/pool.json"),),
        "pool_merge": (PerformerOutput("pool", "file", mode="mutate", path_template="{out}/pool.json"),),
        "arrange": (PerformerOutput("arrangement", "file", path_template="{brief_out}/arrangement.json"),),
        "cut": (
            PerformerOutput("timeline", "file", path_template="{brief_out}/hype.timeline.json"),
            PerformerOutput("assets", "file", path_template="{brief_out}/hype.assets.json"),
            PerformerOutput("metadata", "file", path_template="{brief_out}/hype.metadata.json"),
        ),
        "refine": (
            PerformerOutput("refine", "file", path_template="{brief_out}/refine.json"),
            PerformerOutput("timeline", "file", mode="mutate", path_template="{brief_out}/hype.timeline.json"),
            PerformerOutput("assets", "file", mode="mutate", path_template="{brief_out}/hype.assets.json"),
            PerformerOutput("metadata", "file", mode="mutate", path_template="{brief_out}/hype.metadata.json"),
        ),
        "render": (PerformerOutput("video", "file", path_template="{brief_out}/hype.mp4"),),
        "editor_review": (PerformerOutput("editor_review", "file", path_template="{brief_out}/editor_review.json"),),
        "validate": (PerformerOutput("validation", "file", path_template="{brief_out}/validation.json"),),
    }
)

_CONDITIONS: Mapping[str, tuple[ConditionSpec, ...]] = MappingProxyType(
    {
        "transcribe": (ConditionSpec("requires_input", input="audio"),),
        "scenes": (ConditionSpec("requires_input", input="video"),),
        "quality_zones": (ConditionSpec("requires_input", input="video"),),
        "shots": (ConditionSpec("requires_input", input="video"),),
        "arrange": (ConditionSpec("requires_input", input="brief"),),
        "cut": (ConditionSpec("requires_input", input="brief"),),
    }
)

_DESCRIPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "transcribe": "Transcribe source audio into transcript.json.",
        "scenes": "Detect source-video scene boundaries.",
        "arrange": "Compose a brief-specific arrangement from the source pool.",
        "cut": "Create Reigh-compatible timeline, assets, and metadata JSON.",
        "render": "Render the brief timeline to hype.mp4 through Remotion.",
        "validate": "Validate the rendered video against timeline and metadata.",
    }
)


def builtin_steps_by_name() -> Mapping[str, Step]:
    """Return the existing legacy Step objects keyed by step name."""

    steps = {step.name: step for step in build_pool_steps()}
    missing = [name for name in STEP_ORDER if name not in steps]
    if missing:
        raise ValueError(f"build_pool_steps() is missing STEP_ORDER entries: {', '.join(missing)}")
    return MappingProxyType(steps)


def builtin_performers() -> tuple[PerformerDefinition, ...]:
    """Return read-only performer definitions for every legacy pipeline step."""

    steps = builtin_steps_by_name()
    return tuple(_performer_from_step(steps[name]) for name in STEP_ORDER)


def builtin_performer_map() -> Mapping[str, PerformerDefinition]:
    """Return built-in performer definitions keyed by performer id."""

    return MappingProxyType({performer.id: performer for performer in builtin_performers()})


def performer_id_for_step(step_name: str) -> str:
    return f"builtin.{step_name}"


def _performer_from_step(step: Step) -> PerformerDefinition:
    cache = _cache_from_step(step)
    performer = PerformerDefinition(
        id=performer_id_for_step(step.name),
        name=_display_name(step.name),
        kind="built_in",
        version="1.0",
        description=_DESCRIPTIONS.get(step.name, f"Legacy ArtAgents pipeline step: {step.name}."),
        inputs=_INPUTS.get(step.name, ()),
        outputs=_OUTPUTS.get(step.name, _outputs_from_sentinels(step)),
        command=None,
        cache=cache,
        conditions=_CONDITIONS.get(step.name, ()),
        graph=GraphMetadata(
            depends_on=tuple(_upstream_steps(step.name)),
            provides=tuple(output.name for output in _OUTPUTS.get(step.name, ())),
        ),
        isolation=IsolationMetadata(mode="subprocess"),
        metadata={
            "legacy_step": step.name,
            "legacy_step_order": STEP_ORDER.index(step.name),
            "command_builder": "artagents.pipeline.build_pool_steps",
        },
    )
    return validate_performer_definition(performer)


def _cache_from_step(step: Step) -> CachePolicy:
    if step.always_run:
        return CachePolicy(mode="always_run", always_run=True, per_brief=step.per_brief)
    return CachePolicy(mode="sentinel", sentinels=step.sentinels, per_brief=step.per_brief)


def _outputs_from_sentinels(step: Step) -> tuple[PerformerOutput, ...]:
    root_placeholder = "brief_out" if step.per_brief else "out"
    return tuple(
        PerformerOutput(
            _name_from_sentinel(sentinel),
            "file",
            path_template=f"{{{root_placeholder}}}/{sentinel}",
        )
        for sentinel in step.sentinels
    )


def _upstream_steps(step_name: str) -> tuple[str, ...]:
    index = STEP_ORDER.index(step_name)
    return tuple(performer_id_for_step(name) for name in STEP_ORDER[:index])


def _display_name(step_name: str) -> str:
    return step_name.replace("_", " ").title()


def _name_from_sentinel(sentinel: str) -> str:
    return sentinel.removesuffix(".json").removesuffix(".mp4").replace(".", "_")


__all__ = ["builtin_performer_map", "builtin_performers", "builtin_steps_by_name", "performer_id_for_step"]
