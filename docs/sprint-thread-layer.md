# Sprint Plan: Thread / Variant / Iteration-Video Layer

## Executive Summary

This is a focused 10-working-day sprint to ship the Astrid thread, variant, and iteration-video layer.

The sprint goal is one usable loop: every executor/orchestrator run is stamped into a thread, sibling variants can be kept or dismissed, and an agent can render a 60-second iteration video that explains how a finished artifact came together.

The target demo fixture is `runs/astrid_logo_v3`.

Week 1 ships the data layer.

Week 2 ships the iteration-video MVP.

The irreversible work is SD-008: once agents start producing post-sprint runs, each run either has complete metadata or it does not, forever.

That is why the wrapper, schema, redaction, artifact hashing, variant grouping, and brief snapshotting land before any video polish.

Scope-in for v1 includes the SD-035 sprint phasing, the SD-041 privacy/redaction policy, SD-042 concurrent variant selection semantics, and the SD-043 cost guardrail.

Scope-in for renderers is exactly three modality renderers from SD-035: `image_grid`, `audio_waveform`, and `generic_card`.

Scope-in for v1 data shapes is trimmed by `## Deferred for v1 (Trimmed Scope)` below: the killer demo and privacy guarantees remain, while low-return agent-facing complexity is deferred.

The SD-036 scope-out list is explicit: thread split/merge/attach/detach and automatic lock repair are out, with only `backfill` in v1; 4 of 7 modality renderers (`video_pip`, `text_diff`, `model_turntable`, `code_scroll`); cross-modal sub-pursuits and `--mode parallel|interleaved`; `--direction` natural-language parsing with the flag accepted as label-only; `--why` reasoning surface on `iteration_video inspect`; `thread doctor` auto-fix suggestions; `cut --variants N`; brief-similarity heuristics and semantic-distance dilation; human-facing browse UI for threads.

The v1 trim further defers the `thread doctor` detection-only smell line, `[hint]` fan-out line, Warn brief-novelty tier, `preview_modes`, `host_id`, low/high cost ranges, and formal N-1 schema migration machinery.

Critical path: Day 1 atomic index and IDs -> Day 2 wrapper/schema/CLI plumbing with Frozen Schema Review -> Day 3 attribution/prefix/agent docs -> Day 4 lifecycle/reaper/variants -> Day 5 brief/provenance/backfill/docs -> Days 6-9 iteration prepare/assemble/orchestrator -> Day 10 dogfood demo.

Top risk 1 is schema churn after Day 2; mitigation is the Frozen Schema Review gate: any post-Day-2 field change requires explicit review and a same-PR compatibility plan before merge.

Top risk 2 is lock contention under parallel runs; mitigation is `fcntl` locking with a 30-second timeout and stale-lock guidance that tells the user to verify no Astrid writer is active before manual lock-file removal. No lock-repair command ships in v1.

Top risk 3 is iteration summarization cost or rate pressure; mitigation is `ARTAGENTS_SUMMARIZE_CONCURRENCY` defaulting to 4, exponential backoff per `builtin.understand` call, SD-043 summary cache, and a hard `max_iterations` cap inside `iteration.prepare`.

Definition of done: all post-wrapper runs have v1 metadata, the week-1 SD-037 coverage is green as trimmed, full pytest is green, `runs/astrid_logo_v3` renders all five SD-022 outputs, `--no-content` works for thread/report views, and the Day-10 demo checklist is signed.

SD-041 redaction: `runs/` remains local and gitignored, secret-like CLI values are replaced with `***REDACTED***`, `runs/<slug>/private/` artifacts are sha-only, and `--no-content` suppresses plaintext in `thread show` and the iteration report.

SD-042 selection semantics: selections are append-only; the most recent write is authoritative on read; prior selections remain history but do not affect current keepers.

SD-043 cost guardrail: `iteration.prepare` refuses above `max_iterations`, caches summaries by `(run_id, summarizer_model_version)`, and `iteration_video inspect` prints estimated cost before render.

Agent UX surface: v1 intentionally keeps stdout predictable: `[thread]` every run, `[variants]` only for unresolved variants, optional `Notice:`, then command output after one blank separator.

Day-10 demo: produce a 60-second `iteration.mp4` against `runs/astrid_logo_v3`, screen-share it, verify the report and quality JSON, and capture stdout proving every run showed the correct `[thread]` prefix before render.

## Deferred for v1 (Trimmed Scope)

These deferrals are part of this sprint plan, not follow-up suggestions. They reduce agent-facing surface area while preserving the demo, data quality, and privacy guarantees.

- **DEF-1 — Warn tier brief-novelty.** Ship Notice tier only in v1; defer brief-novelty Warn heuristics until there is a real corpus for threshold tuning.
- **DEF-2 — `[thread-health]` smell line on `thread list`.** Defer this parseable nudge; the underlying data still exists for later detection.
- **DEF-3 — `[hint]` line for sequential same-executor fan-out.** Defer the soft nudge to avoid another stdout format in v1.
- **DEF-4 — Four `role` values trimmed to two.** Ship `role: variant` and `role: other` with `other` as the default; finer role vocabulary waits for a consumer.
- **DEF-5 — `preview_modes` array on `output_artifacts`.** Drop in v1; dispatch by `kind` is enough for the three renderers.
- **DEF-6 — `chosen_from_groups` top-level edge.** Collapse chosen edges into typed `parent_run_ids` entries: `{run_id, kind: "causal" | "chosen", group?}`.
- **DEF-7 — Four iteration-video executors collapsed to two.** Ship `iteration.prepare` and `iteration.assemble`; `prepare` owns collect, summarize, score, quality, cap, and cache.
- **DEF-8 — `external_service_calls` six fields trimmed to three.** Keep `model`, `model_version`, and `request_id`; defer `seed`, `cost_usd`, and `latency_ms`.
- **DEF-9 — Cost block low/high range and recommendation triplet trimmed to one estimate.** Print `Estimated cost: ~$0.42 (47 calls x $0.009)` style output.
- **DEF-10 — `host_id` field.** Drop until cross-machine sync has a real consumer.

Schema-versioning machinery is also trimmed: keep `schema_version: 1` on persisted records, but drop the formal N-1 reader, migration helper, and migration `.bak` test from v1. Atomic index writes still rotate `.bak` because that is correctness, not migration machinery.

## Settled Decisions

- **SD-001** — Use the noun `thread` everywhere user/agent-facing. _load_bearing: true_
- **SD-002** — Keep `runs/` flat; thread membership is metadata, never folder movement. _load_bearing: true_
- **SD-003** — Store the thread map in `.astrid/threads.json` with `fcntl` lock, atomic replace, and `.bak` rotation. _load_bearing: true_
- **SD-004** — Use 26-character Crockford ULIDs for `run_id`, `thread_id`, and `group_id`. _load_bearing: true_
- **SD-005** — `parent_run_ids` records plural causal ancestry, not temporal previous-run order. _load_bearing: true_
- **SD-006** — Auto-attribute under lock with explicit thread, lineage inference, active open thread, reopen window, then new thread. _load_bearing: true_
- **SD-007** — Thread lifecycle is `open -> archived -> (re)open` with lazy enforcement and no daemon. _load_bearing: true_
- **SD-008** — Write a v1 `run.json` for every eligible run; this plan applies the DEF trims to the field set. _load_bearing: true_
- **SD-009** — Snapshot briefs to `brief.copy.txt` and stamp `brief_content_sha256`. _load_bearing: true_
- **SD-010** — Capture external model provenance; v1 keeps `model`, `model_version`, and `request_id` per DEF-8. _load_bearing: true_
- **SD-011** — Resolve consumed input artifacts to producer run IDs at consumption time. _load_bearing: true_
- **SD-012** — `host_id` is deferred for v1 per DEF-10. _load_bearing: false_
- **SD-013** — Variants are opt-in; v1 uses `role: variant | other`, default `other`, per DEF-4. _load_bearing: true_
- **SD-014** — Selection state is append-only thread state in `selections.jsonl`. _load_bearing: true_
- **SD-015** — Curatorial chosen edges are preserved; v1 stores them as typed `parent_run_ids` entries per DEF-6. _load_bearing: true_
- **SD-016** — Maintain denormalized `groups.json` for variant lookup. _load_bearing: true_
- **SD-017** — Keep the five variant gestures and make keep/dismiss mandatory when variants exist. _load_bearing: true_
- **SD-018** — Emit runner prefix lines to stdout before command output; v1 trims line classes to `[thread]`, `[variants]`, and `Notice:`. _load_bearing: true_
- **SD-019** — Add the provenance block to `hype.metadata.json`. _load_bearing: true_
- **SD-020** — Ship one polymorphic `builtin.iteration_video` orchestrator. _load_bearing: true_
- **SD-021** — Reuse `builtin.render`; v1 collapses new iteration work into `iteration.prepare` and `iteration.assemble`, and `assemble` writes the render adapter files per DEF-7. _load_bearing: true_
- **SD-022** — Emit the five iteration-video outputs as one variant group. _load_bearing: true_
- **SD-023** — Default ancestry is provenance-graph, with report labels for in-thread versus pulled-by-ancestry runs. _load_bearing: true_
- **SD-024** — Enforce `data_quality` floor 0.6 unless `--force` is used and logged. _load_bearing: true_
- **SD-025** — Add the `ModalityRenderer` registry. _load_bearing: true_
- **SD-026** — V1 dispatches renderers by artifact `kind`; `preview_modes` is deferred per DEF-5. _load_bearing: true_
- **SD-027** — Keep the iteration-video gesture surface small; `inspect` is the primary discovery command. _load_bearing: true_
- **SD-028** — Select audio bed automatically; never generate music. _load_bearing: true_
- **SD-029** — Always provide loud `generic_card` fallback for unknown modalities. _load_bearing: true_
- **SD-030** — Integrate only at executor/orchestrator chokepoints, with documented no-op gates. _load_bearing: true_
- **SD-031** — Patch only `generate_image` and `logo_ideas` to opt into variants. _load_bearing: true_
- **SD-032** — Use `xxhash` for `inputs_digest` and `sha256` for output artifact integrity. _load_bearing: true_
- **SD-033** — Run the in-flight reaper lazily once per process. _load_bearing: true_
- **SD-034** — Preserve backwards compatibility and provide `thread backfill`. _load_bearing: true_
- **SD-035** — Week 1 is data; Week 2 is iteration-video MVP with exactly three renderers. _load_bearing: true_
- **SD-036** — Keep the sprint cuts out of scope. _load_bearing: true_
- **SD-037** — Ship the required week-1 coverage, adjusted only where DEF trims remove features. _load_bearing: true_
- **SD-038** — Add `docs/threads.md`, the SKILL.md paragraph, and inspect footers; do not edit per-tool `STAGE.md`. _load_bearing: true_
- **SD-039** — Keep `schema_version` fields; formal N-1 migration machinery is trimmed from v1. _load_bearing: true_
- **SD-040** — Persist only repo-relative or content-addressed paths. _load_bearing: true_
- **SD-041** — Ship privacy/redaction and `--no-content` surfaces. _load_bearing: true_
- **SD-042** — Document append-only, last-write-wins selection semantics for agents. _load_bearing: true_
- **SD-043** — Ship the iteration-video cost guardrail before render. _load_bearing: true_
- **SD-044** — Preserve recorded tradeoffs for future readers, not as sprint constraints. _load_bearing: false_

