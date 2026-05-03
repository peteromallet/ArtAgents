# First Rite Orchestrator

Use `builtin.first_rite` as an onboarding moment for an agent that has just
landed in the repo. It writes a fixed prompt to `runs/first-rite/prompt.txt`,
calls `builtin.generate_image` to render it, and opens the result for the
maker.

The rite is a working example of an orchestrator composing an executor — the
shape every new orchestrator should follow.

Run:

```bash
python3 -m artagents orchestrators run builtin.first_rite
```

Dry-run (no API call, no image written, no `open`):

```bash
python3 -m artagents orchestrators run builtin.first_rite -- --dry-run
```

Override the output directory if the default collides:

```bash
python3 -m artagents orchestrators run builtin.first_rite -- --out runs/my-rite
```

Skip opening the image (useful in headless contexts):

```bash
python3 -m artagents orchestrators run builtin.first_rite -- --no-open
```
