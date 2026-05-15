"""Gitignore-aware filter for shutil.copytree.

Walks upward from a source root collecting ``.gitignore`` files,
parses patterns, and produces a ``shutil.copytree``-compatible
*ignore* callback that skips gitignored paths plus hard-coded
common exclusions.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Callable, Iterable

# ---------------------------------------------------------------------------
# Hard-coded skip patterns (always excluded, even without a .gitignore)
# ---------------------------------------------------------------------------
_ALWAYS_SKIP: tuple[str, ...] = (
    ".git/",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".venv/",
    "venv/",
    "node_modules/",
    ".astrid/",
)


def _match_pattern(rel_path: str, pattern: str, is_dir_only: bool, path_is_dir: bool) -> bool:
    """Test a single gitignore-style pattern against *rel_path*.

    A pattern without a ``/`` (except leading or trailing) matches
    anywhere in the tree (basename match).  ``**`` matches zero or
    more intermediate segments.
    Directory-only patterns (trailing ``/``) only match directories.
    """
    if is_dir_only and not path_is_dir:
        return False

    # If the pattern contains no slash (except leading), it matches
    # against the basename anywhere in the tree (like git does).
    stripped = pattern.lstrip("/")
    if "/" not in stripped and "**" not in pattern:
        # Basename-only pattern — match against the final component
        basename = rel_path.rsplit("/", 1)[-1] if "/" in rel_path else rel_path
        return fnmatch.fnmatch(basename, pattern)

    # Pattern contains a path separator — full-path match.
    return fnmatch.fnmatch(rel_path, pattern)


def _is_ignored(
    rel_path: str,
    patterns: Iterable[tuple[str, bool, bool, str]],
    path_is_dir: bool,
) -> bool:
    """Determine whether *rel_path* is ignored by the collected patterns.

    Patterns are processed in order; the last matching pattern wins.
    Negation patterns (``!``) un-ignore a previously ignored path.

    Returns ``True`` if the path should be excluded.
    """
    ignored = False
    for pattern, is_negation, is_dir_only, _source_dir in patterns:
        if _match_pattern(rel_path, pattern, is_dir_only, path_is_dir):
            ignored = not is_negation
    return ignored


class GitIgnoreFilter:
    """Collects ``.gitignore`` patterns from a source tree and filters paths."""

    def __init__(self, source_root: str | Path):
        self.source_root: Path = Path(source_root).resolve()
        self._patterns: list[tuple[str, bool, bool, str]] = []  # (pattern, is_negation, is_dir_only, source_dir)
        self._collect()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        """Return ``True`` if *rel_path* should be excluded.

        *rel_path* must be relative to *source_root*.
        """
        # Hard-coded skips are checked first (always excluded, never negated).
        for skip in _ALWAYS_SKIP:
            if skip.endswith("/"):
                # Directory-only skip: match anywhere in tree (like git does)
                dir_name = skip.rstrip("/")
                if is_dir and (fnmatch.fnmatch(rel_path, dir_name)
                               or fnmatch.fnmatch(rel_path, "**/" + dir_name)
                               or rel_path.rstrip("/").endswith("/" + dir_name)):
                    return True
            else:
                if fnmatch.fnmatch(rel_path, skip) or fnmatch.fnmatch(rel_path, "**/" + skip):
                    return True

        return _is_ignored(rel_path, self._patterns, is_dir)

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    def _collect(self) -> None:
        """Walk upward from *source_root* collecting all ``.gitignore`` files."""
        # Walk from the root upward to filesystem boundary, collecting
        # .gitignore files.  Patterns from parent directories shadow children
        # (prepended so later patterns from deeper dirs override).
        collected: list[tuple[str, bool, bool, str]] = []
        current = self.source_root
        seen: set[str] = set()

        while True:
            gitignore = current / ".gitignore"
            if gitignore.is_file() and str(gitignore) not in seen:
                seen.add(str(gitignore))
                # Parent patterns go first (deeper patterns override)
                parent_patterns = self._parse_gitignore(gitignore)
                collected = parent_patterns + collected

            parent = current.parent
            if parent == current:  # Reached filesystem root
                break
            current = parent

        self._patterns = collected

    @staticmethod
    def _parse_gitignore(path: Path) -> list[tuple[str, bool, bool, str]]:
        """Parse a single ``.gitignore`` file into pattern tuples."""
        patterns: list[tuple[str, bool, bool, str]] = []
        source_dir = str(path.parent)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return patterns

        for line in lines:
            stripped = line.rstrip()
            # Skip empty lines and comments
            if not stripped or stripped.startswith("#"):
                continue

            is_negation = False
            if stripped.startswith("!"):
                is_negation = True
                stripped = stripped[1:]

            # Trailing slash -> directory-only
            is_dir_only = stripped.endswith("/")
            if is_dir_only:
                stripped = stripped.rstrip("/")

            # Strip leading / (git treats root-relative patterns specially)
            if stripped.startswith("/"):
                stripped = stripped[1:]

            if stripped:
                patterns.append((stripped, is_negation, is_dir_only, source_dir))

        return patterns


# ---------------------------------------------------------------------------
# Factory: returns a shutil.copytree-compatible ignore callback
# ---------------------------------------------------------------------------


def gitignore_filter(
    source_root: str | Path,
) -> Callable[[str, list[str]], set[str]]:
    """Return an *ignore* callable compatible with :func:`shutil.copytree`.

    Usage::

        shutil.copytree(src, dst, ignore=gitignore_filter(src))
    """
    filt = GitIgnoreFilter(source_root)

    def _ignore(directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        dir_path = Path(directory)
        for name in names:
            full = dir_path / name
            try:
                rel = str(full.relative_to(filt.source_root))
            except ValueError:
                # Directory is outside source root — skip filtering.
                continue
            is_dir = full.is_dir()
            if filt.is_ignored(rel, is_dir=is_dir):
                ignored.add(name)
        return ignored

    return _ignore


__all__ = ["GitIgnoreFilter", "gitignore_filter"]
