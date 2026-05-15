# Media Production Pack

## Purpose
AI-assisted media production capabilities for video trailer creation.

## Components
- **ingest_assets** executor: Ingests and validates project assets from a source directory.
- **make_trailer** orchestrator: Coordinates asset ingestion and assembly into a trailer.
- **project-title-card** element: A Remotion effect for rendering project title cards.

## Entrypoints
- `ingest_assets`: Run the asset ingestion executor.
- `make_trailer`: Run the trailer orchestration pipeline.

## Required Context
- `brief`: A creative brief describing the desired output.
- `project_config`: Project configuration including output settings.

## Secrets
- `OPENAI_API_KEY` (required): For AI-assisted media generation.
- `UNSPLASH_ACCESS_KEY` (optional): For stock image search.

## Dependencies
- Python: openai>=1.0.0, requests
- npm: @remotion/player@4.0.0
- System: ffmpeg
