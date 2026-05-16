# Astrid Pack Portfolio

User- and agent-facing reference: which packs are always available, which
ship with Astrid but use the installable-pack contract, and which depend
on third-party services and require explicit setup.

For the engineering source of truth (per-component rationale, dependency
edges, cross-pack import graph, Phase 8 anchor choice) see
[`docs/git-backed-packs/sprint-09/portfolio.md`](git-backed-packs/sprint-09/portfolio.md).

## Quick answer — what is always available?

- The **`builtin`** pack. It ships in the repo, requires no install
  action, and contains the canonical hype pipeline (`builtin.hype`),
  every primitive it depends on (transcribe, scenes, cut, render,
  validate, etc.), and the standalone primitives every agent can reach
  for end-to-end (`builtin.generate_image`, `builtin.publish`,
  `builtin.understand`, …).

Everything else listed below is **bundled** in the source tree but
treated as installable: it goes through the same `PackResolver` +
`PackValidator` code path that an external pack would. A few components
inside the `external/` pack additionally require a third-party account,
SDK install, or running daemon and are flagged separately as **Optional
installable**.

## Classification table

| Pack id         | Classification         | What ships                                                                                                       | Install action required?                                                  |
| --------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `builtin`       | **Core**               | Canonical hype pipeline + every primitive used end-to-end across packs.                                          | None — always available.                                                  |
| `iteration`     | Bundled installable    | `iteration.prepare`, `iteration.assemble` — iteration-video artifact preparation and assembly.                    | None at runtime; uses the installable-pack contract.                      |
| `upload`        | Bundled installable    | `upload.youtube` — publish a finished video via the shared banodoco-social Zapier integration.                    | YouTube/Zapier credentials in env (`YOUTUBE_*` / Zapier hook URL).        |
| `external`      | Bundled installable    | Adapters around third-party services (RunPod, fal.ai, VibeComfy/ComfyUI, Moirae). Pack itself is bundled.        | Per-executor: see Optional installable below.                             |
| `seinfeld`      | Bundled installable    | LTX-2.3 LoRA training stack (`seinfeld.dataset_build`, `seinfeld.lora_train`, `seinfeld.aitoolkit_*`, …).         | RunPod account + AI-Toolkit pod template; OpenAI / Gemini API keys for VLM steps. |
| `_core`         | (non-pack, infra)      | `_core/skill/SKILL.md` only — used by the skills installer; not a runtime pack.                                  | n/a                                                                       |

## Optional installable — third-party-service executors

These executors live inside the bundled `external` pack today but
depend on external accounts or SDKs. They are tracked for extraction
into separate installable packs — see
[`docs/git-backed-packs/sprint-09/optional-extraction.md`](git-backed-packs/sprint-09/optional-extraction.md).

| Executor id                       | Service                                          | What you need                                                            |
| --------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------ |
| `external.runpod.provision`       | RunPod GPU pods                                  | `RUNPOD_API_KEY`, network template id.                                   |
| `external.runpod.exec`            | RunPod GPU pods                                  | An existing pod handle (output of `external.runpod.provision`).          |
| `external.runpod.teardown`        | RunPod GPU pods                                  | `RUNPOD_API_KEY`, pod id.                                                |
| `external.runpod.session`         | RunPod GPU pods                                  | Composite of provision → exec → teardown with guaranteed cleanup.        |
| `external.moirae`                 | Moirae terminal-as-cinema renderer               | Moirae CLI installed locally (`pipx install moirae` or similar).         |
| `external.vibecomfy.run`          | VibeComfy / ComfyUI                              | VibeComfy CLI + running ComfyUI daemon or RunPod ComfyUI pod.            |
| `external.vibecomfy.validate`     | VibeComfy / ComfyUI                              | VibeComfy CLI (no daemon required for validate).                         |
| `external.fal_foley`              | fal.ai `hunyuan-video-foley`                     | `FAL_KEY`.                                                               |

## Deprecated

_(none in Sprint 9.)_

## Per-component classification of `builtin`

The `builtin` pack itself is partitioned by per-component classification —
**primitive**, **canonical-demo-internal**, **candidate-to-extract**.
That breakdown is shown alongside the capability tables in `SKILL.md`
and documented with full rationale at
[`docs/git-backed-packs/sprint-09/portfolio.md#3-builtin-per-component-rationale-step-13`](git-backed-packs/sprint-09/portfolio.md#3-builtin-per-component-rationale-step-13).

Short version:

- **primitive** — reusable building block end-to-end. Examples: `render`,
  `asset_cache`, `generate_image`, `transcribe`, `understand`,
  `publish`.
- **canonical-demo-internal** — called only from the canonical hype
  pipeline. Examples: `shots`, `triage`, `pool_build`, `cut`, `refine`,
  `validate`, `hype`.
- **candidate-to-extract** — would ship cleanly as its own future
  bundled-installable pack; recorded for a later extraction sprint and
  **not** moved this sprint. Examples: `animate_image`, `sprite_sheet`,
  `thumbnail_maker`, `event_talks`, `foley_map`, `human_review`.

## How to inspect a pack

```bash
python3 -m astrid packs list
python3 -m astrid packs inspect <pack_id>
python3 -m astrid packs inspect <pack_id> --agent
python3 -m astrid executors list
python3 -m astrid orchestrators list
```

`packs inspect --agent` prints the structured agent-facing metadata
declared in `pack.yaml` (`normal_entrypoints`, `do_not_use_for`,
`required_context`, secrets, dependencies, component counts, bounded
STAGE excerpts).
