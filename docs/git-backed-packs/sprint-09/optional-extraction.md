# Sprint 9 — Optional Installable Extraction Path

Phase 3 / Step 7 of `sprint-9-pack-portfolio-20260516-0040/plan_v5.md`. Documents the path by which the four
third-party-service executors under `astrid/packs/external/executors/` are extracted out of the source tree
into standalone, separately-installed packs in a **future** sprint.

**This sprint does NOT move them.** See §3 below for the explicit non-action statement. Sprint 9 only:
1. Restructures `external/` to the bundled-installable layout (Phase 2 Step 5, partially pre-landed on this
   branch — see `inventory.md` §6).
2. Splits the runpod and vibecomfy multi-executor wrappers into sibling manifests (Step 5.2).
3. Adds `schema_version: 1` to every per-component manifest (Step 5.5, already complete on this branch).
4. Documents the extraction path here.

## 1. Candidate optional-installable inventory

The four `external/*` executor packages all wrap a **third-party service** behind a thin Astrid manifest
+ adapter. They are correctly classified as Optional Installable because:

- they require credentials / API keys / external SDKs that not every Astrid user will hold;
- they ship for the *minority* use case (each is opt-in);
- their failure modes (rate limits, billing, regional availability) are outside Astrid's runtime guarantees;
- removing them from the Core source tree shrinks Astrid's install footprint and dependency surface.

| candidate                                                | target external-repo name   | git-url it would install from                          | runtime-level third-party dependency                                                                                                                                                                                | secrets / env vars                                          | runtime adapter pattern                                                |
|----------------------------------------------------------|-----------------------------|--------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------|-----------------------------------------------------------------------|
| `external.fal_foley` (one executor)                      | `astrid-pack-fal-foley`     | `https://github.com/peteromallet/astrid-pack-fal-foley` | `fal-client>=0.7.0` (already pinned in `requirements.txt`). Adapter currently reaches into `astrid.packs.builtin.orchestrators.logo_ideas.run` for the shared `fal` HTTP helpers (`FAL_QUEUE_URL`, `_http_get_bytes`, `_http_post_json`, `poll_fal_result`) and `astrid.packs.builtin.orchestrators.vary_grid.run._load_env_var`. The extraction must vendor or repackage those helpers (see §2.4). | `FAL_KEY` (read via `_load_env_var`).                       | Subprocess `python -m astrid.packs.external.executors.fal_foley.run`. |
| `external.moirae` (one executor)                         | `astrid-pack-moirae`        | `https://github.com/peteromallet/astrid-pack-moirae`    | The `moirae` PyPI package (Moirae is a separate project at `https://github.com/peteromallet/Moirae`). The adapter runs `python -m moirae <screenplay> -o <output>` via subprocess.                                  | None at the Astrid layer (Moirae owns its own credentials). | Subprocess shim that delegates to `python -m moirae`.                  |
| `external.runpod` (4 sibling executors: `external.runpod.provision`, `external.runpod.exec`, `external.runpod.teardown`, `external.runpod.session`) | `astrid-pack-runpod`        | `https://github.com/peteromallet/astrid-pack-runpod`    | `runpod_lifecycle` (imported as `from runpod_lifecycle.api import find_gpu_type`, etc.). Today `runpod_lifecycle` lives in a separate skill / package surfaced by the `runpod-lifecycle` skill in the workspace.   | `RUNPOD_API_KEY` (read inside `runpod_lifecycle`).          | Single `astrid.packs.external.executors.runpod.run` module dispatched by subcommand (`provision` / `exec` / `teardown` / `session`); manifests share the runtime module and differ only in argv. |
| `external.vibecomfy` (2 sibling executors: `external.vibecomfy.run`, `external.vibecomfy.validate`) | `astrid-pack-vibecomfy`     | `https://github.com/peteromallet/astrid-pack-vibecomfy` | The `vibecomfy` package (`from vibecomfy.cli import …` invoked via `python -m vibecomfy.cli {command} {workflow}`).                                                                                                | Whatever VibeComfy itself reads (FAL / ComfyUI / RunPod credentials depending on workflow). | Subprocess shim that delegates to `vibecomfy.cli`.                     |

