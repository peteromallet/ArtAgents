# Seinfeld Pack — External Contract Migration Notes

The seinfeld pack is the Sprint 8 migration proof: a real built-in pack
converted to the external pack contract end-to-end (declared content roots,
v1 manifests, structured component layout). This document records the
compatibility gaps surfaced during migration and the temporary fields that
remain pending Sprint 9 follow-up.

## Status — closed in Sprint 9 (HEAD `c40c14f`)

Sprint 9 lands the remaining Sprint 8 gaps. Closure summary:

| Gap | Status | Sprint 9 landing                                                                                                                                                  |
| --- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 3   | closed | Legacy top-level `command:` removed from every seinfeld manifest (and every builtin/external manifest). Runner reads from `runtime.command.argv` exclusively.    |
| 4   | closed | Orchestrator `runtime.kind` removed in favour of `runtime.type`. `lora_train` orchestrator manifest no longer carries the collision.                              |
| 5   | closed | `additionalProperties: false` re-enabled on both `executor.json` and `orchestrator.json` v1 schemas. Every shipped manifest validates under the strict schema.   |
| 7   | closed | `kind: built_in` replaced with `kind: external` on every seinfeld component. Runtime dispatch already routed through `_run_external_executor`; rename is now semantic-honest. |
| 8   | closed | `pack.yaml` parser surgery — nested-YAML `content:` block is now read by the same code path that the resolver uses; the legacy `_parse_flat_yaml` rejection is gone. |

Sprint 9 also lands the following structural changes that affect this pack
(and every other pack) — not gaps per se, but worth recording here for the
migration audit trail:

- **In-process → subprocess dispatch.** `astrid run executor <id>` now
  shells out via the manifest's `runtime.command.argv` for every executor.
  The hype orchestrator's *internal* pipeline composition (the
  `build_pool_steps` graph that runs transcribe → … → validate) stays
  in-process; only direct executor invocation changed.
- **`build_pipeline_context` re-export removed** from
  `astrid/core/executor/__init__.py`. The symbol now lives only on its
  defining module; nothing outside the hype orchestrator package should
  import it.
- **Hype orchestrator helpers internalised.** `_optional_asset_path` and
  `_parse_asset_pairs` moved out of `astrid/core/orchestrator/runner.py`
  and into `astrid/packs/builtin/orchestrators/hype/_pipeline.py`, where
  the only callers live.
- **`qualified_id` regex relaxed** in the v1 schema (`_defs.json`) to
  permit multi-segment dotted ids. Existing 3-segment ids such as
  `external.runpod.exec`, `external.runpod.provision`,
  `external.vibecomfy.run` keep working without aliases.
- **Per-executor argv inventory** captured at
  `docs/git-backed-packs/sprint-09/builtin-argv-inventory.md`. That artifact
  is the source of truth for the strict-schema rewrite of every builtin
  manifest's `runtime.command.argv` and the eventual cleanup of stale
  flags.
- **Phase 8 parity anchor**: `asset_cache` was chosen as the named builtin
  whose end-to-end subprocess invocation is exercised by the new portfolio
  parity test. Rationale: stdlib-only, no OpenAI/ffmpeg dependencies, and
  an `HYPE_CACHE_DIR` env knob the test points at `tmp_path` so the prune
  scan exits cleanly. `transcribe` was **rejected** as an anchor because
  it imports the `openai` SDK and requires `OPENAI_API_KEY` + ffmpeg on
  PATH before any short-circuit can run. `validate` was **rejected**
  because it consumes rendered hype output (`--video --metadata
  --timeline`) and cannot be exercised standalone without first running
  the full pipeline.

The remainder of this document is the original Sprint 8 gap log, kept as
historical record. Gaps 1, 2, and 6 are structural (not landings) and
remain accurate as written.

## Gap 1 — Flat → structured content layout

`pack.yaml` originally declared:

```yaml
content:
  executors: '.'
  orchestrators: '.'
```

This relied on the resolver's legacy rglob fallback to scan every nested
directory for component manifests. After migration:

```yaml
content:
  executors: executors
  orchestrators: orchestrators
  schemas: schemas
```

Components now live under `executors/` and `orchestrators/` subdirectories
matching the v1 external-pack layout. `schemas:` is declared even though
the directory already existed; declaring it completes the full external
contract.

## Gap 2 — Python module paths shift

Moving components into subdirectories changes their import paths:

