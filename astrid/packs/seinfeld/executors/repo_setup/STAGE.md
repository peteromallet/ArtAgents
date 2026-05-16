# seinfeld.repo_setup

Idempotent git submodule initializer for the `ostris/ai-toolkit` upstream
reference.  Ensures `astrid/packs/seinfeld/ai_toolkit/upstream/` is checked
out at a pinned SHA so that later executors (`aitoolkit_stage` in particular)
can read the upstream config schema without depending on a live pod.

**Invocation (standalone)**:

```bash
python3 -m astrid.packs.seinfeld.executors.repo_setup.run --out /tmp/repo_setup_test
```

**Invocation via orchestrator**:

```yaml
# lora_train orchestrator preflight calls this via framework:
python3 -m astrid executors run seinfeld.repo_setup --out runs/seinfeld-lora/000-repo-setup
```

**Idempotency**: If `ai_toolkit/upstream/.git` already exists, the executor
exits 0 with `{status: "already_initialized"}` and does not touch the
submodule.

**Requirements**: A git working tree (`git submodule add` only works inside
a `.git` checkout — dev-time only).

**Pinned SHA**: `f38de2a2fedfafa4bf298806d1efcabb4a357cbc` (HEAD of
ostris/ai-toolkit main as of 2026-05-12; confirmed LTX 2.3 support).