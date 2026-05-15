"""Canonical hype orchestrator used by the Phase 9 author-test smoke fixture.

The legacy ``builtin.hype`` lived under ``builtin/hype/`` as a Stage-based
runtime; this sibling ``hype.py`` is the DSL-flavored orchestrator the author
test path replays. ``compile.resolve_orchestrator`` loads it via
``spec_from_file_location`` so the file/folder coexist without import
collision.
"""

from __future__ import annotations

from astrid.orchestrate import attested, code, orchestrator


@orchestrator("builtin.hype")
def hype():
    return [
        code("noop", argv=["python3", "-c", "print('ok')"]),
        attested(
            "review",
            command="echo review",
            instructions="approve to finish",
            ack="actor",
        ),
    ]
