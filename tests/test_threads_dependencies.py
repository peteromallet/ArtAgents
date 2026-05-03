from __future__ import annotations

from pathlib import Path


def test_xxhash_dependency_declared_and_importable() -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()
    assert any(line.strip() == "xxhash>=3.4" for line in requirements)

    import xxhash

    assert xxhash.xxh64_hexdigest(b"artagents")
