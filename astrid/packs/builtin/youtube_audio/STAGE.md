---
name: youtube_audio
description: Search YouTube for a query and download the top hit's audio as MP3 via yt-dlp.
---

# YouTube Audio Executor

Use `builtin.youtube_audio` to source background tracks for video composites
without leaving the Astrid CLI. Wraps `yt-dlp`'s `ytsearch1:` selector
plus `--extract-audio` so you give it a free-text query and get an MP3.

## Quick reference

```bash
python3 -m astrid executors run builtin.youtube_audio \
  --input query="Moby Extreme Ways official audio" \
  --out runs/audio/extreme-ways
```

Output is `runs/audio/extreme-ways.mp3` (the executor appends `.mp3`
automatically when no extension is given).

## Inputs

| name  | type   | description |
|-------|--------|-------------|
| query | string | Free-text YouTube search query — top result's audio is downloaded. |

## Outputs

| name  | type | description |
|-------|------|-------------|
| audio | file | MP3 audio extracted from the top YouTube result. |

## Requirements

- `yt-dlp` on `PATH` (`pip install yt-dlp` or `brew install yt-dlp`)
- `ffmpeg` on `PATH` (yt-dlp uses it for the audio-format conversion)

The executor checks both binaries at start and exits with a clear error
if either is missing.

## Composing with the rest of the pipeline

Most useful as a one-shot before a render:

```bash
# 1. Download a track
python3 -m astrid executors run builtin.youtube_audio \
  --input query="lo-fi study beat" --out runs/audio/lofi

# 2. Mux it under a rendered composite (start at 4s, fade out last 2.5s)
ffmpeg -y -i composed.mp4 -i runs/audio/lofi.mp3 \
  -filter_complex "[1:a]atrim=0:DURATION,asetpts=PTS-STARTPTS,adelay=4000|4000,afade=t=out:st=FADE_START:d=2.5[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k composed_with_music.mp4
```

Where `DURATION = video_duration - 4` and `FADE_START = video_duration - 2.5`.

## Caveats

- **Respect YouTube's terms of service and copyright** — only download
  material you have rights to use (your own uploads, Creative Commons
  tracks, royalty-free libraries, music you license, etc.).
- The top search hit is what you get; for a specific track it's worth
  including the artist name and the word "audio" or "official" in the
  query to avoid live performances and long-tail uploads.
- Network is required at runtime. The cache mode is `none` so re-runs
  always hit yt-dlp; if you need caching, write to a stable `--out` path
  and check existence yourself before invoking.
- `yt-dlp` versions drift quickly; if a download fails, run
  `pip install -U yt-dlp` first.
