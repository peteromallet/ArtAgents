"""Sprint 9 Phase 6 Step 12 — public id resolution parity.

Verifies that every public id flagged as "at risk" during the Sprint 9
migration still resolves through the default executor / orchestrator
registries. The Step 9.0 `qualified_id` regex relaxation made it possible to
keep every existing id (notably the 3-segment `external.runpod.*` and
`external.vibecomfy.*` ids), so no aliases were introduced. This test is the
parity guard for that decision.

See `docs/git-backed-packs/sprint-09/migration-aliases.md`.
"""

from __future__ import annotations

import pytest

from astrid.core.executor.registry import (
    load_default_registry as load_executor_registry,
)
from astrid.core.orchestrator.registry import (
    load_default_registry as load_orchestrator_registry,
)


# The six 3-segment ids that survive only because the qualified_id regex was
# relaxed in Step 9.0. These are the load-bearing cases for this test.
PRESERVED_EXECUTOR_IDS = [
    "external.runpod.provision",
    "external.runpod.exec",
    "external.runpod.teardown",
    "external.runpod.session",
    "external.vibecomfy.run",
    "external.vibecomfy.validate",
    # One canonical 2-segment id per remaining pack — sanity checks that the
    # regex relaxation did not regress the common case either.
    "builtin.asset_cache",
    "iteration.prepare",
    "upload.youtube",
    "seinfeld.aitoolkit_stage",
]

# One canonical orchestrator per pack that ships orchestrators.
PRESERVED_ORCHESTRATOR_IDS = [
    "builtin.hype",
    "seinfeld.lora_train",
]


@pytest.fixture(scope="module")
def executor_registry():
    return load_executor_registry()


@pytest.fixture(scope="module")
def orchestrator_registry():
    return load_orchestrator_registry()


@pytest.mark.parametrize("public_id", PRESERVED_EXECUTOR_IDS)
def test_preserved_executor_id_resolves(public_id, executor_registry):
    executor = executor_registry.get(public_id)
    assert executor is not None, f"{public_id!r} did not resolve"
    assert executor.id == public_id
    # And the first segment still matches its owning pack, i.e. no silent
    # rename slipped through the migration.
    assert executor.metadata.get("source_pack") == public_id.split(".", 1)[0]


@pytest.mark.parametrize("public_id", PRESERVED_ORCHESTRATOR_IDS)
def test_preserved_orchestrator_id_resolves(public_id, orchestrator_registry):
    orchestrator = orchestrator_registry.get(public_id)
    assert orchestrator is not None, f"{public_id!r} did not resolve"
    assert orchestrator.id == public_id
    assert (
        orchestrator.metadata.get("source_pack") == public_id.split(".", 1)[0]
    )
