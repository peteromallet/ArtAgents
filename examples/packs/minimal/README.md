# Minimal Example Pack

A minimal external pack demonstrating the Astrid pack contract.

## What's Inside

- **`minimal.ingest_assets`** — An executor that ingests and validates project assets.
- **`minimal.make_trailer`** — An orchestrator that coordinates asset ingestion and assembly into a trailer.

## Usage

The pack lives under `examples/packs/minimal/`. It is **not** a built-in
discovered pack — it demonstrates the external pack contract. You can
evaluate and run it without installing:

```bash
# Validate the pack structure
python3 -m astrid packs validate examples/packs/minimal

# Inspect the executor
python3 -m astrid executors inspect minimal.ingest_assets --pack-root examples/packs/minimal

# Inspect the orchestrator
python3 -m astrid orchestrators inspect minimal.make_trailer --pack-root examples/packs/minimal
```

To run inside a bound session:

```bash
python3 -m astrid attach
# Inside the session:
orchestrators run minimal.make_trailer --pack-root examples/packs/minimal --out /tmp/minimal-out
```

## Structure

```
minimal/
  pack.yaml
  README.md
  AGENTS.md
  executors/
    ingest_assets/
      executor.yaml
      run.py
  orchestrators/
    make_trailer/
      orchestrator.yaml
      run.py
  elements/
```
