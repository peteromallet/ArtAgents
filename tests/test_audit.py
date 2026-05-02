from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from artagents import audit
from artagents.audit import AuditContext


def test_audit_registers_asset_graph_and_report(tmp_path: Path) -> None:
    run = tmp_path / "run"
    artifact = run / "frames" / "frame.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("hello audit", encoding="utf-8")

    ctx = AuditContext.for_run(run)
    source_id = ctx.register_asset(kind="source", path=artifact, label="Source")
    output_id = ctx.register_asset(kind="text", path=artifact, label="Output", parents=[source_id])
    ctx.register_node(stage="demo", parents=[source_id], outputs=[output_id])

    events = audit.load_ledger(run)
    graph = audit.build_graph(events)
    assert {node["id"] for node in graph["nodes"]} >= {source_id, output_id}
    assert {"from": source_id, "to": output_id} in graph["edges"]

    report = audit.write_report(run)
    assert report == run / "audit" / "report.html"
    html = report.read_text(encoding="utf-8")
    assert "hello audit" in html
    assert "Asset Journey" in html


def test_graph_collapses_duplicate_stable_ids_and_dedupes_edges(tmp_path: Path) -> None:
    run = tmp_path / "run"
    artifact = run / "asset.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("v1", encoding="utf-8")
    ctx = AuditContext.for_run(run)
    parent_id = ctx.register_asset(kind="source", label="Source")
    first_id = ctx.register_asset(kind="text", path=artifact, label="Output", parents=[parent_id])
    artifact.write_text("v2", encoding="utf-8")
    second_id = ctx.register_asset(kind="text", path=artifact, label="Output", parents=[parent_id])

    graph = audit.build_graph(audit.load_ledger(run))

    assert first_id == second_id
    assert [node["id"] for node in graph["nodes"]].count(first_id) == 1
    assert graph["edges"].count({"from": parent_id, "to": first_id}) == 1
    latest = next(node for node in graph["nodes"] if node["id"] == first_id)
    assert latest["preview"]["text"] == "v2"


def test_audit_redacts_secret_like_values(tmp_path: Path) -> None:
    ctx = AuditContext.for_run(tmp_path / "run")
    ctx.register_node(
        stage="secret-test",
        metadata={"OPENAI_API_KEY": "sk-testsecret1234567890", "nested": {"token": "hf_abcdefghijklmnop"}},
    )
    event = json.loads(ctx.ledger_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["metadata"]["OPENAI_API_KEY"] == "<redacted>"
    assert event["metadata"]["nested"]["token"] == "<redacted>"


def test_pipeline_audit_cli_json(tmp_path: Path, capsys) -> None:
    pytest.importorskip("jsonschema")
    from artagents.pipeline import main as pipeline_main

    ctx = AuditContext.for_run(tmp_path / "run")
    asset_id = ctx.register_asset(kind="source", label="Only source")

    assert pipeline_main(["audit", "--run", str(tmp_path / "run"), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(node["id"] == asset_id for node in payload["nodes"])


def test_pipeline_audit_env_propagation_and_fallback(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("jsonschema")
    from artagents import pipeline

    script = tmp_path / "child.py"
    script.write_text(
        "import os, pathlib\n"
        "out = pathlib.Path(os.environ['CHILD_OUT'])\n"
        "out.write_text(os.environ.get('ARTAGENTS_AUDIT_RUN_DIR', ''), encoding='utf-8')\n",
        encoding="utf-8",
    )
    out = tmp_path / "run"
    args = type(
        "Args",
        (),
        {
            "out": out,
            "brief_out": out,
            "verbose": False,
            "audit": AuditContext.for_run(out),
            "no_audit": False,
            "extra_args": {},
        },
    )()
    monkeypatch.setenv("CHILD_OUT", str(out / "sentinel.txt"))
    step = pipeline.Step("demo", ("sentinel.txt",), lambda _: [sys.executable, str(script)])

    assert pipeline.run_step(step, step.build_cmd(args), args) == 0
    assert (out / "sentinel.txt").read_text(encoding="utf-8") == str(out)
    events = [json.loads(line) for line in (out / "audit" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(event.get("registration_source") == "pipeline_fallback" for event in events)


def test_ambient_register_outputs_from_producer(monkeypatch, tmp_path: Path) -> None:
    from artagents.executors.scenes import run as scenes

    run = tmp_path / "run"
    monkeypatch.setenv("ARTAGENTS_AUDIT_RUN_DIR", str(run))
    json_path = run / "scenes.json"
    csv_path = run / "scenes.csv"

    scenes.write_outputs([{"index": 1, "start": 0.0, "end": 1.0, "duration": 1.0}], json_path, csv_path)

    events = [json.loads(line) for line in (run / "audit" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(event.get("kind") == "scenes" and event.get("path") == "scenes.json" for event in events)
    assert any(event.get("event") == "node.created" and event.get("stage") == "scenes" for event in events)


def test_ambient_register_outputs_inherits_parent_ids(monkeypatch, tmp_path: Path) -> None:
    from artagents.executors.scenes import run as scenes

    run = tmp_path / "run"
    parent_id = "source-parent"
    monkeypatch.setenv("ARTAGENTS_AUDIT_RUN_DIR", str(run))
    monkeypatch.setenv("ARTAGENTS_AUDIT_PARENT_IDS", parent_id)

    scenes.write_outputs([{"index": 1, "start": 0.0, "end": 1.0, "duration": 1.0}], run / "scenes.json", run / "scenes.csv")

    graph = audit.build_graph(audit.load_ledger(run))
    scenes_node = next(node for node in graph["nodes"] if node.get("kind") == "scenes")
    assert {"from": parent_id, "to": scenes_node["id"]} in graph["edges"]
