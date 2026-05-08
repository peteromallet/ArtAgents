"""Walk astrid/packs/*/skill/SKILL.md and yield SkillDescriptors.

A "skill" here is a Claude-style frontmatter document (`name`, `description`)
plus the directory it lives in. Hermes-only extras live under an optional
`metadata.hermes.*` block in the same file; Claude/Codex ignore unknown keys.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from astrid._paths import REPO_ROOT
from astrid.core._search import short_description_or_truncated

PACKS_DIR = REPO_ROOT / "astrid" / "packs"

# Tokens forbidden in the shared SKILL.md (they leak Hermes-specific dynamic
# behavior into a file Claude/Codex also read).
FORBIDDEN_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\$\{HERMES_[A-Z0-9_]+\}"),
    re.compile(r"!`[^`]+`"),
)


@dataclass(frozen=True)
class SkillDescriptor:
    pack_id: str
    name: str
    description: str
    short_description: str
    skill_dir: Path
    skill_md: Path
    hermes_metadata: dict = field(default_factory=dict)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    # Frontmatter ends at the next standalone "---" line.
    lines = text.splitlines()
    if len(lines) < 2:
        return {}, text
    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}, text
    frontmatter_block = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :])
    try:
        import yaml

        data = yaml.safe_load(frontmatter_block) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, body


def list_skills(packs_dir: Path | None = None) -> list[SkillDescriptor]:
    base = packs_dir or PACKS_DIR
    descriptors: list[SkillDescriptor] = []
    if not base.exists():
        return descriptors
    for pack_dir in sorted(base.iterdir()):
        if not pack_dir.is_dir():
            continue
        skill_md = pack_dir / "skill" / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        front, body = _parse_frontmatter(text)
        name = str(front.get("name") or pack_dir.name)
        description = str(front.get("description") or "")
        # Reuse the canonical short blurb shape from the discovery layer.
        short = short_description_or_truncated(
            short=str(front.get("short_description") or ""),
            description=description,
        )
        hermes_meta = {}
        metadata = front.get("metadata") or {}
        if isinstance(metadata, dict) and isinstance(metadata.get("hermes"), dict):
            hermes_meta = dict(metadata["hermes"])
        descriptors.append(
            SkillDescriptor(
                pack_id=pack_dir.name,
                name=name,
                description=description,
                short_description=short,
                skill_dir=skill_md.parent,
                skill_md=skill_md,
                hermes_metadata=hermes_meta,
            )
        )
    return descriptors


def lint_shared_skill_md(text: str) -> list[str]:
    """Return human-readable findings if `text` contains forbidden tokens."""
    findings: list[str] = []
    for pattern in FORBIDDEN_TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(f"forbidden token in shared SKILL.md: {match.group(0)!r}")
    return findings


def get(pack_id: str, packs_dir: Path | None = None) -> SkillDescriptor:
    for descriptor in list_skills(packs_dir):
        if descriptor.pack_id == pack_id:
            return descriptor
    raise KeyError(f"no installable skill for pack {pack_id!r}")


__all__ = [
    "FORBIDDEN_TOKEN_PATTERNS",
    "PACKS_DIR",
    "SkillDescriptor",
    "get",
    "lint_shared_skill_md",
    "list_skills",
]
