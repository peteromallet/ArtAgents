from __future__ import annotations

from artagents.threads.ids import CROCKFORD_ALPHABET, generate_group_id, generate_run_id, generate_thread_id, is_ulid


def test_thread_run_and_group_ids_are_crockford_ulids() -> None:
    values = [generate_thread_id(), generate_run_id(), generate_group_id()]
    for value in values:
        assert len(value) == 26
        assert set(value) <= set(CROCKFORD_ALPHABET)
        assert is_ulid(value)


def test_generated_ulids_are_monotonic_in_process() -> None:
    values = [generate_run_id() for _ in range(1000)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)