## Hard Constraints (from design)

### Week 1: Data Layer

- **Day 1** lands SD-001, SD-002, SD-003, SD-004, SD-032, SD-039, and SD-040: thread naming, flat `runs/` with metadata, locked atomic index, ULIDs, hash strategy, `schema_version: 1`, and repo-relative paths.
- **Day 2** lands the irreversible SD-008 wrapper/schema core and SD-030 chokepoint integration: eligible executor/orchestrator runs begin/finalize records, no-op gates stay safe, `upload.youtube` remains a zero-artifact no-op, and the Frozen Schema Review closes the day.
- **Day 2** also starts SD-041 by redacting secret-like CLI values to `***REDACTED***` and treating `runs/<slug>/private/` as sha-only.
- **Day 3** lands SD-006, SD-018, and the Day-3 pieces of SD-038: auto-attribution with lineage inference, stdout prefix lines, SKILL.md guidance, and active-thread inspect footers.
- **Day 3** carries the agent-UX stability rule: prefix output is stdout-only, ordered, and treated as a public CLI contract governed by `schema_version`.
- **Day 4** lands SD-007, SD-013, SD-014, SD-015, SD-016, SD-017, SD-031, SD-033: lifecycle tail, lazy reaper, v1 variant schema, append-only selections, typed chosen edges, groups index, variant gestures, and the two allowed producer patches.
- **Day 5** lands SD-009, SD-019, SD-034, and the long-form part of SD-038: brief snapshotting, provenance block in `hype.metadata.json`, `thread backfill`, and `docs/threads.md`.
- **Fail-closed reminder**: the default output artifact role is `other` in v1; only `astrid/packs/builtin/generate_image/run.py` and `astrid/packs/builtin/logo_ideas/run.py` opt into `role: variant` per SD-031 and DEF-4. No other executor `run.py` is modified.

### Week 2: Iteration Video MVP

- **Day 6** lands SD-023, SD-024, SD-025, and the first v1 half of SD-021: modality registry, exactly three renderers, provenance-graph collection, and `data_quality` inside `iteration.prepare`.
- **Day 6** also starts SD-043 inside `iteration.prepare`: count candidate runs before dispatch, honor `max_iterations`, and prepare cache keys.
- **Day 7** completes the SD-021 `iteration.prepare` work: summarization through `builtin.understand`, scoring, cache writes, cost-cap refusal, and deterministic ordering.
- **Day 8** lands SD-026, SD-027, SD-028, and SD-029 inside `iteration.assemble`: v1 kind-based renderer dispatch, direction as label-only, chaptered mode only, automatic audio-bed selection, and loud `generic_card` fallback.
- **Day 9** lands SD-020, SD-022, and the orchestrator surface of SD-043: `builtin.iteration_video`, the five output artifacts, `iteration_video inspect`, estimated cost, and `--no-content` report behavior.
- **Day 10** lands SD-035 acceptance: dogfood against `runs/astrid_logo_v3`, full integration pass, 60-second demo render, and observable failure-mode checks.
- **Sprint cuts**: SD-036 remains out of scope in full, and DEF-1 through DEF-10 are explicitly not implemented in this sprint.

## Open Question Resolutions

- **OQ-1: Day-by-day allocation.** Resolved by the Week 1 and Week 2 sections: Days 1-5 are data, Days 6-10 are iteration video, with Day 2 as the schema freeze and Day 10 as the demo gate.
- **OQ-2: Summarization parallelism.** Use `ThreadPoolExecutor(max_workers=int(os.environ.get("ARTAGENTS_SUMMARIZE_CONCURRENCY", "4")))` inside the summarize phase of `iteration.prepare`, with exponential backoff per `builtin.understand` call. Keep `ARTAGENTS_SUMMARIZE_SEQUENTIAL=1` as an implementation/debug fallback if rate limits or local determinism require it.
- **OQ-3: Prefix format.** Width is `min(120, $COLUMNS)` when `$COLUMNS` is available, otherwise 120. ANSI color is allowed only when stdout is a TTY and `NO_COLOR` is unset. Labels truncate to 32 display characters; IDs are never truncated. All prefix lines stream to stdout before command output. V1 order is `[thread] -> [variants] -> Notice: -> blank line -> command output`; `[hint]` and `Warn:` are deferred by DEF-3 and DEF-1. Format stability is governed by `schema_version` and the Definition of Done.
- **OQ-4: Reaper timing.** Run the SD-033 in-flight reaper lazily on first index read per process. It is not a daemon and not a per-command directory walk after the first read.
- **OQ-5: Global documentation location.** Use `docs/threads.md` for the long-form reference. Day 3 lands a short stub explaining the prefix; Day 5 expands privacy, selection semantics, tier firing rules, inspect-before-render, and deferred features.
- **OQ-6: Quality floor formula.** `data_quality = 0.5*parent_capture_score + 0.3*has_brief_sha + 0.2*has_resolved_input_artifact`, where `parent_capture_score = (runs_with_parents + valid_roots)/total_runs` and `valid_root iff input_artifacts==[]`. The floor is 0.6. Refusal reports name only unresolved-producer runs; valid roots are not penalized and are never listed as missing lineage.

## Week 1: Data Layer (Days 1-5)

Week 1 ships the irreversible record layer. By end of Day 5, every eligible run after the wrapper lands writes v1 metadata, variants are selectable, briefs are snapshotted, provenance is embedded into the hype pipeline, and the agent-facing docs explain the stdout prefix before agents rely on it.

### Day 1

**Goal**

Build the thread-state foundation before touching the executor/orchestrator chokepoints.

**Deliverables**

- Add `astrid/threads/ids.py` with monotonic, 26-character Crockford ULID generation for `run_id`, `thread_id`, and `group_id`.
- Add `astrid/threads/schema.py` with `schema_version: 1` constants and typed v1 shapes for `threads.json`, `run.json`, `selections.jsonl`, `groups.json`, and the provenance block.
- Apply the v1 schema-versioning trim: keep `schema_version` fields, but do not build the formal N-1 reader, migration helper, or migration `.bak` test in this sprint.
- Add `astrid/threads/index.py` for `.astrid/threads.json` with a sidecar lock file, `fcntl.flock`, a 30-second acquire timeout, tmp-write + fsync + directory fsync + `os.replace`, and rotated `.bak`.
- On lock timeout, emit actionable guidance to verify no Astrid writer is active before manually removing a stale lock file. Do not name or ship a lock-repair command in v1.
- Enforce repo-relative or content-addressed paths for all persisted JSON; reject absolute paths at schema/write boundaries.
- Append `xxhash>=3.4` to `requirements.txt` for fast `inputs_digest` computation.

**SDs landed**

SD-001, SD-002, SD-003, SD-004, SD-032, SD-039 as trimmed, SD-040.

**Acceptance**

- `.astrid/threads.json` is created on first write with `schema_version: 1`, `threads`, and `active_thread_id`.
- A simulated partial write recovers from `.bak` without losing the previous index.
- Eight parallel writers can allocate distinct run/thread IDs and update the index without lost writes.
- A stuck lock owner produces a timeout after 30 seconds and the error text explains safe manual stale-lock remediation without naming a repair command.
- Persisted paths in the index test fixture are repo-relative or content-addressed; an absolute path fixture fails validation.
- `python3 -c "import xxhash"` succeeds in the test environment after installing requirements.

**Tests**

- `tests/test_threads_index.py`: schema creation, lock acquisition, atomic replace, `.bak` recovery, timeout message, and no lost updates under concurrent writers.
- `tests/test_threads_dependencies.py`: `xxhash` importability and requirements declaration.

### Day 2

**Goal**

Put the v1 run record behind the single executor/orchestrator chokepoints and freeze the schema before broader feature work continues.

**Deliverables**

- Add `astrid/threads/record.py` for begin/finalize record construction.
- Add `astrid/threads/wrapper.py` with `threads.begin(request)` and `threads.finalize(record_id, result)` helpers.
- Modify `ExecutorRunRequest` at `astrid/core/executor/runner.py:43` and the orchestrator run request equivalent to carry `thread`, `variants`, and `from_variant`.
- Add `--thread <id|@new|@none>`, `--variants N`, and `--from <run-id>:<n>` to both `python3 -m astrid executors run ...` and `python3 -m astrid orchestrators run ...`.
- Wrap `run_executor()` at `astrid/core/executor/runner.py:75` and the orchestrator-runner equivalent with begin/finalize.
- Preserve all SD-030 no-op gates: `dry_run=True`, unwritable output, output under `tempfile.gettempdir()`, `request.thread == "@none"`, and `ARTAGENTS_THREADS_OFF=1`.
- Leave the `upload.youtube` short-circuit at `astrid/core/executor/runner.py:78` untouched; verify it produces zero thread artifacts and zero errors.
- Write the trimmed SD-008 v1 `run.json` fields: `schema_version`, `run_id`, `thread_id`, typed `parent_run_ids[]`, `executor_id`, `orchestrator_id`, `kind`, `started_at`, `ended_at`, `returncode`, `out_path`, `cli_args_redacted`, `agent_version`, `brief_content_sha256`, `inputs_digest`, `input_artifacts[]`, `output_artifacts[]`, `external_service_calls[]`, and `starred`.
- Use typed `parent_run_ids` entries for both causal and chosen edges: `{run_id, kind: "causal"}` and `{run_id, kind: "chosen", group: "..."}`. Do not add top-level `chosen_from_groups` in v1.
- Keep `external_service_calls` to three fields per DEF-8: `model`, `model_version`, and `request_id`.
- Drop `host_id` from Day 2 and from the v1 schema per DEF-10.
- Resolve `input_artifacts[*].produced_by_run_id` at consumption time by matching artifact sha256 against known output artifacts.
- Compute `inputs_digest` with `xxhash` and compute `output_artifacts[*].sha256` at finalize time without blocking mid-run.
- Broaden `cli_args_redacted`: any argv key matching case-insensitive `(KEY|TOKEN|SECRET|PASSWORD|PASSPHRASE|API_?KEY|BEARER)` has its value replaced with literal `***REDACTED***`.
- Treat paths under `runs/<slug>/private/` as opaque: record sha256 and labels only, with `kind: private` where applicable.
- Specify the v1 prefix-line ordering contract even though implementation lands Day 3: stdout only, `[thread]`, then `[variants]` when present, then `Notice:` when present, then one blank separator line, then command output.
- End the day with the Frozen Schema Review checkpoint.

