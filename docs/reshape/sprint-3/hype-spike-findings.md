# Hype-spike findings — Sprint 3 schema/adapter port

**Branch:** `reshape/sprint-3-hype-spike` (throwaway; pushed for archival, NEVER merged into `reshape/sprint-3`)
**Ported:** first three `builtin.hype` steps (transcribe → cut → render) as a paper port at `.spike/hype_first_three_ported.py`
**Status:** NO stop-line tripped. Dynamic discovery is expressible. Schema mostly fits with three should-tier revisions; one must-tier clarification.

---

## STOP-LINE check

The brief's stop-line is *"dynamic discovery cannot be expressed by static-tree schema"*. Specifically: hype's middle phase fans out across discovered scenes (`for_each item in scenes.json.scenes`). Verdict:

- The new schema's `repeat.for_each.from_ref` referring to a prior-sibling `produces` name **does** express this. The validator (T7's I5 invariant) resolves `transcribe.produces.scenes_list` → real prior produces → tree is well-formed.
- No `schema-redesign.md` required. Proceed to T6.

The remaining findings are revisions — none block sprint-3 schema lock.

---

## Gap G1 — Group-step `produces` aggregation is under-specified (MUST clarify before T7)

**Symptom:** the brief reads *"Group step has children, no command. Its `produces` aggregates from descendants."* but does not pin down:
- Is the parent's `produces` map the *union* of descendant produces, or is the parent allowed to declare its own *new* names that re-export descendant artifacts under different paths?
- On sibling-id uniqueness (Invariant I2): are descendant `produces` names checked against the parent's own `produces` map, or only against the parent's children?
- If a tombstoned descendant has a name in the aggregated map, what happens at I3 (produces-ref integrity)?

**Hype impact:** the real hype pipeline has 15 leaf executors that any future `hype` group step would aggregate. Two distinct artifacts can share short names across nested groups (`final_video` in render, `final_video` in editor_review). Today the legacy `nested` kind sidesteps this because group-step `produces` is opaque.

**Proposed lock-in (T6/T7):**
- Group `produces` declarations are **fresh names**, not auto-aggregation. The group declares which descendant artifacts get *re-exported* under the group's namespace via explicit `re_export: {name: child-step-id.produces.name}` syntax, OR group declares no produces at all and downstream callers reference `group_id/child_id.produces.name`.
- I2 sibling-id uniqueness checks group `produces` keys against *other group siblings* only, never against descendants.
- I3 dangling-ref check follows the explicit `re_export` chain.

**Schema revision needed:** add `re_export: dict[str, str] | None` to `Step` (group-step-only). Lock during T6.

**Status (T6):** LANDED. `Step.re_export: tuple[tuple[str, str], ...] | None` added; `__post_init__` rejects re_export on leaf steps; `_validate_step` parses `re_export` from JSON (rejects on non-group, non-dict, empty, or malformed `<child-id>.produces.<name>` refs); `_step_to_dict` round-trips. Full descendant-resolution (does each ref actually resolve to a real produces?) deferred to T7 validator I3.

---

## Gap G2 — Cost field needs a sidecar convention for local-adapter steps

**Symptom:** brief says completion events carry `cost: {amount, currency, source}` when an adapter declares one. Local adapter is a subprocess. Subprocesses *cannot* mutate the parent's outbound event payload — they exit with a return code and produce files. The schema declares the field but the wire is missing.

**Hype impact:** transcribe calls Gemini (paid API). render calls Remotion (GPU minutes). Both have real per-step USD cost that needs to surface. If cost only flows from "the adapter declared it", local-adapter steps can never declare cost — which makes the field a Sprint-4/5a-only signal and removes hype's primary use case.

**Proposed lock-in:**
- Local-adapter convention: subprocess MAY write `produces/<step-id>/v<N>/cost.json` containing `{amount, currency, source}`. T11's local-adapter `complete()` reads it if present, populates `CompleteResult.cost`. If absent, cost is omitted (NOT null — per the watch-item).
- Document this in the local-adapter docstring and in `docs/reshape/sprint-3/async-completion.md` (T25).

**Schema revision needed:** none — `CostEntry` shape already correct. Convention-level, documented at T11.

