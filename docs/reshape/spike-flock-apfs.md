# Spike: flock-on-APFS

**Date:** 2026-05-11
**Purpose:** Confirm `fcntl.flock` honors exclusive locks across processes on macOS APFS for `events.jsonl`-shaped append workloads.

## Findings Summary

All 3 test cases pass. `fcntl.flock` is reliable for exclusive locking on macOS APFS.

## Test Results

### 1. Exclusive lock prevents interleaved writes (`test_flock_exclusive_prevents_interleaved_writes`)

- **Setup:** Two child processes each do 100 `flock(LOCK_EX)` + append iterations to the same file.
- **Result:** PASSED. All 200 lines are valid JSON. No interleaved lines detected.
- **Verification:** Every line in the output file parses as valid JSON; total line count matches expected 200.

### 2. Blocking lock waits until release (`test_flock_blocks_until_release`)

- **Setup:** P1 acquires `LOCK_EX` and holds for 0.5s. P2 attempts blocking `LOCK_EX`.
- **Result:** PASSED. P2 blocks until P1 releases. Total elapsed time >= 0.4s confirms blocking behavior.
- **Verification:** Both processes complete successfully; P2's completion is gated on P1's release.

### 3. Non-blocking lock fails when held (`test_flock_nonblocking_fails_when_held`)

- **Setup:** P1 acquires `LOCK_EX` and signals. P2 attempts `LOCK_EX | LOCK_NB`.
- **Result:** PASSED. P2's non-blocking acquisition raises `BlockingIOError` (or `OSError`) as expected.
- **Verification:** P2 correctly reports "blocked_as_expected" status.

## Caveats

1. **APFS only:** These tests were run on macOS with APFS. NFS or other network filesystems may not support `flock` reliably. This is acceptable for Astrid's local-first design.
2. **Process-local:** `flock` provides advisory locking between processes on the same host. It does not provide distributed locking across machines.
3. **File descriptor scope:** Locks are released when the file descriptor is closed or the process exits. The `with open(...) as fh:` pattern ensures clean unlock on scope exit.
4. **No deadlock detection:** `flock` does not detect deadlocks. Care must be taken in Sprint 1 to avoid deadlock scenarios (e.g., single lock for events per run is sufficient).

## Stop-Line Assessment

**No stop-line triggered.** `flock` is reliable on macOS APFS. Sprint 1's locked event-append design is viable.

## Reproducibility

Tests are deterministic and repeatable. To re-run:

```bash
pytest tests/spikes/test_flock_apfs.py -v
```

All 3 tests should pass consistently on macOS with APFS.