| Old | New |
| --- | --- |
| `astrid.packs.seinfeld.lora_register` | `astrid.packs.seinfeld.executors.lora_register` |
| `astrid.packs.seinfeld.repo_setup` | `astrid.packs.seinfeld.executors.repo_setup` |
| `astrid.packs.seinfeld.aitoolkit_stage` | `astrid.packs.seinfeld.executors.aitoolkit_stage` |
| `astrid.packs.seinfeld.aitoolkit_train` | `astrid.packs.seinfeld.executors.aitoolkit_train` |
| `astrid.packs.seinfeld.lora_eval_grid` | `astrid.packs.seinfeld.executors.lora_eval_grid` |
| `astrid.packs.seinfeld.lora_train` | `astrid.packs.seinfeld.orchestrators.lora_train` |
| `astrid.packs.seinfeld.dataset_build` | `astrid.packs.seinfeld.orchestrators.dataset_build` |

Every hardcoded reference is updated: 14 manifest references
(7 manifests × 2 fields each — `command.argv` + `metadata.runtime_module`,
counting `runtime.command.argv` for orchestrators), 7 cross-component
subprocess calls in `orchestrators/lora_train/run.py`, 7 test imports
under `tests/packs/seinfeld/`, and 7 STAGE / sprint-brief docs.

## Gap 3 — Legacy `command` vs v1 `runtime`

The runner reads `executor.command.argv` from the **top level** of the
manifest, while the v1 schema expects `runtime.command.argv` inside a
`runtime` object. Both fields coexist in each executor manifest during this
sprint — both point to the same updated module path. Removing the legacy
top-level `command` field is deferred to Sprint 9, after the runner is
taught to read from `runtime.command.argv` exclusively.

## Gap 4 — `runtime.kind` vs `runtime.type`

The orchestrator runner reads `runtime.kind` (legacy field) while the v1
schema requires `runtime.type`. Both fields coexist in orchestrator
manifests during this sprint, with identical values (`command`).
Consolidation onto `runtime.type` is deferred to Sprint 9.

## Gap 5 — `additionalProperties` temporarily relaxed

The v1 executor and orchestrator schemas (`astrid/packs/schemas/v1/
executor.json`, `orchestrator.json`) flip `additionalProperties: false` to
`true` for this sprint so the legacy fields (top-level `command`, legacy
metadata, cache/isolation hints, etc.) can coexist with the new v1 fields
without failing validation. The minimal example pack still validates
cleanly. Re-enabling `additionalProperties: false` is tracked for Sprint 9
once the full manifest restructuring is complete.

## Gap 6 — `samples_collage` stays at pack root

`samples_collage/` is a PEP 420 namespace package: no manifest, no
`__init__.py`. It is invoked as `python3 -m
astrid.packs.seinfeld.samples_collage.run` from the `lora_train`
orchestrator (line 191 of `orchestrators/lora_train/run.py`) and does
**not** migrate into `executors/`. The stray-manifest checker only flags
directories that contain a manifest file, so leaving `samples_collage` at
the pack root is safe. Do not add an `executor.yaml` here.

## Gap 7 — `kind: built_in` retained on all components

All 7 seinfeld components keep `kind: built_in` in their manifests even
though structurally the pack now matches the external contract. Runtime
dispatch already sends seinfeld components through `_run_external_executor`
because they lack `pipeline_step` metadata, so the runtime behavior matches
external packs regardless of the `kind` value. The semantic rename to
`kind: external` is deferred to Sprint 9 to keep the migration diff
minimal.

## Gap 8 — Nested YAML in `pack.yaml` (DEBT-025)

`pack.yaml` uses nested YAML for `content:` (indented keys for
`executors:`, `orchestrators:`, `schemas:`). The resolver-internal path
(`_load_pack_manifest_resolver` in `astrid/core/pack.py`) and the validator
(`PackValidator._load_yaml` in `astrid/packs/validate.py`) both use
`yaml.safe_load` and handle nested YAML correctly. However, the public
`load_pack_manifest()` flat parser (`_parse_flat_yaml`) rejects indented
lines and would crash on this pack.yaml.

This is pre-existing debt tracked as DEBT-025 and is **not** fixed in this
sprint. Callers that need to read pack.yaml for the seinfeld pack should
use the resolver-internal path (`_load_pack_manifest_resolver`) or call
`yaml.safe_load` directly, consistent with how `extract_trust_summary()`
already handles nested manifests.

## Sprint 9 Phase 6 Step 12 — no aliases needed

Sprint 9 renamed zero seinfeld public ids; every `seinfeld.<slug>` id from
Sprint 8 is preserved unchanged. See
`docs/git-backed-packs/sprint-09/migration-aliases.md` for the cross-pack
audit.
