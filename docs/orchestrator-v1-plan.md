---
title: "Orchestrator V1 Plan"
mode: "doc / metaplan"
status: "draft"
scope: "task-mode orchestrator runtime and authoring plan"
---

# Orchestrator V1 Plan

## 1. Executive Summary

Astrid V1 adds task mode: a single-host, file-based way to put an agent inside a frozen plan and advance it through creative pipeline work one permitted command at a time. The plan can mix code, AI, and human steps without introducing a daemon, web server, or pretend sandbox. Runtime behavior collapses to three step kinds: `code` for deterministic argv subprocesses, `attested` for agent or human work that requires identity-pinned acknowledgment and evidence, and `nested` for child-plan delegation whose structure remains visible to the gate for hashing and pinning. Iteration and fan-out are not separate kinds; they are body attributes that can wrap any step or nested block through `repeat.until` and `repeat.for_each`. Migration stays additive: existing pack mechanics, JSON manifests, and `python` / `command` runtime kinds keep working while the new Python DSL compiles hash-pinned task plans for V1 runs.

## 2. Goals & Non-Goals

Goals: freeze task-mode runs around immutable `plan.json`; gate every command before runner side effects; use exactly `code`, `attested`, and `nested`; model loops through `repeat`; use golden `events.jsonl` as regression output; split lifecycle verbs by audience; keep packs and legacy orchestrator manifests loadable.

Non-goals: no daemon, no web server, no HMAC or keyed crypto, no `.index.db`, no shared CAS, and no sandbox against malicious agents. V1 is honor-based with strong logging and accidental-edit tripwires.

## 3. Data Model

Task-mode state lives under `~/Documents/reigh-workspace/astrid-projects/<slug>/`:

```text
active_run.json
runs/<run-id>/plan.json
runs/<run-id>/events.jsonl
runs/<run-id>/AGENT.md
runs/<run-id>/steps/<step-id>/produces/
runs/<run-id>/steps/<step-id>/iterations/NNN/
runs/<run-id>/steps/<step-id>/items/<item-id>/
runs/<run-id>/inbox/
.cas/<sha256>
```

`active_run.json` is `{ "run_id": "<run-id>", "plan_hash": "sha256:<hex>" }`. `plan.json` is immutable after `astrid start`, supersedes checklist naming because the shape is a tree, and is the runtime truth the gate hashes; existing `OrchestratorPlan` / `OrchestratorPlanStep` in `astrid/core/orchestrator/runner.py` remain dry-run display scaffolding. `events.jsonl` is append-only and hash-chained as plain `sha256(prev_hash + canonical_event_json)` with no HMAC. There is no `.index.db`; status and audit read files directly.

## 4. Step Kinds

`code` is deterministic argv subprocess execution. It is a strict superset of `RUNTIME_KINDS={python,command}` in `astrid/core/orchestrator/schema.py`, may call `python3 -m astrid executors run <name> ...`, and must not call `astrid orchestrators run`.

`attested` is agent or human work with instructions, produces, identity-pinned ack, and evidence. Agent attestations require `--agent <id>`. Human attestations require `--actor <name>` matching `ARTAGENTS_ACTOR`. Self-acks and unpinned actors are rejected.

`nested` is the only sub-orchestrator delegation mechanism. The child plan is data in the compiled tree so the gate can hash, pin, and derive cursors from its structure.

## 5. Iteration & Fan-Out

Iteration and fan-out are body attributes, not kinds. `repeat.until` supports `user_approves`, `verifier_passes`, and `quorum`, with `max_iterations` and `on_exhaust`; attempts write under `iterations/NNN/`. `repeat.for_each` expands a body over an input set and writes per-item state under `items/<item-id>/`; `ack --item <id>` supports partial approval.

## 6. Produces & Inline Checks

