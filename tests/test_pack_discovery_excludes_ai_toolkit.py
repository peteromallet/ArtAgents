"""Pack discovery skips ai_toolkit/upstream submodule trees."""

from __future__ import annotations

from pathlib import Path

import pytest

from astrid.core.pack import (
    PackDefinition,
    PackResolver,
    PackValidationError,
    iter_executor_roots,
    iter_orchestrator_roots,
)


def _make_pack(root: Path, declared: dict[str, str] | None = None) -> PackDefinition:
    return PackDefinition(
        id="testpack",
        name="testpack",
        version="0.1.0",
        root=root,
        manifest_path=root / "pack.yaml",
        metadata={},
        declared_content=declared or {},
    )


def test_iter_executor_roots_skips_ai_toolkit_upstream(tmp_path: Path) -> None:
    """When executors are declared at a sub-root, ai_toolkit is naturally excluded."""
    pack_root = tmp_path / "testpack"
    exec_root = pack_root / "executors"
    real_dir = exec_root / "real_exec"
    real_dir.mkdir(parents=True)
    (real_dir / "executor.yaml").write_text("id: testpack.real\n")

    # ai_toolkit submodule outside the declared executors root.
    submodule_exec = pack_root / "ai_toolkit" / "upstream" / "examples" / "fake"
    submodule_exec.mkdir(parents=True)
    (submodule_exec / "executor.yaml").write_text("id: should.not.be.discovered\n")

    pack = _make_pack(pack_root, declared={"executors": "executors"})
    roots = iter_executor_roots(pack)
    paths = {p.resolve() for p in roots}
    assert real_dir.resolve() in paths
    assert submodule_exec.resolve() not in paths
    for p in paths:
        assert "ai_toolkit" not in p.parts


def test_iter_orchestrator_roots_skips_ai_toolkit_upstream(tmp_path: Path) -> None:
    pack_root = tmp_path / "testpack"
    orch_root = pack_root / "orchestrators"
    real_orch = orch_root / "real_orch"
    real_orch.mkdir(parents=True)
    (real_orch / "orchestrator.yaml").write_text("id: testpack.real\n")

    submodule_orch = pack_root / "ai_toolkit" / "upstream" / "orch"
    submodule_orch.mkdir(parents=True)
    (submodule_orch / "orchestrator.yaml").write_text("id: should.not.be.discovered\n")

    pack = _make_pack(pack_root, declared={"orchestrators": "orchestrators"})
    roots = iter_orchestrator_roots(pack)
    paths = {p.resolve() for p in roots}
    assert real_orch.resolve() in paths
    assert submodule_orch.resolve() not in paths


def test_iter_executor_roots_raises_when_content_not_declared(tmp_path: Path) -> None:
    """Sprint 9: packs without declared content roots are a hard error."""
    pack_root = tmp_path / "testpack"
    pack_root.mkdir(parents=True)
    pack = _make_pack(pack_root, declared={})
    with pytest.raises(PackValidationError, match="content.executors not declared"):
        iter_executor_roots(pack)


def test_iter_orchestrator_roots_raises_when_content_not_declared(tmp_path: Path) -> None:
    pack_root = tmp_path / "testpack"
    pack_root.mkdir(parents=True)
    pack = _make_pack(pack_root, declared={})
    with pytest.raises(PackValidationError, match="content.orchestrators not declared"):
        iter_orchestrator_roots(pack)


def test_pack_resolver_raises_on_undeclared_content(tmp_path: Path) -> None:
    """Sprint 9: PackResolver raises when a discovered pack omits content roots."""
    packs_root = tmp_path / "packs"
    pack_root = packs_root / "testpack"
    pack_root.mkdir(parents=True)
    (pack_root / "pack.yaml").write_text(
        "id: testpack\nname: Test\nversion: '1.0'\n", encoding="utf-8"
    )

    with pytest.raises(PackValidationError, match="content.executors not declared"):
        PackResolver(packs_root)


def test_pack_resolver_skips_ai_toolkit_with_declared_roots(tmp_path: Path) -> None:
    """When a pack declares content roots, the resolver scans only the
    declared directory, which naturally excludes ai_toolkit."""
    packs_root = tmp_path / "packs"
    pack_root = packs_root / "testpack"
    pack_root.mkdir(parents=True)
    (pack_root / "pack.yaml").write_text(
        "schema_version: 1\n"
        "id: testpack\nname: Test\nversion: '1.0'\n"
        "content:\n"
        "  executors: my_execs\n"
        "  orchestrators: my_orchs\n",
        encoding="utf-8",
    )

    # Real executor in declared root
    real_dir = pack_root / "my_execs" / "real_exec"
    real_dir.mkdir(parents=True)
    (real_dir / "executor.yaml").write_text(
        '{"id":"testpack.real","name":"r","kind":"built_in","version":"1.0",'
        '"command":{"argv":["echo"]},"cache":{"mode":"none"}}',
        encoding="utf-8",
    )

    # ai_toolkit submodule -- should never be discovered
    submodule_exec = pack_root / "ai_toolkit" / "upstream" / "examples" / "fake"
    submodule_exec.mkdir(parents=True)
    (submodule_exec / "executor.yaml").write_text(
        '{"id":"should.not.be.discovered","name":"x","kind":"built_in",'
        '"version":"1.0","command":{"argv":["echo"]},"cache":{"mode":"none"}}',
        encoding="utf-8",
    )

    resolver = PackResolver(packs_root)
    roots = resolver.iter_executor_roots(resolver.get_pack("testpack"))
    paths = {p.resolve() for p in roots}
    assert real_dir.resolve() in paths
    for p in paths:
        assert "ai_toolkit" not in p.parts
