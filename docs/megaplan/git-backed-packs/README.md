# Git-Backed Packs Megaplan Chain

This directory prepares the chained megaplan run for
`docs/git-backed-packs-plan.md`.

Run from the repository root only after the chain setup branch has been reviewed:

```bash
megaplan chain start --spec docs/megaplan/git-backed-packs/chain.yaml
```

## Megaplan Cloud

The cloud spec is at `docs/megaplan/git-backed-packs/cloud.yaml`. It deploys a
Railway-backed runner from the isolated setup branch:
`megaplan/git-backed-packs-chain-setup`.

Export the secrets named in the cloud spec before deploying:

```bash
export GITHUB_TOKEN=...
export ANTHROPIC_API_KEY=...
export DEEPSEEK_API_KEY=...
export OPENAI_API_KEY=...
```

Build and deploy the cloud runner:

```bash
megaplan cloud build --cloud-yaml docs/megaplan/git-backed-packs/cloud.yaml
megaplan cloud deploy --cloud-yaml docs/megaplan/git-backed-packs/cloud.yaml
```

Start the remote chain:

```bash
megaplan cloud chain docs/megaplan/git-backed-packs/chain.yaml \
  --idea-dir docs/megaplan/git-backed-packs/ideas \
  --cloud-yaml docs/megaplan/git-backed-packs/cloud.yaml
```

Monitor it:

```bash
megaplan cloud status --chain --cloud-yaml docs/megaplan/git-backed-packs/cloud.yaml
megaplan cloud logs --cloud-yaml docs/megaplan/git-backed-packs/cloud.yaml
megaplan cloud attach --cloud-yaml docs/megaplan/git-backed-packs/cloud.yaml
```

The runner boots in `idle` mode on purpose. `megaplan cloud chain` is the
preferred launch path because it uploads the chain spec and milestone idea
files to the remote workspace before starting `megaplan chain start` in the
`megaplan-chain` tmux session. With `merge_policy: review`, the chain should
pause at milestone PR boundaries for review/merge instead of silently flowing
into `main`.

The chain is configured with:

- One milestone branch per sprint: `megaplan/git-backed-packs/sprint-XX-*`.
- `merge_policy: review`, so each milestone should wait for review/merge instead
  of silently flowing into `main`.
- Normal rubric profiles (`premium`, `thoughtful`) rather than copied profiles.
- A YAML anchor that routes DeepSeek phases through the direct DeepSeek API:
  `hermes:deepseek:deepseek-v4-pro`.

The optional sandbox sprint is intentionally not in the default chain because
the chain runner does not support disabled milestones. Add it as a separate
follow-up chain once Sprint 9 is complete and the security posture is still
worth pursuing.
