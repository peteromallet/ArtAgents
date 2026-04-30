# First-Class No-Audio Mode Plan

Motivation: the pipeline should support a run like `python3 pipeline.py --brief brief.txt --theme 2rp --out runs/foo --render --target-duration 28` without `--audio` or `--video`, and produce a clean visual-only MP4. The output timeline must not contain an `a1` track or a synthetic silent rant clip.

Deliverable summary: add a real no-audio pipeline mode, require an explicit target duration for that mode, keep source-cut and pure-generative-with-audio behavior unchanged, and test the exact timeline shape.

## Verification And Critique

The failed plan got the broad direction right but missed several load-bearing details.

- `pipeline.py:259-289` rejects no-audio today twice: first by requiring `--video or --audio`, then by raising `--audio when --video is omitted`. A no-audio mode needs to change both gates.
- `pipeline.py:617` only derives `arrange.py --target-duration` from `probe_audio_duration(args.audio)` when `args.video is None`. With no audio, this must come from a new top-level pipeline flag. There is no safe implicit default because the requested invocation is 28 seconds, below the source-cut 75-90 second window.
- `arrange.py:270-312` and `arrange.py:316-351` still tell the LLM the target is "anchored to the rant audio" and that only stingers may have `audio_source: null`. That is actively wrong for no-audio mode. A pipeline-only change will still ask Claude for dialogue clips from an all-generative pool.
- `pool_merge.py:94-97` already works with no source pool: if `<out>/pool.json` is missing it starts from `_skeleton()` at `pool_merge.py:25-30`, merges effect entries, and writes a valid generative-only pool. The failed plan was silent here, but this part does work.
- `pool_build.py:160-161` requires surviving source visual and dialogue entries, but `pipeline.py:725-727` already skips `pool_build` whenever `args.video is None`. No no-audio change belongs in `pool_build.py`.
- `cut.py:495-506` only adds `clip_a_rant` when `primary_asset is None` and `rant` exists in the registry. In no-audio mode there should be no `rant`, so this block naturally does not add an audio clip.
- `cut.py:611-615` still returns `tracks: [v1, v2, a1]` unconditionally. This directly violates the requirement. The failed plan's "clip_a_rant falls through" claim is insufficient because a declared empty `a1` track is still an `a1` track.
- `cut.py:957` defines pure-generative as `args.video is None and args.audio is not None`; `cut.py:958-967` still requires `--transcript`; and `cut.py:1004-1013` only permits `primary_asset = None` for audio-backed `"rant"` mode. These need a separate no-audio branch.
- `cut.py:1037-1038` correctly skips `validate_arrangement_duration_window()` for all-generative arrangements. Keep this. Do not reintroduce the 75-90 second window for no-audio.
- `refine.py:123-145` already resolves primary asset to `None` for metadata snapshots with `primary_asset: null` and for a single audio-only asset. That fix should not be redesigned. However, `pipeline.py:627-653` still runs `refine` whenever `--render` is set, and `refine.py:569-575` requires a transcript path. No-audio mode should skip `refine`, not feed it fake audio.
- `validate.py:93-98` transcribes before `validate.py:106-107` loads the timeline and metadata. The existing visual-caption skip at `validate.py:121-139` does not help because it runs after transcription. A direct `validate.py` no-audio guard must load the timeline before `run_transcribe()`.
- `timeline.py:169-170` makes `tracks` optional and `timeline.py:532-542` only validates `tracks` if present. A timeline without `a1` is schema-valid. `remotion/src/lib/tracks.ts:16-19` maps no audio tracks to an empty array, and `remotion/src/HypeComposition.tsx:193-196` renders zero audio tracks cleanly.
- `themes/banodoco-default/theme.json` has only visual fields. `themes/arca-gidan/theme.json:81-88` has an `audio` style block, but current code only validates it in `theme_schema.py:151-158`; arrange/cut/render do not consume it. Do not edit themes for this change.
- The 28.000s visual + 28.053s silent WAV drift from the path-A render is structurally eliminated by no-audio mode because there is no audio stream. It remains a separate bug for synthetic-silent-WAV workflows and should not be fixed here.

