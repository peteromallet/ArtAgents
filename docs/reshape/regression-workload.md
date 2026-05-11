# Regression Workload — Sprint 0 Baseline

## Status: No Prior hype Runs Found

**Date assessed:** 2026-05-11

### Search results

1. **`~/Documents/reigh-workspace/astrid-projects/`**: The project directory exists but is empty. No projects, runs, or timelines are present on disk.

2. **Repo test fixtures**:
   - `examples/hype.timeline.json` — A sample hype timeline artifact. This is a static example file, not tied to an actual project run.
   - `tests/fixtures/iteration_video/assembled/hype.timeline.json` — A test fixture for iteration-video assembly tests. Also a static artifact, not a live run.
   - `tests/fixtures/multitrack_cut/hype.timeline.golden.json` — Golden file for multitrack cut tests.

   None of these correspond to actual runnable projects with `runs/<run-id>/` directories containing `timeline.json`, `plan.json`, or `events.jsonl`.

3. **No completed hype runs**: No `run_id`, plan, transcript path, brief path, or final mp4 path is available.

### Implication

- **SHA256 of final mp4**: NOT AVAILABLE — no hype run has been completed on this machine.
- **Command line**: NOT APPLICABLE — no project exists to reference.

### Next Steps (for later sprints)

When a hype run is completed (before Sprint 5a), update this document with:

1. Project slug
2. Run ID
3. Exact command line used
4. Expected output paths:
   - Transcript path
   - Brief path
   - Final mp4 path
5. SHA256 of the final mp4

This will become the regression gate that every later sprint must pass before merging `reshape/` back to `main`.