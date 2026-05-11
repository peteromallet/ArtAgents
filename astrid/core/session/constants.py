"""Session-layer tunables.

These are module-level constants (not Enum members) so tests can monkeypatch
them via ``monkeypatch.setattr`` if a scenario needs different thresholds.
"""

from __future__ import annotations

# A session that has not written an event in this many seconds AND whose
# session-file mtime is older than ``STUCK_SESSION_MTIME_SECONDS`` is flagged
# by ``astrid status`` as suspected-dead. Defaults picked honestly: 60s
# allows for slow human review; 5min is well above any normal verb runtime.
STUCK_NO_EVENT_SECONDS: int = 60
STUCK_SESSION_MTIME_SECONDS: int = 300
