"""Pack discovery skips ai_toolkit/upstream submodule trees."""

from __future__ import annotations

from pathlib import Path

from astrid.core.pack import (
    PackDefinition,
    iter_executor_roots,
    iter_orchestrator_roots,
)


def _make_pack(root: Path) -> PackDefinition:
    return PackDefinition(
        id="testpack",
        name="testpack",
        version="0.1.0",
        root=root,
        manifest_path=root / "pack.yaml",
        metadata={},
    )


def test_iter_executor_roots_skips_ai_toolkit_upstream(tmp_path: Path) -> None:
    pack_root = tmp_path / "testpack"
    # Real executor under the pack
    real_dir = pack_root / "real_exec"
    real_dir.mkdir(parents=True)
    (real_dir / "executor.yaml").write_text("id: testpack.real\n")

    # Synthetic ai-toolkit submodule with its own executor.yaml that must
    # NOT be discovered.
    submodule_exec = pack_root / "ai_toolkit" / "upstream" / "examples" / "fake"
    submodule_exec.mkdir(parents=True)
    (submodule_exec / "executor.yaml").write_text("id: should.not.be.discovered\n")

    pack = _make_pack(pack_root)
    roots = iter_executor_roots(pack)
    paths = {p.resolve() for p in roots}
    assert real_dir.resolve() in paths
    assert submodule_exec.resolve() not in paths
    # Defensive: no path under ai_toolkit at all
    for p in paths:
        assert "ai_toolkit" not in p.parts


def test_iter_orchestrator_roots_skips_ai_toolkit_upstream(tmp_path: Path) -> None:
    pack_root = tmp_path / "testpack"
    real_orch = pack_root / "real_orch"
    real_orch.mkdir(parents=True)
    (real_orch / "orchestrator.yaml").write_text("id: testpack.real\n")

    submodule_orch = pack_root / "ai_toolkit" / "upstream" / "orch"
    submodule_orch.mkdir(parents=True)
    (submodule_orch / "orchestrator.yaml").write_text("id: should.not.be.discovered\n")

    pack = _make_pack(pack_root)
    roots = iter_orchestrator_roots(pack)
    paths = {p.resolve() for p in roots}
    assert real_orch.resolve() in paths
    assert submodule_orch.resolve() not in paths
