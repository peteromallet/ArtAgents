# Make Trailer — Stage

## Purpose
Reads a creative brief, coordinates media asset ingestion, plans trailer scenes using AI (when API keys are available), and produces a structured trailer build manifest. This manifest can then be rendered using Remotion elements (project-title-card, etc.).

## Entrypoint
- `run.py` — Python CLI script with `--out` and `--brief` arguments.

## Expected Input
- A creative brief file (plain text or JSON Schema brief) describing the trailer's goals, tone, and assets.

## Output
- A `trailer_manifest.txt` file with scene descriptions and element references.

## Dependencies
- Python: `openai>=1.0.0` (for AI-assisted scene planning)
- System: `ffmpeg` (for video processing)
