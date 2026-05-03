# Example Orchestrator

Use `builtin.example` when a workflow needs to coordinate multiple existing
executors or orchestrators.

Inspect first:

```bash
python3 -m artagents orchestrators inspect builtin.example --json
```

Dry-run:

```bash
python3 -m artagents orchestrators run builtin.example --dry-run -- --dry-run
```

Run:

```bash
python3 -m artagents orchestrators run builtin.example -- --dry-run
```