## Settled Decisions

**SD-001**: Introduce explicit no-audio mode when both `args.video is None` and `args.audio is None`.  
`load_bearing: true`  
Reason: overloading pure-generative-with-audio would preserve the silent-rant mental model and miss the no-`a1` requirement.

**SD-002**: Require `--target-duration` in no-audio mode; do not invent a default.  
`load_bearing: true`  
Reason: no source duration exists, and the desired 28s output is outside the source-cut default window.

**SD-003**: Keep audio-backed pure-generative behavior byte-compatible.  
`load_bearing: true`  
Reason: current `--audio`-only path intentionally transcribes and adds `clip_a_rant`.

**SD-004**: No-audio timelines must omit the `a1` track definition, not merely omit `a1` clips.  
`load_bearing: true`  
Reason: the user explicitly asked for no `a1` track at all.

**SD-005**: Skip `transcribe`, `refine`, `editor_review`, and pipeline-driven `validate` in no-audio mode.  
`load_bearing: true`  
Reason: these steps are audio/dialogue or source-review oriented and either require transcript artifacts or produce misleading results.

**SD-006**: Make direct `validate.py` robust for no-audio timelines by short-circuiting before transcription.  
`load_bearing: false`  
Reason: pipeline should skip validate, but direct CLI users should not hit Whisper for a visual-only timeline.

**SD-007**: Teach `arrange.py` a no-audio prompt mode instead of relying on `--allow-generative-effects` alone.  
`load_bearing: true`  
Reason: the current prompt says the target is anchored to rant audio and constrains `audio_source: null` to stingers only.

**SD-008**: Leave `pool_merge.py`, `pool_build.py`, `timeline.py`, `refine._resolve_primary_asset`, and theme files structurally unchanged unless tests prove otherwise.  
`load_bearing: false`  
Reason: verified current behavior is already adequate or already fixed.

## Step 1: Pipeline Argument Model

Files:

- `pipeline.py:94-160`: add `--target-duration` as a float option near `--audio`. Help text: `Target output duration in seconds; required when both --video and --audio are omitted.`
- `pipeline.py:254-289`: replace the current required `--video or --audio` gate with `--brief` + `--out` as the always-required inputs, then normalize media mode:
  - source-cut: `args.video is not None`, `args.audio` defaults to `args.video`;
  - audio-backed generative: `args.video is None`, `args.audio is not None`;
  - no-audio: both absent, `args.audio = None`, and `args.target_duration > 0` is required.
- `pipeline.py:321-328`: keep the existing `path is None` guard in the input existence loop.
- `pipeline.py:317-319`: improve default `brief_slug` only for generic brief filenames. If `--brief-slug` is absent and `args.brief.stem.lower()` is one of `{"brief", "plan", "prompt"}`, use `args.out.name`; otherwise keep `args.brief.stem`.

Rationale: the requested invocation uses `brief.txt`; defaulting that to `briefs/brief/` is poor UX when `--out runs/foo` already carries the run identity. This is not no-audio-specific in principle, but it matters most for brief-only runs.

## Step 2: Pipeline Step Selection

Files:

- `pipeline.py:723-728`: replace the current `args.video is None` source-only skip with explicit mode predicates:
  - when `args.video is None`, continue skipping `scenes`, `quality_zones`, `shots`, `triage`, `scene_describe`, `quote_scout`, and `pool_build`;
  - when `args.audio is None`, additionally skip `transcribe`, `refine`, `editor_review`, and `validate`.
- `pipeline.py:440-720`: leave the `Step` definitions in one place; filter in `build_steps()` instead of making the list construction branchy.
- `pipeline.py:408-437`: keep the existing `if args.audio is not None` guard for forwarding `--audio` to `cut.py`.
- `pipeline.py:911-918`: no special no-audio handling should be needed here once `build_steps()` filters correctly. Keep the existing `--render` behavior for audio-bearing modes.

Do not create fake `transcript.json` in pipeline. Fake transcript artifacts would make later cache checks look like real transcription and blur the contract. Instead, make no-audio legal in `cut.py`.

## Step 3: Target Duration Plumbing