**SDs landed**

SD-008 as trimmed, SD-010 as trimmed, SD-011, SD-030, SD-032, SD-041 redaction base, SD-043 unaffected but unblocked by metadata.

**Acceptance**

- `executors run` and `orchestrators run` both accept and pass through `--thread`, `--variants`, and `--from`.
- Eligible executor runs write `run.json`, update `.astrid/threads.json`, and finalize `ended_at` and `returncode`.
- Eligible orchestrator runs write the same v1 metadata through the orchestrator chokepoint.
- `ARTAGENTS_THREADS_OFF=1` produces no thread artifacts and no errors.
- `--thread @none` produces no thread artifacts and no errors.
- `upload.youtube` produces zero thread artifacts and zero errors.
- Secret-like CLI values are redacted to exactly `***REDACTED***`.
- `runs/<slug>/private/` content is represented by sha/label metadata only.
- The prefix-ordering test fixture reflects the trimmed v1 order: `[thread] -> [variants] -> Notice: -> blank line -> command output`.
- **Frozen Schema Review:** `schema_version=1` is frozen at end of Day 2. Any field addition, removal, or rename after end-of-Day-2 requires explicit sprint-lead review and a same-PR compatibility note before merge. Formal N-1 migration machinery remains deferred by the v1 trim.

**Tests**

- `tests/test_threads_record.py`: begin/finalize, required fields, returncode finalization, sha handling, and typed `parent_run_ids`.
- `tests/test_threads_cli_plumbing.py`: executor and orchestrator run flags populate request fields.
- `tests/test_threads_redaction.py`: KEY/TOKEN/SECRET/PASSWORD/PASSPHRASE/API_KEY/BEARER-class argv values become `***REDACTED***`.
- `tests/test_threads_upload_youtube_noop.py`: `upload.youtube` bypass creates no artifacts and raises no thread-layer error.
- `tests/test_threads_line_ordering.py`: synthesized prefix block uses stdout and the trimmed v1 order.

### Day 3

**Goal**

Make thread attribution visible and explainable to agents the same day it appears in command output.

**Deliverables**

- Add `astrid/threads/attribute.py` with the five-branch SD-006 decision function, evaluated at run start under the index lock:
  1. explicit `--thread <id>` / `@new` / `@none` wins;
  2. lineage inference scans input-like args for `runs/<R>/` and inherits `R`'s thread;
  3. open active thread joins;
  4. archived active thread within `IDLE_REOPEN_WINDOW` reopens and joins;
  5. otherwise create a new thread.
- Add `astrid/threads/prefix.py` for v1 stdout prefix lines per SD-018 and OQ-3.
- Ship Notice tier only per DEF-1. Notice fires on first run of process, gap greater than 1 hour, cwd change, and auto-reopen of archived thread. Warn brief-novelty is deferred.
- Add `python3 -m astrid thread new`, `thread list`, and `thread show` CLI.
- Add `thread show @active --no-content` for SD-041.
- Do not add `[thread-health]` smell lines on `thread list`; DEF-2 defers that output format.
- Modify `_run_external_executor` at `astrid/core/executor/runner.py:258` to thread `ARTAGENTS_THREAD_ID` into the subprocess env when present, so external executor processes inherit the parent thread without re-stamping.
- Child wrappers skip begin when `ARTAGENTS_THREAD_ID` is set and instead attach to the parent context.
- Append this exact SKILL.md paragraph:

  > At the start of any session that will produce runs, run python3 -m astrid thread show @active first. The [thread] prefix on every command output is your continuous indicator; if it shows the wrong thread, run thread new or pass --thread @new to your next command. Selections are append-only; the most recent write is authoritative on read; prior selections are preserved as history but do not affect current keepers.

- Add a Day-3 `docs/threads.md#what-the-prefix-means` stub explaining `[thread]`, `[variants]`, `Notice:`, the blank-line separator, and `--no-content`.
- Add a footer line to `executors inspect` and `orchestrators inspect` output naming the active thread and pointing to `python3 -m astrid thread show @active`.
- Add an adjacent docs/SKILL note, outside the exact paragraph, that agents should run `iteration_video inspect <thread>` before render once the Week 2 orchestrator exists.
- Risk-day cut-list if Day 3 slips past 6pm: defer rich `thread list` columns first, then defer the docs/threads prefix stub to a minimal three-line stub. Auto-attribute, prefix output, nested-env propagation, SKILL.md paragraph, and inspect footers are never cut.

**SDs landed**

SD-006, SD-018 as trimmed, SD-038 Day-3 pieces, SD-041 `thread show --no-content`, SD-042 agent-facing sentence.

**Acceptance**

- The five auto-attribution branches are covered with a frozen clock.
- Lineage inference wins over the active pointer when any input-like arg points into `runs/<R>/`.
- `[thread]` appears on stdout before command output for every eligible `executors run` and `orchestrators run`.
- `Notice:` appears only for the v1 Notice triggers.
- No `Warn:` line is produced by v1 brief-novelty logic because that logic is deferred.
- `thread show @active --no-content` emits IDs, labels, hashes, and status without plaintext brief/prompt content.
- External executor subprocesses inherit `ARTAGENTS_THREAD_ID` and do not create duplicate begin records.
- SKILL.md contains the exact paragraph above.
- `executors inspect` and `orchestrators inspect` show the active-thread footer.

**Tests**

- `tests/test_threads_attribute.py`: all five branches, lineage precedence, reopen window, and frozen-clock behavior.
- `tests/test_threads_prefix.py`: stdout placement, width/truncation behavior, color gating, and v1 Notice triggers.
- `tests/test_threads_nested.py`: parent-to-child inheritance and skip-begin behavior when `ARTAGENTS_THREAD_ID` is set.
- `tests/test_threads_skill_md_text.py`: exact SKILL.md paragraph match.
- `tests/test_threads_no_content.py`: `thread show @active --no-content` suppresses plaintext.

### Day 4

**Goal**

Complete lifecycle commands and variants without expanding the agent-facing surface beyond the five SD-017 gestures.

**Deliverables**

- Add `python3 -m astrid thread archive` and `thread reopen` in the morning carryover slot.
- Implement SD-007 lifecycle windows: `IDLE_ARCHIVE_WINDOW=7d` and `IDLE_REOPEN_WINDOW=48h`, lazy enforcement on read, no daemon.
- Implement SD-033 in-flight reaper lazily on first index read per process. It scans `runs/*/run.json` for `ended_at: null` records whose stamped owner PID is gone and marks them `returncode: -1`, `ended_at: <now>`, and `status: "orphaned"`.
- Extend `output_artifacts` with v1 variant fields: `role`, `group`, `group_index`, `duration`, and `variant_meta`.
- Use the trimmed role enum per DEF-4: `role: "variant" | "other"`, defaulting to `other`.
- Do not add `preview_modes`; DEF-5 defers it and Week 2 dispatches by `kind`.
- Add `astrid/threads/selections.py` to append selection events to `.astrid/threads/<thread-id>/selections.jsonl` with line-buffered atomic appends and no fcntl lock per SD-042.
- Add `astrid/threads/groups.py` to maintain denormalized `.astrid/threads/<thread-id>/groups.json`.
- Store chosen variant consumption as typed entries in `parent_run_ids`, not top-level `chosen_from_groups`, per DEF-6.
- Add `thread keep <run-id>:<n>[,<n>]`, `thread keep <run-id>:none`, and `thread group <run-id> <run-id> ...`.
- Keep exactly five variant gestures: `--variants N`, `--from <run-id>:<n>`, `thread keep`, `thread group`, and the `[variants]` nag that tells the agent which gesture is required.
- Emit `[variants]` only when unresolved variants exist; it is silenced after `thread keep ...` or `thread keep ...:none`.
- Do not add the `[hint]` fan-out line; DEF-3 defers it.
- Put the SD-042 sentence in `[variants]` help and `thread keep --help`: "selections are append-only; the most recent write is authoritative on read; prior selections are preserved as history but do not affect current keepers."
- Patch only `astrid/packs/builtin/generate_image/run.py` and `astrid/packs/builtin/logo_ideas/run.py`.
- `generate_image` declares `role: variant` on generated image siblings, emits `group=sha256(run_id+prompt_index)[:16]`, sets `group_index`, and fills `duration` where applicable.
- `logo_ideas` folds `name`, `rationale`, `prompt`, and `generated.*` into `variant_meta`, stamps `role: variant`, `group`, and `group_index`.
- No other executor `run.py` is modified.

**SDs landed**

SD-007, SD-013 as trimmed, SD-014, SD-015 as trimmed, SD-016, SD-017, SD-031 as trimmed, SD-033, SD-042 CLI help.

**Acceptance**

- `thread archive` moves an open thread to archived and updates the active pointer deterministically.
- `thread reopen` reopens an archived thread and can make it active.
- Lazy lifecycle enforcement archives idle threads on read without a daemon.
- The reaper marks orphaned in-flight runs once per process and does not re-scan on every command.
- Heterogeneous outputs group only `role: variant`; all unspecified artifacts default to `role: other`.
- `groups.json` reflects variant groups, keepers, and descendants after run writes and selection writes.
- Concurrent `thread keep` appends preserve all history; reads use the most recent write as authoritative.
- `[variants]` appears only for unresolved variants and is silenced by keep or explicit none.
- No `[hint]` line is emitted in v1.
- Only `generate_image` and `logo_ideas` producer files are scheduled for variant-output changes.

**Tests**

