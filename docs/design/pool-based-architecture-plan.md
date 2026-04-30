
# Implementation Plan: Pool-Based Hype-Cut Architecture Design Doc (revision 4)

## Overview
Produce a ~6000-word markdown design doc at `tools/docs/design/pool-based-architecture.md` restructuring `tools/` around per-source `pool.json` + per-brief `arrangement.json`. Deliverable is the doc; no code changes.

**Root-cause check.** The four open flags from iteration 3 (`correctness`, `all_locations`, `callers`, FLAG-007) all point at the same gap: `hype.metadata.json`. Iteration 3 specified arrangement-driven `cut.py` but left the per-clip metadata sidecar — which is the actual contract `validate.py:113-167` reads — undefined. Not a wrong-approach signal; a one-paragraph specification gap. Per gate guidance, the fix lands as a bullet under `§8.a` (file-level diff), **not a new §8 subsection** (gate repeatedly warned against §8 expansion).

**The one fix this revision makes:**

**Specify the `hype.metadata.json` replacement schema in §8.a.** `cut.py:522-586` today writes per-clip metadata from picks (`picked_by`, `pick_rationale`, `source_transcript_text`, `caption_kind`, `score`, `source_scene_id`) plus `pipeline.picks_provenance`. `validate.py:113-167` reads `caption_kind` + `source_transcript_text` keyed by clip id. When `cut.py` moves to `arrangement.json` + `pool.json`, the design doc must specify:
- Per-clip sidecar keyed by timeline `clip_id` with: `pool_id`, `pool_kind`, `source_ids {segment_ids?, scene_id?}`, `caption_kind` (derived deterministically from `pool_kind`: `dialogue`→`"dialogue"`, `visual`→`"visual"`, reaction/applause→`"visual"`, text-overlay clip→`"text"`), `source_transcript_text` (resolved from `transcript.json` via `source_ids.segment_ids` for dialogue-kind clips; for text-typed clips, copied from `text_overlay.content`; null/absent for b-roll visual clips), `arrangement_notes?` (optional author text), `score` (carry through pool entry's relevant score — `quotability` for dialogue, `deep_score` for visual, `triage` if that's all there is).
- Top-level provenance: `pipeline.pool_provenance` replacing `pipeline.picks_provenance`, containing `{pool_sha256, arrangement_sha256, brief_sha256, source_slug, brief_slug}` so any rendered clip is traceable back to the exact pool entry + arrangement + brief that produced it.
- **`validate.py`'s caller contract is preserved**: same field names (`caption_kind`, `source_transcript_text`), same clip-id keying, only the derivation changes. This lets the three validation classes (dialogue vs transcript / b-roll duration-only / text exact-string) fall out naturally from `caption_kind`.

**Settled decisions SD-001 through SD-014** from gate metadata are carried forward and not re-litigated. The only metadata-shape question the doc answers is the one above.

**Repository shape (verified, adding `cut.py:522-586` and `validate.py:113-167` to the set):**
- `tools/timeline.py:16,22,86-93` — TrackKind/ClipType/TextClipData.
- `tools/cut.py:371-373` (scene_score) + `tools/cut.py:522-586` (picks-driven metadata sidecar today) + `tools/cut.py:761-789` (singleton output write) — extension surface.
- `tools/validate.py:74-88,169-183` (default artifact `validation.json`) + `tools/validate.py:113-167` (caller contract: reads `caption_kind` + `source_transcript_text` per clip id).
- `tools/pipeline.py:20,35-49,140-165,194-251` — orchestration.
- `tools/gemini_picks.py:103-123,228-320`, `tools/gemini_review.py:97-109,118-170`, `tools/gemini_refine.py:40-48,105-157,225-239` — descope evidence.
- `tools/runs/ados_2026/picks.json:26-33` — clip_004 moth visual.
- `tools/runs/ados_loose/transcript.json` segments 185–186 — applause text.
- `tools/README.md:16-45,147-176,178-255` — picks format, metadata sidecar docs, pipeline sentinels. All in §8.e rewrite scope.

