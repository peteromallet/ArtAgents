# Reference files vendored from reigh-app

These files are read-only references for Sprint 2 (Remotion renderer).
They were copied from `/Users/peteromalley/Documents/reigh-workspace/reigh-app/`
so that the megaplan planner worker can read them (workers cannot access
files outside the project_dir).

**Do not edit these files.** They are the semantic ground truth for the
Remotion composition port. The cloned versions in `tools/remotion/src/`
are what gets bundled; these are just the source of truth to port from.

## Paths map
- `reigh-app/src/tools/video-editor/types/index.ts` — TimelineConfig / TimelineClip / TrackDefinition / AssetRegistry TypeScript types
- `reigh-app/src/tools/video-editor/lib/config-utils.ts` — the authoritative trim / duration / volume / speed sanitization functions. When porting, match these exactly.
- `reigh-app/src/tools/video-editor/lib/render-bounds.ts` — viewport layout math. Returns `ViewportMediaLayout = {fullBounds, visibleBounds, renderBounds, mediaBounds, cropValues}` — four `RenderBounds` objects, NOT a flattened CSS style. Consumers apply `renderBounds` as the outer clipping viewport and `mediaBounds` as the inner media position. Two-layer render is load-bearing for crop/manual-position.
- `reigh-app/src/tools/video-editor/lib/editor-utils.ts` — `getVisualTracks` / `getAudioTracks` partitioning helpers.
- `reigh-app/src/tools/video-editor/compositions/TimelineRenderer.tsx` — root composition
- `reigh-app/src/tools/video-editor/compositions/VisualClip.tsx` — per-clip visual renderer (Video/Img). **Two-layer:** outer `<div style={viewportStyle}>` from `renderBounds` with `overflow: hidden`, inner `<Video>`/`<Img>` from `mediaBounds` with `maxWidth: none, maxHeight: none`. See `VisualClip.tsx:156-210` for the exact shape.
- `reigh-app/src/tools/video-editor/compositions/AudioTrack.tsx` — audio track renderer
- `reigh-app/src/tools/video-editor/compositions/TextClip.tsx` — text clip renderer
- `reigh-app/src/tools/video-editor/compositions/MediaErrorBoundary.tsx` — error boundary wrapper (**not ported** in Sprint 2 scope)
- `reigh-app/package.json` — dependency versions to match

## Critical semantics the port must preserve verbatim
These were factual errors in earlier plan iterations; do not regress them:

1. **Trim math (config-utils.ts:34-48):**
   `trimBefore = secondsToFrames(max(0, from))`
   `trimAfter = secondsToFrames(to)` *if* `to > from`, else undefined.
   No subtraction from asset duration. Pass the target frame through.

2. **Timeline duration floor (config-utils.ts:93-99):**
   `Math.max(1, ...)` — a single-frame floor, NOT `fps` frames.

3. **Image type detection (VisualClip.tsx:105):**
   `assetEntry.type?.startsWith('image')` — accepts `image`, `image/png`, etc.
   NOT strict equality `type === 'image'`.

4. **Playback rate (config-utils.ts:51-53):**
   `speed > 0 ? speed : 1` — zero and negative speeds fall back to 1.

5. **Volume sanitization (config-utils.ts:55-59):**
   `Math.max(0, volume)` with fallback `1` when not finite.
   Track volume and clip volume multiply: `track.muted ? 0 : track.volume * clip.volume`.
