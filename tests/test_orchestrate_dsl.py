"""DSL unit tests for artagents.orchestrate (Phase 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from artagents.core.task.plan import load_plan
from artagents.orchestrate import (
    OrchestrateDefinitionError,
    attested,
    code,
    file_nonempty,
    json_file,
    plan,
    repeat_for_each,
)


def _valid_argv() -> list:
    return ["python3", "-m", "artagents", "executors", "run", "builtin.transcribe", "--project", "demo"]


class TestTypedHandle:
    def test_handle_str_form(self) -> None:
        transcribe = code("transcribe", argv=_valid_argv(), produces={"transcript": json_file()})
        assert str(transcribe.transcript) == "transcribe.produces.transcript"

    def test_typo_raises_at_definition_time(self) -> None:
        transcribe = code("transcribe", argv=_valid_argv(), produces={"transcript": json_file()})
        with pytest.raises(OrchestrateDefinitionError) as excinfo:
            _ = transcribe.transcrpt
        msg = str(excinfo.value)
        assert "transcrpt" in msg
        assert "transcript" in msg
        assert "transcribe" in msg


class TestArgvGuards:
    def test_orchestrators_run_argv_rejected(self) -> None:
        with pytest.raises(OrchestrateDefinitionError) as excinfo:
            code(
                "bad",
                argv=["python3", "-m", "artagents", "orchestrators", "run", "builtin.hype"],
            )
        assert "orchestrators" in str(excinfo.value).lower()

    def test_orchestrators_run_via_artagents_binary_rejected(self) -> None:
        with pytest.raises(OrchestrateDefinitionError):
            code("bad", argv=["artagents", "orchestrators", "run", "x"])

    def test_argv_accepts_produces_handles_and_stringifies(self) -> None:
        # FLAG-006: argv may carry _ProducesHandle entries; they stringify
        # before shlex.join so the resulting command embeds the produces ref.
        transcribe = code("transcribe", argv=_valid_argv(), produces={"transcript": json_file()})
        cut = code("cut", argv=["echo", transcribe.transcript], produces={"out": json_file()})
        assert cut.command == "echo transcribe.produces.transcript"


class TestAttestedGuards:
    def test_sentinel_only_attested_rejected_at_construction(self) -> None:
        with pytest.raises(OrchestrateDefinitionError) as excinfo:
            attested(
                "review",
                command="review.sh",
                instructions="review the artifact",
                ack="agent",
                produces={"x": file_nonempty()},
            )
        assert "sentinel" in str(excinfo.value).lower()

    def test_attested_with_semantic_check_accepted(self) -> None:
        step = attested(
            "review",
            command="review.sh",
            instructions="review",
            ack="agent",
            produces={"summary": json_file()},
        )
        assert step.kind == "attested"


class TestReservedAttrCollision:
    """FLAG-004: produces names colliding with _StepHandle attrs are rejected."""

    @pytest.mark.parametrize(
        "reserved",
        ["id", "kind", "command", "argv", "plan", "produces", "repeat", "instructions", "ack"],
    )
    def test_reserved_attr_rejected(self, reserved: str) -> None:
        with pytest.raises(OrchestrateDefinitionError) as excinfo:
            code("x", argv=_valid_argv(), produces={reserved: json_file()})
        assert reserved in str(excinfo.value)
        assert "reserved" in str(excinfo.value).lower()


class TestRepeatForEachCompilation:
    def test_for_each_from_compiles_to_dotted_ref(self) -> None:
        transcribe = code("transcribe", argv=_valid_argv(), produces={"transcript": json_file()})
        process = code(
            "process",
            argv=["echo", "x"],
            repeat=repeat_for_each(from_=transcribe.transcript),
        )
        p = plan("sample.foo", [transcribe, process])
        d = p.to_dict()
        assert d["steps"][1]["repeat"] == {
            "for_each": {"from": "transcribe.produces.transcript"}
        }


class TestRoundTrip:
    def test_to_dict_round_trips_through_load_plan(self, tmp_path: Path) -> None:
        transcribe = code("transcribe", argv=_valid_argv(), produces={"transcript": json_file()})
        cut = code("cut", argv=["echo", transcribe.transcript], produces={"out": json_file()})
        p = plan("sample.foo", [transcribe, cut])
        payload = p.to_dict()

        # Write payload byte-for-byte and re-validate via the public load_plan.
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = load_plan(plan_path)
        assert loaded.plan_id == "sample.foo"
        assert len(loaded.steps) == 2
        assert loaded.steps[0].id == "transcribe"
        assert loaded.steps[1].id == "cut"

    def test_duplicate_sibling_step_ids_rejected(self) -> None:
        with pytest.raises(OrchestrateDefinitionError) as excinfo:
            plan(
                "sample.foo",
                [
                    code("dup", argv=_valid_argv(), produces={"a": json_file()}),
                    code("dup", argv=_valid_argv(), produces={"b": json_file()}),
                ],
            )
        assert "dup" in str(excinfo.value)