**Constraints (unchanged):** 12 sections in order; under ~6000 words; no new reigh-app `TrackKind`/`ClipType`; no LLM timestamps; markdown only. **Do not add §8 subsections.** **Do not spec render_remotion.py or reigh-app bridge in this revision** (gate warned this would trigger ESCALATE).

## Main Phase

### Step 1: Extract exact quotes and anchors from source files (read-only)
**Scope:** Small
1. **Read** these lines:
   - `tools/timeline.py:16,22,86-93` — TrackKind/ClipType/TextClipData for §6.
   - `tools/cut.py:371-373` (scene_score) + **`:522-586` (current picks-driven metadata sidecar — note the exact field names `picked_by`, `pick_rationale`, `source_transcript_text`, `caption_kind`, `score`, `source_scene_id`, and `pipeline.picks_provenance`) + `:761-789` (singleton output)** — §8.a extension surface.
   - **`tools/validate.py:113-167`** — confirm the exact field names `caption_kind` and `source_transcript_text` are keyed by clip id; §8.a must preserve these verbatim. Plus `:74-88,169-183` for default artifact `validation.json`.
   - `tools/pipeline.py:20,35-49,140-165,194-251` — §8.b rewiring.
   - `tools/gemini_picks.py:103-123`, `:228-320` — §1 status quo.
   - `tools/gemini_review.py:97-109,118-170` + `tools/gemini_refine.py:40-48,105-157,225-239` — §8.d descope evidence.
   - `tools/pick_timing.py:35-71` — `0.4` overlap threshold → §7.
   - `tools/runs/ados_2026/picks.json` (clip_003 dialogue + clip_004 moth) + `tools/runs/ados_loose/transcript.json` segments 185–186 + `tools/runs/ados_loose/plan.json`.
   - `tools/examples/hype.timeline.full.json` — multitrack + text-clip shape for §6.
   - **`tools/README.md:16-45,147-176,178-255`** — the three paragraph blocks §8.e rewrites (Picks Format, `hype.metadata.json` description, pipeline sentinels/Sprint 3).
2. **Do not** modify any file.

### Step 2: Create the output directory and scaffold the doc
**Scope:** Small
1. `mkdir -p tools/docs/design/` if absent.
2. Write `tools/docs/design/pool-based-architecture.md` with H1, ≤4-sentence lead, and 12 `## N. <Title>` headers in the required order.

### Step 3: Draft §1 Problem Statement and §2 Architecture Overview
**Scope:** Small
1. **§1** names the four structural problems, each paired with an ADOS symptom.
2. **§1 clip_004** (SD-007): quote the hallucination verbatim from the task description (caption said Pom's motivation quote; src range resolved to interviewer's next question). Follow with one sentence stating this was observed during prior authoring work on an earlier ADOS export and is not reproducible from `runs/ados_2026/picks.json` today (whose clip_004 is the moth visual at `picks.json:26-33`). Add the repo-verifiable vignette: every pick in that file has `keep_audio=true` and `caption_kind=null` — the structural-coupling problem from the checked-in repo.
3. **§2 ASCII diagram** — stages with models:
   - `INGEST (deterministic — Whisper / PySceneDetect / ffmpeg)` → `transcript.json`, `scenes.json`, `shots.json`.
   - `POOL BUILDER (per-source, brief-agnostic)` → `triage.py` (Claude Haiku), `scene_describe.py` (Gemini), `quote_scout.py` (Claude Sonnet, **no brief input**), `pool_build.py` (deterministic) → `pool.json`.
   - `ARRANGE (per-brief)` → `arrange.py` (Claude Sonnet, `pool.json` + `brief.txt`) → `arrangement.json`.
   - `ASSEMBLE` → `cut.py` extended → `hype.timeline.json`, `hype.assets.json`, **`hype.metadata.json` (new pool-provenance schema — see §8.a)**.
   - `RENDER` → Remotion → `hype.mp4`.
   - `VALIDATE` → `validate.py` → `validation.json`.
   - Annotate `pool.json` as per-source pivot, `arrangement.json` as per-brief pivot.

