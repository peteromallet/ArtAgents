# Ingest Assets — Stage

## Purpose
Ingests raw media assets from a source directory, validates file types (images, video clips, audio, scripts), normalizes filenames, and produces a structured asset manifest for downstream orchestrators like make_trailer.

## Entrypoint
- `run.py` — Python CLI script with `--source` and `--out` arguments.

## Expected Input
- A source directory containing media files.

## Output
- An `assets_manifest.txt` file listing all discovered assets.

## Dependencies
- No external Python packages required beyond stdlib.