- `tests/test_threads_variants.py`: variant grouping, default `role: other`, typed chosen parent edges, keep/none behavior, and groups index updates.
- `tests/test_threads_variants_help.py`: SD-042 sentence in `[variants]` help and `thread keep --help`.
- `tests/test_threads_reaper.py`: lazy reaper marks dead in-flight records once per process.
- `tests/test_threads_lifecycle.py`: archive/reopen windows and active-pointer behavior.

### Day 5

**Goal**

Finish week-1 durability: brief snapshots, provenance, backwards compatibility, and long-form agent documentation.

**Deliverables**

- Implement SD-009 brief snapshotting: every eligible run writes `runs/<slug>/brief.copy.txt` and stamps `brief_content_sha256`.
- Keep SD-041 brief privacy path-based only: content under `runs/<slug>/private/` is sha-only in `run.json`; default briefs remain plaintext snapshots; there is no dedicated brief-privacy flag.
- Add the `pipeline.provenance` block to `hype.metadata.json` through the thread provenance bridge/wrapper integration, without editing protected producer internals.
- The provenance block carries `schema_version`, `thread_id`, denormalized `thread_label`, `run_id`, typed `parent_run_ids[]`, `contributing_runs[{run_id, thread_id, artifact_path, sha256}]`, `starred`, and `agent_version`.
- Add `python3 -m astrid thread backfill` per SD-034. Backfill scans existing `runs/*/` directories without `run.json`, computes hashes, and adopts orphan directories into auto-named threads clustered by hash-graph connected components, not mtime.
- Expand `docs/threads.md` from the Day-3 stub into the long-form SD-038 reference.
- `docs/threads.md` includes `## Privacy & Redaction`: `runs/` gitignore note, KEY/TOKEN/SECRET/PASSWORD/PASSPHRASE/API_KEY/BEARER redaction patterns, `runs/<slug>/private/` convention, and `--no-content`.
- `docs/threads.md` includes `## Concurrent Variant Selection` with the exact SD-042 sentence.
- `docs/threads.md` includes `## Tier Firing Rules` as a short v1 table: `[thread]` every eligible run, `[variants]` when unresolved variants exist, and `Notice:` for first-run-of-process/gap/cwd-change/auto-reopen.
- `docs/threads.md` includes `## Inspect Before Render`, pointing agents to `iteration_video inspect <thread>` before Week 2 renders.
- `docs/threads.md` includes `## Deferred Features` listing SD-036 and DEF-1 through DEF-10.

**SDs landed**

SD-009, SD-019 as trimmed, SD-034, SD-038 long reference, SD-041 documentation, SD-042 documentation.

**Acceptance**

- A run with a brief writes `brief.copy.txt` and the sha in `run.json` matches the snapshot content.
- A private brief under `runs/<slug>/private/` records hashes/labels only and does not expose plaintext in `run.json`.
- `hype.metadata.json` contains the provenance block and remains useful if `.astrid/threads.json` is deleted.
- `thread_label` and `agent_version` are denormalized into the provenance block.
- Backfill adopts existing run directories without moving files.
- Backfilled threads are clustered by hash graph, not modification time.
- `ARTAGENTS_THREADS_OFF=1` still leaves existing behavior unchanged.
- `docs/threads.md` contains the required sections and does not introduce a dedicated brief-privacy flag.
- All existing pytest tests pass without modification at the end of Week 1.

**Tests**

- `tests/test_threads_provenance.py`: `hype.metadata.json` provenance block, denormalized label/version, typed parent edges, and behavior after index deletion.
- `tests/test_threads_off.py`: `ARTAGENTS_THREADS_OFF=1` and no-op compatibility.
- `tests/test_threads_backfill.py`: existing run adoption, hash-graph clustering, and no file moves.
- `tests/test_threads_brief_private.py`: brief snapshot sha, private path sha-only behavior, and no dedicated brief-privacy flag.
- `tests/test_threads_md_sections.py`: required `docs/threads.md` headings and v1 tier table.

## Week 2: Iteration Video MVP (Days 6-10)

Week 2 turns the week-1 metadata into the demo artifact. The v1 implementation uses two new executors, `iteration.prepare` and `iteration.assemble`, plus the existing `builtin.render` path. `iteration.assemble` materializes the render-compatible `hype.timeline.json` and `hype.assets.json` adapter files, so no post-assemble `builtin.cut` pass runs. This applies DEF-7 while preserving the SD-020 through SD-029 behavior that matters for the sprint: polymorphic modality handling, provenance-graph ancestry, quality floor, loud fallback, and the five SD-022 outputs.

### Day 6

**Goal**

Create the modality registry and the first half of `iteration.prepare`: collect the provenance graph, classify modalities, and compute data quality before any summarization calls can spend money.

**Deliverables**

- Add `astrid/modalities/__init__.py` and the registry loader per SD-025.
- Add exactly three renderer modules:
  - `astrid/modalities/image_grid.py`
  - `astrid/modalities/audio_waveform.py`
  - `astrid/modalities/generic_card.py`
- Each renderer declares `kinds`, `clip_modes`, `default_clip_mode_for(shape, style)`, `produces_audio`, and `cost_hint`.
- Register `generic_card` last in the fallback chain so specific renderers always win when they match.
- Add `python3 -m astrid modalities list` and `python3 -m astrid modalities inspect <renderer>`.
- Add `astrid/packs/iteration/prepare/` as the single v1 prepare executor.
- Implement the collection phase inside `iteration.prepare`: walk typed `parent_run_ids` backward from the target run using the provenance graph, not thread membership alone.
- Label runs in the prepare manifest as `in_thread` or `pulled_by_ancestry` for the future HTML report.
- Compute `data_quality` with the OQ-6 formula: `0.5*parent_capture_score + 0.3*has_brief_sha + 0.2*has_resolved_input_artifact`.
- Define `parent_capture_score = (runs_with_parents + valid_roots)/total_runs` and `valid_root iff input_artifacts==[]`.
- Generate `iteration.quality.json` with missing signals, valid roots, unresolved-producer runs, and the computed score.
- Refusal reports must name only unresolved-producer runs. Valid roots are never named as missing lineage.
- Start SD-043 guarding inside `iteration.prepare`: count candidate runs before any `builtin.understand` dispatch and prepare the summary cache key shape.

**SDs landed**

SD-023, SD-024 collection/quality phase, SD-025, SD-029 fallback registration, SD-043 cap placement, DEF-7.

**Acceptance**

- `python3 -m astrid modalities list` shows exactly `image_grid`, `audio_waveform`, and `generic_card`.
- `python3 -m astrid modalities inspect generic_card` shows it is a fallback renderer.
- A mixed fixture resolves image artifacts to `image_grid`, audio artifacts to `audio_waveform`, and unknown kinds to `generic_card`.
- `generic_card` is last in the fallback chain.
- `iteration.prepare` walks typed `parent_run_ids` backward and does not infer ancestry from mtime or flat thread order.
- `iteration.quality.json` includes `data_quality`, missing signals, valid roots, and unresolved-producer runs.
- A root-heavy fixture with `input_artifacts==[]` does not get penalized by `parent_capture_score`.
- A low-quality fixture refuses before render and lists only unresolved-producer runs.
- No `builtin.understand` call is made before `max_iterations` is checked.

**Tests**

- `tests/test_modalities_registry.py`: exactly three renderers, inspect output, and fallback ordering.
- `tests/test_iteration_prepare_collect.py`: provenance-graph walking, in-thread versus pulled-by-ancestry labels, and typed parent edge handling.
- `tests/test_iteration_quality.py`: OQ-6 formula, valid-root handling, unresolved-producer report, and quality floor refusal.

### Day 7

**Goal**

Complete `iteration.prepare` with summarization, cost guardrail, caching, and deterministic scoring.

**Deliverables**

- Implement the summarization phase inside `iteration.prepare` by calling `builtin.understand` through `ThreadPoolExecutor(max_workers=int(os.environ.get("ARTAGENTS_SUMMARIZE_CONCURRENCY", "4")))`.
- Add exponential backoff around each `builtin.understand` call.
- Add `ARTAGENTS_SUMMARIZE_SEQUENTIAL=1` as a deterministic/debug fallback.
- Enforce the SD-043 cap inside `iteration.prepare` before any uncached summarize dispatch.
- `max_iterations` defaults to 200 and is configurable by `--max-iterations` and `ARTAGENTS_ITERATION_MAX`.
- If the candidate run count exceeds `max_iterations`, `iteration.prepare` exits non-zero with an actionable message naming the cap, `--max-iterations`, and `ARTAGENTS_ITERATION_MAX`.
- Direct `python3 -m astrid executors run iteration.prepare ...` invocations cannot bypass the cap.
- Add the SD-043 cache at `.astrid/iteration_cache/<run_id>__<summarizer_model_version>.json`.
- Cache lookup happens before dispatch; the cap is evaluated against the uncached summarize count after cache lookup, so re-rendering a large already-summarized thread does not fail just because its history is long.
- The cost estimate metadata records `summarize_calls`, `uncached_summarize_calls`, `summarizer_model_version`, and per-call estimate used by Day 9 inspect.
- Implement deterministic scoring/order inside `iteration.prepare`: causal depth first, selection-event tiebreaks second, run ULID third.
- Emit `iteration.manifest.json` draft data from prepare: ordered run list, renderer candidates by kind, quality score, summary cache hits/misses, and allocation hints.

**SDs landed**

SD-021 as trimmed, SD-024 scoring preconditions, SD-043 cap/cache/cost metadata, DEF-7.

**Acceptance**

- `iteration.prepare` refuses above `max_iterations` before any uncached `builtin.understand` call.
- The refusal message names the default cap, the `--max-iterations` override, and `ARTAGENTS_ITERATION_MAX`.
- Direct executor invocation of `iteration.prepare` enforces the same cap.
- Cache files use `.astrid/iteration_cache/<run_id>__<summarizer_model_version>.json`.
- Re-running prepare uses cached summaries and only dispatches new `builtin.understand` calls for cache misses.
- Cap evaluation is based on uncached summarize count after cache lookup.
- Ordering is stable across repeated runs with the same graph and selection log.
- `iteration.manifest.json` draft contains enough data for `iteration.assemble` without re-walking the graph.

**Tests**

- `tests/test_iteration_prepare_cap.py`: executor-level cap refusal, direct invocation coverage, and no dispatch before refusal.
- `tests/test_iteration_prepare_cache.py`: cache key, cache hit/miss behavior, and cap based on uncached summarize count after cache lookup.
- `tests/test_iteration_prepare_score.py`: deterministic ordering by causal depth, selection-event tiebreak, then ULID.