`produces` declares artifacts and checks beside the step that creates or attests them, using `astrid.verify` helpers: `file_nonempty`, `json_schema`, `json_file`, `audio_duration_min`, `image_dimensions`, and `all_of`. The gate runs checks after completion or ack; failure records the verifier output and rewinds the cursor. `passes_test` remains a normal `code` step. Sentinel-existence-only checks are rejected for non-trivial attested outputs.

## 7. Gate Above Dispatch

The gate checks: `active_run.json` exists; `plan.json` hash matches the pin; `events.jsonl` chain is intact; and the incoming command matches `plan[derived_cursor].command`. Any failure exits non-zero and prints one exact recovery command: start for missing active run, abort for integrity failure, or `astrid next --project <slug>` for command mismatch.

Ordering is load-bearing. The first gate sits in `astrid/pipeline.py:15`; a defensive decorator re-checks at `astrid/core/orchestrator/runner.py:132`, the top of `run_orchestrator()`, before `_prepare_project_request()` at line 135 and `thread_wrapper.begin_orchestrator_run()` at line 136. Rejection writes zero project-run files. `events.jsonl` is the single task-mode provenance surface; `astrid/threads/wrapper.py:21-26` keeps existing thread env provenance in `runs/<id>/run.json`.

## 8. Lifecycle Verbs

Task-mode verbs extend top-level `astrid/pipeline.py:15`, not `astrid orchestrators`. Existing `astrid orchestrators run|list|inspect|validate` in `astrid/core/orchestrator/cli.py` stays unchanged.

Agent mid-run verbs: `next`, `ack`, `status`, `abort`. Operator verbs: `start`, `abort`, `status`, `runs ls`. Author verbs: `author new`, `author check`, `author describe`, `author test`, `author compile`, `author explain`.

## 9. Ack Decisions

`approve` advances when the current step is awaiting approval and checks pass. `retry` is only valid after verifier failure and reruns with stderr/verifier output as feedback. `iterate --feedback` is only valid for `repeat.until=user_approves` and appends to cumulative constraints. `abort` ends the run. Attested steps require `--agent` or `--actor` as above; `--item <id>` targets one `repeat.for_each` item.

## 10. Authoring

`astrid.orchestrate` is the only committed representation for new task plans. `astrid author compile` writes gitignored `<pack>/build/<orch>.json`, and runtime hashes that compiled artifact. Pack additions are `<pack>/<orch>.py`, `<pack>/build/<orch>.json`, `<pack>/fixtures/<name>/`, and `<pack>/golden/<name>.events.jsonl`.

`author check` is sub-second static validation: schema, references, nested plan resolution, semantic checks for non-trivial attested produces, sentinel-only rejection, and rejection of `code` argv to `astrid orchestrators run`. `author describe` prints the DAG. `author test --fixture` runs `--dry-run --auto-approve` and diffs `events.jsonl` against the fixture golden.

## 11. Stop-Hook Nudge

V1 nudge is out-of-process and Claude Code only. A Stop hook runs `astrid next`; every `next` response includes the prohibition preamble verbatim, including repeated calls, so context decay is countered by re-injection.

## 12. Phasing

Phase 1 - Kernel + `ARTAGENTS_TASK_RUN_ID` env contract

- Scope: hash-chained `events.jsonl`, plan hash pin, active run pointer, gate above dispatch, and env contract.
- Files touched: `astrid/core/task/{gate.py,events.py,active_run.py,env.py}`, `astrid/pipeline.py:15`, `astrid/core/orchestrator/runner.py:132`, `astrid/core/orchestrator/runner.py:135`, `astrid/core/orchestrator/runner.py:136`, `astrid/core/executor/runner.py`, `astrid/packs/builtin/hype/run.py`, `astrid/core/project/run.py`, `astrid/threads/wrapper.py:21-26`.
- Classification: additive.
- Exit criteria: hand-authored `plan.json` runs end-to-end; rejected command writes zero project-run files; all three `prepare_project_run()` callers honor `ARTAGENTS_TASK_RUN_ID`; `tests/test_project_runs.py` still passes for standalone runs.
- Test strategy: hash/gate unit tests, `pytest tests/test_project_runs.py`, and one golden code-step event run.

