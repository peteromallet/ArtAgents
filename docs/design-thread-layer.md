# Thread / Variant / Iteration-Video Layer — Design Context

This document captures the design decisions converged on for adding a creative-iteration tracking layer to ArtAgents. It is the input to a sprint plan; it is not itself the sprint plan.

The layer adds three things on top of the existing executor/orchestrator/elements model:

1. **Threads** — automatic grouping of runs into creative pursuits.
2. **Variants** — sibling outputs of a single attempt, with selection semantics.
3. **Iteration video** — an orchestrator that renders a video walkthrough of any pursuit, polymorphic across modalities (image, audio, video, text, 3D, code).

The whole system exists to support one killer demo: open a finished artifact, see the N runs that fed it (including sibling variants and prompt diffs) as a video.

## Architectural premises

- ArtAgents is **invoked by LLM agents** (Claude Code, etc.), not human operators. UX optimizes for an actor with no persistent memory across conversations.
- Every invocation produces files in `runs/<slug>/`. Today these are flat siblings; the new layer adds metadata stamping without changing the directory contract.
- The existing chokepoints are `run_executor()` in `artagents/core/executor/runner.py:75` and the orchestrator dispatch in `artagents/core/orchestrator/runner.py`. All new behavior lives in or above these wrappers — **no executor or orchestrator implementation is modified except where it produces variant outputs.**
- `.artagents/` is the canonical local-state root (already in `.gitignore`). New persistent state lives there.
- All path references in persisted JSON must be repo-relative or content-addressed. No absolute paths.

## Settled Decisions

- **SD-001** — Use the noun `thread` for a creative pursuit, not `workstream`/`session`/`pursuit`. The name appears in every `[thread]` prefix line and must match the creator's mental model. _load_bearing: true_
  Rationale: chosen after explicit subagent debate; matches creator language ("pull on this thread"); short to type; the git overload is tolerable in the creative-tools domain.

- **SD-002** — Tags-not-folders: every run writes a `runs/<slug>/run.json` with a `thread_id` field. The `runs/` directory stays flat. Re-grouping (split/merge/attach) is a metadata edit, never a `mv` operation. _load_bearing: true_
  Rationale: coupling physical layout to logical grouping makes re-attribution destructive and breaks path references in older timelines. Identity is by ULID, never by path.

- **SD-003** — A single index file `.artagents/threads.json` holds the thread map and `active_thread_id` pointer. All updates go through `fcntl.flock` on a sidecar lock file plus atomic write (tmp + fsync + `os.replace`), with a rotated `.bak`. _load_bearing: true_
  Rationale: parallel runs must not lose updates; the index is small enough that single-file is correct.

- **SD-004** — IDs are 26-char Crockford ULIDs (`run_id`, `thread_id`, `group_id`), monotonic within a process. References between records are always by ULID, never by path or label. _load_bearing: true_
  Rationale: lex-sortable, stable across renames, no central registry needed.

- **SD-005** — `parent_run_ids` on a run is **plural and causal**, derived from input-artifact hashes against producer `run_id`s — not the temporal previous run in the thread. A run with no consumed artifacts has empty `parent_run_ids` (it is a root). _load_bearing: true_
  Rationale: temporal parentage lies during interleaved work; causal parentage is reconstructible and honest.

- **SD-006** — Auto-attribute decision function, evaluated at run start under the lock:
  1. Explicit `--thread <id>` or `@new` / `@none` wins.
  2. **Lineage inference**: if any input arg points inside `runs/<R>/`, inherit `R`'s thread.
  3. Else active pointer is `open` → join.
  4. Else active is `archived` and within `IDLE_REOPEN_WINDOW` (default 48h) → reopen and join.
  5. Else create new thread.
  _load_bearing: true_
  Rationale: lineage inference is the highest-ROI auto-attribution improvement; it removes a whole class of mis-grouping when the agent works across shells.

- **SD-007** — Thread lifecycle: `open → archived → (re)open`. Archive triggers are explicit command, successful export/publish, or idle ≥ `IDLE_ARCHIVE_WINDOW` (default 7d). Reopen triggers are explicit command or new run within `IDLE_REOPEN_WINDOW`. Lazy enforcement on read; no daemon. _load_bearing: true_