### Day 8

**Goal**

Assemble the editable timeline from prepared iteration data and enforce the quality floor at the point where rendering would otherwise begin.

**Deliverables**

- Add `astrid/packs/iteration/assemble/`.
- Read the `iteration.prepare` manifest and `iteration.quality.json`; do not re-run collection or summarization.
- Resolve renderer by artifact `kind` only per DEF-5. Do not use `preview_modes`.
- Apply style precedence from SD-027 with the v1 trim: theme > direction label > style preset > defaults. `--direction` is accepted as a label only and not parsed into structured creative instructions.
- Support v1 `--mode chaptered` only. `parallel` and `interleaved` remain SD-036 cuts.
- Implement audio-bed selection per SD-028: if `produces_audio` renderers cover more than 40% of clip duration, use iterations-as-bed; else theme-declared bed; else silence plus subtle room tone. Never generate music.
- Emit `iteration.timeline.json` that is editable and re-renderable through `builtin.render`.
- Emit the final `iteration.manifest.json` ordered run list with allocations and modality decisions.
- Enforce SD-024 quality floor: if `data_quality < 0.6`, refuse with actionable `python3 -m astrid thread backfill ...` commands for unresolved-producer runs.
- `--force` bypasses the floor and is logged into provenance/manifest with `forced: true`.
- Refusal reports never name valid roots.
- Implement SD-029 loud fallback for unknown kinds: add `<aside class="renderer-fallback">no renderer for kind:&lt;X&gt;</aside>` to the future report payload and emit a renderer-fallback diagnostic in command output. This is not the deferred prefix-tier `Warn:` line.

**SDs landed**

SD-024 render-floor enforcement, SD-026 as trimmed, SD-027 as trimmed, SD-028, SD-029, DEF-5, DEF-7.

**Acceptance**

- `iteration.assemble` maps known image/audio kinds to `image_grid` and `audio_waveform`.
- Unknown kinds use `generic_card` and produce the fallback HTML aside payload.
- No dispatch path reads or requires `preview_modes`.
- `--direction` is preserved as a label and not parsed.
- `--mode parallel` and `--mode interleaved` are rejected or reported as deferred; `chaptered` works.
- Audio-bed selection follows the >40% audio coverage rule and never requests generative music.
- `data_quality < 0.6` refuses before adapter file creation or `builtin.render`.
- Refusal output lists exact backfill commands for unresolved-producer runs and does not list valid roots.
- `--force` allows assembly and records `forced: true`.
- `iteration.timeline.json` and final `iteration.manifest.json` are produced for passing fixtures.

**Tests**

- `tests/test_iteration_assemble.py`: renderer resolution by kind, style precedence, timeline/manifest emission, and v1 mode handling.
- `tests/test_quality_floor.py`: refusal below 0.6, valid roots not named, force bypass logged, and no render dispatch before refusal.
- `tests/test_iteration_video_fallback.py`: `generic_card` fallback payload and command-output diagnostic.

### Day 9

**Goal**

Wire the `builtin.iteration_video` orchestrator and make `iteration_video inspect` the safe discovery command before render.

**Deliverables**

- Add `astrid/packs/builtin/iteration_video/` as `builtin.iteration_video`.
- Wire the v1 orchestrator chain: `iteration.prepare -> iteration.assemble -> builtin.render -> finalize`.
- Reuse `builtin.render`; do not duplicate render pipeline internals. `iteration.assemble` owns the adapter handoff by writing `hype.timeline.json` and `hype.assets.json`.
- Emit the SD-022 five-output set:
  - `iteration.mp4`
  - `iteration.timeline.json`
  - `iteration.manifest.json`
  - `iteration.report.html`
  - `iteration.quality.json`
- Represent all five outputs as one variant group with ancestry and fallback annotations.
- Add `iteration_video inspect <thread>` as the primary discovery command before render.
- `inspect` prints detected modalities, chosen renderers, quality score, summary cache hit/miss count, and estimated cost.
- Use the DEF-9 Cost block format: `Estimated cost: ~$0.42 (47 calls x $0.009)`. One number, no low/high range, no recommendation triplet.
- `inspect` uses the same prepare counting logic as render but must not dispatch `builtin.understand` or render work.
- Support the v1 flags: `--renderers`, `--clip-mode`, `--direction` as label-only, `--mode chaptered`, `--audio-bed`, and `--max-iterations`.
- Reject or clearly defer `--mode parallel|interleaved` and natural-language direction parsing per SD-036.
- Forward `--max-iterations` into `iteration.prepare`, where the cap is enforced.
- Honor SD-041 `--no-content` in `iteration.report.html`: hashes, labels, and structural provenance remain; plaintext prompt/brief content is suppressed.
- Include `in-thread` versus `pulled-by-ancestry` labels in `iteration.report.html`.
- Include the SD-029 fallback aside for any `generic_card` iterations.

**SDs landed**

SD-020, SD-021 as trimmed, SD-022, SD-023 report labels, SD-027 as trimmed, SD-029 report surfacing, SD-041 report privacy, SD-043 inspect estimate, DEF-7, DEF-9.

**Acceptance**

- `python3 -m astrid orchestrators inspect builtin.iteration_video --json` exposes the orchestrator metadata and stage file.
- `iteration_video inspect <thread>` performs discovery without rendering or calling `builtin.understand`.
- Inspect output includes detected modalities, chosen renderers, `Quality:`, cache hit/miss counts, and the single-line `Estimated cost: ~$X.XX (N calls x $Y.YYY)` block.
- `--max-iterations` changes the inspect estimate and is forwarded to `iteration.prepare` during render.
- Rendering produces all five SD-022 outputs.
- The five outputs are grouped together, with non-video artifacts defaulting to `role: other`.
- `iteration.report.html --no-content` contains no plaintext prompt/brief content.
- Report labels distinguish `in-thread` from `pulled-by-ancestry`.
- Unknown modality injection produces the fallback aside in the report.

**Tests**

- `tests/test_iteration_video_inspect.py`: no-render inspect path, detected modalities, renderer decisions, quality line, cache counts, and single-number Cost block.
- `tests/test_iteration_video_no_content.py`: report redaction in `--no-content` mode.
- `tests/test_iteration_video_outputs.py`: five-output set, variant group metadata, and role defaults.
- `tests/test_iteration_video_orchestrator.py`: v1 chain order and `--max-iterations` forwarding into `iteration.prepare`.

### Day 10

**Goal**

Dogfood the sprint against `runs/astrid_logo_v3` and make the demo observable, not anecdotal.

**Deliverables**

- Run Day-5 `thread backfill` against `runs/astrid_logo_v3` if it has not already been adopted.
- Run `python3 -m astrid thread show @active` before any iteration-video command in the dogfood session.
- Run `iteration_video inspect <thread>` and capture the inspect output before render.
- Produce a 60-second `iteration.mp4` against `runs/astrid_logo_v3`.
- Produce all five SD-022 outputs: `iteration.mp4`, `iteration.timeline.json`, `iteration.manifest.json`, `iteration.report.html`, and `iteration.quality.json`.
- Screen-share the 60-second video and sign a manual checklist with date and reviewer name.
- Manual checklist items: video plays end-to-end; report opens; `in-thread` and `pulled-by-ancestry` labels are visible; typed `parent_run_ids` includes kept-variant edges; Cost block is visible in inspect; `--no-content` report renders sha-only sensitive sections; loud-fallback path is verified by injecting an unknown kind.
- Capture stdout from every `executors run` and `orchestrators run` invocation during dogfood.
- Verify observably in the dogfood log:
  - every invocation emitted a `[thread]` prefix line on stdout before other command output;
  - the prefix correctly identified the active thread by ULID;
  - lineage inference fired when any `--brief`, `--asset`, `--video`, or `--input` arg pointed inside `runs/<R>/`;
  - the `[variants]` nag fired for the logo-candidate-producing run and was silenced after `thread keep`;
  - `thread show @active` was called by the operating agent before `iteration_video`.
- Convert the dogfood log into `tests/test_dogfood_failure_modes.py` as a transcript-replay test.
- Run the full SD-037 week-1 integration suite and the Week-2 iteration-video tests.

**SDs landed**

SD-035 final acceptance, SD-037 full regression, SD-041 dogfood privacy, SD-043 dogfood cost visibility, SD-020 through SD-029 end-to-end.

**Acceptance**

- `runs/astrid_logo_v3` dogfood reaches `data_quality >= 0.6` without penalizing valid roots.
- The 60-second `iteration.mp4` exists and plays end-to-end.
- `iteration.timeline.json` is editable/re-renderable through `builtin.render`.
- `iteration.manifest.json` contains ordered runs, allocations, renderer decisions, cache stats, and typed chosen edges.
- `iteration.report.html` opens locally and shows provenance labels.
- `iteration.quality.json` records the score and any missing/inferred signals.
- `iteration_video inspect` output includes a single-number estimated Cost block before render.
- `--no-content` mode suppresses plaintext prompt/brief content in the report.
- The fallback injection path visibly annotates unknown kinds in HTML.
- The dogfood log proves `[thread]` prefix coverage, active-thread correctness, lineage inference, `[variants]` nag/silence behavior, and pre-render `thread show @active`.
- Manual demo checklist is signed with date and reviewer name.

**Tests**

- `tests/test_dogfood_failure_modes.py`: transcript replay for `[thread]` prefix, active-thread ULID, lineage inference, `[variants]` nag/silence, and pre-render `thread show @active`.
- `tests/test_iteration_video_dogfood.py`: smoke fixture for the five SD-022 outputs against `runs/astrid_logo_v3` or its compact test fixture equivalent.
- Full daily regression: `pytest --tb=no -q --no-header`.

## Agent UX Surface

The v1 agent UX is intentionally smaller than the earlier review list. DEF-1, DEF-2, DEF-3, and DEF-9 remove noisy or low-return surfaces. The remaining commitments are the surfaces an agent must reliably read and act on during the sprint.

### UX-1: Prefix Discipline

**Day tag:** Day 3 implementation; Day 5 long-form documentation; Day 10 dogfood verification.

Every eligible `executors run` and `orchestrators run` emits `[thread]` on stdout before command output. This is the always-on memory aid for agents operating across short tool-result contexts.

Acceptance: Day 10 dogfood captures stdout from every executor/orchestrator invocation and verifies each one emitted `[thread]` before other command output.