Phase 2 - Three step kinds

- Scope: implement `code`, `attested`, and `nested` event records while legacy `python` and `command` manifests still load.
- Files touched: `astrid/core/task/`, `astrid/core/orchestrator/schema.py`, `astrid/core/orchestrator/runner.py`, `astrid/core/executor/runner.py`.
- Classification: additive.
- Exit criteria: a non-hype task plan runs `code(argv=["python3", "-m", "astrid", "executors", "run", "<leaf-executor>", ...])`; attested and nested dry runs emit expected events.
- Test strategy: step-kind validation tables and golden events for all three kinds.

Phase 3 - Produces + repeat

- Scope: inline produces checks, cursor rewind, `repeat.until`, and `repeat.for_each`.
- Files touched: `astrid/core/task/`, `astrid/verify/`, `astrid/core/orchestrator/runner.py`.
- Classification: additive.
- Exit criteria: failed checks rewind; `iterations/NNN/` and `items/<item-id>/` appear only when needed; partial item approval works.
- Test strategy: verifier unit tests and golden runs for retry, iteration, and fan-out.

Phase 4 - Authoring + structure guardrails

- Scope: DSL, verify helpers, `author new/check/describe`, and static guardrails.
- Files touched: `astrid/orchestrate/`, `astrid/verify/`, `astrid/pipeline.py:15`, `astrid/structure.py:27` (`TOP_LEVEL_ARTAGENTS_DIRS += orchestrate, verify`), `tests/test_doctor_setup.py`, root `.gitignore` excluding `<pack>/build/`.
- Classification: additive.
- Exit criteria: `python3 -m astrid doctor` accepts new packages; `author check` rejects code argv to orchestrators; build JSON is gitignored.
- Test strategy: `pytest tests/test_doctor_setup.py`, author-check tests, describe snapshots.

Phase 5 - Lifecycle verbs split

- Scope: top-level agent/operator/author verbs while `astrid orchestrators` remains unchanged.
- Files touched: `astrid/pipeline.py:15`, `astrid/core/task/`, `tests/test_canonical_cli.py`.
- Classification: additive.
- Exit criteria: `next`, `ack`, `status`, `abort`, `start`, `runs ls`, and `author ...` dispatch correctly.
- Test strategy: `pytest tests/test_canonical_cli.py` plus golden ack-decision runs.

Phase 6 - Stop-hook nudge

- Scope: Claude Code hook and mandatory preamble on every `next`.
- Files touched: `astrid/core/task/`, `docs/AGENT.md` template, hook setup docs.
- Classification: additive.
- Exit criteria: repeated `next` calls include the preamble verbatim.
- Test strategy: CLI snapshots and one no-cursor-move golden run.

Phase 7 - Per-project CAS

- Scope: `<slug>/.cas/<sha256>` and symlink-based produces.
- Files touched: `astrid/core/task/`, `astrid/core/project/run.py`.
- Classification: additive.
- Exit criteria: artifacts store once and link into step produces; no shared CAS exists.
- Test strategy: CAS unit tests and artifact-reuse golden run.

Phase 8 - Inbox surface

- Scope: `runs/<run-id>/inbox/` completion-signal protocol.
- Files touched: `astrid/core/task/`, lifecycle status/next handlers.
- Classification: additive.
- Exit criteria: inbox files validate into events; stale or malformed files are ignored.
- Test strategy: inbox parser tests and external-attestation golden run.

Phase 9 - Author test with golden runs

- Scope: `author test --fixture` dry-runs, auto-approves, and diffs against `<pack>/golden/<fixture>.events.jsonl`.
- Files touched: `astrid/orchestrate/`, `astrid/core/task/`, `astrid/packs/*/fixtures/`, `astrid/packs/*/golden/`.
- Classification: additive.
- Exit criteria: fixture tests fail on event drift and pass when intentionally regenerated.
- Test strategy: author-test integration tests and canonical pack golden fixtures.

