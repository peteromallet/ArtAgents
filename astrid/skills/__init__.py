"""Public API for the multi-harness skills install layer.

Three harnesses: Claude Code, Codex, Hermes. One source of truth: per-pack
``astrid/packs/<pack>/skill/SKILL.md`` with Claude-style frontmatter.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from . import discovery, state
from .discovery import SkillDescriptor, list_skills
from .harnesses import ADAPTERS, HarnessAdapter, adapter_for, all_adapters

NUDGE_INTERVAL_DAYS = 7
NUDGE_ENV = "ARTAGENTS_NO_NUDGE"


def install(
    pack_ids: Iterable[str] | None,
    harness_names: Iterable[str] | None,
    *,
    mechanism: str = "symlink",
    force: bool = False,
    dry_run: bool = False,
    state_path: Path | None = None,
) -> dict:
    descriptors = _resolve_descriptors(pack_ids)
    targets = _resolve_harnesses(harness_names)
    current_state = state.load(state_path)

    report: dict = {"actions": []}
    for harness_name, adapter in targets.items():
        kwargs: dict = {"force": force}
        if harness_name == "hermes":
            kwargs["mechanism"] = mechanism
        if harness_name == "codex":
            kwargs["all_after_descriptors"] = list(_codex_after_set(current_state, descriptors, install=True))
        if dry_run:
            steps = adapter.plan("install", descriptors, **kwargs)
        else:
            steps = adapter.apply("install", descriptors, **kwargs)
            for descriptor in descriptors:
                target = adapter.target_for(descriptor)
                state.record_install(
                    current_state,
                    harness_name,
                    descriptor.pack_id,
                    target=str(target),
                    mechanism=kwargs.get("mechanism", "symlink"),
                )
        report["actions"].append({"harness": harness_name, "steps": [_step_to_dict(s) for s in steps]})

    if not dry_run:
        state.save(current_state, state_path)
    return report


def uninstall(
    pack_ids: Iterable[str] | None,
    harness_names: Iterable[str] | None,
    *,
    dry_run: bool = False,
    state_path: Path | None = None,
) -> dict:
    descriptors = _resolve_descriptors(pack_ids)
    targets = _resolve_harnesses(harness_names)
    current_state = state.load(state_path)

    report: dict = {"actions": []}
    for harness_name, adapter in targets.items():
        kwargs: dict = {}
        if harness_name == "codex":
            kwargs["all_after_descriptors"] = list(_codex_after_set(current_state, descriptors, install=False))
        if dry_run:
            steps = adapter.plan("uninstall", descriptors, **kwargs)
        else:
            steps = adapter.apply("uninstall", descriptors, **kwargs)
            for descriptor in descriptors:
                state.record_uninstall(current_state, harness_name, descriptor.pack_id)
        report["actions"].append({"harness": harness_name, "steps": [_step_to_dict(s) for s in steps]})

    if not dry_run:
        state.save(current_state, state_path)
    return report


def sync(
    *,
    mechanism: str = "symlink",
    force: bool = False,
    dry_run: bool = False,
    state_path: Path | None = None,
) -> dict:
    descriptors = list_skills()
    targets = _resolve_harnesses(None)
    current_state = state.load(state_path)

    report: dict = {"actions": []}
    for harness_name, adapter in targets.items():
        kwargs: dict = {"force": force}
        if harness_name == "hermes":
            kwargs["mechanism"] = mechanism
        if harness_name == "codex":
            kwargs["all_after_descriptors"] = list(descriptors)
        if dry_run:
            steps = adapter.plan("install", descriptors, **kwargs)
        else:
            steps = adapter.apply("install", descriptors, **kwargs)
            for descriptor in descriptors:
                target = adapter.target_for(descriptor)
                state.record_install(
                    current_state,
                    harness_name,
                    descriptor.pack_id,
                    target=str(target),
                    mechanism=kwargs.get("mechanism", "symlink"),
                )
            # Prune orphan installs from state.
            installed_ids = {d.pack_id for d in descriptors}
            current_state["installs"][harness_name] = {
                pid: info
                for pid, info in current_state["installs"].get(harness_name, {}).items()
                if pid in installed_ids
            }
        report["actions"].append({"harness": harness_name, "steps": [_step_to_dict(s) for s in steps]})

    if not dry_run:
        state.save(current_state, state_path)
    return report


def doctor(*, state_path: Path | None = None, heal: bool = False) -> dict:
    descriptors = list_skills()
    detected = {name: adapter for name, adapter in all_adapters().items() if adapter.detect()}

    report: dict = {
        "detected": list(detected.keys()),
        "results": [],
        "lint": [],
        "drift": [],
        "healed": [],
    }
    for descriptor in descriptors:
        text = descriptor.skill_md.read_text(encoding="utf-8")
        for finding in discovery.lint_shared_skill_md(text):
            report["lint"].append({"pack": descriptor.pack_id, "finding": finding})

    current_state = state.load(state_path)
    state_changed = False
    for harness_name, adapter in detected.items():
        installed_ids = set(current_state["installs"].get(harness_name, {}).keys())
        for descriptor in descriptors:
            fs_record = adapter.discover_installed(descriptor)
            in_state = descriptor.pack_id in installed_ids
            in_fs = fs_record is not None

            if not in_state and not in_fs:
                report["results"].append(
                    {
                        "harness": harness_name,
                        "pack": descriptor.pack_id,
                        "ok": False,
                        "message": "not installed",
                    }
                )
                continue

            if in_fs and not in_state:
                # Filesystem has it; state is missing. Drift — heal optional.
                report["drift"].append(
                    {
                        "harness": harness_name,
                        "pack": descriptor.pack_id,
                        "kind": "state-missing",
                        "message": (
                            f"installed on disk at {fs_record.target} but missing from state file; "
                            f"run `skills doctor --heal` to record it"
                        ),
                    }
                )
                if heal:
                    state.record_install(
                        current_state,
                        harness_name,
                        descriptor.pack_id,
                        target=str(fs_record.target),
                        mechanism=fs_record.mechanism,
                    )
                    state_changed = True
                    report["healed"].append(
                        {"harness": harness_name, "pack": descriptor.pack_id, "action": "recorded-from-fs"}
                    )

            if in_state and not in_fs:
                report["drift"].append(
                    {
                        "harness": harness_name,
                        "pack": descriptor.pack_id,
                        "kind": "fs-missing",
                        "message": (
                            "state file claims installed but filesystem disagrees; "
                            "run `skills install --force` or `skills uninstall`"
                        ),
                    }
                )
                if heal:
                    state.record_uninstall(current_state, harness_name, descriptor.pack_id)
                    state_changed = True
                    report["healed"].append(
                        {"harness": harness_name, "pack": descriptor.pack_id, "action": "removed-from-state"}
                    )

            ok, msg = adapter.verify(descriptor)
            report["results"].append(
                {"harness": harness_name, "pack": descriptor.pack_id, "ok": ok, "message": msg}
            )

    if heal and state_changed:
        state.save(current_state, state_path)
    return report


def list_state(*, state_path: Path | None = None) -> dict:
    descriptors = list_skills()
    current_state = state.load(state_path)
    detected = {name: adapter for name, adapter in all_adapters().items() if adapter.detect()}
    items = []
    for descriptor in descriptors:
        per_harness = {}
        for harness_name, adapter_cls in ADAPTERS.items():
            info = current_state["installs"].get(harness_name, {}).get(descriptor.pack_id)
            adapter = detected.get(harness_name) or adapter_cls()
            fs_record = None
            try:
                fs_record = adapter.discover_installed(descriptor)
            except Exception:
                fs_record = None
            in_state = info is not None
            in_fs = fs_record is not None
            installed = in_state or in_fs
            drift = (in_state and not in_fs) or (in_fs and not in_state)
            entry = {
                "installed": installed,
                "detected": harness_name in detected,
                "info": info,
                "fs_installed": in_fs,
                "state_installed": in_state,
                "drift": drift,
            }
            if fs_record is not None:
                entry["fs_target"] = str(fs_record.target)
                entry["fs_mechanism"] = fs_record.mechanism
            per_harness[harness_name] = entry
        items.append(
            {
                "pack_id": descriptor.pack_id,
                "name": descriptor.name,
                "short_description": descriptor.short_description,
                "harnesses": per_harness,
            }
        )
    return {"packs": items, "detected": list(detected.keys())}


def nudge_if_needed(*, argv: list[str], state_path: Path | None = None, stream=sys.stderr) -> bool:
    """Optionally print a one-line nudge to ``stream``.

    Returns True if a nudge was emitted. Cheap path: env var or no detected
    harness aborts before any IO beyond two os.path checks.
    """
    if os.environ.get(NUDGE_ENV):
        return False
    if argv and "--quiet" in argv:
        return False
    if not argv or argv[0] == "skills":
        return False

    detected = {name: adapter for name, adapter in all_adapters().items() if adapter.detect()}
    if not detected:
        return False

    descriptors = list_skills()
    if not descriptors:
        return False
    expected_ids = {d.pack_id for d in descriptors}

    current_state = state.load(state_path)
    stale_harnesses: list[str] = []
    for harness_name in detected:
        installed = set(current_state["installs"].get(harness_name, {}).keys())
        if not expected_ids.issubset(installed):
            stale_harnesses.append(harness_name)

    if not stale_harnesses:
        return False

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=NUDGE_INTERVAL_DAYS)
    fresh_for_all = True
    for harness_name in stale_harnesses:
        last = current_state.get("nudge", {}).get(harness_name, {}).get("last_shown_at")
        if not last:
            fresh_for_all = False
            break
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            fresh_for_all = False
            break
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        if last_dt < cutoff:
            fresh_for_all = False
            break
    if fresh_for_all:
        return False

    pretty = " / ".join(name.capitalize() for name in stale_harnesses)
    message = (
        f"[astrid] Tip: install the skills layer for {pretty}: "
        f"python3 -m astrid skills install --all   (suppress: {NUDGE_ENV}=1)"
    )
    print(message, file=stream)
    for harness_name in stale_harnesses:
        state.record_nudge(current_state, harness_name)
    state.save(current_state, state_path)
    return True


def _resolve_descriptors(pack_ids: Iterable[str] | None) -> list[SkillDescriptor]:
    available = list_skills()
    if pack_ids is None:
        return available
    requested = list(pack_ids)
    by_id = {d.pack_id: d for d in available}
    missing = [pid for pid in requested if pid not in by_id]
    if missing:
        raise KeyError(f"unknown pack(s): {missing}")
    return [by_id[pid] for pid in requested]


def _resolve_harnesses(harness_names: Iterable[str] | None) -> dict[str, HarnessAdapter]:
    if harness_names is None or list(harness_names) == ["all"]:
        return {name: adapter for name, adapter in all_adapters().items() if adapter.detect()}
    selected: dict[str, HarnessAdapter] = {}
    for name in harness_names:
        if name not in ADAPTERS:
            raise KeyError(f"unknown harness {name!r}; valid: {sorted(ADAPTERS)}")
        adapter = adapter_for(name)
        if adapter.detect():
            selected[name] = adapter
    return selected


def _codex_after_set(
    current_state: dict,
    changed_descriptors: list[SkillDescriptor],
    *,
    install: bool,
) -> list[SkillDescriptor]:
    """Compute the descriptors that will be installed for codex AFTER applying.

    AGENTS.md should reflect post-state, so we union/diff against the current
    install record.
    """
    available = {d.pack_id: d for d in list_skills()}
    installed_now = set(current_state["installs"].get("codex", {}).keys())
    if install:
        result_ids = installed_now.union(d.pack_id for d in changed_descriptors)
    else:
        result_ids = installed_now.difference(d.pack_id for d in changed_descriptors)
    return [available[pid] for pid in sorted(result_ids) if pid in available]


def _step_to_dict(step) -> dict:
    return {
        "description": step.description,
        "target": str(step.target) if step.target else None,
        "extras": dict(step.extras),
    }


__all__ = [
    "NUDGE_ENV",
    "NUDGE_INTERVAL_DAYS",
    "doctor",
    "install",
    "list_skills",
    "list_state",
    "nudge_if_needed",
    "sync",
    "uninstall",
]