### Step 4: Draft §3 `pool.json` schema + ADOS worked examples
**Scope:** Medium
1. **Envelope** (SD-012):
   ```
   id, kind ("dialogue"|"visual"|"reaction"|"applause"|"music"),
   asset, src_start, src_end, duration,   # deterministic; never LLM-written
   source_ids {segment_ids?, scene_id?},
   scores {triage?, deep?, quotability?: float},   # brief-agnostic only
   excluded, excluded_reason?
   ```
   Note: brief-specific relevance is computed by `arrange.py` in memory, not persisted.
2. **Kind-specific**: dialogue → `text, speaker?, quote_kind`; visual → `motion_tags[], mood_tags[], subject, camera`; reaction/applause → `intensity (0–1), event_label`; music → `bed_kind, energy`.
3. **Worked examples** (SD-008): dialogue from `runs/ados_2026/picks.json` clip_003 ("It began a couple of years ago…"); visual from `runs/ados_2026/picks.json:26-33` ("Glowing white moth flying", 5015.5–5017.0); applause from `runs/ados_loose/transcript.json` segments 185–186 ("Round of applause for Kajai."). Cite filename + indices in the doc.
4. **Note** that `id` is the sole handle arranged clips and `hype.metadata.json` entries both point back to (the `pool_id` ↔ `clip_id` linkage defined in §8.a).

### Step 5: Draft §4 per-stage specs
**Scope:** Medium
1. Uniform template: Purpose · Tier (per-source / per-brief) · Inputs · Outputs · Model + 3–5 line prompt sketch · Failure modes · Cost/wall-clock (ADOS).
2. **Triage** (`triage.py`, Claude Haiku, per-source): `shots.json`+`scenes.json` → grids (~3 scenes × 3 keyframes each) → `triage.json` `{scene_id, keep_score 0–5, suggested_mood_tags[]}`; ~235 grid calls for 704 ADOS scenes.
3. **Deep visual** (`scene_describe.py`, Gemini, per-source): survivors (triage_score ≥ 3, ~70 ADOS scenes) → `scene_describe.json` `{scene_id, deep_score, motion_tags[], mood_tags[], subject, camera}`.
4. **Dialogue scout** (`quote_scout.py`, Claude Sonnet, per-source, **brief-agnostic**, SD-012): inputs `transcript.json` only — **no `brief.txt`**. Output `quote_scout.json` `{segment_ids[], quote_kind, speaker?, quotability 0–1}`. Generic quotability = sentence shape + closure + speaker attribution quality + filler-word penalty. 1–2 Sonnet long-context calls **paid once per source**.
5. **Pool writer** (`pool_build.py`, per-source, deterministic): merges `triage.json` + `scene_describe.json` + `quote_scout.json`; resolves `src_start/src_end` from `scenes.json`/`transcript.json`; writes `pool.json`.
6. **Arrange** (`arrange.py`, Claude Sonnet, per-brief): `pool.json` + `brief.txt` → `arrangement.json`; prompt sketch emits `pool_id` references only; composer computes relevance against brief in-memory. 1 Sonnet call per brief.
7. Invariant: every prompt sketch declares the output schema forbids time fields — IDs only.

### Step 6: Draft §5 `arrangement.json` schema + §6 multitrack timeline mapping
**Scope:** Medium
1. **§5 schema**:
   ```
   { brief_text, target_duration_sec,
     clips: [ { order, audio_source: pool_id|null, visual_source: pool_id,
                text_overlay?: {content, style_preset?}, notes? } ] }
   ```
   No numeric times. `arrangement.json` lives under the per-brief subdirectory (§8.c).