- **SD-008** — `run.json` schema (frozen for v1 of the layer). Required fields:
  ```
  schema_version, run_id, thread_id, parent_run_ids[], chosen_from_groups[],
  executor_id, orchestrator_id, kind, started_at, ended_at, returncode,
  out_path, cli_args_redacted, agent_version, host_id,
  brief_content_sha256, inputs_digest,
  input_artifacts: [{path, sha256, produced_by_run_id, kind}],
  output_artifacts: [{path, sha256, kind, role, group, group_index, preview_modes, duration, variant_meta}],
  external_service_calls: [{service, request_id, model, model_version, seed?, cost_usd?, latency_ms}],
  starred: bool
  ```
  _load_bearing: true_
  Rationale: this is the irreversible part. Every run produced after sprint day 1 either has these fields or doesn't, forever. Metadata can be collected now and used by deferred features later.

- **SD-009** — Brief snapshotting: every run writes `runs/<slug>/brief.copy.txt` and stamps `brief_content_sha256` in `run.json`. Briefs get edited in place between runs; without snapshotting, prompt diffs in the iteration video are unreconstructable. _load_bearing: true_

- **SD-010** — `external_service_calls` captures `model` and `model_version` per call, plus `seed`, `cost_usd`, `latency_ms`, and `request_id` where available. Models drift (gpt-image-1 → gpt-image-2 produces different outputs); `agent_version` (toolkit git sha) is insufficient on its own. `request_id` lets deleted external artifacts be re-fetched. _load_bearing: true_

- **SD-011** — `input_artifacts` records `produced_by_run_id` at the moment of consumption (computed from artifact sha256 against known runs). Without this, the causal DAG must be reconstructed later from hashes — possible but expensive and broken if intermediate runs are deleted. _load_bearing: true_

- **SD-012** — `host_id` = `sha256(hostname:user)[:16]`. Captured per run for provenance only. Not used for tracking, not transmitted. Lets a future sync tool reconcile cross-machine threads. _load_bearing: false_
  Rationale: cheap to capture, expensive to add later if missed.

- **SD-013** — Variants primitive: extend each `output_artifact` with `role` (`variant`/`ancillary`/`manifest`/`index`), `group` (= `sha256(run_id + group_label)[:16]`), `group_index`, and a free-form `variant_meta` blob. **Default role is `ancillary`. Executors must opt in to `variant`. Fail closed.** _load_bearing: true_
  Rationale: heterogeneous outputs (4 candidates + grid + manifest) cannot accidentally poison the variant group; executors that produce siblings declare them explicitly.

- **SD-014** — Selection state lives at the thread, not the artifact. An append-only `.artagents/threads/<thread-id>/selections.jsonl` records each `{ts, group, kept[], discarded[], by, note?}` event. Never mutated. Current-keepers reduces over the log. _load_bearing: true_
  Rationale: handles partial selection, deselection, and revision without losing history; concurrent picks are safe (last write wins on read).

- **SD-015** — `chosen_from_groups: [{group, sha256}]` on a consuming run is a **separate edge** from `parent_run_ids`. The DAG distinguishes "descended from X" (causal) from "picked over its siblings" (curatorial). The iteration video needs both. _load_bearing: true_

- **SD-016** — Denormalized `.artagents/threads/<thread-id>/groups.json` index gives O(1) lookups for "what variants for run #N, which kept, which descended." Updated on run-write and selection-write. _load_bearing: true_

- **SD-017** — Agent gesture surface for variants — exactly five commands, one of which is mandatory-per-attempt:
  ```
  thread keep <run-id>:<n>[,<n>]      # mandatory when variants exist
  thread keep <run-id>:none           # explicit dismiss (silences the [variants] nag)
  thread group <run-id> <run-id> ...  # post-hoc retroactive grouping
  --variants N                        # request a sibling group up front
  --from <run-id>:<n>                 # consume a specific variant; defaults to most-recent kept in thread
  ```
  No more, no less. _load_bearing: true_

- **SD-018** — Runner-emitted prefix lines on every `executors run` and `orchestrators run` invocation, written to stdout BEFORE the rest of the command output (so the agent sees them in tool result):
  ```
  [thread]   <label> · run #N · parent #M[:vK]
  [variants] run #N produced K siblings — none kept (use: thread keep N:K)   # only when unresolved variants exist
  ```
  Plus tiered Notice / Warn lines for first-run-of-process, gap >1h, brief novelty, auto-reopen of archived thread. _load_bearing: true_
  Rationale: the agent's working memory is the previous tool's stdout; thread state must be in that stream every turn.

