# Async Completion — Sprint 3

Two worked examples demonstrating inbox-driven async completion for the
`local` and `manual` adapters. Both patterns rely on the inbox path+version
match introduced in Sprint 3 T10.

---

## Worked example 1: Local adapter — subprocess outlives the tab

### Setup

A leaf step `transcribe` uses the `local` adapter to run a long ffmpeg
transcription. The operator launches it from one terminal tab, closes the tab
mid-run, and resumes from a different tab.

```
$ astrid plan add-step \
    --project my-project \
    --run-id run-1 \
    --step-id transcribe \
    --adapter local \
    --command "ffmpeg -i input.mp4 -vn -acodec pcm_s16le output.wav"
```

```
$ astrid next --project my-project --run-id run-1
step_dispatched: transcribe [local] v1
  pid=12345  started=2026-05-12T07:30:00.000Z
  command: ffmpeg -i input.mp4 -vn -acodec pcm_s16le output.wav
```

### Tab close

The operator closes the terminal tab (or the network drops). The subprocess
survives because `LocalAdapter.dispatch` uses `start_new_session=True` (POSIX
session detach). The child process is not in the parent's process group and
does not receive SIGHUP.

### Re-attach

From a new tab:

```
$ astrid attach my-project
bound session sess-abc to my-project

$ astrid next --project my-project --run-id run-1
```

**What happens:**

1. `cmd_next` resolves the current cursor: `(transcribe, v1, <hash>)`.
2. `astrid next` calls `LocalAdapter.poll(step, run_ctx)`, which reads
   `steps/transcribe/v1/dispatch.json` to find `pid=12345`.
3. `os.kill(12345, 0)` probes whether the process is still alive.
   - If alive: `astrid next` reports `pending` and re-polls on the next call.
   - If dead (ProcessLookupError): the adapter returns `done`.
4. On `done`, `LocalAdapter.complete()` checks:
   - `steps/transcribe/v1/returncode` (written by the subprocess wrapper): 0
   - `steps/transcribe/v1/produces/output.wav` exists and is non-empty.
5. The gate emits `step_completed` and the cursor advances to the next step.

**Key property:** No inbox entry is needed here because the subprocess writes
its results directly to the step directory. The adapter's `poll`/`complete`
methods reconstruct state from those sidecars. The inbox path+version match
is not triggered because the completion is synchronous (same-run, same-session).

---

## Worked example 2: Manual adapter — out-of-band ack via inbox

### Setup

A step `human-review` uses the `manual` adapter. A human reviewer performs the
work in an external tool and submits the result as an inbox entry.

```
$ astrid plan add-step \
    --project my-project \
    --run-id run-1 \
    --step-id human-review \
    --adapter manual \
    --command "Review the generated clips at http://localhost:8080/review" \
    --requires-ack
```

```
$ astrid next --project my-project --run-id run-1
step_dispatched: human-review [manual] v1
  command: Review the generated clips at http://localhost:8080/review
  dispatch payload: runs/run-1/steps/human-review/v1/dispatch.json
```

The operator reads `dispatch.json`, performs the review, and produces a
completion payload.

### Inbox submission

The reviewer (or an external agent) writes a completion entry into
`runs/run-1/inbox/`:

```json
{
  "schema_version": 2,
  "plan_step_path": ["human-review"],
  "step_version": 1,
  "status": "completed",
  "source": "inbox",
  "submitted_by": "reviewer-bot",
  "submitted_by_kind": "agent",
  "payload": {
    "decision": "approved",
    "notes": "All clips look correct."
  }
}
```

**Critical:** `submitted_by` and `submitted_by_kind` are **required** for
inbox-driven completion. Without them, the `ManualAdapter.complete()` method
rejects the entry and moves it to `.rejected/`.

### Consume

The operator (or `astrid next` in auto-consume mode) picks up the inbox entry:

```
$ astrid next --project my-project --run-id run-1
```

**What happens:**

1. `scan_inbox` finds the entry in `inbox/`.
2. `_parse_entry` validates `schema_version:2` + `plan_step_path` +
   `step_version`.
3. `consume_inbox_entry` matches `(plan_step_path, step_version)` against the
   cursor's current step.
   - Match: `("human-review", 1)` → entry is applied.
   - Mismatch: entry stays in `inbox/` for the next consumer.
   - Stale (tombstoned or fully-superseded step): entry moves to
     `.rejected/<sha256>`.
4. The gate writes `produces/completion.json` to
   `steps/human-review/v1/produces/`.
5. `ManualAdapter.complete()` reads the sidecar, verifies identity
   (`submitted_by_kind` must be `"agent"` or `"actor"`), and returns
   `CompleteResult(status="completed")`.
6. The gate emits `step_completed` and the cursor advances.

### Equivalent ack-driven path

The same `completion.json` format works when the completion arrives via
`astrid ack` instead of the inbox:

```
$ astrid ack human-review --project my-project --run-id run-1 \
    --agent reviewer-bot --decision approve
```

`cmd_ack` writes the same `produces/completion.json` sidecar. The adapter
reads it identically regardless of whether the source was `ack` or `inbox`.

---

## Inbox destinations (stop-line guarantee)

Every inbox entry lands in exactly one of:

| Destination | Reason |
|---|---|
| `inbox/` | Entry matches cursor; waiting for `consume_inbox_entry` |
| `.consumed/<sha256>` | Entry was successfully consumed and applied |
| `.rejected/<sha256>` | Entry is stale, malformed, or missing required identity |

There is no code path that silently drops an entry. The stop-line from the
Sprint 3 brief ("no entry vanishes silently") is enforced by the `scan_inbox`
→ `consume_inbox_entry` pipeline: every recognized JSON file is either
consumed, rejected, or left in place for a later consumer.