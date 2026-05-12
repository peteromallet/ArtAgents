"""Fetch + checksum artifacts for remote-artifact adapter; idempotent on retry."""

from __future__ import annotations

import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from astrid.core.task.plan import ProducesEntry, Step

FetchStatus = Literal["completed", "awaiting_fetch", "failed"]


@dataclass
class FetchResult:
    status: FetchStatus
    fetched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)
    # sha256 per fetched artifact name
    checksums: dict[str, str] = field(default_factory=dict)
    reason: str | None = None


def _step_dir(run_ctx: "RunContext") -> Path:  # noqa: F821
    """Resolve runs/<run>/steps/<id>/v<N>/... for this dispatch."""
    base = run_ctx.project_root / "runs" / run_ctx.run_id / "steps"
    for segment in run_ctx.plan_step_path:
        base = base / segment
    base = base / f"v{run_ctx.step_version}"
    if run_ctx.iteration is not None:
        base = base / "iterations" / f"{run_ctx.iteration:03d}"
    elif run_ctx.item_id is not None:
        base = base / "items" / run_ctx.item_id
    return base


def fetch_artifacts(
    step: Step,
    run_ctx: "RunContext",  # noqa: F821
    manifest: dict[str, str | None] | None = None,
) -> FetchResult:
    """Fetch artifacts declared in step.produces from the produces directory.

    Each artifact:
    1. Must exist as a non-empty file at ``produces/<name>``.
    2. sha256 is computed on-the-fly.
    3. If *manifest* provides a declared checksum, compare.
    4. Missing files or checksum mismatches are recorded individually.

    Idempotent — re-running on an already-complete step just re-verifies.
    """
    step_dir = _step_dir(run_ctx)
    produces_root = step_dir / "produces"
    remote_state_path = step_dir / "remote_state.json"

    # Load declared checksums from remote_state.json manifest if present.
    declared_checksums: dict[str, str] = {}
    if manifest is not None:
        for name, expected in manifest.items():
            if isinstance(expected, str) and expected:
                declared_checksums[name] = expected
    elif remote_state_path.exists():
        try:
            state = json.loads(remote_state_path.read_text(encoding="utf-8"))
            manifest_data = state.get("manifest", {})
            if isinstance(manifest_data, dict):
                for name, expected in manifest_data.items():
                    if isinstance(expected, str) and expected:
                        declared_checksums[name] = expected
        except (json.JSONDecodeError, OSError):
            pass

    # If no produces declared, this is a no-artifact step — completed trivially.
    if not step.produces:
        return FetchResult(status="completed")

    # Collect all produces entries to verify.
    entries: list[ProducesEntry] = list(step.produces)

    fetched: list[str] = []
    missing: list[str] = []
    mismatched: list[str] = []
    checksums: dict[str, str] = {}

    def _verify_one(entry: ProducesEntry) -> tuple[str, str | None, str | None]:
        """Verify a single artifact. Returns (name, sha256, mismatch_reason)."""
        name = entry.path
        candidate = produces_root / entry.path
        if not candidate.exists() or candidate.stat().st_size == 0:
            return (name, None, "missing")

        sha256 = _sha256_file(candidate)
        declared = declared_checksums.get(name)
        if declared and sha256 != declared:
            expected_short = entry.checksum or declared
            return (
                name,
                sha256,
                f"checksum mismatch: computed={sha256[:16]}..., "
                f"declared={expected_short[:16]}...",
            )
        return (name, sha256, None)

    # Parallel verification: each artifact independently; failures don't
    # block others.
    with ThreadPoolExecutor(max_workers=max(1, len(entries))) as pool:
        futures = {pool.submit(_verify_one, e): e for e in entries}
        for future in as_completed(futures):
            try:
                name, sha256_val, mismatch_reason = future.result()
            except Exception as exc:
                entry = futures[future]
                missing.append(entry.path)
                continue

            if mismatch_reason is not None:
                if mismatch_reason == "missing":
                    missing.append(name)
                else:
                    mismatched.append(name)
                if sha256_val:
                    checksums[name] = sha256_val
            else:
                fetched.append(name)
                if sha256_val:
                    checksums[name] = sha256_val

    if not missing and not mismatched:
        return FetchResult(status="completed", fetched=fetched, checksums=checksums)
    if missing and not mismatched:
        return FetchResult(
            status="awaiting_fetch",
            fetched=fetched,
            missing=missing,
            mismatched=mismatched,
            checksums=checksums,
            reason=f"missing artifacts: {missing}",
        )
    return FetchResult(
        status="awaiting_fetch",
        fetched=fetched,
        missing=missing,
        mismatched=mismatched,
        checksums=checksums,
        reason=f"missing={missing}, mismatched={mismatched}",
    )


def _sha256_file(path: Path) -> str:
    """Return sha256 hex digest for *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()