- **SD-019** — Provenance block in `hype.metadata.json` (added to `pipeline` block by `builtin.cut`). Carries `{thread_id, thread_label (denormalized), run_id, parent_run_ids[], chosen_from_groups[], contributing_runs[{run_id, thread_id, artifact_path, sha256}], starred, agent_version}`. Denormalization of `thread_label` and `agent_version` makes the artifact self-contained after `rm -rf .artagents/`. _load_bearing: true_

- **SD-020** — `builtin.iteration_video` is a single orchestrator polymorphic across modalities, not per-modality orchestrators. Real threads are heterogeneous (storyboard → animation, music video) and the agent shouldn't have to pick a modality before knowing what's in the thread. _load_bearing: true_

- **SD-021** — Iteration-video executor chain: `iteration.collect` → `iteration.summarize` (calls `builtin.understand` in parallel) → `iteration.score` → `iteration.assemble` → `builtin.cut` → `builtin.render`. Three new executors; the rest are reused. `iteration.assemble` is the only piece with non-trivial new visual logic. _load_bearing: true_

- **SD-022** — Iteration-video outputs (a single variant group):
  ```
  iteration.mp4              # the rendered video (chosen variant)
  iteration.timeline.json    # editable, re-renderable via builtin.render
  iteration.manifest.json    # ordered run list with allocations
  iteration.report.html      # ancillary; the real artifact for timeline-heavy threads
  iteration.quality.json     # missing/inferred per iteration
  ```
  _load_bearing: true_

- **SD-023** — Default ancestry is `provenance-graph` (walk `parent_run_ids` backward from target), not `thread`. Threads are a human construct that drift; causal parentage is hash-derived and doesn't lie. The HTML report labels which runs were "in-thread" vs "pulled in by ancestry." _load_bearing: true_

- **SD-024** — Quality floor: `iteration.collect` computes a `data_quality` score in [0,1]. If below `quality_floor` (default 0.6), the orchestrator **refuses to render** and emits an actionable report listing the specific runs missing `parent_run_ids` with exact backfill commands. `--force` bypasses, logged into provenance. _load_bearing: true_
  Rationale: silently rendering a video that misorders or omits half the runs destroys trust permanently. Refusal must be a helpful editor, not a bureaucrat.

- **SD-025** — `ModalityRenderer` registry at `artagents/modalities/` (sibling to `elements/`, `executors/`, `orchestrators/`). Each renderer is a small declarative file declaring `kinds`, `clip_modes`, `default_clip_mode_for(shape, style)`, `produces_audio`, `cost_hint`. Discoverable via `python3 -m artagents modalities {list, inspect}`. _load_bearing: true_
  Rationale: replaces a hardcoded global decision table that would become unmaintainable as modalities multiply. Each renderer owns its own scoped logic.

- **SD-026** — Capability declarations on artifacts: extend `output_artifacts` with `preview_modes: [...]` and `duration` (where applicable). Producers declare what previews are tractable. The renderer registry resolves `(kind, preview_modes)` to a renderer at assembly time. _load_bearing: true_

- **SD-027** — Agent surface for iteration video — five flags + one inspect command total:
  ```
  iteration_video inspect <thread>          # primary discovery; prints detected modalities, chosen renderers, defaults, --why reasoning
  --renderers image=grid,audio=waveform,video=pip
  --clip-mode <run-id>=pip                  # single-iteration override (escape hatch)
  --direction "natural language"            # one-off creative direction (parsed into structured hints; falls back gracefully)
  --mode chaptered|parallel|interleaved     # for cross-modal threads (default: chaptered)
  --audio-bed iterations|theme|silence|<path>
  ```
  Precedence: theme > direction > style preset > defaults. _load_bearing: true_

- **SD-028** — Audio-bed automatic selection: if `produces_audio` renderers cover >40% of clip duration → iterations-as-bed (cross-fade between audio variants). Else theme-declared bed. Else silence + subtle room tone. **Never generative music** — ages badly, fights the content. _load_bearing: true_

- **SD-029** — `generic_card` renderer is always registered as a fallback. When it fires, every iteration that uses it gets a "no renderer for `kind:<X>`" annotation in the HTML report and a stdout warning. Unknown modalities degrade gracefully and **loudly**. _load_bearing: true_