**Dependency declarations needing migration.** When each pack ships in its own repo, its `requirements.txt`
(or `pack.yaml`'s `dependencies:` block once the contract grows one) must declare its own runtime deps. The
canonical migration:

| candidate          | Astrid-today requirements line       | future-pack declaration                                                                                                                                                                                                                            |
|--------------------|--------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `fal_foley`        | `fal-client>=0.7.0` (in core)        | move to `astrid-pack-fal-foley/requirements.txt`. Core Astrid drops the line once `external/executors/fal_foley/` is removed.                                                                                                                       |
| `moirae`           | (no current core declaration)        | declare `moirae>=<version>` in `astrid-pack-moirae/requirements.txt`. Document the source repo (`https://github.com/peteromallet/Moirae`) in the pack's `README.md`.                                                                              |
| `runpod`           | (no current core declaration — `runpod_lifecycle` is provided by the skill, not by `requirements.txt`) | declare `runpod_lifecycle @ git+https://github.com/…` (or its eventual PyPI name) in `astrid-pack-runpod/requirements.txt`. Ship the `runpod-lifecycle` skill alongside or document it as a co-installed prerequisite. |
| `vibecomfy`        | (no current core declaration)        | declare `vibecomfy @ git+https://github.com/…` in `astrid-pack-vibecomfy/requirements.txt`. The skill of the same name documents the package.                                                                                                       |

## 2. Extraction procedure (Step 7.2)

The extraction is **not** done this sprint. The procedure below is the canonical script for a future
"Sprint 10+ optional-pack extraction" run. It is per-pack; run it four times.

### 2.1 — Bootstrap a new external repo

1. `mkdir -p astrid-pack-<name>; cd astrid-pack-<name>; git init`.
2. `python3 -m astrid packs new astrid-pack-<name> --owner <github-user> --kind external` (the canonical
   scaffold command; produces `pack.yaml`, `executors/`, `README.md`, `requirements.txt`, `tests/` skeleton).
3. Confirm the scaffolded `pack.yaml` declares `content.executors: executors` and `schema_version: 1` (the
   structured-layout target Sprint 9 codifies for every pack).

### 2.2 — Copy the executor manifest(s) and runtime module

For each manifest currently under `Astrid/astrid/packs/external/executors/<slug>/`:

1. Copy `executor.yaml` (or, for split-wrapper packs, every sibling `*.yaml`) into the new repo at
   `executors/<slug>/executor.yaml`. Preserve the existing id verbatim — the regex relaxation landed in
   Sprint 9 Step 9.0 permits 3-segment dotted ids, so `external.runpod.provision`, `external.vibecomfy.run`,
   etc. stay valid public ids.
2. Rewrite `command.argv`'s module path from `astrid.packs.external.executors.<slug>.run` to
   `astrid_pack_<name>.<slug>.run` (or whatever Python module path the new repo exposes). Keep all
   placeholders (`{python_exec}`, `{out}`, …) unchanged.
3. Copy `run.py`, every helper module under the slug directory, and any `STAGE.md` / `README.md`.

### 2.3 — Declare runtime, secrets, and dependencies in the new pack

1. Add the third-party runtime dep to `astrid-pack-<name>/requirements.txt` (see the table in §1).
2. Document required secrets in `astrid-pack-<name>/README.md` (`FAL_KEY` for fal_foley, `RUNPOD_API_KEY`
   for runpod, etc.). Reference Astrid's existing env-file convention (`--env-file`) so users hook the pack
   up the same way they do today.
3. If the pack consumes vendored helpers that currently live in `builtin/` (the `fal_foley` adapter is the
   only example — it imports `_http_get_bytes`, `_http_post_json`, `poll_fal_result`, `FAL_QUEUE_URL` from
   `logo_ideas.run` and `_load_env_var` from `vary_grid.run`), **either** vendor those helpers into the new
   pack (preferred — eliminates the cross-pack import) **or** declare a runtime dependency on the
   astrid-core pack with the helper exposed as a stable public API. See §2.4.
4. Update `pack.yaml` metadata (`name`, `version: 0.1.0`, `description`) to reflect the standalone pack.

### 2.4 — Resolve cross-pack helper dependencies

Today `astrid/packs/external/executors/fal_foley/run.py` imports from sibling builtin executors:

```python
from astrid.packs.builtin.orchestrators.logo_ideas.run import (
    FAL_QUEUE_URL, _http_get_bytes, _http_post_json, poll_fal_result,
)
from astrid.packs.builtin.orchestrators.vary_grid.run import _load_env_var
```

`_load_env_var` is also pervasive — its absence in the extracted pack would break every fal-backed executor.
Two acceptable extraction strategies (pick per-pack at extraction time):

- **Vendor:** copy the helpers (`FAL_QUEUE_URL`, the four `_http_*` / `poll_fal_result` helpers, and
  `_load_env_var`) into a new module inside `astrid-pack-fal-foley/_helpers/fal_http.py`. Pro: zero cross-pack
  coupling. Con: code duplication if `logo_ideas` / `vary_grid` themselves are ever extracted later — but they
  are classified `primitive` in Sprint 9, so they stay in Core.
- **Public API:** promote the helpers into a stable public module like `astrid.packs.builtin.executors.fal_http`
  (still inside builtin Core), then have the extracted pack import from that path. Pro: single source of truth.
  Con: extends Astrid Core's surface area, which contradicts the Optional-Installable goal of shrinking Core.

The plan recommends **vendor** for `fal_foley`. The other three candidates (`moirae`, `runpod`, `vibecomfy`)
have no current cross-pack imports from `builtin/` and need no §2.4 resolution.

### 2.5 — Publish and remove the bundled copy

1. Push the new repo to GitHub at the URL recorded in the §1 table.
2. Tag a `v0.1.0` release; verify `pip install git+<url>@v0.1.0` resolves cleanly in a fresh venv.
3. Run the pack's own test suite against the published tag.
4. In the Astrid repo: delete `astrid/packs/external/executors/<slug>/` (and the now-empty parent if it was
   the last slug); remove the dep line from `requirements.txt` (`fal-client>=0.7.0` for fal_foley); update
   `docs/pack-portfolio.md` (the user-facing overview added in Sprint 9 Phase 7 Step 15) to move the candidate
   row out of the `Bundled installable` section and into a new `Available as a separate install` section that
   links to the new repo's README.
5. Verify the four `external/*` ids no longer appear in `python3 -m astrid executors list` output by default;
   verify they DO appear once the user `pip install`s the extracted pack and re-runs `astrid packs list`.

### 2.6 — Test plan for the extraction commit

1. `python3 -m astrid packs validate astrid/packs/external` — clean exit (the four candidates are gone).
2. `python3 -m astrid executors list | grep external.<slug>` — empty.
3. In a fresh venv: `pip install git+<extracted-pack-url>; python3 -m astrid packs list | grep external.<slug>` — present.
4. End-to-end: invoke one executor from the extracted pack (e.g. `astrid run executor external.fal_foley --clip sample.mp4 --out tmp/`) and confirm exit 0.
5. Confirm no `tests/test_packs_shipped_ids.py` assertion still hardcodes the extracted slug — the test was
   already updated in Sprint 9 Step 6.12; the extraction sprint must re-audit it.

## 3. Explicit non-action statement (Step 7.3)

**This sprint does NOT move the four `external/*` candidates out of the source tree.** They remain under
`astrid/packs/external/executors/` for the duration of Sprint 9. Sprint 9 only:

1. Restructures `external/` to the bundled-installable layout (Phase 2 Step 5).
2. Splits the runpod (already pre-landed on this branch) and vibecomfy (residual) multi-executor wrappers
   into sibling manifests using underscore-cased filenames with the existing 3-segment dotted ids preserved.
3. Adds `schema_version: 1` to every per-component manifest (already complete on this branch).
4. Documents the extraction path in this file.

The actual move is a follow-up sprint. Re-doing the analysis at extraction time is unnecessary; the
target-repo names, git URLs, dependency lines, secrets, and helper-resolution strategy are all captured in
§1 and §2 above. A reasonable name for that follow-up is "Sprint N: extract optional-installable
third-party-service packs".

## 4. Cross-references

- Classification rationale for each candidate: `portfolio.md` § "Top-level pack-classification table",
  row `external`, and per-component flags `F-WRAPPER-SPLIT`, `F-QID-REGEX`, `F-BUILTIN-IMPORT` in
  `inventory.md` §6.
- Migration alias non-action: `migration-aliases.md` (Phase 6 Step 12.3) records that the regex relaxation
  in Step 9.0 preserves every existing 3-segment id, so the extraction does **not** create any aliased ids.
- The `runpod-lifecycle` and `vibecomfy` skills already document the underlying packages and provide a
  template for the extracted pack READMEs.
