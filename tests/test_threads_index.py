from __future__ import annotations

import fcntl
import json
import multiprocessing
import time
from pathlib import Path

import pytest

from astrid.threads.ids import generate_run_id, generate_thread_id
from astrid.threads.index import ThreadIndexLockTimeout, ThreadIndexStore
from astrid.threads.schema import (
    SCHEMA_VERSION,
    ThreadSchemaError,
    empty_threads_index,
    make_thread_record,
    validate_persisted_path,
    validate_run_record,
)


def test_index_created_on_first_write_with_schema_version(tmp_path: Path) -> None:
    store = ThreadIndexStore(tmp_path)
    thread_id = generate_thread_id()
    index = empty_threads_index()
    index["threads"][thread_id] = make_thread_record(thread_id=thread_id, label="Logo sprint")
    index["active_thread_id"] = thread_id

    written = store.write(index)

    assert written["schema_version"] == SCHEMA_VERSION
    assert (tmp_path / ".astrid" / "threads.json").is_file()
    on_disk = json.loads((tmp_path / ".astrid" / "threads.json").read_text(encoding="utf-8"))
    assert on_disk["active_thread_id"] == thread_id
    assert on_disk["threads"][thread_id]["label"] == "Logo sprint"


def test_index_rotates_bak_and_recovers_from_partial_write(tmp_path: Path) -> None:
    store = ThreadIndexStore(tmp_path)
    first_id = generate_thread_id()
    second_id = generate_thread_id()
    first = empty_threads_index()
    first["threads"][first_id] = make_thread_record(thread_id=first_id, label="First")
    first["active_thread_id"] = first_id
    store.write(first)

    second = store.read()
    second["threads"][second_id] = make_thread_record(thread_id=second_id, label="Second")
    second["active_thread_id"] = second_id
    store.write(second)

    assert store.backup_path.is_file()
    store.index_path.write_text('{"schema_version": 1, "threads": ', encoding="utf-8")

    recovered = store.read()

    assert recovered["active_thread_id"] == first_id
    assert first_id in recovered["threads"]
    restored = json.loads(store.index_path.read_text(encoding="utf-8"))
    assert restored["active_thread_id"] == first_id


def test_lock_timeout_guidance_avoids_thread_gc(tmp_path: Path) -> None:
    store = ThreadIndexStore(tmp_path, lock_timeout=0.15)
    store.state_dir.mkdir(parents=True, exist_ok=True)
    with store.lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        started = time.monotonic()
        with pytest.raises(ThreadIndexLockTimeout) as raised:
            store.read()
        elapsed = time.monotonic() - started
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    message = str(raised.value)
    assert elapsed >= 0.10
    assert "threads.json lock" in message
    assert "thread gc" not in message


def test_repo_relative_and_content_addressed_path_validation() -> None:
    assert validate_persisted_path("runs/logo/run.json") == "runs/logo/run.json"
    assert validate_persisted_path("sha256:" + "a" * 64) == "sha256:" + "a" * 64
    with pytest.raises(ThreadSchemaError):
        validate_persisted_path("/tmp/logo/run.json")
    with pytest.raises(ThreadSchemaError):
        validate_persisted_path("../secret.txt")
    with pytest.raises(ThreadSchemaError):
        validate_run_record(
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": generate_run_id(),
                "thread_id": generate_thread_id(),
                "parent_run_ids": [],
                "out_path": "/tmp/absolute",
                "input_artifacts": [],
                "output_artifacts": [],
                "external_service_calls": [],
            }
        )


def test_concurrent_writers_do_not_lose_updates(tmp_path: Path) -> None:
    thread_id = generate_thread_id()
    store = ThreadIndexStore(tmp_path)
    index = empty_threads_index()
    index["threads"][thread_id] = make_thread_record(thread_id=thread_id, label="Concurrent")
    index["active_thread_id"] = thread_id
    store.write(index)

    run_ids = [generate_run_id() for _ in range(8)]
    processes = [
        multiprocessing.Process(target=_append_run_id, args=(tmp_path, thread_id, run_id))
        for run_id in run_ids
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)

    assert all(process.exitcode == 0 for process in processes)
    final_index = store.read()
    assert sorted(final_index["threads"][thread_id]["run_ids"]) == sorted(run_ids)


def _append_run_id(repo_root: Path, thread_id: str, run_id: str) -> None:
    store = ThreadIndexStore(repo_root)

    def mutate(index):
        index["threads"][thread_id]["run_ids"].append(run_id)

    store.update(mutate)
