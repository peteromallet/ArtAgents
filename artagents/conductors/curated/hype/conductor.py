"""Built-in hype pipeline conductor metadata."""

from artagents import pipeline
from artagents.conductors import ConductorSpec, RuntimeSpec


conductor = ConductorSpec(
    id="builtin.hype",
    name="Hype Pipeline",
    kind="built_in",
    version="1.0",
    description="Orchestrates the built-in hype editing pipeline.",
    runtime=RuntimeSpec(
        kind="python",
        module="artagents.conductors.curated.hype.runtime",
        function="run",
    ),
    child_performers=[f"builtin.{name}" for name in pipeline.STEP_ORDER],
    cache={"mode": "none"},
    metadata={"legacy_entrypoint": "pipeline.py"},
)
