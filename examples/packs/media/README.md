# Media Production Pack

A realistic media production pack for video trailer creation with AI-assisted workflows.

## Overview

This pack provides all the components needed for a media production pipeline:
- Asset ingestion and validation
- Trailer orchestration and assembly
- Visual effects via Remotion components

## Installation

```bash
astrid packs install examples/packs/media
```

## Usage

```bash
# Validate the pack
astrid packs validate examples/packs/media

# Run the asset ingestion executor
python3 executors/ingest_assets/run.py --source /path/to/assets --out /path/to/output

# Run the trailer orchestrator
python3 orchestrators/make_trailer/run.py --out /path/to/output --brief /path/to/brief.txt
```

## Requirements

- Python 3.10+
- ffmpeg
- OpenAI API key
- Node.js (for Remotion components)
