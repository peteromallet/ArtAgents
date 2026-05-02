from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path


if "ARTAGENTS_TIMELINE_COMPOSITION_SRC" not in os.environ:
    _package_src = Path(tempfile.mkdtemp(prefix="artagents-timeline-composition-src-"))
    os.environ["ARTAGENTS_TIMELINE_COMPOSITION_SRC"] = str(_package_src)
    atexit.register(lambda: shutil.rmtree(_package_src, ignore_errors=True))