2. **§5 example**: 3–4 clips — dialogue-spine; dialogue + b-roll visual_source; dialogue + text_overlay.
3. **§6 mapping**: `a1`=audio track (audio_source); `v1`=primary visual (speaker footage); `v2`=overlay visual (visual_source when differs; volume=0); `text_overlay` → `clipType:"text"` clip on highest-numbered active visual track (SD-005).
4. **Callout** (SD-003, quoting `tools/timeline.py:16,22` verbatim): _"`TrackKind = Literal['visual','audio']`; `ClipType = Literal['media','hold','text','effect-layer']`. `v1`, `v2`, and `text` are local names in this doc only — no new reigh-app fields."_
5. Round-trip example mirroring `tools/examples/hype.timeline.full.json`.

### Step 7: Draft §7 rubrics, §8 migration plan, §9 cost/time
**Scope:** Medium
1. **§7 rubrics** (SD-014):
   - Triage keep `triage_score ≥ 3` (0–5); deep minimum `deep_score ≥ 0.4`; pool-time `quotability ≥ 0.4`; arrange-time `relevance ≥ 0.5` (in-memory); dialogue overlap `0.4` from `pick_timing`; visual duration window `[0.8s, 6.0s]`.
   - Composer `excluded:true`: duration <0.8s, duration >20s, dialogue kind missing audio, overlapping `segment_ids` already consumed.
   - Legacy `scene_score = duration * (1 + scene_word_count / 50.0)` (`cut.py:371-373`) called out as replaced.
2. **§8 migration plan** — **exactly five labelled subsections (a–e); no additions**:
   - **a. File-level diff.**
     - Delete `tools/gemini_picks.py`.
     - New `tools/triage.py`, `tools/scene_describe.py`, `tools/quote_scout.py`, `tools/pool_build.py`, `tools/arrange.py`.
     - **Extend `tools/cut.py`** — read `arrangement.json` via `--arrangement` and `pool.json` via `--pool`. Emit multitrack (v1+v2 visual, a1 audio) with text-typed clips. Keep `scene_score` as a utility but not the primary ranking.
       **New `hype.metadata.json` schema (replaces the pick-centric sidecar at `cut.py:522-586`, closes FLAG-007 / `correctness` / `all_locations` / `callers`):**
       ```
       {
         clips: {
           <clip_id>: {
             pool_id: string,               # references pool.json entry; null for text clips
             pool_kind: "dialogue" | "visual" | "reaction" | "applause" | "music" | "text",
             source_ids: { segment_ids?, scene_id? },
             caption_kind: "dialogue" | "visual" | "text",   # derived from pool_kind
                                                              # dialogue → "dialogue"
                                                              # visual/reaction/applause/music → "visual"
                                                              # text-overlay clip → "text"
             source_transcript_text: string | null,
                 # dialogue: joined transcript.segments[segment_ids].text
                 # text: text_overlay.content
                 # visual: null
             arrangement_notes: string | null,   # from arrangement clip.notes
             score: float | null                  # quotability for dialogue, deep_score for visual, triage fallback
           }
         },
         pipeline: {
           pool_provenance: {                 # replaces pipeline.picks_provenance
             pool_sha256, arrangement_sha256, brief_sha256,
             source_slug, brief_slug
           }
         }
       }
       ```
       **Caller-contract preservation**: `validate.py:113-167`'s field names (`caption_kind`, `source_transcript_text`) are preserved verbatim — only derivation changes. The three validation classes fall out of `caption_kind` directly: `"dialogue"` → token-similarity vs transcript; `"visual"` → skip text similarity, check duration bounds only (matches today's `caption_kind=="visual"` tolerance); `"text"` → exact-string match of `source_transcript_text`. `clip_id` in `hype.timeline.json` remains the join key `validate.py` already uses.
     - **Extend `tools/validate.py`** — no caller-contract change (intentionally). Extension is internal: switch on `caption_kind` to route to dialogue/visual/text validators. Tolerate `pool_id=null` on text clips.
     - Deprecate `tools/runs/*/plan.json` → per-run `brief.txt`.
   - **b. `pipeline.py` rewiring** (SD-010 + SD-013). Edits against `pipeline.py:20,35-49,140-165,194-251`:
     - Remove `picks` step + `gemini_picks.py --plan` invocation.
     - Add per-source steps: `triage` (`triage.json`), `scene_describe` (`scene_describe.json`), `quote_scout` (`quote_scout.json`, brief-agnostic), `pool_build` (`pool.json`).
     - Add per-brief steps: `arrange` (`arrangement.json`), `cut` (`hype.timeline.json`, `hype.assets.json`, `hype.metadata.json`), `render` (`hype.mp4`), `validate` (`validation.json`).
     - CLI: drop `--plan`; add `--source <slug>` + `--brief <slug>`; replace `cut.py --picks` with `cut.py --arrangement --pool`.
     - Caching: per-source sentinels survive `brief.txt` change; `arrangement.json`/`hype.*`/`validation.json` invalidate on `brief.txt` change. Re-entry for a second brief is `arrange` — scout does not re-run.
   - **c. Artifact layout** (SD-009, with `hype.metadata.json` under per-brief):
     ```
     runs/<source>/
       transcript.json, scenes.json, shots.json
       triage.json, scene_describe.json, quote_scout.json, pool.json
       briefs/<brief>/
         brief.txt
         arrangement.json
         hype.timeline.json, hype.assets.json, hype.metadata.json
         hype.mp4
         validation.json
     ```
   - **d. `gemini_refine.py` / `gemini_review.py` fate** (SD-006): **redesign or descope**. Evidence: `gemini_review.py:97-109,118-170` asks for `pick_index` + `cut_timestamp`; `gemini_refine.py:40-48,105-157,225-239` extracts by numeric range + asks for seconds. Both structurally timestamp-coupled. **Recommendation v1: descope to v2** — remain in repo on legacy `picks.json` flow, not wired into new `pipeline.py`. v2 sketch (noted only): review emits `{clip_order, critique, suggested_pool_id_swap}`; refine emits `{clip_order, replacement_pool_id | new_pool_entry_draft}`. Neither touches seconds.
   - **e. `README.md` rewrite** (SD-011). `tools/README.md:16-45` (Picks Format), `:147-176` (**`hype.metadata.json` description — must rewrite to the new pool-provenance schema above**), `:178-215` (Gemini helpers), `:215-255` (pipeline sentinels + Sprint 3). New README names `pool.json`/`arrangement.json` as handoff formats and lists the new step order.
