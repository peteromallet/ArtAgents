"""Built-in thumbnail maker conductor metadata."""

from artagents.conductors import ConductorSpec, Port, RuntimeSpec


conductor = ConductorSpec(
    id="builtin.thumbnail_maker",
    name="Thumbnail Maker",
    kind="built_in",
    version="1.0",
    description="Plans source evidence and thumbnail generation candidates for a video/query pair.",
    runtime=RuntimeSpec(
        kind="python",
        module="artagents.conductors.curated.thumbnail_maker.runtime",
        function="run",
    ),
    inputs=[
        Port(
            name="video",
            type="path",
            required=False,
            description="Source video path or URL. Can also be supplied as passthrough --video.",
        ),
        Port(
            name="query",
            type="string",
            required=False,
            description="Thumbnail direction. Can also be supplied as passthrough --query.",
        ),
    ],
    cache={"mode": "none"},
    metadata={"legacy_entrypoint": "thumbnail_maker.py"},
)
