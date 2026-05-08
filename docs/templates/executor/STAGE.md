# Example Executor

Use `builtin.example` when one concrete input artifact should be converted into
one result artifact.

Inspect first:

```bash
python3 -m astrid executors inspect builtin.example --json
```

Dry-run:

```bash
python3 -m astrid executors run builtin.example --input input=path/to/input.json --out runs/example --dry-run
```

Run:

```bash
python3 -m astrid executors run builtin.example --input input=path/to/input.json --out runs/example
```