Files:

- `pipeline.py:617`: replace the current audio-probe-only expression with a helper such as `_arrange_target_duration(args) -> float | None`.
- `pipeline.py:373-389`: keep `probe_audio_duration()` unchanged, and call it only when `args.video is None and args.audio is not None`.
- `pipeline.py:596-623`: pass `--target-duration {value:.6f}` when `args.video is None` and either:
  - audio exists, using `probe_audio_duration(args.audio)`;
  - no audio exists, using `args.target_duration`.
- `pipeline.py:596-623`: continue passing `--allow-generative-effects` whenever `args.video is None`.

Expected behavior:

- source-cut with `--video`: no `--target-duration` passed to arrange;
- `--audio` only: target duration is probed from the audio exactly as today;
- no-audio: target duration comes from the top-level CLI flag exactly.

## Step 4: Arrange No-Audio Prompt Mode

Files:

- `arrange.py:270-312`: add a `no_audio: bool = False` parameter to `_build_user_prompt()`.
- `arrange.py:316-351`: add the same `no_audio` parameter to `_hard_constraint_prompt_lines()`.
- `arrange.py:494-503`: add `no_audio: bool = False` to `build_arrangement()`.
- `arrange.py:553-562`: add `no_audio: bool = False` to `build_revised_arrangement()` for consistency, even though no-audio pipeline skips editor review/revise.
- `arrange.py:634-649`: add `--no-audio` as a boolean flag.
- `arrange.py:693-702`: pass `args.no_audio` into `build_arrangement()`.
- `arrange.py:684-692`: pass `args.no_audio` into `build_revised_arrangement()`.
- `pipeline.py:596-623`: pass `--no-audio` to `arrange.py` only when `args.video is None and args.audio is None`.

Prompt changes:

- In no-audio mode, replace "anchored to the rant audio" with "visual-only; no audio track will be rendered."
- In no-audio mode, require every clip to use `audio_source: null`.
- In no-audio mode, require every clip to use a generative `visual_source`.
- In no-audio mode, remove or rewrite dialogue-only constraints at `arrange.py:288-292` and `arrange.py:330-334`.
- In no-audio mode, allow `visual_source.role` to be `primary` or `stinger`; prefer `primary` for full-screen text-card beats. Avoid `overlay` wording because there is no underlying audio.

Schema changes:

- Keep `RESPONSE_SCHEMA` shape unchanged. It already allows `audio_source: null`.
- Do not loosen `timeline.validate_arrangement()`. `timeline.py:789-792` already requires a visual when audio is null, which is exactly right.

## Step 5: Cut No-Audio Mode

Files:

- `cut.py:39-80`: update `--audio` help to say it is optional and only used for audio-backed pure-generative mode.
- `cut.py:947-968`: introduce `no_audio = args.video is None and args.audio is None` next to the existing `pure_generative = args.video is None and args.audio is not None`.
- `cut.py:958-967`: require `--scenes` only when neither `pure_generative` nor `no_audio` is true.
- `cut.py:966-988`: require and load `--transcript` only when `not no_audio`. In no-audio mode set `transcript = None`.
- `cut.py:1004-1013`: allow `primary_asset = None` when `no_audio` is true and no `main` asset exists. Keep the existing `"rant"` branch unchanged for audio-backed pure-generative mode.
- `cut.py:1037-1038`: leave the all-generative duration-window skip unchanged.
- `cut.py:1040`: `arrangement_edl_rows()` already accepts `transcript: list | None`; no change expected.

Acceptance details:

- No-audio mode should emit an empty asset registry unless theme generation assets are represented elsewhere by the effect `generation` context. Do not invent a dummy audio asset.
- No-audio mode should not accept an arrangement with `audio_source` entries. `compile_arrangement_plan()` will fail naturally if the source pool has no dialogue entries.

## Step 6: Cut Track Elision

Files:

- `cut.py:485-617`: change `build_multitrack_timeline()` to build `tracks` from actual needs instead of returning `a1` unconditionally.
- `cut.py:495-537`: any emitted `clip_a_rant`, `clip_a_<order>`, or speaker `clip_v1_<order>` implies audio-backed mode and should include `a1`.
- `cut.py:538-578`: source visual overlays still imply `v2`.
- `cut.py:553-564`: generative visual clips can use `v1` or `v2` based on role.
- `cut.py:579-597`: text overlays still use `v2`.
- `cut.py:609-617`: replace the literal tracks list with:
  - always include `v1` if any clip targets `v1`, or if there are no clips;
  - include `v2` only if any clip targets `v2`;
  - include `a1` only if any clip targets `a1`.

Important: this step is load-bearing. The failed plan only noticed that `clip_a_rant` falls through, but `cut.py:611-615` currently declares `a1` even when no audio clip exists.

## Step 7: Validate Direct CLI No-Audio Guard

Files:

- `validate.py:82-91`: after resolving paths and checking that timeline/metadata exist, load `timeline` and `metadata` before any transcription.
- `validate.py:93-98`: move this transcription block below the no-audio check.
- `validate.py:106-108`: remove the later duplicate timeline/metadata load after moving it up.
- `validate.py:93-108`: add an early no-audio branch:
  - detect no audio with `not any(clip.get("track") == "a1" for clip in timeline.get("clips", []))`;
  - write `validation.json` with `summary.skipped_no_audio: true`, zero failures, and an empty `clips` list;
  - print `validate: skipped because timeline has no audio track`;
  - return 0.

Pipeline-driven no-audio runs should not call `validate.py` at all after Step 2. This step protects direct usage and future callers.

## Step 8: Refine And Editor Review Policy

Files:

- `pipeline.py:723-728`: Step 2 should filter `refine` and `editor_review` when `args.audio is None`.
- `pipeline.py:878-908`: do not modify `_run_revise()` for no-audio mode, because editor review is skipped and no revise loop should execute.
- `refine.py`: no code changes. `_resolve_primary_asset()` at `refine.py:123-145` is already fixed, but `refine.py:569-575` still requires a transcript and is not a meaningful no-audio stage.
- `editor_review.py`: no code changes. It is video/source-review leaning and can be revisited later once there is a visual-only review rubric.

Reason: no-audio mode is not "silent dialogue"; it is a visual-only generator. Audio-bound trim review and editor micro-fixes should not run.

## Step 9: Documentation Updates

Files:

- `README.md:7-13`: distinguish audio-backed pure-generative mode from no-audio mode.
- `README.md:270-289`: document `--target-duration` and the no-audio step list.
- `README.md:316-324`: mention that no-audio renders skip refine, editor review, and validate.

Keep the docs short. Do not describe this as a silent WAV replacement; the point is absence of an audio track.

## New CLI Surface

No-audio visual-only render:

```bash
python3 pipeline.py \
  --brief brief.txt \
  --theme 2rp \
  --out runs/foo \
  --render \
  --target-duration 28
```

No-audio plan-only run:

```bash
python3 pipeline.py \
  --brief brief.txt \
  --theme arca-gidan \
  --out runs/arca-short \
  --target-duration 30
```

Audio-backed pure-generative mode remains unchanged:

```bash
python3 pipeline.py \
  --audio rant.wav \
  --brief brief.txt \
  --theme 2rp \
  --out runs/foo-audio \
  --render
```

Source-cut mode remains unchanged:

```bash
python3 pipeline.py \
  --video source.mp4 \
  --brief brief.txt \
  --theme banodoco-default \
  --out runs/foo-source \
  --render
```

Invalid no-audio invocation:

```bash
python3 pipeline.py --brief brief.txt --out runs/foo
```

Expected error: `pipeline.py: --target-duration is required when both --video and --audio are omitted`.

## Test List