3. **§9 cost/time** — ADOS-grounded (2h / 704 / 1015):
   - Per-source pool build (paid once): triage ~235 Haiku grid calls + deep ~70 Gemini clip calls + scout 1–2 Sonnet long-context calls + deterministic pool_build. Give $ ranges + wall-clock minutes per stage, tagged "as of early 2026".
   - Per-brief: 1 Sonnet arrange call + cut/render/validate (deterministic/GPU-bound).
   - Break-even: pool amortizes after ≥2 briefs per source.

### Step 8: Draft §10 failure modes, §11 open questions, §12 non-goals
**Scope:** Small
1. **§10** (≥5, with fallbacks): triage drops a wanted scene → composer picks sibling `scene_id`; deep Gemini fails → pool entry gets `deep: null`; scout misses a quote → hand-add a pool-patch entry merged by `pool_build.py`; composer references missing `pool_id` → `arrange.py` validates on write, fail fast; validate transcript drift on dialogue → warning (matches existing `caption_kind=="visual"` tolerance), `validation.json` still written. 6th: conflicting `--brief` slug → fail fast naming `runs/<source>/briefs/<brief>/`.
2. **§11** (≥5 substantive): pool invalidation on source re-encode (content hash vs mtime); multi-speaker segment attribution; deep-describe caching across projects by scene content hash; `arrange.py` streaming vs one-shot; `TextClipData` style defaults; 6th — brief-aware scout rescoring in a later version (not v1); 7th — review/refine v2 redesign or retire.
3. **§12 v1 non-goals**: no new reigh-app `TrackKind`/`ClipType`/`AssetRegistry` fields; no cross-source b-roll library; no cross-brief pool sharing; no sidechain ducking; no auto-cut-to-beat; no transitions beyond what `cut.py` emits today; no web UI; no v1 redesign of `gemini_review.py`/`gemini_refine.py`; no brief-aware scout pass in v1; **no render_remotion.py props changes in v1** (reigh-app Remotion bridge stays unchanged — the metadata schema uses clip_id keying that the existing Remotion props already expose).

