# Minimal Example Pack — Agent Guide

## When to Use This Pack

Use this pack as a reference when creating your own external Astrid packs.
It demonstrates the minimal structure, manifest format, and CLI workflow.

## Entrypoints

- **`minimal.make_trailer`** — Orchestrator that coordinates asset ingestion and assembly.

## Executors

- **`minimal.ingest_assets`** — Ingests and validates project assets.

## Notes

This pack is not a built-in. It lives at `examples/packs/minimal/` and
demonstrates the `--pack-root` evaluation path.
