# Orchestrator V1 Bake-off Assessment

A retrospective on the four-phase profile bake-off (Phases 6 through 9 of the
orchestrator V1 plan, run on 2026-05-05) covering ~$84 of model spend across 18
arms, the bugs it surfaced in the megaplan harness, and the cost/quality
tradeoffs that should inform the default profile mix going forward.

## 1. Executive summary

Four consecutive phases of the orchestrator V1 plan (stop-hook nudge,
per-project CAS, inbox surface, author-test + goldens) were each run as a
concurrent multi-profile bake-off — three profiles for Phase 6, five profiles
for Phases 7-9 — using the megaplan worktree harness. The all-Claude control
won every phase (4/4) on quality grounds, but the cheap profiles were not
embarrassingly bad — each shipped working code, full test passes, and only a
small number of high-stakes correctness deviations. The exercise validated the
blind/structured assessment workflow, confirmed that plan quality predicts
execute quality, surfaced and fixed three real harness bugs, and produced four
shippable commits on `main` (`1115518`, `1681c1a`, `d93bec6`, `53fdd68`). The
remaining open question is whether `deepseek-claude-critique` (Claude-as-critic
with DeepSeek leads and executors) is good enough to be the routine default
when the spec is fully nailed down — early signal says yes, but the sample is
four phases.

## 2. Phase-by-phase results

All five profiles unless noted: `all-claude` (control), `deepseek-kimi-deepseek`
(dkd), `claude-kimi-deepseek-or` (ckd-or), `all-deepseek-or`, and
`deepseek-claude-critique` (dcc). All winners were `all-claude`. Costs are USD
and are the megaplan-orchestrator-reported `total_cost_usd` across the
plan/critique/revise/finalize/execute pipeline for that arm.

### Phase 6 — stop-hook nudge (commit `1115518`)

3-way bake-off (`all-deepseek-or` and `dcc` were not yet in the rotation). What
shipped: out-of-process Claude Code Stop-hook re-injecting the SD-023
prohibition preamble while a task run is active; safe global no-op when no run
exists. 7 new tests, 714 passing.

| Profile  | Status | Cost   | Notes                                                                          |
|----------|--------|--------|--------------------------------------------------------------------------------|
| all-claude | done | $10.48 | Winner. Two-tier discovery (cwd ancestor → projects-root scan) + slug guard.   |
| ckd-or   | done   | $3.38  | Misdirected writes to main repo (idea-brief abs-path bled through).            |
| dkd      | done   | $0.56  | Same misdirected-write incident; cheaper but no working diff in worktree.      |

The Phase 6 misdirected-write incident is the first harness bug section
(`a0ed9f51`). Runner-up was effectively n/a — both non-control arms failed the
sandbox-safety bar before reviewing on quality.

### Phase 7 — per-project CAS (commit `1681c1a`)

What shipped: per-project `<projects_root>/<slug>/.cas/<sha256>` content store
hooked into `_run_inline_checks`; produces files are interned and replaced with
a relative symlink. 5 new tests, 719 passing.

| Profile        | Status         | Cost   | Notes                                                      |
|----------------|----------------|--------|------------------------------------------------------------|
| all-claude     | done           | $10.97 | Winner. Only arm with end-to-end gate-driven test.         |
| ckd-or         | done           | $3.47  | Runner-up. Clean implementation; weaker isolation tests.   |
| dcc            | done           | $2.67  | Solid implementation, lighter test surface.                |
| dkd            | awaiting_human | $0.69  | Did not finalize; only arm not to reach `done`.            |
| all-deepseek-or| done           | $0.80  | Shipped a fallback path violating per-project invariant.   |

Key spec deviation: `all-deepseek-or` shipped a "global fallback CAS" branch
when the project root could not be resolved — exactly the cross-project leakage
SD-008 / SD-029 forbid.

### Phase 8 — inbox surface (commit `d93bec6`)

What shipped: opt-in `inbox/` directory under `runs/<run-id>/`; `next` consumes
valid approves by re-entering `gate_command`, `status` is read-only and counts
pending. Malformed entries quarantined to `inbox/.rejected/<sha256>`. 3 new
test files, 725 passing.

