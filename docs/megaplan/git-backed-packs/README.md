# Git-Backed Packs Megaplan Chain

This directory prepares, but does not launch, the chained megaplan run for
`docs/git-backed-packs-plan.md`.

Run from the repository root only after the chain setup branch has been reviewed:

```bash
megaplan chain start --spec docs/megaplan/git-backed-packs/chain.yaml
```

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
