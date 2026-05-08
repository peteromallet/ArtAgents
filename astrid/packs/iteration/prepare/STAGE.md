# Iteration Prepare Executor

`iteration.prepare` collects the thread/provenance graph for a target run and
emits the data needed by `iteration.assemble` without rendering.

It walks typed `parent_run_ids`, thread provenance `contributing_runs`, and
artifact-hash ancestry from the target run. Runs are labelled `in_thread` when
they belong to the target thread and `pulled_by_ancestry` when they are brought
in only by provenance.

Outputs:

- `iteration.manifest.json`
- `iteration.quality.json`

The OQ-6 quality score is:

`0.5*parent_capture_score + 0.3*has_brief_sha + 0.2*has_resolved_input_artifact`

`max_iterations` is enforced before any uncached summary dispatch. The default
cap is 200 and can be changed with `--max-iterations` or
`ARTAGENTS_ITERATION_MAX`.

Gateway form:

```bash
python3 -m astrid executors run iteration.prepare --out runs/prepare --input target_run_id=<run-id>
```

Direct form:

```bash
python3 -m astrid.packs.iteration.prepare.run --target-run-id <run-id> --out runs/prepare
```