| Profile        | Status | Cost   | Notes                                                              |
|----------------|--------|--------|--------------------------------------------------------------------|
| all-claude     | done   | $13.32 | Winner. Only arm preserving identity / plan-hash / chain invariants.|
| ckd-or         | done   | $3.67  | Committed a `_throwaway_repro.py` debug file.                       |
| dcc            | done   | $2.53  | Imported private `_run_inline_checks` and `_latest_event_for_step`. |
| dkd            | done   | $0.74  | Required `evidence` as `list[str]`, rejecting spec dict shape.      |
| all-deepseek-or| done   | $0.71  | Bypassed identity by writing private events instead of acks.        |

The Phase 8 spread is the most informative of the four. Three of the four
non-control arms each shipped a working but invariant-violating implementation,
and they each violated a *different* invariant. The all-Claude arm was the only
one to recognize that "external completion signal" should re-enter the existing
gate rather than create a parallel ingestion path.

### Phase 9 — author test + goldens (commit `53fdd68`)

What shipped: `artagents author test --pack <p> --orchestrator <o> --fixture
<f>`; runs a compiled plan in a scratch dir with auto-approval gated on
`ARTAGENTS_AUTHOR_TEST=1`, normalizes `events.jsonl`, diffs against committed
golden, `--regenerate` to rewrite. Adjacent `_ack_approve` shlex-split bug also
fixed. 4 new test files (one removed), 725 passing.

| Profile        | Status | Cost   | Notes                                                                                         |
|----------------|--------|--------|-----------------------------------------------------------------------------------------------|
| all-claude     | done   | $23.74 | Winner. Preserved canonical `attestor_kind` enum; fixed adjacent `_ack_approve` bug.          |
| ckd-or         | done   | $5.07  | Runner-up.                                                                                    |
| dcc            | done   | $2.80  | Introduced `attestor_kind="system"` outside canonical {agent,actor} — kernel-invariant break. |
| dkd            | done   | $1.16  | Wrong test filenames (consolidated to one); wrong orchestrator id `builtin.hype_smoke`.       |
| all-deepseek-or| done   | $1.02  | Flattened `attestor_kind` to "agent" regardless of `step.ack.kind`.                           |

Phase 9 had the largest cost spread of the four (23x between the most expensive
and cheapest arm) and the most spec-deviation severity from the cheap arms —
two of three DeepSeek-led arms broke the canonical kind enum in incompatible
ways. The winner itself shipped a small naming drift: fixtures and goldens
landed at `builtin/fixtures/...` and `builtin/golden/...` rather than the
spec'd `builtin/hype/fixtures/...`, due to a file/folder import shadow on
`builtin/hype/`. This is a real but minor deviation; called out here so the
bake-off table is honest about the fact that no arm was perfectly spec-faithful
on Phase 9.

## 3. Cost-quality picture

Aggregate spend across the four phases (USD, megaplan-reported):

| Profile         | Phase 6 | Phase 7 | Phase 8 | Phase 9 | Total  | Multiple of cheapest |
|-----------------|---------|---------|---------|---------|--------|----------------------|
| all-claude      | 10.48   | 10.97   | 13.32   | 23.74   | 58.51  | 17.0x                |
| ckd-or          | 3.38    | 3.47    | 3.67    | 5.07    | 15.59  | 4.5x                 |
| dcc             | —       | 2.67    | 2.53    | 2.80    | 8.00   | 2.3x (3-phase basis) |
| all-deepseek-or | —       | 0.80    | 0.71    | 1.02    | 2.53   | 1.0x (3-phase basis) |
| dkd             | 0.56    | 0.69    | 0.74    | 1.16    | 3.15   | 1.0x (4-phase basis) |

Note that `dcc` and `all-deepseek-or` did not run on Phase 6, so their totals
are over three phases. On the three phases where every profile ran, the spread
is roughly: all-claude $48.0 vs `dkd` $2.6 — about 18x. The actual figures from
the harness are slightly higher than the rough numbers in the bake-off
prompt-tracking notes, primarily because megaplan's
plan/critique/revise/finalize overhead is higher for Claude-as-author than was
estimated up front.

The headline tension: `all-claude` won every phase but cost 12x to 23x more
than the cheapest alternative. The cheap alternatives were not broken — they
shipped working code with full suite passes — but they consistently introduced
a small number of high-stakes correctness bugs (canonical enum violations,
encapsulation breaches, fixture-path errors, identity-bypass patterns,
cross-project leakage). On orchestrator V1 this matters because the kernel
invariants the cheap arms violated (attestor_kind enum, identity match,
per-project isolation) are exactly the ones the project exists to enforce. On a
codebase with weaker invariants the same arms might be production-grade.