## 13. Canonical Migration

Use `astrid/packs/builtin/hype/` as the canonical additive migration. Add `hype.py`, gitignored `build/hype.json`, `fixtures/smoke/`, and `golden/smoke.events.jsonl`; keep `orchestrator.yaml`, `STAGE.md`, and `run.py`. Existing JSON still loads through `load_orchestrator_manifest` in `astrid/core/orchestrator/schema.py`.

```python
from astrid.orchestrate import code, nested, plan
from astrid.verify import file_nonempty, json_file

hype = plan("builtin.hype", [
    code("transcribe", argv=["python3", "-m", "astrid", "executors", "run", "builtin.transcribe", "..."], produces={"transcript": json_file("transcript.json")}),
    code("cut", argv=["python3", "-m", "astrid", "executors", "run", "builtin.cut", "..."], produces={"timeline": json_file("hype.timeline.json"), "assets": json_file("hype.assets.json")}),
    code("render", argv=["python3", "-m", "astrid", "executors", "run", "builtin.render", "..."], produces={"video": file_nonempty("hype.mp4")}),
    nested("thumbnail", plan="builtin.thumbnail_maker", produces={"thumbnail": file_nonempty("thumbnail.png")}),
])
```

Sub-orchestrator delegation appears only as `nested`. Child `prepare_project_run()` calls inherit `ARTAGENTS_TASK_RUN_ID`, skip child `run.json`, and mirror produces under parent `runs/<task-run-id>/steps/<step-id>/produces/`; standalone behavior stays unchanged.

## 14. Documentation Deliverables

| Document | Audience | Size target | Content |
| --- | --- | --- | --- |
| `AUTHORING.md` | Human and LLM authors | About one page | DSL, verify helpers, compile/check/test, and code-vs-nested boundary. |
| `AGENT.md` template | In-flight agent | Short run contract | Dropped into `runs/<run-id>/AGENT.md` with task-mode rules and preamble. |
| `README.md` updates | Operators | Quickstart | `start`, `next`, `ack`, `status`, and recovery examples. |
| `AGENTS.md` update | Agents | Cross-link | Points to `AUTHORING.md` and repeats qualified `<pack>.<orch>` ids. |

## 15. Risk Register

| Risk | Trigger | Mitigation |
| --- | --- | --- |
| Single-host assumption | No daemon means two operators can race. | Validate the chain before each command and print recovery commands. |
| Semantic verifier discipline | Authors regress to sentinel-existence checks. | `author check` rejects sentinel-only attested outputs. |
| Context-decay re-injection | Long sessions forget prohibitions. | Stop-hook nudge calls `next`; every response repeats the preamble. |
| Honor-model boundary | A malicious local agent edits files. | State plainly that hash chains are logs and tripwires, not sandboxing. |
| V1 infrastructure creep | A daemon, web server, HMAC, `.index.db`, or shared CAS is proposed as a shortcut. | Reject it for V1 and keep the design single-host, file-based, plain-hash, file-walk, and per-project. |

## 16. Cut Points

Phase 3 ships a useful frozen-plan runner: gate, three step kinds, produces checks, and repeat/fan-out. Phase 5 ships the author-friendly CLI surface. Phases 6-9 are polish and scale: nudge, CAS, inbox, and golden author tests.

## 17. Open-Call Confirmations

