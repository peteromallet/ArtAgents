import contextlib
import io
import re
from pathlib import Path

from artagents.executors import cli as executors_cli
from artagents.orchestrators import cli as orchestrators_cli
from artagents.threads.index import ThreadIndexStore
from artagents.threads.schema import make_thread_record


THREAD_ID = "01ARZ3NDEKTSV4RRFFQ69G5FW0"
SKILL_PARAGRAPH = (
    "At the start of any session that will produce runs, run python3 -m artagents thread show @active first. "
    "The [thread] prefix on every command output is your continuous indicator; if it shows the wrong thread, "
    "run thread new or pass --thread @new to your next command. Selections are append-only; the most recent "
    "write is authoritative on read; prior selections are preserved as history but do not affect current keepers."
)


def test_threads_doc_covers_required_t11_sections_without_lock_repair_command() -> None:
    text = Path("docs/threads.md").read_text(encoding="utf-8")
    for heading in (
        "## Model",
        "## Prefixes",
        "## Privacy & Redaction",
        "## Concurrent Variant Selection",
        "## Tier Firing Rules",
        "## Inspect Before Render",
        "## Stale Locks",
        "## Deferred",
    ):
        assert heading in text
    compact = re.sub(r"\s+", " ", text.lower())
    assert "selections are append-only; the most recent write is authoritative on read; prior selections are preserved as history" in compact
    assert "python3 -m artagents.orchestrators.iteration_video.run inspect <thread>" in text
    assert "hype.timeline.json" in text and "hype.assets.json" in text and "iteration.mp4" in text
    assert "preview_modes" in text
    assert "thread gc" not in text


def test_skill_includes_thread_session_guidance() -> None:
    text = Path("SKILL.md").read_text(encoding="utf-8")
    assert SKILL_PARAGRAPH in text
    assert "python3 -m artagents.orchestrators.iteration_video.run inspect <thread>" in text


def test_executor_and_orchestrator_inspect_show_active_thread_footer(tmp_path: Path, monkeypatch) -> None:
    thread = make_thread_record(thread_id=THREAD_ID, label="Footer Thread")
    ThreadIndexStore(tmp_path).write({"schema_version": 1, "active_thread_id": THREAD_ID, "threads": {THREAD_ID: thread}})
    monkeypatch.setenv("ARTAGENTS_REPO_ROOT", str(tmp_path))

    executor_stdout = io.StringIO()
    with contextlib.redirect_stdout(executor_stdout):
        assert executors_cli.main(["inspect", "builtin.render"]) == 0
    executor_output = executor_stdout.getvalue()
    assert f"active_thread: Footer Thread ({THREAD_ID})" in executor_output
    assert "thread_details: python3 -m artagents thread show @active" in executor_output

    orchestrator_stdout = io.StringIO()
    with contextlib.redirect_stdout(orchestrator_stdout):
        assert orchestrators_cli.main(["inspect", "builtin.iteration_video"]) == 0
    orchestrator_output = orchestrator_stdout.getvalue()
    assert f"active_thread: Footer Thread ({THREAD_ID})" in orchestrator_output
    assert "thread_details: python3 -m artagents thread show @active" in orchestrator_output