- **SD-030** — Single chokepoint integration: `run_executor()` at `artagents/core/executor/runner.py:75` and the orchestrator-runner equivalent are wrapped with `threads.begin(request)` / `threads.finalize(record_id, result)`. The wrapper is a no-op when: `dry_run=True`, `request.out` is unwritable or under `tempfile.gettempdir()`, `request.thread == "@none"`, or env `ARTAGENTS_THREADS_OFF=1` is set. **No executor's `run.py` is modified except where it produces variant outputs.** _load_bearing: true_

- **SD-031** — Existing-executor patches required by this layer:
  - `artagents/packs/builtin/generate_image/run.py` — declare `role: variant` on the N images; emit `group` from `(run_id, prompt_index)`; populate `preview_modes` and `duration`.
  - `artagents/packs/builtin/logo_ideas/run.py` — fold existing rich per-candidate metadata (`name`, `rationale`, `prompt`, `generated.*`) into `variant_meta` and stamp `role: variant`, `group`, `group_index`.
  - All other executors are unmodified for v1.
  _load_bearing: true_

- **SD-032** — Hashing strategy: `xxhash` for `inputs_digest` (fast, non-cryptographic, used for dedup detection only). `sha256` for `output_artifacts[*].sha256` (one-shot at run end, never blocking the runner mid-run). Multi-GB renders must not block. _load_bearing: true_

- **SD-033** — In-flight reaper: any run start scans `runs/*/run.json` for records with `ended_at: null` whose owning process is gone (PID stamped at begin). Marks them `returncode: -1, ended_at: <now>, status: "orphaned"`. Lazy, runs at most once per process. _load_bearing: true_

- **SD-034** — Backwards compatibility is mandatory. Existing `runs/*/` directories without `run.json` continue to work unmodified. `python3 -m artagents thread backfill` scans, computes hashes, and adopts orphan dirs into auto-named threads (clustered by hash-graph connected components, not mtime). All existing tests must pass without modification. _load_bearing: true_

- **SD-035** — Sprint phasing constraints (load-bearing for the planner):
  - **Week 1 (days 1–5) is the data layer.** Thread schema, locking, atomic write, `run_executor` wrapper, auto-attribute, prefix lines, `thread {new, list, show, archive, reopen}` CLI, variants (`role`/`group`/`selections.jsonl`/`groups.json`/`chosen_from_groups`), `[variants]` nag, `thread keep`, executor patches, brief snapshotting, in-flight reaper, provenance block in `hype.metadata.json`, `preview_modes`/`duration` on artifacts. **All metadata fields in SD-008 must ship by end of week 1**, because every run after sprint day 1 either has them or doesn't, forever.
  - **Week 2 (days 6–10) is the iteration video MVP.** `iteration.collect`, `iteration.summarize`, `iteration.score`, `iteration.assemble`, `builtin.iteration_video`, HTML report, quality floor, modality registry framework with **3 renderers only** (`image_grid`, `audio_waveform`, `generic_card`), `inspect` subcommand, end-to-end demo render against an existing thread (`runs/artagents_logo_v3` is a known-good fixture).
  _load_bearing: true_

- **SD-036** — Sprint cuts (explicitly out of scope for the 2-week sprint, deferred to follow-up):
  - `thread {split, merge, attach, detach, gc}` (only `backfill` ships in v1)
  - 4 of 7 modality renderers: `video_pip`, `text_diff`, `model_turntable`, `code_scroll`
  - Cross-modal sub-pursuits and `--mode parallel|interleaved`
  - `--direction` natural-language parsing (flag accepted but treated as label only)
  - `--why` reasoning surface on `iteration_video inspect`
  - `thread doctor` auto-fix suggestions (detection-only smell line ships in v1)
  - `cut --variants N` (timeline variants)
  - Brief-similarity heuristics, semantic-distance dilation
  - Human-facing browse UI for threads
  _load_bearing: true_

- **SD-037** — Test coverage required for week-1 ship:
  - Schema round-trip + version migration N-1 → N
  - Atomic write + lock acquisition + partial-write recovery via `.bak`
  - Auto-attribute decision function (every branch, including lineage inheritance) with frozen clock
  - Concurrency: 8 parallel subprocess runs, all recorded, no lost updates
  - `run_executor` integration end-to-end: `run.json` written, index updated, finalization records returncode
  - Orchestrator integration: nested executor inherits parent thread via env
  - Backwards compat: `ARTAGENTS_THREADS_OFF=1` produces no artifacts and no errors; missing `.artagents/` is auto-created; existing `runs/*/` without `run.json` work unchanged
  - Variants: heterogeneous outputs (variant + ancillary + manifest) result in only the variants being grouped
  - Provenance: `hype.metadata.json` carries the block; `thread_label` survives index deletion
  - All existing pytest tests pass without modification
  _load_bearing: true_

