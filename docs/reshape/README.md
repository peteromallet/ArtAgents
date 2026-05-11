# Sprint 0 — Prerequisites Deliverables

**Branch:** `reshape/sprint-0` (created from `main`)

## Deliverables

| # | Deliverable | File Location |
|---|------------|---------------|
| 1 | Branch | `reshape/sprint-0` |
| 2 | Snapshot script | `scripts/snapshot_astrid_projects.sh` |
| 3 | Inventory script | `scripts/inventory_astrid_projects.py` |
| 4 | Inventory baseline CSV | `docs/reshape/inventory-baseline-YYYYMMDD.csv` |
| 5 | Two-tab harness | `tests/concurrency/two_tab_harness.py` |
| 6 | Harness smoke test | `tests/concurrency/test_two_tab_harness_smoke.py` |
| 7 | Env inheritance spike | `tests/spikes/test_env_inheritance.py` |
| 8 | Env inheritance findings | `docs/reshape/spike-env-inheritance.md` |
| 9 | Flock-on-APFS spike | `tests/spikes/test_flock_apfs.py` |
| 10 | Flock-on-APFS findings | `docs/reshape/spike-flock-apfs.md` |
| 11 | Regression workload | `docs/reshape/regression-workload.md` |

## Snapshot

Run `bash scripts/snapshot_astrid_projects.sh` at the start of each sprint to create a dated tarball at `~/astrid-snapshots/astrid-projects-<timestamp>.tar.gz`.

## Inventory

Run `python3 scripts/inventory_astrid_projects.py` to generate a CSV inventory of all project artifacts. The baseline CSV is at `docs/reshape/inventory-baseline-YYYYMMDD.csv`.

## Tests

```bash
# Two-tab harness smoke test
pytest tests/concurrency/test_two_tab_harness_smoke.py -v

# Env inheritance spike
pytest tests/spikes/test_env_inheritance.py -v

# Flock-on-APFS spike
pytest tests/spikes/test_flock_apfs.py -v

# All Sprint 0 tests
pytest tests/concurrency/ tests/spikes/ -v
```

## Docs

- `docs/reshape/spike-env-inheritance.md` — Results of the env inheritance audit
- `docs/reshape/spike-flock-apfs.md` — Results of the flock-on-APFS spike
- `docs/reshape/regression-workload.md` — Pinned regression workload baseline