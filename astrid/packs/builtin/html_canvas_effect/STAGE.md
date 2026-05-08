# HTML Canvas Effect Executor

Use `builtin.html_canvas_effect` when you want to create a local, editable
Remotion effect element that uses `<HtmlInCanvas>` for canvas post-processing.

This executor scaffolds the element. It does not render the final video and it
does not replace `builtin.render`; timelines should still render through the
normal Remotion timeline compositor.

Inspect first:

```bash
python3 -m astrid executors inspect builtin.html_canvas_effect --json
```

Dry-run through the canonical executor CLI:

```bash
python3 -m astrid executors run builtin.html_canvas_effect \
  --input effect_id=glass-product-card \
  --input label="Glass Product Card" \
  --out runs/html-canvas-effect \
  --dry-run
```

Run directly:

```bash
python3 -m astrid.packs.builtin.html_canvas_effect.run \
  --effect-id glass-product-card \
  --label "Glass Product Card" \
  --out runs/html-canvas-effect/report.json
```

Output:

- `astrid/packs/local/elements/effects/<effect-id>/component.tsx`
- `astrid/packs/local/elements/effects/<effect-id>/element.yaml`
- report JSON at `--out`
- preview `timeline.json` and `assets.json` next to the report

Render the preview through the normal renderer:

```bash
python3 -m astrid.packs.builtin.render.run \
  --timeline runs/html-canvas-effect/timeline.json \
  --assets runs/html-canvas-effect/assets.json \
  --out runs/html-canvas-effect/preview.mp4
```

Rendering note:

The generated element intentionally declares HTML-in-canvas requirements in its
metadata. Current Astrid render should remain the default path, but using the
element in a timeline requires a Remotion version that exposes
`HtmlInCanvas` (`>=4.0.455`) and may require `--gl=angle` or `--gl=swangle` for
shader-heavy variants.
