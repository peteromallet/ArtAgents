"""Moirae curated folder performer."""

from artagents.performers import PerformerOutput, PerformerPort, PerformerSpec


PERFORMER = PerformerSpec(
    id="external.moirae",
    name="Moirae",
    kind="external",
    version="0.1.0",
    description="Curated metadata for running Moirae against a screenplay to create a video. The MVP manifest does not install Moirae or its external binaries.",
    inputs=[
        PerformerPort(
            "screenplay",
            "file",
            required=True,
            description="Screenplay file consumed by Moirae.",
        )
    ],
    outputs=[
        PerformerOutput(
            "video",
            "file",
            mode="create_or_replace",
            placeholder="output",
            description="Rendered video path produced by Moirae.",
        )
    ],
    command={
        "argv": [
            "{python_exec}",
            "-m",
            "moirae",
            "{screenplay}",
            "-o",
            "{output}",
        ]
    },
    cache={"mode": "none"},
    conditions=[{"kind": "requires_input", "input": "screenplay"}],
    graph={
        "consumes": ["screenplay"],
        "provides": ["video"],
    },
    isolation={
        "mode": "subprocess",
        "requirements": ["moirae"],
        "binaries": ["asciinema", "agg", "ffmpeg"],
        "network": False,
    },
    metadata={
        "homepage": "https://github.com/peteromallet/Moirae",
        "manifest_only": True,
        "binary_requirements_enforced": "explicit_check_only",
    },
)
