"""Materialize ArtAgents project timelines into renderable timeline files."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from artagents import timeline as banodoco_timeline

from . import paths
from .project import require_project
from .run import require_run_record
from .schema import validate_project_timeline
from .source import require_source
from .timeline import load_timeline

DEFAULT_THEME = "banodoco-default"


class ProjectMaterializeError(RuntimeError):
    """Raised when a project timeline cannot be materialized."""


def materialize_project_timeline(
    project_slug: str,
    *,
    root: str | Path | None = None,
    theme: str = DEFAULT_THEME,
) -> tuple[banodoco_timeline.TimelineConfig, banodoco_timeline.AssetRegistry]:
    require_project(project_slug, root=root)
    project_timeline = load_timeline(project_slug, root=root)
    return materialize_project_timeline_payload(project_timeline, root=root, theme=theme)


def materialize_project_timeline_payload(
    project_timeline: dict[str, Any],
    *,
    root: str | Path | None = None,
    theme: str = DEFAULT_THEME,
) -> tuple[banodoco_timeline.TimelineConfig, banodoco_timeline.AssetRegistry]:
    project_timeline = validate_project_timeline(project_timeline)
    project_slug = project_timeline["project_slug"]
    clips: list[dict[str, Any]] = []
    registry: dict[str, dict[str, Any]] = {}

    for placement in project_timeline.get("placements", []):
        ref = placement.get("source", {})
        if ref.get("kind") == "source":
            source_id = ref["id"]
            source = require_source(project_slug, source_id, root=root)
            asset_key = f"source:{source_id}"
            registry[asset_key] = deepcopy(source["asset"])
            clips.append(_clip_from_source_placement(placement, asset_key=asset_key))
            continue
        if ref.get("kind") == "run":
            clip, run_registry = require_run_clip(project_slug, ref["run_id"], ref["clip_id"], root=root)
            materialized_clip = _clip_from_run_placement(
                placement,
                clip,
                project_slug=project_slug,
                run_id=ref["run_id"],
                registry=registry,
                run_registry=run_registry,
                root=root,
            )
            clips.append(materialized_clip)
            continue
        raise ProjectMaterializeError(f"placement {placement.get('id')!r} has unsupported source kind {ref.get('kind')!r}")

    config: banodoco_timeline.TimelineConfig = {
        "theme": theme,
        "clips": clips,
    }
    tracks = project_timeline.get("tracks")
    if tracks:
        config["tracks"] = deepcopy(tracks)
    assets: banodoco_timeline.AssetRegistry = {"assets": registry}
    banodoco_timeline.validate_timeline(config)
    banodoco_timeline.validate_registry(assets)
    return config, assets


def require_run_clip(
    project_slug: str,
    run_id: str,
    clip_id: str,
    *,
    root: str | Path | None = None,
) -> tuple[dict[str, Any], banodoco_timeline.AssetRegistry]:
    require_run_record(project_slug, run_id, root=root)
    timeline_path = paths.run_timeline_path(project_slug, run_id, root=root)
    assets_path = paths.run_assets_path(project_slug, run_id, root=root)
    if not timeline_path.is_file():
        raise FileNotFoundError(
            f"run timeline not found for {run_id}: {timeline_path}. "
            f"Next command: python3 -m artagents projects show --project {project_slug}"
        )
    if not assets_path.is_file():
        raise FileNotFoundError(
            f"run assets not found for {run_id}: {assets_path}. "
            f"Next command: rerun the tool with --project {project_slug} or inspect {timeline_path}"
        )
    run_timeline = banodoco_timeline.load_timeline(timeline_path)
    run_registry = banodoco_timeline.load_registry(assets_path)
    for clip in run_timeline.get("clips", []):
        if isinstance(clip, dict) and clip.get("id") == clip_id:
            return deepcopy(clip), run_registry
    available = sorted(
        str(clip.get("id"))
        for clip in run_timeline.get("clips", [])
        if isinstance(clip, dict) and isinstance(clip.get("id"), str)
    )
    detail = f" Available clip ids: {', '.join(available)}." if available else " The run timeline has no clip ids."
    raise FileNotFoundError(
        f"clip not found in run {run_id}: {clip_id}.{detail} "
        f"Next command: inspect {timeline_path} and pass --clip <clip-id>."
    )


def _clip_from_source_placement(placement: dict[str, Any], *, asset_key: str) -> dict[str, Any]:
    clip: dict[str, Any] = {
        "asset": asset_key,
        "at": placement["at"],
        "clipType": "media",
        "id": placement["id"],
        "track": placement["track"],
    }
    for source_key, clip_key in (("from", "from"), ("to", "to")):
        if source_key in placement:
            clip[clip_key] = placement[source_key]
    for key in ("entrance", "exit", "transition", "effects", "params"):
        if key in placement:
            clip[key] = deepcopy(placement[key])
    return clip


def _clip_from_run_placement(
    placement: dict[str, Any],
    run_clip: dict[str, Any],
    *,
    project_slug: str,
    run_id: str,
    registry: dict[str, dict[str, Any]],
    run_registry: banodoco_timeline.AssetRegistry,
    root: str | Path | None = None,
) -> dict[str, Any]:
    clip = deepcopy(run_clip)
    clip["id"] = placement["id"]
    clip["track"] = placement["track"]
    clip["at"] = placement["at"]
    if "from_" in clip and "from" not in clip:
        clip["from"] = clip.pop("from_")
    for key in ("from", "to"):
        if key in placement:
            clip[key] = placement[key]
    for key in ("entrance", "exit", "transition", "effects", "params"):
        if key in placement:
            clip[key] = deepcopy(placement[key])
    asset_key = clip.get("asset")
    if isinstance(asset_key, str) and asset_key:
        assets = run_registry.get("assets", {})
        if asset_key not in assets:
            raise FileNotFoundError(
                f"asset {asset_key!r} referenced by clip {run_clip.get('id')!r} was not found in run {run_id} assets.json. "
                f"Next command: inspect {paths.run_assets_path(project_slug, run_id, root=root)}"
            )
        namespaced_key = f"run:{run_id}:{asset_key}"
        registry[namespaced_key] = deepcopy(assets[asset_key])
        clip["asset"] = namespaced_key
    return clip


def write_materialized_project_timeline(
    project_slug: str,
    out_dir: str | Path,
    *,
    root: str | Path | None = None,
    theme: str = DEFAULT_THEME,
) -> tuple[Path, Path]:
    config, registry = materialize_project_timeline(project_slug, root=root, theme=theme)
    output = Path(out_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    timeline_path = output / "hype.timeline.json"
    assets_path = output / "hype.assets.json"
    banodoco_timeline.save_timeline(config, timeline_path)
    banodoco_timeline.save_registry(registry, assets_path)
    return timeline_path, assets_path


__all__ = [
    "ProjectMaterializeError",
    "materialize_project_timeline",
    "materialize_project_timeline_payload",
    "require_run_clip",
    "write_materialized_project_timeline",
]
