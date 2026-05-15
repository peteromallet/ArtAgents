# Legacy Templates (Deprecated)

This directory contains JSON-shaped templates for the *internal* built-in pack format used before Sprint 1.

**These templates are deprecated.** The canonical authoring path is now:

```bash
python3 -m astrid packs new <id>
python3 -m astrid executors new <pack>.<slug>
python3 -m astrid orchestrators new <pack>.<slug>
python3 -m astrid elements new <kind> <pack>.<slug>
```

See `docs/creating-packs.md` for the current authoring guide.

## Historical Note

These templates describe the legacy manifest shape used by built-in
executors, orchestrators, and elements inside `astrid/packs/`. They are
retained for reference but are **not** the recommended starting point for
new pack development.
