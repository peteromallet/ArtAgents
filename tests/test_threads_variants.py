from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from artagents.core.executor.registry import ExecutorRegistry
from artagents.core.executor.runner import ExecutorRunRequest, run_executor
from artagents.core.executor.schema import ExecutorDefinition
from artagents.contracts.schema import CommandSpec, Output
from artagents.threads.ids import generate_run_id, generate_thread_id
from artagents.threads.index import ThreadIndexStore
from artagents.threads.record import build_run_record, finalize_run_record, write_run_record
from artagents.threads.schema import make_thread_record
from artagents.threads.variants import (
    VariantState,
    keep_selection,
    read_current_keepers,
    selection_history,
    update_groups_for_run,
    variant_prefix_message,
    write_sidecar,
)


def test_default_output_role_other_without_variant_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    out = repo / "runs" / "plain"
    (out / "note.txt").parent.mkdir(parents=True)
    (out / "note.txt").write_text("plain", encoding="utf-8")

    record = finalize_run_record(
        build_run_record(run_id=generate_run_id(), thread_id=generate_thread_id(), kind="executor", out_path=out, repo_root=repo),
        repo_root=repo,
        out_path=out,
        returncode=0,
    )

    assert record["output_artifacts"][0]["role"] == "other"
    assert update_groups_for_run(repo, record) is None


def test_variant_sidecar_groups_only_variant_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    thread_id = generate_thread_id()
    run_id = generate_run_id()
    out = repo / "runs" / "variants"
    image = out / "image-1.png"
    text = out / "manifest.json"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")
    text.write_text("{}", encoding="utf-8")
    write_sidecar(
        out,
        [
            {
                "path": image,
                "role": "variant",
                "group": "abc123def4567890",
                "group_index": 1,
                "variant_meta": {"prompt": "mark"},
            }
        ],
    )

    record = finalize_run_record(
        build_run_record(run_id=run_id, thread_id=thread_id, kind="executor", out_path=out, repo_root=repo),
        repo_root=repo,
        out_path=out,
        returncode=0,
    )
    update_groups_for_run(repo, record)

    by_path = {item["path"]: item for item in record["output_artifacts"]}
    assert by_path["runs/variants/image-1.png"]["role"] == "variant"
    assert by_path["runs/variants/image-1.png"]["group"] == "abc123def4567890"
    assert by_path["runs/variants/manifest.json"]["role"] == "other"
    groups = VariantState(repo, thread_id).read_groups()
    assert list(groups["groups"]) == ["abc123def4567890"]
    assert groups["groups"]["abc123def4567890"]["artifacts"][0]["variant_meta"] == {"prompt": "mark"}


def test_keep_none_and_last_write_wins_selection_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    thread_id, run_id = _variant_run(repo, group="grp1")

    keep_selection(repo, thread_id, f"{run_id}:none")
    keep_selection(repo, thread_id, f"{run_id}:1")

    history = selection_history(repo, thread_id)
    assert len(history) == 2
    keepers = read_current_keepers(repo, thread_id)
    assert keepers["grp1"][0]["run_id"] == run_id
    assert variant_prefix_message(repo, thread_id) is None


def test_concurrent_group_updates_preserve_heterogeneous_groups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    thread_id = generate_thread_id()

    def worker(index: int) -> None:
        _variant_run(repo, thread_id=thread_id, group=f"group{index}", run_slug=f"run-{index}")

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    groups = VariantState(repo, thread_id).read_groups()
    assert sorted(groups["groups"]) == [f"group{index}" for index in range(6)]


def test_typed_from_ref_parent_edge_includes_chosen_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path, monkeypatch)
    thread_id, parent_run_id = _variant_run(repo, group="chosen-group")
    ThreadIndexStore(repo).write(
        {"schema_version": 1, "active_thread_id": thread_id, "threads": {thread_id: make_thread_record(thread_id=thread_id, label="T")}}
    )
    registry = ExecutorRegistry([_writer_executor("test.writer")])
    out = repo / "runs" / "child"

    run_executor(ExecutorRunRequest("test.writer", out=out, from_ref=f"{parent_run_id}:1"), registry)

    record = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert record["parent_run_ids"] == [{"group": "chosen-group", "kind": "chosen", "run_id": parent_run_id}]


def _variant_run(
    repo: Path,
    *,
    thread_id: str | None = None,
    group: str,
    run_slug: str = "variant",
) -> tuple[str, str]:
    thread_id = thread_id or generate_thread_id()
    run_id = generate_run_id()
    out = repo / "runs" / run_slug
    image = out / f"{group}.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(group.encode("utf-8"))
    write_sidecar(out, [{"path": image, "role": "variant", "group": group, "group_index": 1}])
    record = finalize_run_record(
        build_run_record(run_id=run_id, thread_id=thread_id, kind="executor", executor_id="test.variant", out_path=out, repo_root=repo),
        repo_root=repo,
        out_path=out,
        returncode=0,
    )
    write_run_record(record, out / "run.json")
    update_groups_for_run(repo, record)
    return thread_id, run_id


def _writer_executor(executor_id: str) -> ExecutorDefinition:
    return ExecutorDefinition(
        id=executor_id,
        name="Writer",
        kind="external",
        version="1.0",
        command=CommandSpec(argv=("python3", "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).mkdir(parents=True, exist_ok=True); (Path(sys.argv[1]) / 'ok.txt').write_text('ok')", "{out}")),
        outputs=(Output(name="ok", type="file", path_template="{out}/ok.txt"),),
    )


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("ARTAGENTS_REPO_ROOT", str(repo))
    for name in ("ARTAGENTS_THREADS_OFF", "ARTAGENTS_THREAD_INHERITED", "ARTAGENTS_THREAD_ID", "ARTAGENTS_RUN_ID", "ARTAGENTS_PARENT_RUN_ID"):
        monkeypatch.delenv(name, raising=False)
    return repo
