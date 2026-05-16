from astrid.packs.iteration.executors.prepare import run as prepare


def test_oq6_quality_formula_counts_valid_roots_without_penalty() -> None:
    root = prepare.RunNode(
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FC0",
        record={"input_artifacts": [], "brief_content_sha256": "a" * 64},
        depth=1,
        label="in_thread",
        parent_edges=[],
    )
    child = prepare.RunNode(
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FC1",
        record={"input_artifacts": [{"sha256": "b" * 64}], "brief_content_sha256": "a" * 64},
        depth=0,
        label="in_thread",
        parent_edges=[{"run_id": root.run_id, "kind": "causal"}],
    )

    quality = prepare.compute_quality([root, child], target_run_id=child.run_id)

    assert quality["parent_capture_score"] == 1.0
    assert quality["valid_roots"] == [root.run_id]
    assert quality["data_quality"] == 1.0
    assert quality["unresolved_producer_runs"] == []


def test_oq6_quality_reports_only_unresolved_non_roots() -> None:
    root = prepare.RunNode(
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FD0",
        record={"input_artifacts": []},
        depth=1,
        label="in_thread",
        parent_edges=[],
    )
    unresolved = prepare.RunNode(
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FD1",
        record={"input_artifacts": [{"sha256": "c" * 64}]},
        depth=0,
        label="in_thread",
        parent_edges=[],
        unresolved_parent_run_ids=["01ARZ3NDEKTSV4RRFFQ69G5FD2"],
    )

    quality = prepare.compute_quality([root, unresolved], target_run_id=unresolved.run_id)

    assert quality["parent_capture_score"] == 0.5
    assert quality["data_quality"] == 0.45
    assert quality["unresolved_producer_runs"] == [
        {
            "run_id": unresolved.run_id,
            "missing_parent_run_ids": ["01ARZ3NDEKTSV4RRFFQ69G5FD2"],
            "reason": "missing referenced producer",
        }
    ]
    assert root.run_id not in {item["run_id"] for item in quality["unresolved_producer_runs"]}
