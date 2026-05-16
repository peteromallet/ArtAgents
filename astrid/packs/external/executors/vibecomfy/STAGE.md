---
name: vibecomfy
description: Curated Astrid executor metadata for invoking VibeComfy workflow actions through the public CLI surface.
---

# VibeComfy

Curated Astrid executor metadata for invoking VibeComfy workflow actions through
the public CLI surface:

- `external.vibecomfy.run` maps to `python -m vibecomfy.cli run {workflow}`
- `external.vibecomfy.validate` maps to `python -m vibecomfy.cli validate {workflow}`

Install the executor package through the explicit Astrid executor install flow before
running these actions. Both executors share the `vibecomfy` package environment via
the folder-level `PACKAGE_ID`.
