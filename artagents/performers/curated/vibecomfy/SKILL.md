# VibeComfy

Curated ArtAgents performer metadata for invoking VibeComfy workflow actions through
the public CLI surface:

- `external.vibecomfy.run` maps to `python -m vibecomfy.cli run {workflow}`
- `external.vibecomfy.validate` maps to `python -m vibecomfy.cli validate {workflow}`

Install the performer package through the explicit ArtAgents performer install flow before
running these actions. Both performers share the `vibecomfy` package environment via
the folder-level `PACKAGE_ID`.
