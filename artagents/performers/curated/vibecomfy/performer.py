"""VibeComfy curated folder performers."""

from artagents.performers import PerformerPort, PerformerSpec


PACKAGE_ID = "vibecomfy"

_WORKFLOW_INPUT = PerformerPort(
    "workflow",
    "file",
    required=True,
    description="VibeComfy workflow JSON file.",
)

_COMMON_METADATA = {
    "homepage": "https://github.com/peteromallet/VibeComfy",
    "cli_module": "vibecomfy.cli",
}

PERFORMERS = [
    PerformerSpec(
        id="external.vibecomfy.run",
        name="VibeComfy Run",
        kind="external",
        version="0.1.0",
        description="Run a VibeComfy workflow through the VibeComfy CLI.",
        inputs=[_WORKFLOW_INPUT],
        command={
            "argv": [
                "{python_exec}",
                "-m",
                "vibecomfy.cli",
                "run",
                "{workflow}",
            ]
        },
        cache={"mode": "none"},
        conditions=[{"kind": "requires_input", "input": "workflow"}],
        graph={
            "consumes": ["workflow"],
            "provides": ["vibecomfy_run"],
        },
        isolation={
            "mode": "subprocess",
            "requirements": ["vibecomfy"],
            "network": True,
        },
        metadata={
            **_COMMON_METADATA,
            "vibecomfy_command": "run",
        },
    ),
    PerformerSpec(
        id="external.vibecomfy.validate",
        name="VibeComfy Validate",
        kind="external",
        version="0.1.0",
        description="Validate a VibeComfy workflow through the VibeComfy CLI.",
        inputs=[_WORKFLOW_INPUT],
        command={
            "argv": [
                "{python_exec}",
                "-m",
                "vibecomfy.cli",
                "validate",
                "{workflow}",
            ]
        },
        cache={"mode": "none"},
        conditions=[{"kind": "requires_input", "input": "workflow"}],
        graph={
            "consumes": ["workflow"],
            "provides": ["vibecomfy_validation"],
        },
        isolation={
            "mode": "subprocess",
            "requirements": ["vibecomfy"],
            "network": False,
        },
        metadata={
            **_COMMON_METADATA,
            "vibecomfy_command": "validate",
        },
    ),
]