### Step 9: Verify word budget and pass-to-pass criteria
**Scope:** Small
1. **Word count** (`wc -w`): target <~6000. Trim order: §4 prompt sketches first; then §9 cost commentary; then §1 auxiliary vignette. Do **not** trim §8.a metadata contract or scout brief-agnostic language.
2. **Pass-to-pass checklist**:
   - 12 sections in order.
   - §1 clip_004 verbatim + prior-authoring disclaimer + repo vignette.
   - §2 diagram labels model per stage; scout marked "no brief input"; `hype.metadata.json` called out as part of ASSEMBLE output.
   - §3 three worked entries; envelope carries `quotability` (not `relevance`).
   - §4 five stages tagged per-source or per-brief; scout reads transcript only.
   - §5 only `pool_id` references.
   - §6 TrackKind/ClipType callout verbatim.
   - §7 concrete thresholds.
   - §8 five subsections; `§8.a` contains the `hype.metadata.json` schema (with `clips[<clip_id>].caption_kind` derivation table + `source_transcript_text` derivation rules + `pipeline.pool_provenance`); `§8.b` lists `validation.json` sentinel; `§8.c` tree includes `validation.json`; `§8.e` names `tools/README.md:147-176` as a rewrite target.
   - §9 names 2h/704/1015.
   - §10 ≥5 failures + fallbacks.
   - §11 ≥5 questions.
   - §12 non-goals including "no brief-aware scout pass v1", "no v1 redesign of review/refine", and "no render_remotion.py props changes in v1".
3. **Forbidden-pattern grep**:
   - No `TrackKind = [` literal beyond `'visual','audio'`.
   - No `ClipType = [` literal beyond `'media','hold','text','effect-layer'`.
   - No LLM prompt sketch asking for numeric seconds.
   - No "retarget" connected to review/refine.
   - §4 scout subsection must not list `brief.txt` or `brief_text` as an input.
4. **Cross-consistency checks**:
   - (SD-012 lock) §2 / §4 / §7 / §8.b / §8.c agree scout is per-source and brief-agnostic; `quote_scout.json` sits at source tier.
   - (SD-013 lock) `validation.json` in both §8.b sentinel list and §8.c tree.
   - **(New — FLAG-007 lock)** `hype.metadata.json`: the field names `caption_kind` and `source_transcript_text` appear in both §8.a (schema) and §8.a (validate caller-contract-preservation paragraph). The schema's `caption_kind` enum is `"dialogue" | "visual" | "text"` (not `null`), matching the three validation classes. `pipeline.pool_provenance` replaces `pipeline.picks_provenance`.
5. Read-through for typos and cross-reference integrity.

## Execution Order
1. Re-read source anchors (Step 1), especially `cut.py:522-586` and `validate.py:113-167` — these two define the metadata caller contract that §8.a must preserve.
2. Scaffold file (Step 2).
3. Draft §1→§12 forward (Steps 3–8). §8.a metadata schema is the sensitive new content on this revision — write it in the same pass as the `cut.py` extend bullet so the `caption_kind` / `source_transcript_text` derivation stays coherent.
4. Run verification (Step 9) including the new metadata cross-consistency lock.

## Validation Order
1. Pass-to-pass checklist.
2. §8 five-subsection audit.
3. §8.a metadata contract audit — schema keys present, `caption_kind` derivation explicit, `source_transcript_text` derivation rules by clip kind explicit, `validate.py` caller-contract preservation statement present.
4. Word count (`wc -w`).
5. Forbidden-pattern grep.
6. Cross-consistency sweep (scout tier + `validation.json` sentinel + metadata contract).
7. Final read-through.
