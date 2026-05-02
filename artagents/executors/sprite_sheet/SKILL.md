# Sprite Sheet Executor

Use `builtin.sprite_sheet` to create animation sprite sheets and sliced frame
previews from a subject plus animation description.

Dry-run or inspect first:

```bash
python3 pipeline.py executors inspect builtin.sprite_sheet
python3 pipeline.py executors run builtin.sprite_sheet --out runs/sprites/wave --input animation=wave --input subject="neon courier" --dry-run
```

Requires image API credentials for generation and `ffmpeg` for slicing/preview
exports.

## Outputs

Expected files include:

- `{out}/sprite_manifest.json`
- `{out}/sprite_sheet.png`
- `{out}/sprite_sheet_alpha.png`
- `{out}/frames/frame_001.png` and sibling frame PNGs
- `{out}/sprite_preview.mp4`
- `{out}/web/sprite_sheet.webp` and web preview outputs when web export is enabled

Safety-edge warnings mean one or more sliced frames touch the configured edge
margin. Treat that as a soft QA warning for prototypes and a prompt/layout retry
signal for production sprites.
