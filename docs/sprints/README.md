# Reigh ↔ Banodoco Convergence — Sprint Briefs

Each file in this directory is a self-contained brief for one ~2-week sprint of the convergence work described in [`tools/docs/reigh-convergence-architecture.md`](../reigh-convergence-architecture.md). Each is intended to be consumed by a future `megaplan init --mode code --from-doc tools/docs/sprints/sprint-N-<slug>.md` invocation.

## Sequence

| # | Sprint | Phases | Deliverable Demo |
|---|---|---|---|
| 1 | [shared-schema-scaffold](sprint-1-shared-schema-scaffold.md) | Phase 1 partial | Banodoco emits a timeline that the shared schema validates; Python types regenerate from TS Zod via CI gate. |
| 2 | [schema-complete-and-reigh-lift](sprint-2-schema-complete-and-reigh-lift.md) | Phase 1 complete + Phase 2 partial | Reigh loads existing timelines unchanged; serializer tolerates new fields. |
| 3 | [loud-placeholders-and-ops-extraction](sprint-3-loud-placeholders-and-ops-extraction.md) | Phase 2 complete + Phase 3 partial | Unknown `clipType` shows labeled placeholder, not silent black void; read-only Theme chip visible. |
| 4 | [timeline-ops-and-composition-prep](sprint-4-timeline-ops-and-composition-prep.md) | Phase 3 complete + Phase 4a/b | Agent can mutate `params` / `theme` / `theme_overrides` via chat; theme-api stable; codemod ready. |
| 5 | [composition-and-renderer-dispatch](sprint-5-composition-and-renderer-dispatch.md) | Phase 4 complete | A saved `clipType="section-hook"` renders the actual themed frame in Reigh's `@remotion/player` preview. |
| 6 | [banodoco-pipeline-and-publish](sprint-6-banodoco-pipeline-and-publish.md) | Phase 5 + Phase 6 | `tools/pipeline.py publish` ships a Banodoco-authored timeline into Reigh; user opens it and previews correctly. |
| 7 | [bidirectional-agent-handoff](sprint-7-bidirectional-agent-handoff.md) | Phase 7 | Reigh chat enqueues `banodoco_timeline_generate`; worker writes the result; user sees it appear. |
| 8 | [themed-render-via-orchestrator](sprint-8-themed-render-via-orchestrator.md) | Phase 8 | Reigh user authors a themed timeline and exports an MP4 via `banodoco_render_timeline`. |

## Schedule risk (load-bearing)

Codex's sprint allocation puts all of Phase 4 in Sprint 5 (5 person-weeks budget) but its own per-phase estimate flags Phase 4 at **7 pw**. The 2 pw shortfall is real — Phase 4 covers shared composition packaging, plugin registry codegen, theme-api stability, codemod, first peer-dep theme package, and the `TimelineRenderer.tsx` dispatch replacement. If Sprint 5 spills, Phase 5 + Phase 6 (Sprint 6) are likely to slip too, and Phase 8 becomes a Sprint 9 / post-window item.

Mitigation: Sprint 5 targets Phase 4a/b/c (packaging) with stretch goal 4d (renderer dispatch). If 4d slips, it becomes Sprint 6's first half and Phase 5 + Phase 6 split across Sprints 6 and 7, pushing Phase 7 → Sprint 8 and Phase 8 → Sprint 9. Each brief flags this risk where relevant.

## Inheritance

Every sprint brief inherits **all `SD-NNN` settled decisions** from the architecture doc's Settled Decisions section verbatim. Cite them by id; don't restate. The architecture doc is the source of truth.

## Load-bearing cross-cutting decisions

Two decisions cross all sprints and must be honored everywhere:

- **SD-034 Task Lifecycle Contract** — every async task type honors idempotency-via-versioned-RPC, retry semantics on 409, `correlation_id`, writer-identity-vs-mutation split, status path (realtime + task-status poll, no SSE), artifact write semantics. Sprints 7 and 8 implement; earlier sprints must not introduce designs that conflict.
- **SD-035 Phase 8 worker-runtime contract** — gates Sprints 7 and 8. The choice between Pinned Railway / per-task RunPod / in-process Python must be settled before Sprint 7 code lands.