### UX-2: Notice Discipline

**Day tag:** Day 3 implementation; Day 5 tier table.

V1 ships Notice tier only. `Notice:` fires on first run of process, gap greater than 1 hour, cwd change, and auto-reopen of an archived thread. There is no Warn brief-novelty trigger in v1.

Acceptance: tests cover each Notice trigger, and dogfood logs are reviewable for Notice frequency without enforcing a Warn-rate metric.

### UX-3: Variant Nag Discipline

**Day tag:** Day 4 implementation; Day 5 docs.

`[variants]` appears only when a run produced unresolved variants. It points to the required keep/dismiss gesture and is silenced by `thread keep <run-id>:<n>[,<n>]` or `thread keep <run-id>:none`.

Acceptance: Day 10 dogfood verifies the logo-candidate-producing run emitted `[variants]` and that the line disappeared after `thread keep`.

### UX-4: SKILL.md Exact Wording

**Day tag:** Day 3.

The sprint commits to this exact paragraph in `SKILL.md`:

> At the start of any session that will produce runs, run python3 -m astrid thread show @active first. The [thread] prefix on every command output is your continuous indicator; if it shows the wrong thread, run thread new or pass --thread @new to your next command. Selections are append-only; the most recent write is authoritative on read; prior selections are preserved as history but do not affect current keepers.

Refinements during the sprint require an explicit plan update because agents will pattern-match this text.

Acceptance: `tests/test_threads_skill_md_text.py` asserts the exact paragraph.

### UX-5: Output-Format Stability

**Day tag:** Day 2 contract; Day 3 implementation; Definition of Done.

The v1 prefix formats `[thread]`, `[variants]`, and `Notice:` are public CLI contract. `schema_version` governs the format. Any format change requires a major `schema_version` bump and a transition period documented in `docs/threads.md`.

Acceptance: the Definition of Done treats prefix format as load-bearing for agent compatibility.

### UX-6: Line Ordering

**Day tag:** Day 2 contract; Day 3 implementation; Day 5 docs.

All prefix lines are written to stdout before any other command output. V1 order is:

```text
[thread]
[variants]  # only when present
Notice:     # only when present

command output
```

There is one blank separator line between the prefix block and command output.

Acceptance: `tests/test_threads_line_ordering.py` synthesizes a run where all v1 prefix lines fire and asserts stdout order.

### UX-7: Inspect Before Render

**Day tag:** Day 3 SKILL/docs note; Day 5 `docs/threads.md`; Day 9 command implementation.

Agents must run `iteration_video inspect <thread>` before `iteration_video` render. Inspect is the discovery gesture: it shows detected modalities, chosen renderers, quality score, cache counts, and estimated cost before render work begins.

Acceptance: Day 10 dogfood log proves `thread show @active` and `iteration_video inspect <thread>` were called before render.

### UX-8: Cost Estimate

**Day tag:** Day 9.

`iteration_video inspect <thread>` prints a single v1 Cost line before render:

```text
Estimated cost: ~$0.42 (47 calls x $0.009)
```

No low/high range and no recommendation enum ship in v1 per DEF-9.

Acceptance: `tests/test_iteration_video_inspect.py` asserts the single-number Cost line and verifies inspect does not render or dispatch `builtin.understand`.

### UX-9: Failure-Mode Dogfood Acceptance

**Day tag:** Day 10.

The primary UX failure mode is silent misattribution. Dogfood must make attribution observable, not assumed.

Acceptance: `tests/test_dogfood_failure_modes.py` replays the dogfood transcript and verifies `[thread]` prefix coverage, active-thread ULID correctness, lineage inference for `runs/<R>/` input args, `[variants]` nag/silence behavior, and pre-render `thread show @active`.

### UX-10: Tier Firing Table

**Day tag:** Day 5.

`docs/threads.md` includes a short v1 table mapping surface to trigger and example:

- `[thread]`: every eligible executor/orchestrator run.
- `[variants]`: unresolved variant group exists.
- `Notice:`: first run of process, gap greater than 1 hour, cwd change, or auto-reopen.

Acceptance: `tests/test_threads_md_sections.py` checks that the table exists and does not document deferred extra line formats as v1 features.

## Critical Path

The critical path is the sequence where slipping one node directly threatens the Day-10 demo:

1. **Day 1: atomic index + `xxhash`.** The sprint needs locked `.astrid/threads.json`, ULIDs, repo-relative paths, and `xxhash>=3.4` before any run metadata can be trusted.
2. **Day 2: wrapper + CLI plumbing + Frozen Schema Review.** `run_executor()` and the orchestrator runner must write trimmed SD-008 records, both CLI surfaces must accept `--thread`/`--variants`/`--from`, redaction must work, and `schema_version=1` must freeze by end of day.
3. **Day 3: auto-attribute + nested env + SKILL.md + inspect footer.** Lineage inference, `[thread]` output, `ARTAGENTS_THREAD_ID` propagation, exact SKILL.md guidance, and inspect footers are the adoption-critical surfaces.
4. **Day 4: variants + lifecycle CLI tail + reaper.** `archive`/`reopen`, lazy reaper, `role: variant | other`, selections, groups, typed chosen parent edges, and the two SD-031 producer patches must land before dogfood data is generated.
5. **Day 5: brief + provenance + `docs/threads.md` + backfill.** This is the latest acceptable date for week-1 metadata durability: brief snapshots, `hype.metadata.json` provenance, thread backfill, and long-form docs.
6. **Day 6: modality registry + prepare collection.** The exact three renderers and OQ-6 quality calculation must exist before the video path can make honest decisions.
7. **Day 7: `iteration.prepare` summarize cap + cache + scoring.** The SD-043 cap/cache must live inside `iteration.prepare`, with `ARTAGENTS_SUMMARIZE_CONCURRENCY` parallelism and deterministic ordering.
8. **Day 8: `iteration.assemble` + quality floor.** Timeline assembly, kind-based renderer dispatch, audio-bed policy, quality refusal, and loud fallback must land before orchestrator wiring.
9. **Day 9: orchestrator + inspect Cost line.** `builtin.iteration_video` wires `iteration.prepare -> iteration.assemble -> builtin.render -> finalize`, emits the five SD-022 outputs, and exposes the single-estimate Cost line before render.
10. **Day 10: dogfood + 60-second demo + failure-mode acceptance.** `runs/astrid_logo_v3` must render, the manual checklist must be signed, and the dogfood transcript must prove attribution behavior.

The end-of-Day-2 Frozen Schema Review is the most important process gate. The Day-5 metadata milestone is the latest point where the sprint can still generate reliable dogfood data.

## Risks and Mitigations

1. **Day-3 overpack.** Auto-attribute, prefix lines, nested env, three thread CLI commands, exact SKILL.md text, inspect footers, `--no-content`, and a docs stub are still a dense day.
   **Mitigation:** archive/reopen/reaper already moved to Day 4; if Day 3 slips past 6pm, defer rich `thread list` columns first, then reduce `docs/threads.md#what-the-prefix-means` to the minimal stub. Auto-attribute, prefix output, nested-env propagation, exact SKILL.md paragraph, and inspect footers are never cut.

2. **Lock contention under concurrent writers.** SD-037 includes 8 parallel subprocess runs, and a stuck owner could block the whole layer.
   **Mitigation:** `fcntl.flock` uses a 30-second acquire timeout; timeout errors explain safe manual stale-lock remediation without naming a repair command; `tests/test_threads_index.py` covers 8 parallel writers and stuck-owner timeout messaging.

3. **Chokepoint regression breaks existing tools.** Wrapping `run_executor()` and the orchestrator runner can accidentally affect dry runs, temp outputs, upload paths, or old workflows.
   **Mitigation:** SD-030 no-op gates are tested daily; `upload.youtube` at `astrid/core/executor/runner.py:78` is explicitly covered by `tests/test_threads_upload_youtube_noop.py`; full pytest runs at each day boundary.

4. **Schema bug after Day 2.** A late SD-008 field change can poison all new runs or force rushed migration work.
   **Mitigation:** the Frozen Schema Review freezes `schema_version=1` at end of Day 2; later field additions/removals/renames require explicit sprint-lead review, a compatibility note, and test updates before merge. Formal migration helper machinery is not part of v1.

5. **`builtin.understand` rate limits or latency.** Iteration summaries can produce many calls, and rate limits would block Day 9/10.
   **Mitigation:** `iteration.prepare` uses `ThreadPoolExecutor(max_workers=int(os.environ.get("ARTAGENTS_SUMMARIZE_CONCURRENCY", "4")))`, exponential backoff per call, `ARTAGENTS_SUMMARIZE_SEQUENTIAL=1` fallback, and the SD-043 cache to reduce repeat calls.

6. **Cost blowup on large threads.** An agent may inspect or render a long thread without realizing how many summaries it triggers.
   **Mitigation:** SD-043 cap is enforced inside `iteration.prepare`; `iteration_video inspect` prints `Estimated cost: ~$X.XX (N calls x $Y.YYY)` before render; cache hit/miss counts make repeated renders visible.

7. **Privacy regression.** Briefs, prompts, argv values, or reports may leak sensitive local content.
   **Mitigation:** SD-041 is path-based and explicit: `runs/<slug>/private/` is sha-only, `--no-content` applies to `thread show` and `iteration.report.html`, and redaction replaces KEY/TOKEN/SECRET/PASSWORD/PASSPHRASE/API_KEY/BEARER-class values with `***REDACTED***`; Day-2 and Day-5 tests gate this.

8. **Dogfood fixture insufficiency.** `runs/astrid_logo_v3` might be missing enough provenance for `data_quality >= 0.6`.
   **Mitigation:** Day 5 backfill adopts the directory and computes hashes; Day 6 quality reporting distinguishes valid roots from unresolved producers; if the score is still below floor, `--force` may be used only with the forced provenance marker and a report explaining the missing signals.

9. **Dependency drift.** `xxhash` is new and may be missed in local setup.
   **Mitigation:** Day 1 appends `xxhash>=3.4` to `requirements.txt`; `tests/test_threads_dependencies.py` asserts importability; daily setup/doctor checks catch environment drift.

10. **Renderer fallback hides missing modality support.** Unknown kinds might silently become bland cards and make the demo look falsely complete.
    **Mitigation:** `generic_card` is registered last but loudly annotates fallback with `<aside class="renderer-fallback">no renderer for kind:&lt;X&gt;</aside>` and a command-output diagnostic; Day 10 manually injects an unknown kind to verify the path.