The decision is real, not foregone: a project that can absorb a small
post-merge correction loop, where the spec is fully written down and the
critic is competent, can run a `dcc`-style profile and pay 7x less. A project
where one wrong canonical enum value is a silent kernel-invariant break — like
this one — pays the all-Claude premium and treats it as insurance.

## 4. Profile-mix learnings

### 4.1 Plan quality predicts execute quality

Across all four phases the executor mostly tracked its plan literally. When
the plan flagged a real risk in critique/revise, the executor handled it; when
the plan was verbose-but-shallow or contained gibberish artifacts, the
executor's code reflected that. Phase 8 is the cleanest example: the
all-Claude plan explicitly identified the "do not bypass identity" risk and
chose `gate_command` re-entry; three other arms' plans never named this
constraint, and all three executors shipped a parallel-ingestion design that
violated it. Phase 9's `attestor_kind` deviations are similar — `dcc`'s plan
discussed needing a way to mark author-test provenance and proposed a new
enum value; the executor faithfully implemented that planned-but-wrong
solution.

The implication is that the highest-leverage improvement to a cheap profile is
not a better executor model but a better critic/plan author. Spending an extra
couple of cents on critique to flag canonical-enum risks pays for itself in
executor cycles spent chasing post-merge correction.

### 4.2 Claude-as-critic raises non-Claude plans by a measurable amount

The cleanest A/B in the data is `all-deepseek-or` vs `deepseek-claude-critique`
on Phases 7-9. Same lead author (DeepSeek), same executor (DeepSeek via
OpenRouter), only the critic differs (Kimi-via-OpenRouter for `dkd`-style and
nothing additional for `all-deepseek-or`, vs Claude as critic for `dcc`). On
each of the three phases where both ran, `dcc` produced a more spec-faithful
implementation than `all-deepseek-or` despite using the same lead and the
same executor:

- Phase 7: `all-deepseek-or` shipped a global-CAS fallback (per-project
  invariant break); `dcc` did not.
- Phase 8: `all-deepseek-or` bypassed identity entirely; `dcc` imported
  private symbols but at least went through the gate.
- Phase 9: both broke `attestor_kind`, but `dcc` chose a non-canonical value
  (`"system"`) — recoverable by enum-extension — whereas `all-deepseek-or`
  silently flattened to a single value, which is harder to detect.

`dcc` cost roughly 3x `all-deepseek-or` ($8.00 vs $2.53 across three phases).
That is the price of a Claude-quality critic on a DeepSeek pipeline, and on
this evidence it is worth paying for a project with hard kernel invariants.

### 4.3 DeepSeek-as-executor works with a strong plan, with a small correctness tax

DeepSeek (via Fireworks for `dkd`, via OpenRouter for `ckd-or` and
`all-deepseek-or`) reliably produced compiling, test-passing code on every
phase it ran. The failure mode is consistent and small: DeepSeek-as-executor
has a measurable rate of small but production-blocking deviations:

- Importing private symbols when public API would have done (Phase 8 dcc).
- Inventing non-canonical enum values when extension should have been a plan
  decision, not an execute decision (Phase 9 dcc, all-deepseek-or).
- Naming drift — files at the wrong path (Phase 9 dkd, partly all-claude),
  consolidated test files instead of separate spec-named files (Phase 9 dkd).
- Cosmetic-but-shouldn't-be-committed files (Phase 8 ckd-or's
  `_throwaway_repro.py`).

None of these are "the model can't write Python." All of them are "the model
under-weighted a constraint that was either implicit in the spec or required
reading three files to discover." This is the executor-side analogue of the
plan-quality finding: a stronger executor critic (or a stricter linter / a
pre-merge `gh pr` style checklist) would have caught most of them.

## 5. Harness bugs surfaced and fixed

The bake-off was a stress test on the megaplan harness as much as on the
profiles. Three real bugs were surfaced and fixed on the megaplan branch
`megaplan/per-milestone-robustness-20260503`. A fourth issue is known and
open.

### 5.1 `c2bbc729` — Fireworks streaming for large `max_tokens`

The Fireworks API returns 400 when `max_tokens > 4096` unless `stream=true` is
also set. The megaplan worker was issuing non-streamed requests with high
`max_tokens` for plan and execute phases, causing intermittent 400s for `dkd`
and `dcc` arms. Fix: worker now streams and reassembles for these requests.
Surfaced when Phase 7 `dkd` failed mid-execute and was visible from the
worker log; would have been hard to spot without four concurrent arms making
the failure pattern obvious.

