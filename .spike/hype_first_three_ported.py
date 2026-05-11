"""Throwaway port: first three hype steps (transcribe → cut → render) as collapsed Step tree.

Lives on reshape/sprint-3-hype-spike only. NEVER merged to reshape/sprint-3.
The real builtin.hype/ pack is NOT modified — this is a paper-port to exercise
the draft Step schema + Adapter Protocol against a real pipeline shape.

Gaps discovered are captured in docs/reshape/sprint-3/hype-spike-findings.md.
"""

from __future__ import annotations

from astrid.core.task.plan import (
    ProducesEntry,
    RepeatForEach,
    Step,
    TaskPlan,
)
from astrid.verify import Check, file_nonempty
from astrid.core.adapter.local import LocalAdapter
from astrid.core.adapter.manual import ManualAdapter

# Step 1: transcribe — local-adapter leaf.
# Reads --source video, writes transcribe.json. No ack required.
transcribe = Step(
    id="transcribe",
    adapter="local",
    command="python -m astrid.packs.builtin.transcribe.run --source {source} --out {out}",
    produces=(
        ProducesEntry(
            name="transcribe",
            path="transcribe.json",
            check=file_nonempty(),
        ),
    ),
    assignee="system",
)

# Step 2: cut — local-adapter leaf, consumes transcribe.json (sibling produces).
# Note: real hype.cut also reads scenes.json; the brief says only port transcribe/cut/render,
# so the scenes step is collapsed into cut for spike purposes. SEE FINDING G2.
cut = Step(
    id="cut",
    adapter="local",
    command="python -m astrid.packs.builtin.cut.run --transcribe {transcribe.produces.transcribe} --out {out}",
    produces=(
        ProducesEntry(
            name="hype_timeline",
            path="hype.timeline.json",
            check=file_nonempty(),
        ),
    ),
    assignee="system",
)

# Step 3: render — local-adapter leaf, consumes hype.timeline.json.
# Cost-bearing (Remotion GPU minutes). SEE FINDING G3.
render = Step(
    id="render",
    adapter="local",
    command="python -m astrid.packs.builtin.render.run --timeline {cut.produces.hype_timeline} --out {out}",
    produces=(
        ProducesEntry(
            name="final_video",
            path="hype.mp4",
            check=file_nonempty(),
        ),
    ),
    assignee="system",
)

HYPE_FIRST_THREE = TaskPlan(
    plan_id="hype.spike.first-three",
    version=2,
    steps=(transcribe, cut, render),
)


# Exercise: adapter Protocol against the stubs. Demonstrates we *can* dispatch
# through the interface; actual execution raises NotImplementedError per T11/T12.
def _demo_adapter_dispatch() -> None:
    """Wires steps to adapter instances; ensures the Protocol shape fits hype's needs."""
    adapters = {"local": LocalAdapter(), "manual": ManualAdapter()}
    for step in (transcribe, cut, render):
        adapter = adapters[step.adapter]
        assert adapter.name == step.adapter
        # Each step would call adapter.dispatch(step, RunContext(...)) at cmd_next time.
        # NotImplementedError is the expected stub raise.


if __name__ == "__main__":
    _demo_adapter_dispatch()
    print(f"ported {len(HYPE_FIRST_THREE.steps)} hype steps to the draft Step shape")