---

## Gap G3 — Command interpolation grammar is unspecified

**Symptom:** the spike port writes things like `--source {source} --transcribe {transcribe.produces.transcribe}`. The schema accepts a `command: str` but doesn't define how `{...}` placeholders get resolved. The legacy hype pack used `{python_exec}` and `{orchestrator_args}` substitution that lived in orchestrator.yaml's `runtime.command.argv`.

**Hype impact:** every leaf step's command needs at minimum: `{source}` (run input), `{out}` (project root output dir), `{step.produces.NAME}` (prior produces resolution), `{python_exec}` (interpreter path). Without a grammar, three options exist: (a) shell `$VAR` expansion via subprocess env, (b) explicit `{...}` placeholder list with kernel-side substitution at dispatch time, (c) make the executor pack responsible.

**Proposed lock-in (recommend in T11):**
- Local adapter pre-substitutes a fixed set: `{run_root}`, `{step_root}` (the `steps/<id>/v<N>/` dir), `{python_exec}`, plus `{X.produces.Y}` resolved from the effective plan at dispatch time.
- Anything else stays literal — escape with `{{`.
- Document at T25.

**Schema revision needed:** none. Convention-level, but **call out in T11's docstring** so packs don't assume shell-style.

---

## Gap G4 — "local" adapter name conflates "runs locally" with "runs on cheap CPU"

**Symptom:** transcribe and render both technically run via `python -m ...` on the host, but transcribe calls a remote LLM API and render uses GPU. Calling these "local" is descriptively correct (the subprocess is local) but semantically misleading for cost/queue/scheduling purposes.

**Hype impact:** Sprint 4 (RunPod lift) and Sprint 5a (`remote-artifact`) both need to distinguish "run a local subprocess that *internally* hits a paid backend" from "queue this on a remote GPU". With three adapter slots filled, the natural future evolution is `remote-artifact` taking over render in Sprint 5a — but transcribe is awkwardly *not* remote-artifact (the LLM is fire-and-forget, not an artifact pull).

**Proposed lock-in:** no schema change for Sprint 3. Document in the hype-spike findings (this file) that `local` is the right label for the subprocess-with-side-effects pattern; the cost sidecar (G2) is sufficient. Revisit in Sprint 4 if a "remote-invoke" adapter becomes needed distinct from `remote-artifact`.

**Schema revision needed:** none.

---

## Gap G5 — Step.repeat.for_each materialisation timing is unclear

**Symptom:** when `cut.repeat.for_each.from_ref = "transcribe.produces.scenes_list"`, the items list is unknown until *after* transcribe completes. The current cursor / `_Frame` model assumes plan tree is fully knowable at run-start.

**Hype impact:** spike's port collapses scenes into cut for brevity, but the real hype pipeline DOES fan out on discovered scenes. T9 (cursor extension) needs to know: items materialise via the existing `for_each_expanded` event (Sprint 1 primitive) — which the spike validated still applies to the collapsed schema.

**Proposed lock-in:** none — Sprint 1's `for_each_expanded` event mechanism already covers this. **Note the dependency in T9's task notes** so the cursor extension preserves the deferred-materialisation path. Not a schema gap, just a watch-item for T9.

**Schema revision needed:** none.

---

## Summary

| # | Gap | Severity | Resolves at |
|---|-----|----------|-------------|
| G1 | Group-step `produces` aggregation under-specified | **must** (blocks T7) | T6 schema lock |
| G2 | Cost sidecar convention for local-adapter | should | T11 + T25 |
| G3 | Command-interpolation grammar | should | T11 + T25 |
| G4 | `local` adapter name semantic overload | nit | future sprint |
| G5 | `for_each.from_ref` deferred materialisation | watch-item | T9 |

**Net:** schema survives the hype shape. One must-tier addition (`re_export` on group steps) lands during T6 alongside the DRAFT-marker removal. Two should-tier conventions documented during T11+T25. No stop-line tripped — proceed.

**Spike branch disposition:** push `reshape/sprint-3-hype-spike` to origin for archival. Do NOT merge into `reshape/sprint-3`. T6 switches back and folds the G1 schema revision in by hand.