### 5.2 `a0ed9f51` — Tool-layer sandbox enforcement

The Phase 6 misdirected-write incident: the idea brief contained an absolute
path line `Project: /Users/.../ArtAgents` that competed with megaplan's
injected `Project directory: <worktree>` line. Both `dkd` and `ckd-or`
followed the brief's path and wrote their changes to the main repo rather
than their respective worktrees. Fix is two-part:

- Strip `Project:` lines from briefs before injection (megaplan side).
- Install a tool-layer sandbox via `install_sandbox(project_dir)` context
  manager that refuses any tool call whose resolved path escapes the project
  directory (e.g. `cd /escape && ...` or absolute writes outside the
  worktree).

This is the most consequential fix of the four — without it, a single
prompt-injection-shaped path in any future idea text could silently write to
main. The defense-in-depth (strip + sandbox) is intentional.

### 5.3 `2a60d147` — Audit drift severity escalates on `files_missing`

The audit phase was previously reporting `severity=low` even when execute
claimed to have written files that did not exist on disk. This made some
bake-off arms look healthier than they were — `all-deepseek-or` Phase 7's
global-CAS fallback was visible only because manual inspection of the diff
caught it. Fix: any non-empty `files_missing` now escalates audit severity to
at least `medium`, which forces the operator to look at it.

### 5.4 Open: light-robustness review tier still skips audit findings

The light-robustness review tier in `_resolve_review_outcome` short-circuits
before consulting audit findings. This is entangled with the
review-outcome-resolution logic and was not fixed during the bake-off run.
Documented as a known issue. Real-world impact today is bounded because the
standard robustness tier is the default, but a future operator who selects
`light` for cheap arms could miss exactly the kind of quiet deviation
described in section 4.3.

## 6. Methodology validations

Two pieces of the bake-off methodology held up well across all four phases.

The blind/structured assessment by sub-agent worked. After each phase, a
sub-agent was given (a) the spec text, (b) the diffs from each profile in
random labeled order, and (c) a structured rubric (correctness, spec
faithfulness, encapsulation, test surface, idiomaticity) — and produced
rankings before profile identities were revealed. The rankings tracked
post-reveal manual review consistently. The plan-quality investigation
sub-agent (used Phases 7-9) gave clean, actionable rankings that would have
been expensive and hard to keep honest if done by the same operator who'd
already glanced at the diffs.

The `bakeoff compare` / `pick` / `merge` workflow worked. `compare` produces
the side-by-side `comparison.md`; `pick` records the choice with a written
rationale; `merge` performs the worktree merge with a pre-merge `git -C
<worktree> diff main --stat` gate. The `--stat` gate is what caught the
Phase 6 misdirected-write incident before any non-winner arm polluted main —
the diff stat against the worktree's own base showed zero changes (because
the writes had gone to the main repo), which was visible and stopped the
merge.

## 7. Open questions and future work

The four-phase result is consistent enough to make a few hypotheses worth
testing on the next phase, but not so consistent that any of them are
settled.

**When is a cheaper profile the right call?** The hypothesis from this run:
when the spec is fully nailed down (every constraint is enumerated, no
implicit invariants) and the executor's job is faithful translation rather
than judgement. None of Phases 6-9 met this bar — each had at least one
implicit invariant that only Claude's executor reliably caught — but the
orchestrator V1 plan deliberately back-loaded the kernel-touching work.
Later phases (test pack expansion, doc deliverables, examples) plausibly
qualify, and the plan should explicitly flag which phases run cheap.

**Is `deepseek-claude-critique` the right routine default?** The 3-phase
sample says `dcc` is meaningfully better than `all-deepseek-or` at ~3x the
cost, and meaningfully cheaper than `all-claude` at ~7x the savings. That is
the right shape for "default for routine work, escalate to all-Claude when
the phase touches kernel invariants." The four-phase sample is too small to
commit to this; running `dcc` alone (no bake-off) on a low-stakes phase
would test whether its small-deviation rate is acceptable without the
tournament structure to catch it.

**The light-robustness review-skip issue.** Open. Should be fixed before
the next bake-off so cheap arms can use the light tier without losing audit
visibility, which would close the gap between `all-deepseek-or` and `dcc`
on cost without losing the correctness signal.

**Bake-offs as a harness stress test.** Three harness bugs in four phases is
a high rate. The next bake-off (whatever it is) should budget time for the
harness fixes that will surface, and the megaplan robustness branch should
remain open.