- **SD-038** — Documentation deliverables for week-1 ship: `docs/threads.md` (one global doc explaining the model), one paragraph appended to `SKILL.md` instructing agents to run `thread show @active` at session start, footer line in `executors inspect` / `orchestrators inspect` output naming the active thread. **No per-tool `STAGE.md` is modified.** _load_bearing: true_

- **SD-039** — Schema versioning: `run.json`, `threads.json`, `selections.jsonl`, `groups.json`, and the `provenance` block all carry `schema_version: int`. Readers accept current and N-1; writers always write current; one-time migration runs on first read at upgrade time, with `.bak`. _load_bearing: true_

- **SD-040** — All paths in persisted JSON are repo-relative or content-addressed. No absolute paths. This makes thread export/sharing (a future feature) work for free as long as we hold the line now. _load_bearing: true_

- **SD-041** — Privacy / redaction policy. Briefs and prompts may contain PII or NDA-bound content. Today everything is plaintext under `runs/` and gets stamped into `run.json` and `external_service_calls`. The sprint must (a) document that `runs/` is gitignored and treated as local-only; (b) define a `secret`-prefixed env var convention that strips matching values from `cli_args_redacted`; (c) add a `--no-content` flag to `thread show` and the iteration-video HTML report that displays only hashes and labels for sensitive content. **Briefs themselves are not redacted by default** — the user opts in by placing them under `runs/<slug>/private/` (a documented convention). _load_bearing: true_
  Rationale: a thread is a creative artifact a user may want to share; the moment sharing exists, redaction must already work or the data is poisoned.

- **SD-042** — Concurrent variant-selection semantics. Two agents (or two terminals) may `thread keep` the same group with conflicting choices simultaneously. The append-only `selections.jsonl` makes this safe but the rule must be **explicitly documented for agents in `SKILL.md` and in the `[variants]` line help text**: "selections are append-only; the most recent write is authoritative on read; prior selections are preserved as history but do not affect current keepers." No locking on selection writes (the file is per-thread + append-only + line-buffered, so atomic appends are safe). _load_bearing: true_

- **SD-043** — Iteration-video cost guardrail. A 47-iteration thread generates ~47 `builtin.understand` calls in `iteration.summarize`. At realistic per-call costs ($0.005–$0.10) this is $0.25–$5 per render, which is fine — but a thread with 500 iterations or repeated re-renders is not. The sprint must (a) cap `iteration.summarize` at `max_iterations` (default 200, configurable, with a clear refusal message above the cap); (b) cache summaries by `(run_id, summarizer_model_version)` keyed in `.artagents/iteration_cache/` so re-renders only summarize new iterations; (c) surface estimated cost in `iteration_video inspect` output **before** the agent commits to a render. _load_bearing: true_
  Rationale: silent cost blowups erode trust; the agent must see the bill before incurring it.

- **SD-044** — Recorded tradeoffs (for future readers, not load-bearing). Two design choices were debated and settled but the alternatives are worth preserving so future maintainers don't relitigate:
  - **Scalar `thread_id` vs pure DAG-derived membership.** Settled as scalar (per SD-002 / SD-008) because (i) root runs with no consumed artifacts have no causal edge and need *some* attribution mechanism; (ii) membership lookups are O(1) field reads instead of graph traversals, which matters for the per-run `[thread]` prefix line; (iii) the agent's mental model needs a name to grab. The DAG (via `parent_run_ids` + `chosen_from_groups`) is preserved alongside the scalar and powers `thread doctor` heuristics, but membership is the scalar. If true multi-thread membership is ever needed (a single run that's a first-class member of two threads), this will need to flip.
  - **`thread` vs other nouns** (`pursuit`, `take`, `session`, `workstream`). Settled as `thread` because creators already say "pull on this thread" and the term appears in every prefix line where shortness matters. Git overload exists but is tolerable in the creative-tools domain. If git terminology bleeds in heavily (e.g., agents start typing `git thread` by mistake), revisit.
  _load_bearing: false_

## Open questions (for the sprint plan to resolve)

These are not settled; the sprint plan should make a call:

- Day-by-day allocation within each week (the broad week split is settled; the per-day breakdown is not).
- Whether `iteration.summarize` parallelism uses Python threads, asyncio, or sequential calls in the v1 MVP.
- Exact format of the prefix line beyond what SD-018 specifies (terminal width handling, color, truncation rules).
- Whether the in-flight reaper (SD-033) runs at process start or lazily on first index read.
- Where the `WORKSTREAMS.md` / `THREADS.md` global doc lives (likely `docs/threads.md`, but confirm against repo conventions).
- Concrete `quality_floor` formula in `iteration.collect`: which signals contribute and with what weights.

## Deferred for v1 (agent-complexity criterion)

These items appear in earlier discussion and Settled Decisions but are **explicitly deferred to a v1.5 follow-up sprint**. The criterion for deferral is *complexity in agent interactions or data shapes that adds little return for v1*. Each is reachable later without migration pain because the data shapes that survive are supersets of the trimmed shapes.

- **DEF-1 — Warn tier brief-novelty.** Implement only the Notice tier in v1 (first-run-of-process, gap >1h, cwd change, auto-reopen of archived thread). Defer Warn brief-novelty heuristic (Levenshtein distance against prior briefs) to v1.5 when there's real corpus to tune the threshold against. Removes a noisy line class agents would learn to ignore.
- **DEF-2 — `[thread-health]` smell line on `thread list`.** Detection-only nudge. Adds a parseable output format. Defer; the underlying data is still captured.
- **DEF-3 — `[hint]` line for sequential same-executor fan-out.** Soft nudge. Adds another output format. Defer.
- **DEF-4 — Four `role` values trimmed to two.** Ship `role: variant` and `role: other` (default) in v1. The `manifest` and `index` values are vocabulary an agent must learn for zero behavior change in v1. Add the finer enum when there's a consumer that branches on it.
- **DEF-5 — `preview_modes` array on `output_artifacts`.** Drop the field for v1. With three renderers in v1, dispatch by `kind` alone is sufficient. Add the field when there's a renderer demanding multi-mode disambiguation (e.g., a 3D renderer offering both turntable and wireframe).
- **DEF-6 — `chosen_from_groups` as a separate top-level edge.** Collapse into typed entries on `parent_run_ids`: `[{run_id, kind: "causal"}, {run_id, kind: "chosen", group: "g_..."}]`. Same information, one edge collection in `run.json` instead of two.
- **DEF-7 — Four iteration-video executors collapsed to two.** Ship `iteration.prepare` (collect + summarize + score combined) and `iteration.assemble` in v1. The internal three-way split inside prepare has no v1 reuse case. Halves the executor surface area an agent inspects.
- **DEF-8 — `external_service_calls` six fields trimmed to three.** Keep `model`, `model_version`, `request_id` (the irreversible provenance bits). Drop `seed`, `cost_usd`, `latency_ms` until a v1 consumer exists. Adding fields later to an array of dicts is forward-compatible.
- **DEF-9 — Cost block low/high range + recommendation triplet → single number.** `Estimated cost: ~$0.42 (47 calls × $0.009)`. One number to parse, no recommendation enum to interpret.
- **DEF-10 — `host_id` field.** No v1 or v2 consumer (cross-machine sync is not on the roadmap). Drop the field. Add when a consumer arrives.

**Net effect on the agent's interaction surface:**
- 2 stdout line formats instead of 5 (`[thread]`, `[variants]`, optional `Notice:`).
- 2 `role` values instead of 4.
- 5 fields per `output_artifact` instead of 7.
- 3 fields per `external_service_call` instead of 6.
- 2 iteration-video executors instead of 4.
- 1 cost number instead of low/high/recommendation triplet.

The killer demo, the data quality, and the privacy guarantees are unchanged. What's removed is the *agent-facing surface area* and the *guess-shape abstractions*.

**Schema versioning machinery (also trimmed):** keep `schema_version: 1` as a field on every persisted shape (cheap, no-regrets). **Drop** the formal N-1 reader, the migration helper machinery, and the `.bak`-rotation-test gate. The Frozen Schema Review process gate at end-of-Day-2 is sufficient discipline. Atomic write + `.bak` rotation for the index file remains (that's correctness, not migration).

## Non-goals

- Cross-machine sync of threads. (Capture `host_id` per SD-012 to enable later.)
- Public API stability of any of the new schemas across major versions.
- Migration tooling for runs produced before the layer ships. (Backfill per SD-034 is best-effort.)
- A general-purpose web UI for browsing threads. (`iteration.report.html` per orchestrator output is the only HTML deliverable.)
