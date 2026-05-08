"""T19: astrid author explain produces a natural-language description that
mentions step ids, kinds (code/attested/nested), repeat semantics
(repeat.until.condition / max_iterations / on_exhaust), and rewind-on-failure
language. Useful for LLMs verifying their compiled plan matches a request.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from astrid.orchestrate import cli as author_cli


_INNER = '''from astrid.orchestrate import orchestrator, code
@orchestrator("demo.inner")
def inner(): return [code("inner_step", argv=["echo","x"])]
'''

_APP = '''from astrid.orchestrate import orchestrator, code, attested, repeat_until, nested
@orchestrator("demo.app")
def app(): return [
    code("transcribe", argv=["echo","t"]),
    attested("review", command="review.sh", instructions="please review", ack="actor",
             repeat=repeat_until(condition="user_approves", max_iterations=3, on_exhaust="fail")),
    nested("delegate", plan="demo.inner"),
]
'''


def test_author_explain_covers_code_attested_nested_repeat_until(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    pack = packs / "demo"
    pack.mkdir(parents=True)
    (pack / "inner.py").write_text(_INNER, encoding="utf-8")
    (pack / "app.py").write_text(_APP, encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = author_cli.main(["explain", "demo.app"], packs_root=packs)
    assert rc == 0
    out = buf.getvalue()
    # All step ids appear (including nested children).
    for sid in ("transcribe", "review", "delegate", "inner_step"):
        assert sid in out, f"explain output missing step id `{sid}`"
    # All three kinds are mentioned.
    for kind in ("code", "attested", "nested"):
        assert kind in out, f"explain output missing kind `{kind}`"
    # Repeat.until semantics.
    assert "repeat.until.condition" in out
    assert "user_approves" in out
    assert "max_iterations=3" in out
    assert "on_exhaust='fail'" in out
    # Rewind-on-failure language.
    assert "rewinds" in out
    # Iteration loop language ("iteration_failed and the next `next` enters iteration N+1").
    assert "iteration_failed" in out
