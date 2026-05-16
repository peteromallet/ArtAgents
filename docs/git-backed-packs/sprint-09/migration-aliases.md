# Sprint 9 — Migration Aliases

**No public ids are renamed by Sprint 9.** The `qualified_id` regex relaxation
in Step 9.0 (`astrid/packs/schemas/v1/_defs.json`) preserved every existing id
across all five runtime packs, including the 3-segment `external.*` ids that
would otherwise have failed the original 2-segment-only pattern. No aliases
table is required.

This document is the explicit Sprint 9 Phase 6 Step 12 sign-off that the
migration did not move any public id.

## Audit summary

Audited via direct manifest reads against
`docs/git-backed-packs/sprint-09/portfolio.md`:

| Pack       | Components in audit | Components in portfolio | Renames |
|------------|--------------------:|------------------------:|--------:|
| `builtin`   | 42 (33 ex + 9 or)  | 42                      | 0       |
| `external`  | 8                   | 8                       | 0       |
| `iteration` | 2                   | 2                       | 0       |
| `upload`    | 1                   | 1                       | 0       |
| `seinfeld`  | 7 (5 ex + 2 or)    | 7                       | 0       |
| **Total**   | **60**              | **60**                  | **0**   |

## Multi-segment ids preserved by the Step 9.0 regex relaxation

The original `qualified_id` regex accepted exactly two dot-separated segments
(`^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`). Step 9.0 relaxed it to admit additional
dot-separated tail segments, which preserves every multi-segment id below.

| public id                       | pack       | kind     | manifest                                                                 |
|---------------------------------|------------|----------|--------------------------------------------------------------------------|
| `external.runpod.provision`     | `external` | executor | `astrid/packs/external/executors/runpod_provision/executor.yaml`         |
| `external.runpod.exec`          | `external` | executor | `astrid/packs/external/executors/runpod_exec/executor.yaml`              |
| `external.runpod.teardown`      | `external` | executor | `astrid/packs/external/executors/runpod_teardown/executor.yaml`          |
| `external.runpod.session`       | `external` | executor | `astrid/packs/external/executors/runpod_session/executor.yaml`           |
| `external.vibecomfy.run`        | `external` | executor | `astrid/packs/external/executors/vibecomfy_run/executor.yaml`            |
| `external.vibecomfy.validate`   | `external` | executor | `astrid/packs/external/executors/vibecomfy_validate/executor.yaml`       |

These six ids are the only ones in the portfolio with more than two segments.
The remaining 54 ids are all 2-segment (`<pack>.<slug>`) and would have parsed
under either the original or the relaxed regex.

## Test coverage

`tests/packs/test_public_id_resolution.py` parametrizes over the six
multi-segment ids above plus one canonical 2-segment id per remaining pack and
asserts each resolves through the default executor / orchestrator registries.
