from __future__ import annotations

import pytest

from astrid.threads import cli
from astrid.threads.variants import SELECTION_SENTENCE


def test_keep_help_documents_append_only_selection_semantics(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["keep", "--help"])
    assert exc.value.code == 0
    assert SELECTION_SENTENCE in capsys.readouterr().out
