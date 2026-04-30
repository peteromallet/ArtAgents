# tools/ — Current Status

_Last updated 2026-04-22._

## What this is

A file-based toolkit for turning a long source recording (livestream, panel, event) into a short hype/trailer cut. Ingest is deterministic (Whisper transcription, PySceneDetect scenes, ffmpeg keyframes); composition is LLM-assisted; rendering is Remotion.

## Current architecture (as of today)

Just completed a pool-based restructure replacing the original `gemini_picks` → `cut` chain. Key principle: **LLMs never return numeric timestamps** — they return stable IDs (`segment_id`, `scene_id`) and Python resolves to timings via `transcript.json` / `scenes.json`. This addresses a real hallucination bug caught by validation in the previous architecture (clip_004 in the ADOS run had a caption describing Pom's motivation quote but timestamps pointing to the interviewer's next question, 30s off).

```
SOURCE → transcribe → scenes → shots
              ↓         ↓        ↓
         POOL BUILDER (brief-agnostic, run once per source):
           · triage.py          (Claude on keyframe grids)
           · scene_describe.py  (Gemini on top-N scenes)
           · quote_scout.py     (Claude on transcript)
           · pool_build.py      (deterministic merge)
                    ↓
                pool.json   ← the hub
                    ↓
         ARRANGE (per brief):
           · arrange.py        (Claude: pool + brief.txt → arrangement.json)
                    ↓
         ASSEMBLE:
           · cut.py --arrangement → multi-track timeline
                    ↓
         RENDER:
           · render_remotion.py → hype.mp4
                    ↓
         VALIDATE:
           · validate.py → re-transcribes output, verifies captions
```

## Tool inventory

### Ingest (deterministic)
- `transcribe.py` — Whisper, audio-only chunking (`-vn` strips video)
- `scenes.py` — PySceneDetect ContentDetector
- `shots.py` — ffmpeg keyframes per scene

### Pool builder (LLM, brief-agnostic)
- `triage.py` — Claude on keyframe grids → `scene_triage.json`
- `scene_describe.py` — Gemini on scene videos → `scene_descriptions.json`
- `quote_scout.py` — Claude on transcript → `quote_candidates.json`
- `pool_build.py` — deterministic merge → `pool.json`

### Composition (LLM, per brief)
- `arrange.py` — Claude on pool + brief → `arrangement.json`

### Assembly & render
- `cut.py` — `arrangement.json` + pool → multi-track `hype.timeline.json`, `hype.assets.json`, `hype.metadata.json`
- `render_remotion.py` — wraps `npx remotion render` with HTTP-served assets (no public-dir copy)
- `tools/remotion/` — standalone Remotion project (cloned from reigh-app)

### Validation & utilities
- `validate.py` — re-transcribes the output mp4 and cross-checks per-clip captions
- `pipeline.py` — top-to-bottom orchestrator with cache-aware `--from` / `--skip`
- `open_in_reigh.py` — bridge for reigh-app Supabase backend (best-effort manual handoff)
- `text_match.py`, `llm_clients.py`, `timeline.py` — shared helpers + schema module

### Schema anchor
- `timeline.py` — Python TypedDicts mirroring reigh-app's `TimelineConfig`. Timeline JSON + AssetRegistry stay byte-compatible with reigh-app.

## What landed in this session

1. **Sprints 1–4** (megaplans): schema foundation, Remotion renderer, update mode + audio retirement + gemini refactor, pipeline runner + reigh-app bridge.
2. **Real-data validation** on ADOS 2026 (2-hour source): rendered 68.8s hype.mp4 end-to-end.
3. **Bug surfacing & fixes from real runs:**
   - `transcribe.py` chunker wasn't stripping video (Whisper 25 MB overflow).
   - `render_remotion.py` used relative paths with wrong cwd; `--public-dir` copied whole source folders blowing out disk.
   - `cut.py` metadata lied about provenance (hardcoded `steps_run`, fake `tool_versions`).
   - `pipeline.py` didn't plumb `--env-file`.
   - Gemini hallucinated timestamps decoupled from caption content.
4. **Validator** (`validate.py`) added — re-transcribes output, cross-checks captions.
5. **Pool-based architecture** rewrite (light code-mode megaplan, 18 tasks, 8 batches, $4.90): new stages, Gemini no longer returns timestamps, multi-track assembly.

## Currently running

First real-data run of the pool-based pipeline (Bash `barswgp0w`). Flow:
- ✓ transcribe — 965 segments from 2h ADOS source
- ⏳ scenes.py — in flight (~20 min for 2h @ 1080p)
- 🔜 shots, triage, scene_describe, quote_scout, pool_build, arrange, cut, render, validate

Output dir: `runs/ados_pool/`. Brief: "75–90s hype, community-forward, mix dialogue spine with b-roll visual stingers, avoid hold screens and long monologues."

Next scheduled check-in at 00:55 (wakeup). First bug will surface in one of the new stages (never run against live APIs before).

## Known issues / open questions

- **Plan.json deprecated** in favor of brief.txt. Old cuts can still be re-run via `--plan` (legacy alias), but it emits a warning.
- **`cut.py --picks` path** also deprecated.
- **Validator false positives** on visual captions (resolved by `caption_kind`: visual clips auto-skip).
- **Pre-existing test failure** in `test_audio_render` (macOS `/var` vs `/private/var` symlink — not related to our work).
- **Reigh-app bridge** still best-effort manual handoff (reigh-app uses Supabase-backed storage, not file-based).
- **Multi-source** (`--asset KEY=PATH`) works end-to-end but the pool assumes single primary asset in v1.
- **Speaker diarization** out of scope for v1.

## Worth reading

- `docs/design/pool-based-architecture-plan.md` — the plan that drove this rewrite (staged from the aborted doc-mode megaplan at iteration 4).
- `_reference/README.md` — reigh-app composition & schema reference.
- `README.md` — user-facing CLI docs (updated per pool flow).
- `examples/hype.timeline.full.json` — golden fixture for reigh-app schema compatibility.

## Quick commands

```bash
# End-to-end with a brief
PYENV_VERSION=3.11.11 python pipeline.py \
  --video <source.mp4> \
  --brief <brief.txt> \
  --out runs/<project>/ \
  --env-file <path/to/.env> \
  --render

# Resume from a specific stage
PYENV_VERSION=3.11.11 python pipeline.py ... --from arrange

# Validate rendered output
PYENV_VERSION=3.11.11 python validate.py \
  --video runs/<project>/hype.mp4 \
  --env-file <path/to/.env>

# Run the test suite
PYENV_VERSION=3.11.11 python -m unittest discover tests -v
```

## Total cost so far (megaplan usage this session)

Sprint 1–4 + cleanup + pool restructure combined: ~$50 in megaplan orchestration + validation. Live API calls for actual pipeline runs additional (Whisper chunks + Gemini video uploads + Claude triage/scout/arrange).