11. **Scope creep into SD-036 cuts or DEF trims.** The sprint can lose focus by adding deferred CLI gestures, renderers, browse UI, or extra output formats.
    **Mitigation:** every deferred-feature request is logged to `docs/threads.md#deferred`; Definition of Done includes that DEF-1 through DEF-10 are documented and not implemented in this sprint.

## Integration Test Plan

The test plan is intentionally file-named. These are planned tests, not code written by this document batch. Each row has an owner day and a pass/fail signal that can be checked in CI.

| Area | Planned test files | Day | Acceptance signal |
| --- | --- | ---: | --- |
| Index, locking, atomic writes | `tests/test_threads_index.py` | 1 | Lock acquisition times out at 30 seconds with actionable stale-lock remediation that avoids a repair command; tmp+fsync+`os.replace` writes a valid index; `.bak` rotation preserves the previous index after an interrupted write. |
| Dependency and IDs | `tests/test_threads_dependencies.py`, `tests/test_threads_ids.py` | 1 | `xxhash>=3.4` is importable from the project environment; generated run/thread/group IDs are 26-char Crockford ULIDs and monotonic within one process. |
| Record schema | `tests/test_threads_record.py` | 2 | `run.json` includes the trimmed v1 SD-008 fields: `schema_version`, `run_id`, `thread_id`, typed `parent_run_ids`, executor/orchestrator IDs, `kind`, timestamps, `returncode`, repo-relative `out_path`, `cli_args_redacted`, `agent_version`, `brief_content_sha256`, `inputs_digest`, `input_artifacts`, `output_artifacts`, three-field `external_service_calls`, and `starred`. |
| CLI plumbing | `tests/test_threads_cli_plumbing.py` | 2 | Both `python3 -m astrid executors run` and `python3 -m astrid orchestrators run` accept `--thread <id|@new|@none>`, `--variants N`, and `--from <run-id>:<n>` and pass them into the request objects without altering tool args after `--`. |
| Chokepoint wrapper | `tests/test_threads_wrapper.py`, `tests/test_threads_upload_youtube_noop.py` | 2 | `threads.begin`/`threads.finalize` wrap normal executor/orchestrator runs; dry runs, tempfile outputs, `--thread @none`, `ARTAGENTS_THREADS_OFF=1`, and `upload.youtube` produce zero thread artifacts and zero thread-layer errors. |
| Redaction and privacy base | `tests/test_threads_redaction.py` | 2 | CLI values whose keys match KEY/TOKEN/SECRET/PASSWORD/PASSPHRASE/API_KEY/BEARER are stored as `***REDACTED***`; persisted paths are repo-relative; `runs/<slug>/private/` inputs are sha-only. |
| Prefix ordering | `tests/test_threads_line_ordering.py` | 2 | A synthetic run with every v1 prefix condition prints to stdout in this exact order before command output: `[thread]`, `[variants]` when present, `Notice:` when present, blank separator line, then command output. |
| Auto-attribution | `tests/test_threads_attribute.py` | 3 | The five SD-006 branches pass with a frozen clock: explicit `--thread`, lineage inference from `runs/<R>/` args, open active thread join, archived-within-window reopen, and new-thread fallback. |
| Nested executor inheritance | `tests/test_threads_nested.py`, `tests/test_threads_nested_env.py` | 3 | `_run_external_executor` threads `ARTAGENTS_THREAD_ID` into subprocess env; child wrappers skip a second begin and inherit the parent thread. |
| Agent text and inspect footers | `tests/test_threads_skill_md_text.py`, `tests/test_threads_inspect_footer.py` | 3 | `SKILL.md` contains the exact committed paragraph; `executors inspect` and `orchestrators inspect` include the active-thread footer. |
| Thread CLI lifecycle | `tests/test_threads_cli.py`, `tests/test_threads_lifecycle.py` | 3-4 | `thread new`, `thread list`, `thread show`, `thread archive`, and `thread reopen` work against `.astrid/threads.json`; lazy lifecycle enforcement has no daemon dependency. |
| In-flight reaper | `tests/test_threads_reaper.py` | 4 | A stale run with `ended_at: null` and a dead stamped PID is marked `returncode: -1`, `status: "orphaned"`, and finalized at most once per process. |
| Variants and selections | `tests/test_threads_variants.py`, `tests/test_threads_variants_help.py`, `tests/test_threads_concurrent.py` | 4 | Only artifacts with `role: "variant"` enter groups; `role: "other"` is the default; append-only `selections.jsonl` is last-write-wins on read; concurrent selection writes preserve history; `[variants]` and `thread keep --help` include the SD-042 sentence. |
| Producer patches | `tests/test_threads_generate_image_variants.py`, `tests/test_threads_logo_ideas_variants.py` | 4 | `generate_image` and `logo_ideas` are the only existing producer patches; they populate `role`, `group`, `group_index`, `duration`, and `variant_meta` as applicable. |
| Brief snapshotting | `tests/test_threads_brief_snapshot.py`, `tests/test_threads_brief_private.py` | 5 | Each run writes `runs/<slug>/brief.copy.txt` and `brief_content_sha256`; private-path briefs are represented by hash/kind only and no dedicated brief-privacy flag exists. |
| Provenance and backfill | `tests/test_threads_provenance.py`, `tests/test_threads_backfill.py`, `tests/test_threads_off.py` | 5 | The thread provenance bridge writes the provenance block into `hype.metadata.json`; `thread backfill` adopts existing `runs/*/` without `run.json`; `ARTAGENTS_THREADS_OFF=1` leaves old workflows unchanged. |
| Thread docs | `tests/test_threads_md_sections.py`, `tests/test_threads_no_content.py` | 5 | `docs/threads.md` contains Privacy & Redaction, Concurrent Variant Selection, Tier Firing Rules, Inspect Before Render, and Deferred Features; `thread show --no-content` omits plaintext content. |
| Modality registry | `tests/test_modalities_registry.py` | 6 | Exactly `image_grid`, `audio_waveform`, and `generic_card` are registered; `generic_card` is last in fallback order; `python3 -m astrid modalities {list, inspect}` reports the declarations. |
| Iteration prepare | `tests/test_iteration_prepare.py`, `tests/test_iteration_prepare_cap.py`, `tests/test_iteration_prepare_cache.py` | 6-7 | `iteration.prepare` walks provenance-graph ancestry, computes OQ-6 data quality without penalizing valid roots, enforces SD-043 before uncached summarize dispatch, and writes/reads `.astrid/iteration_cache/<run_id>__<summarizer_model_version>.json`. |
| Iteration assembly | `tests/test_iteration_assemble.py`, `tests/test_quality_floor.py` | 8 | Renderer dispatch uses `kind` only; `data_quality < 0.6` refuses with backfill commands for unresolved producers and never names valid roots; `--force` logs `forced: true` in provenance. |
| Iteration-video orchestrator | `tests/test_iteration_video.py`, `tests/test_iteration_video_inspect.py`, `tests/test_iteration_video_no_content.py`, `tests/test_iteration_video_fallback.py` | 9 | The orchestrator chains `iteration.prepare -> iteration.assemble -> builtin.render -> finalize`, emits all five SD-022 outputs, `inspect` prints the single-estimate Cost line, `--no-content` strips plaintext report content, and unknown kinds produce the loud `generic_card` fallback annotation. |
| Dogfood transcript | `tests/test_dogfood_failure_modes.py` | 10 | Transcript replay asserts `[thread]` prefix coverage, active-thread ULID correctness, lineage inference for `runs/<R>/` input args, `[variants]` nag then silence after `thread keep`, and pre-render `thread show @active`. |

Daily regression gate: at the end of each day, run the new tests for that day plus `pytest --tb=no -q --no-header`. Day 5 and Day 10 additionally run the full SD-037 suite because those are the data-layer and demo gates.

Deferred-test note: DEF-1 through DEF-10 remove `tests/test_threads_health_smell.py`, `tests/test_threads_hint.py`, separate `tests/test_iteration_summarize_cap.py`, separate `tests/test_iteration_summarize_cache.py`, preview-mode tests, host-id tests, latency/cost-usd tests, and low/high Cost range assertions from v1. Those names are reserved for follow-up work only if the deferred features return.

## Dogfood Plan: `runs/astrid_logo_v3`

The dogfood is the Day-10 demo, not a side quest. It proves that the data layer can adopt real existing output, that selection state is visible to the iteration-video layer, and that an agent operating normally cannot silently misattribute work.

### Day 5: Adopt the Fixture

Run `python3 -m astrid thread backfill runs/astrid_logo_v3` after brief snapshotting, provenance support, variants, and path-based privacy land.

Acceptance:

- A thread is created or reused for `runs/astrid_logo_v3` with a stable ULID and repo-relative paths only.
- Backfill synthesizes `run.json` records for the fixture without moving any files under `runs/`.
- `concepts.json`, `grid.jpg`, `logo-manifest.json`, and `prompts.json` are recorded as `role: "other"` outputs or inputs as appropriate.
- `images/logo-00N.png` artifacts are recorded as `role: "variant"` outputs with `group`, `group_index`, `duration` when available, and `variant_meta` carrying logo-candidate context where reconstructable.
- Private-path handling is tested by placing one copied fixture note under `runs/astrid_logo_v3/private/` and verifying only sha/kind metadata is emitted.
- `thread show @active --no-content` shows the thread and artifact summaries without plaintext brief content.

### Day 9: Inspect Before Render

Before any render, run `iteration_video inspect <thread-id>` against the adopted thread.

Acceptance:

- Inspect lists detected modality `image` and selected renderer `image_grid`.
- Inspect prints `Estimated cost: ~$X.XX (N calls x $Y.YYY)` before any render dispatch.
- Inspect prints the quality score and the missing-signal list; if `data_quality < 0.6`, it names unresolved producers with exact `thread backfill ...` commands and does not name valid roots.
- The operator chooses a kept logo candidate with `thread keep <run-id>:<n>` before rendering; the `[variants]` nag is absent on the next command after the keep.
- `--no-content` mode is exercised for `iteration.report.html` generation and verified to strip plaintext brief/prompt content while preserving hashes and artifact labels.
- A temporary fixture copy injects `kind: "model_3d"` into one artifact to verify SD-029: the report contains `<aside class="renderer-fallback">no renderer for kind:&lt;X&gt;</aside>` and command output includes a loud fallback diagnostic.

### Day 10: Render and Demo