- A1 Confirmed: nested stays data visible to the gate, and `code` argv to `astrid orchestrators run` is forbidden.
- A2 Confirmed: `astrid.orchestrate` Python DSL is the only committed representation, and `<pack>/build/<orch>.json` is gitignored.
- A3 Confirmed: V1 drops `.index.db` and ships with direct file-walk verbs.
- A4 Confirmed: kernel modules land in new `astrid/core/task/` files above the legacy runners.
- A5 Confirmed: lifecycle, operator, and author verbs extend top-level `astrid/pipeline.py:15`; existing `astrid orchestrators` verbs stay unchanged.
- A6 Confirmed: `code` is deterministic argv subprocess execution, may target `astrid executors run <name>`, and must not target `astrid orchestrators run`.
- A7 Confirmed: the gate runs before both `_prepare_project_request()` and `thread_wrapper.begin_orchestrator_run()`, with zero project-run side effects on rejection.
- A8 Confirmed: root `.gitignore` excludes pack-local `<pack>/build/` outputs.
- A9 Confirmed: `ARTAGENTS_TASK_RUN_ID` is the inheritance env surface across orchestrator, executor, hype, project-run, and thread-wrapper code paths.
- A10 Confirmed: task mode skips child `run.json` records but preserves child output dirs and hype artifact mirroring under parent step produces.
- A11 Confirmed: `astrid/orchestrate/` and `astrid/verify/` are new top-level packages accepted by structure checks.

## Settled Decisions

SD-001 three step kinds: Task mode has exactly `code`, `attested`, and `nested` so execution, evidence, and delegation stay distinct.

SD-002 repeat body attributes: Iteration and fan-out are `repeat.until` and `repeat.for_each` body attributes so they apply uniformly to steps and nested bodies.

SD-003 plan naming: Runtime uses immutable `plan.json` instead of checklist naming because the structure is a tree with nested bodies and loops.

SD-004 event hash chain: `events.jsonl` uses plain `sha256(prev_hash + canonical_event_json)` with no HMAC because V1 needs an edit tripwire, not keyed tamper resistance.

SD-005 no index database: V1 ships without `.index.db` because file walking and grep over `events.jsonl` are adequate until measured otherwise.

SD-006 committed DSL: `astrid.orchestrate` Python DSL is the only committed authoring representation so source review happens in Python.

SD-007 generated build JSON: `<pack>/build/<orch>.json` is gitignored and root `.gitignore` excludes pack build outputs because runtime pins generated artifacts.

SD-008 per-project CAS: V1 uses only per-project `<slug>/.cas/<sha256>` storage because shared CAS adds coordination without current need.

SD-009 code boundary: `code` is deterministic argv, a strict superset of `RUNTIME_KINDS={python,command}`, may target `astrid executors run <name>`, and must not target `astrid orchestrators run`.

SD-010 nested boundary: Sub-orchestrator delegation is exclusively `nested` so the gate can hash and pin child structure.

SD-011 gate checks: The gate validates active run presence, plan hash, event chain, and incoming command match before dispatch and prints the exact recovery command on rejection.

SD-012 gate ordering: The gate runs before `_prepare_project_request()` and `thread_wrapper.begin_orchestrator_run()` so rejected commands create zero project-run side effects.

SD-013 provenance surface: `events.jsonl` is the single write surface for task-mode provenance while thread provenance remains in `runs/<id>/run.json`.

SD-014 lifecycle dispatch: Task-mode lifecycle verbs extend `astrid/pipeline.py:15` and the existing `astrid orchestrators` CLI remains unchanged.

SD-015 task kernel namespace: New kernel modules live in `astrid/core/task/` to isolate gate, events, active-run, and env logic from legacy runners.

SD-016 structure guardrails: `TOP_LEVEL_ARTAGENTS_DIRS` adds `orchestrate` and `verify`, with `tests/test_doctor_setup.py` updated so doctor accepts the new packages.

SD-017 task run env: `ARTAGENTS_TASK_RUN_ID` is the integration surface for orchestrator, executor, and hype child calls to attach to the parent task run.

SD-018 child output preservation: Task mode preserves child output dirs and mirrors hype artifacts under `runs/<task-run-id>/steps/<step-id>/produces/` while standalone behavior stays unchanged so `tests/test_project_runs.py` keeps passing.

SD-019 attestor identity: Agent attestations require `--agent`, human attestations require `--actor` matching `ARTAGENTS_ACTOR`, and self-acks are rejected.

