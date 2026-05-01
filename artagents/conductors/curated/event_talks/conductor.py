"""Built-in event talks conductor metadata."""

from artagents.conductors import ConductorSpec, RuntimeSpec


conductor = ConductorSpec(
    id="builtin.event_talks",
    name="Event Talks",
    kind="built_in",
    version="1.0",
    description="Orchestrates event-talk template, search, holding-screen, and render commands.",
    runtime=RuntimeSpec(
        kind="python",
        module="artagents.conductors.curated.event_talks.runtime",
        function="run",
    ),
    cache={"mode": "none"},
    metadata={
        "legacy_entrypoint": "event_talks.py",
        "subcommands": ["ados-sunday-template", "search-transcript", "find-holding-screens", "render"],
    },
)