- `tests/test_pure_generative_pipeline.py`: add `test_no_audio_resolve_args_requires_target_duration` for the clean usage error.
- `tests/test_pure_generative_pipeline.py`: add `test_no_audio_step_list_and_arrange_command` asserting `args.audio is None`, source-only steps are absent, `transcribe/refine/editor_review/validate` are absent, and arrange receives `--target-duration 28.000000`, `--allow-generative-effects`, and `--no-audio`.
- `tests/test_pure_generative_pipeline.py`: update or add an audio-backed regression asserting existing `--audio`-only mode still includes `transcribe`, `refine`, `editor_review`, `validate`, and still probes audio duration.
- `tests/test_arrange.py`: add a no-audio prompt test using a stub Claude response with every `audio_source: null`, proving the prompt does not mention rant audio or dialogue trim constraints in no-audio mode.
- `tests/test_arrange.py`: add a no-audio validation test proving `build_arrangement(..., no_audio=True, allow_generative_effects=True)` accepts all-generative visual clips below 75 seconds.
- `tests/test_multitrack_cut.py` or `tests/test_pure_generative_pipeline.py`: add a no-audio cut test that runs `cut.main()` without `--video`, `--audio`, `--scenes`, or `--transcript` and asserts the emitted timeline has no `a1` track definition, no `a1` clips, and no `clip_a_rant`.
- `tests/test_pure_generative_pipeline.py`: keep or add the existing audio-backed regression asserting `clip_a_rant` is still minted when `--audio` supplies the `"rant"` asset.
- `tests/test_validate.py`: add a direct `validate.py` no-audio test that patches `run_transcribe` to fail if called, invokes `validate.main()` on a no-`a1` timeline, and asserts `summary.skipped_no_audio is True`.
- `tests/test_pipeline_caching.py`: add a brief slug default test for generic `brief.txt` using `args.out.name`, and a non-generic brief name regression preserving `Path(brief).stem`.

Verification commands:

```bash
python -m pytest tests/test_pure_generative_pipeline.py tests/test_arrange.py tests/test_multitrack_cut.py tests/test_validate.py tests/test_pipeline_caching.py -q
python -m pytest -q
```

## Migration Risk

Source-cut byte-identity check:

1. Pick one committed or fixture-backed source-cut run for `themes/banodoco-default`.
2. Run the pipeline before and after the implementation with identical inputs:
   `python3 pipeline.py --video SRC --brief BRIEF --theme banodoco-default --out OUT --render`.
3. Compare `arrangement.json`, `hype.timeline.json`, `hype.assets.json`, and `hype.metadata.json` byte-for-byte after normalizing only known run timestamps if the existing harness already does that. If no timestamp normalizer exists, compare semantic JSON excluding `generated_at`.

Arca source-cut byte-identity check:

1. Repeat the same process with `--theme arca-gidan`.
2. Confirm the `audio` style block in `themes/arca-gidan/theme.json:81-88` remains unused by source-cut output.

Pure-generative-with-audio byte-identity check:

1. Run `python3 pipeline.py --audio rant.wav --brief BRIEF --theme banodoco-default --out OUT --render`.
2. Repeat with `--theme arca-gidan`.
3. Confirm `hype.timeline.json` still declares `a1`, still contains `clip_a_rant`, and still uses the probed audio duration for arrange.

No-audio smoke check:

1. Run `python3 pipeline.py --brief brief.txt --theme 2rp --out runs/foo --render --target-duration 28`.
2. Assert `hype.timeline.json` has no track with `id == "a1"`.
3. Assert no clip has `track == "a1"`.
4. Assert the rendered MP4 duration is approximately 28.000s and has no audio stream according to `ffprobe`.

Risk notes:

- The highest behavioral risk is the arrange prompt. Without Step 4, Claude will keep trying to find dialogue entries that do not exist.
- The highest compatibility risk is track elision. Remotion appears safe because audio tracks map to an empty array, but the rendered smoke test must prove it.
- The path-A audio drift is not migrated. No-audio mode avoids it by producing no audio stream; audio-backed drift should get its own issue.

## Out Of Scope

- No silent WAV synthesis.
- No music-bed generation or use of `theme.audio`.
- No source-cut duration policy changes.
- No changes to `timeline.py` schema or generated TypeScript types unless a test exposes a real schema mismatch.
- No changes to `pool_build.py`.
- No redesign of `refine._resolve_primary_asset`; it is already fixed.
- No new editor-review rubric for visual-only outputs.
- No backwards-compat shims for old internal invocations beyond preserving the current source-cut and audio-backed pure-generative CLI behavior.
