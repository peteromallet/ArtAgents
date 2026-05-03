# Threads

Threads are the local continuity layer for ArtAgents runs. Each eligible executor
or orchestrator run writes `runs/<slug>/run.json`, and `.artagents/threads.json`
keeps the active thread plus ordered run ids. The index is schema version 1,
locked with `fcntl.flock`, written atomically, and rotated through
`.artagents/threads.json.bak`.

## Model

- A thread is an ordered set of run ids with a label and `open` or `archived`
  status.
- A run records trimmed v1 metadata: run id, thread id, typed
  `parent_run_ids`, redacted CLI args, input and output artifact hashes, brief
  hash, provenance, and local output path.
- Parent edges use `{run_id, kind}` objects. `causal` means the run consumed a
  previous run; `chosen` means it consumed a selected variant.
- Output paths are repo-relative. Private content under `runs/<slug>/private/`
  is represented by hashes and labels only.
- `.artagents/iteration_cache/` stores per-run summaries for iteration videos;
  it is cache state, not thread identity.

## Prefixes

Eligible run commands print thread context before command output:

```text
[thread] <label> . run #<n> . <thread-id>
[variants] <unresolved variant guidance>
Notice: <lifecycle notice>

<command output>
```

The stable order is `[thread]`, optional `[variants]`, optional `Notice:`, then a
blank line. `python3 -m artagents thread show @active` is the source of truth if
the prefix is surprising.

## Privacy & Redaction

`runs/` is local output and should stay out of git. CLI values whose keys look
secret-like, including `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PASSPHRASE`,
`API_KEY`, and `BEARER`, are stored as `***REDACTED***` in run records.

Brief snapshots are plaintext by default when the brief is outside the run's
private directory. To opt into path-based privacy, put sensitive inputs under
`runs/<slug>/private/`; thread records keep hashes and labels without storing
the private path or plaintext. Use:

```bash
python3 -m artagents thread show @active --no-content
```

`--no-content` keeps ids, labels, hashes, status, and structural provenance while
suppressing plaintext brief or prompt content. There is no dedicated brief
privacy flag in v1.

## Concurrent Variant Selection

Variant producers write append-only selection events under
`.artagents/threads/<thread-id>/selections.jsonl` and lock-protected group state
under `.artagents/threads/<thread-id>/groups.json`.

Selections are append-only; the most recent write is authoritative on read;
prior selections are preserved as history but do not affect current keepers.

That rule makes concurrent `thread keep` or `thread dismiss` writes safe. Review
history when two terminals disagree, then write the current keeper explicitly:

```bash
python3 -m artagents thread keep <run-id>:<n>[,<n>]
python3 -m artagents thread dismiss <run-id>:none
```

## Tier Firing Rules

| Tier | Fires when | Action |
| --- | --- | --- |
| `[thread]` | Every eligible run is attributed to a thread. | Confirm the label and id before trusting subsequent output. |
| `[variants]` | A run requested variants or an unresolved variant group exists. | Review outputs and run `thread keep` or `thread dismiss`. |
| `Notice:` | Lifecycle attribution needs attention, such as reopening a selected archived thread. | Read the notice before continuing. |

Warn-style brief novelty, fan-out hints, and health-smell lines are deferred and
are not v1 behavior.

## Inspect Before Render

Before rendering an iteration video, inspect the thread:

```bash
python3 -m artagents.orchestrators.iteration_video.run inspect <thread>
```

Inspect does not render and does not dispatch summarization. It reports detected
modalities, chosen renderers, quality, summary-cache hits and misses, and a
single estimated cost line. Add `--no-content` when inspecting a sensitive
thread.

The render path is:

```text
iteration.prepare -> iteration.assemble -> builtin.render -> finalize
```

`iteration.assemble` writes canonical `iteration.*` files and render-compatible
`hype.timeline.json` plus `hype.assets.json`. `builtin.render` consumes that
exact `hype.*` pair and emits `hype.mp4`; the iteration-video orchestrator then
records `iteration.mp4` with the other four SD-022 outputs.

## Stale Locks

If a command times out waiting for `.artagents/threads.json.lock`, first verify
that no ArtAgents process is still running or writing thread state. After that
process check, remove the stale lock file manually and rerun the command. The
index keeps a `.bak` copy for recovery if a previous write was interrupted.

No lock-repair command ships in v1.

## Deferred

V1 deliberately does not ship these deferred surfaces:

- Thread split, merge, attach, detach, or automatic repair commands.
- Extra renderers beyond `image_grid`, `audio_waveform`, and `generic_card`.
- Cross-modal sub-pursuits or `--mode parallel|interleaved`; v1 is chaptered.
- Natural-language parsing of `--direction`; it is a label only.
- `--why` reasoning output on iteration-video inspect.
- Brief-similarity heuristics, semantic-distance dilation, or browse UI.
- Warn novelty, fan-out hinting, and thread-health smell output.
- `preview_modes`, `host_id`, top-level `chosen_from_groups`, cost ranges,
  latency fields, and formal N-1 migration helpers.