Render the final dogfood video through `builtin.iteration_video` with the default chaptered mode and the three v1 renderers only.

Expected outputs:

- `iteration.mp4`: 60-second playable video.
- `iteration.timeline.json`: editable timeline suitable for `builtin.render`.
- `iteration.manifest.json`: ordered run list with allocations and in-thread vs pulled-by-ancestry labels.
- `iteration.report.html`: provenance, variant-selection notes, brief-diff captions when content is allowed, and fallback annotations when injected.
- `iteration.quality.json`: `data_quality >= 0.6` for the normal fixture path, or a forced marker plus explicit missing-signal report if `--force` is used.

Manual checklist:

- [ ] `iteration.mp4` plays end-to-end for 60 seconds.
- [ ] `iteration.report.html` opens locally and labels "in-thread" versus "pulled-by-ancestry" runs.
- [ ] The kept logo candidate appears in the video and the selection history is visible in the report.
- [ ] `iteration.manifest.json` uses typed `parent_run_ids` for causal and chosen edges.
- [ ] `iteration.quality.json` shows `data_quality >= 0.6` on the normal path.
- [ ] `iteration_video inspect <thread-id>` was run before render and its Cost line is copied into the demo notes.
- [ ] `--no-content` mode was rendered or inspected and no plaintext private content appears.
- [ ] The injected unknown-kind path produced the loud `generic_card` fallback annotation.
- [ ] Screen-share completed.
- [ ] Date:
- [ ] Reviewer:

Failure-mode transcript acceptance:

- Capture stdout from every `executors run` and `orchestrators run` invocation used during dogfood.
- Store the transcript fixture for `tests/test_dogfood_failure_modes.py`.
- Assert every eligible invocation emitted a `[thread]` prefix on stdout before command output.
- Assert each prefix identified the active thread by ULID, not by mutable label.
- Assert lineage inference fired whenever any `--brief`, `--asset`, `--video`, or `--input` arg pointed inside `runs/<R>/`.
- Assert the logo-candidate-producing run emitted `[variants]`, and the nag was silenced after `thread keep`.
- Assert the operating agent ran `python3 -m astrid thread show @active` before `iteration_video inspect` or render.
- Assert no run was attributed to `@active` when a more specific lineage-derived thread existed.

## Out of Scope

These cuts are not optional backlog hiding in the sprint. They are excluded so the two-week plan can ship durable metadata, a tight variant primitive, and one demonstrable iteration-video path.

SD-036 sprint cuts:

- Thread split, merge, attach, detach, and automatic lock repair are out of scope; only `thread backfill` ships in v1. Lock-timeout guidance explains safe manual stale-lock remediation and does not point at a repair command.
- Four of seven modality renderers are deferred: `video_pip`, `text_diff`, `model_turntable`, and `code_scroll`.
- Cross-modal sub-pursuits and `--mode parallel|interleaved` are deferred; v1 uses chaptered mode only.
- `--direction` natural-language parsing is deferred; the flag is accepted but treated as a label only.
- The `--why` reasoning surface on `iteration_video inspect` is deferred.
- `thread doctor` auto-fix suggestions are deferred. After DEF-2, no v1 thread-health smell line ships either.
- `cut --variants N` timeline variants are deferred.
- Brief-similarity heuristics and semantic-distance dilation are deferred.
- Human-facing browse UI for threads is deferred.

Additional DEF-1 through DEF-10 trims:

- Warn brief-novelty tier is deferred; v1 ships `[thread]`, `[variants]`, and `Notice:` only.
- Fan-out hinting and thread-health smell output are deferred.
- Variant role enum is trimmed to `variant | other`, with `other` as the default.
- `preview_modes` is deferred; renderer dispatch keys off `kind`.
- Separate `chosen_from_groups` is deferred; chosen edges use typed `parent_run_ids`.
- Separate `iteration.collect`, `iteration.summarize`, and `iteration.score` executors are collapsed into `iteration.prepare`.
- `external_service_calls` stores only `model`, `model_version`, and `request_id`.
- Cost output is a single estimate, not a range or recommendation triplet.
- `host_id` is deferred.
- Formal N-1 reader and migration helper machinery are deferred; the v1 process instead relies on the Day-2 Frozen Schema Review.

SD-044 recorded tradeoffs:

- The sprint keeps the noun `thread` even though it can overlap with git terminology, because SD-001 records that the creator language matters more in this domain.
- The sprint keeps scalar `thread_id` on each run while using typed `parent_run_ids` for DAG membership. The scalar is a human grouping tag; the typed edges carry causal and curatorial relationships.
- These tradeoffs are context for future readers, not extra v1 implementation work.

## Documentation Deliverables

Documentation lands next to the first behavior that needs it. Agents should never see a new prefix or selection rule before the repository explains how to act on it.

| Deliverable | Day | Location | Required content |
| --- | ---: | --- | --- |
| Session-start agent instruction | 3 | `SKILL.md` | Exact paragraph: `At the start of any session that will produce runs, run python3 -m astrid thread show @active first. The [thread] prefix on every command output is your continuous indicator; if it shows the wrong thread, run thread new or pass --thread @new to your next command. Selections are append-only; the most recent write is authoritative on read; prior selections are preserved as history but do not affect current keepers.` |
| Inspect footer | 3 | `executors inspect` and `orchestrators inspect` output | Footer names the active thread and points to `python3 -m astrid thread show @active` for details. |
| Prefix stub | 3 | `docs/threads.md#what-the-prefix-means` | One-page stub that explains `[thread]`, `[variants]`, `Notice:`, stdout ordering, and the blank separator before command output. |
| Long thread reference | 5 | `docs/threads.md` | Privacy & Redaction, Concurrent Variant Selection, Tier Firing Rules, Inspect Before Render, Backfill, Deferred Features. |
| Privacy/redaction reference | 5 | `docs/threads.md#privacy--redaction` | Documents `runs/<slug>/private/`, `--no-content`, argv redaction classes, repo-relative paths, and sha-only private artifacts. |
| Concurrent selection reference | 5 | `docs/threads.md#concurrent-variant-selection` | Includes the exact SD-042 sentence: selections are append-only; the most recent write is authoritative on read; prior selections are preserved as history but do not affect current keepers. |
| Tier firing table | 5 | `docs/threads.md#tier-firing-rules` | V1 table for `[thread]`, `[variants]`, and `Notice:` only. It does not document deferred Warn, hint, or health surfaces as shipped behavior. |
| Inspect-before-render note | 5 | `docs/threads.md#inspect-before-render` | Tells agents to run `iteration_video inspect <thread>` before render and says it shows detected modalities, chosen renderers, estimated cost, and quality score. |
| Deferred features | 5 | `docs/threads.md#deferred` | Lists SD-036 and DEF-1 through DEF-10 so future follow-up work does not re-open v1 scope accidentally. |

No per-tool `STAGE.md` files are modified for this layer.

## Definition of Done

The sprint is done only when every item below is observable:

(a) Every eligible run after the Day-2 wrapper merge writes the trimmed v1 SD-008 `run.json` metadata with `schema_version: 1`.

(b) End-of-Day-2 Frozen Schema Review passed, and any later schema adjustment received explicit sprint-lead review plus updated tests before merge.

(c) The trimmed SD-037 week-1 test suite is green, including schema, locking, concurrency, wrapper, auto-attribute, nested env, variants, provenance, backfill, off-switch, upload.youtube no-op, and redaction coverage.

(d) `pytest --tb=no -q --no-header` is green at the end of each sprint day.

(e) `runs/astrid_logo_v3` dogfood produces all five SD-022 outputs: `iteration.mp4`, `iteration.timeline.json`, `iteration.manifest.json`, `iteration.report.html`, and `iteration.quality.json`.

(f) The Day-10 demo produces a 60-second `iteration.mp4`, is screen-shared live, and has the manual checklist signed with date and reviewer.

(g) The dogfood transcript proves a `[thread]` prefix appeared on stdout before command output for every eligible `executors run` and `orchestrators run` invocation.

(h) The operating agent ran `python3 -m astrid thread show @active` before `iteration_video inspect` or render.

(i) Lineage inference is correct on every dogfood run: any input arg inside `runs/<R>/` inherits `R`'s thread rather than blindly using `@active`.

(j) `[variants]` nag behavior is observable: the logo-candidate-producing run emits the nag, and the next command after `thread keep` is silent for that resolved group.

(k) `docs/threads.md`, `SKILL.md`, and the `executors inspect` / `orchestrators inspect` footers are updated on their scheduled days.

(l) The exact SKILL.md paragraph appears once and matches `tests/test_threads_skill_md_text.py`.

(m) No existing executor `run.py` is modified except `astrid/packs/builtin/generate_image/run.py` and `astrid/packs/builtin/logo_ideas/run.py` for the SD-031 variant producer patches.

(n) `--no-content` works for `thread show` and `iteration.report.html`; brief privacy is path-based through `runs/<slug>/private/`, with no dedicated brief-privacy flag.

(o) The SD-042 last-write-wins sentence appears in SKILL.md, `[variants]` help text, and `thread keep --help`.

(p) `iteration.prepare` refuses at the executor layer when the uncached summarize count exceeds `max_iterations`; direct `executors run iteration.prepare` cannot bypass the SD-043 guardrail.

(q) `iteration_video inspect` prints the DEF-9 single-estimate Cost line before render: `Estimated cost: ~$X.XX (N calls x $Y.YYY)`.

(r) `xxhash>=3.4` is declared in `requirements.txt`, and `tests/test_threads_dependencies.py` verifies it is importable.

(s) `upload.youtube` produces zero thread artifacts and zero thread-layer errors.

(t) Child subprocesses inherit `ARTAGENTS_THREAD_ID`; child wrappers skip begin and do not re-stamp the parent thread.

(u) `cli_args_redacted` replaces KEY/TOKEN/SECRET/PASSWORD/PASSPHRASE/API_KEY/BEARER-class values with `***REDACTED***`.

(v) Prefix-line format is part of the public CLI contract and governed by `schema_version`; format changes require a major schema-version bump plus a transition period documented in `docs/threads.md`.

(w) Prefix line ordering is enforced by tests: `[thread]`, then `[variants]` when present, then `Notice:` when present, then a blank separator line, then command output.

(x) All DEF-1 through DEF-10 deferrals are documented in `## Deferred for v1 (Trimmed Scope)` and `docs/threads.md#deferred`, and none of those deferred features are implemented in this sprint.