SD-020 ack rules: `approve` advances, `retry` is only valid after verifier failure, `iterate --feedback` is only valid for `repeat.until=user_approves`, and `abort` ends the run.

SD-021 inline produces checks: Produces inline checks replace verifier substeps while `passes_test` remains a normal `code` step.

SD-022 semantic checks: `author check` rejects sentinel-only attested outputs because non-trivial artifacts need semantic validation.

SD-023 stop-hook preamble: Every `astrid next` output includes the prohibition preamble verbatim because repeated injection fights context decay.

SD-024 additive migration: Existing `OrchestratorDefinition` JSON manifests and `RUNTIME_KINDS={python,command}` keep working because V1 migration is additive.

SD-025 honor model: V1 is single-host and honor-based with strong logging because it does not defend against malicious local agents.

SD-026 cut points: Phase 3 is the frozen-plan runner ship point and Phase 5 is the author-friendly lifecycle ship point.

SD-027 canonical migration: `astrid/packs/builtin/hype/` is the canonical migration example because it exercises the existing executor pipeline and additive pack layout.

SD-028 phasing order: V1 implementation follows build phases 1-9 so kernel, step semantics, authoring, lifecycle, nudge, CAS, inbox, and golden tests land in dependency order.

SD-029 V1 infrastructure limits: V1 excludes daemon, web server, HMAC/keyed crypto, `.index.db`, and shared CAS so the implementation stays file-based, inspectable, and additive.

## Phase 1 status (kernel landed)

Kernel modules under `astrid/core/task/`: `events.py`, `active_run.py`, `plan.py`, `env.py`, `gate.py`, `__init__.py`. Hash chain is plain `sha256(prev_hash + canonical_event_json(event))` per SD-004; no HMAC, no `.index.db`, no shared CAS (SD-029).

Gate is decorated above dispatch at four entry points: `astrid/pipeline.py` (top-level `main`, fresh dispatch), and defensive reentry checks in `astrid/core/orchestrator/runner.py:run_orchestrator`, `astrid/core/executor/runner.py:run_executor`, and `astrid/packs/builtin/hype/run.py:main` — each placed strictly before `_prepare_project_request()` / `thread_wrapper.begin_orchestrator_run()` so a rejected command writes zero project-run files (SD-012).

Three `prepare_project_run` callers (orchestrator runner, executor runner, hype direct entry) honor the env contract via the centralized branch inside `prepare_project_run` keyed on `is_in_task_run(slug)`; `ARTAGENTS_TASK_RUN_ID` / `ARTAGENTS_TASK_PROJECT` / `ARTAGENTS_TASK_STEP_ID` redirect run output under `<projects_root>/<slug>/runs/<task-run-id>/steps/<step-id>/` and suppress child `run.json` / cumulative `runs.json` writes; hype artifacts mirror under `<step_dir>/produces/` (SD-018). `ARTAGENTS_TASK_STEP_ID` is a Phase 1-introduced sibling env var the design doc names alongside `ARTAGENTS_TASK_RUN_ID`. `command_for_argv(argv)` produces the canonical command-string form that authored `plan.json` step commands must match exactly, including the `--project <slug>` token.

Recovery strings are emitted verbatim per SD-011 (`astrid abort --project <slug>` for active-run / plan-hash / chain / exhausted; `astrid next --project <slug>` for off-cursor), even though those verbs ship in Phase 5.

Deferred: full subprocess env propagation into child code-step launchers (Phase 2; Phase 1 only ships the `child_subprocess_env()` helper used by the e2e smoke); lifecycle verbs `astrid next` / `abort` / `approve` / `retry` / `iterate` (Phase 5); per-project CAS at `<slug>/.cas/<sha256>` (Phase 7, SD-008). New step kinds (`code`, `attested`, `nested`), produces inline checks, and the Python authoring DSL all remain out of Phase 1 scope.
