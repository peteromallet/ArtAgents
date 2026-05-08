"""`astrid author` CLI: compile / check / describe / new (Phase 4) +
test / explain (Phase 5/9).

Phase 9 ``author test`` actually replays a fixture through the gate via
``orchestrate.test_runner.run_fixture`` inside a scratch projects root, then
diffs the resulting events.jsonl against ``<pack>/golden/<fixture>.events.jsonl``
after stripping volatile fields. ``--regenerate`` writes the current events
back as the new golden.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from astrid.core.task.events import read_events
from astrid.core.task.normalize import dump_events_jsonl, normalize_events
from astrid.core.task.plan import (
    AttestedStep,
    CodeStep,
    NestedStep,
    RepeatForEach,
    RepeatUntil,
    TaskPlan,
    TaskPlanError,
    iter_steps_with_path,
    load_plan,
    parse_from_ref,
)

from .compile import (
    DEFAULT_PACKS_ROOT,
    _qualified_split,
    _resolver_for,
    compile_to_path,
    resolve_orchestrator,
)
from .dsl import (
    OrchestrateDefinitionError,
    _PlanBuilder,
    _StepHandle,
)
from .test_runner import run_fixture


_QID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_NEW_TEMPLATE = '''"""Author-scaffolded orchestrator: {qualified_id}.

Edit the steps below to describe your task. Run:
  astrid author check {qualified_id}
  astrid author compile {qualified_id}
  astrid author describe {qualified_id}
"""

from __future__ import annotations

from astrid.orchestrate import (
    code,
    file_nonempty,
    orchestrator,
)


@orchestrator("{qualified_id}")
def {fn_name}():
    return [
        # TODO: replace with the real executor argv and produces.
        code(
            "step_one",
            argv=["python3", "-m", "astrid", "executors", "run", "<pack>.<executor>"],
            produces={{"out": file_nonempty()}},
        ),
    ]
'''


def _packs_root_arg(packs_root: Optional[Path]) -> Path:
    return Path(packs_root) if packs_root is not None else DEFAULT_PACKS_ROOT


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _resolved_plan(qid: str, packs_root: Optional[Path]) -> TaskPlan:
    builder = resolve_orchestrator(qid, packs_root=packs_root)
    payload = builder.to_dict(_resolver=_resolver_for(packs_root))
    # to_dict already round-trips through load_plan; re-parse to get the typed
    # TaskPlan instance for traversal.
    import json
    import os
    import tempfile

    fp = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    try:
        json.dump(payload, fp)
        fp.flush()
        path = fp.name
    finally:
        fp.close()
    try:
        return load_plan(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _cmd_compile(qid: str, packs_root: Optional[Path]) -> int:
    try:
        out_path = compile_to_path(qid, packs_root=packs_root)
    except (OrchestrateDefinitionError, TaskPlanError) as exc:
        _print_err(f"author compile {qid}: {exc}")
        return 1
    print(f"wrote {out_path}")
    return 0


def _cmd_check(qid: str, packs_root: Optional[Path]) -> int:
    started = time.perf_counter()
    try:
        plan = _resolved_plan(qid, packs_root)
    except (OrchestrateDefinitionError, TaskPlanError) as exc:
        _print_err(f"author check {qid}: {exc}")
        return 1
    # The DSL/load_plan validators already enforce: schema, repeat.for_each.from
    # resolves to a prior-sibling produces, attested produces are non-sentinel,
    # nested plans validate, and `code` argv may not target
    # `astrid orchestrators run`. We layer a redundant explicit walk so the
    # author sees a clear pass message and the SLA is exercised.
    for path, step in iter_steps_with_path(plan):
        if isinstance(step, AttestedStep):
            for entry in step.produces:
                if entry.check.sentinel:
                    _print_err(
                        f"author check {qid}: attested step {'/'.join(path)!r} "
                        f"produces[{entry.name!r}] uses sentinel-only check"
                    )
                    return 1
        if isinstance(step, (CodeStep, AttestedStep)) and step.repeat is not None:
            if isinstance(step.repeat, RepeatForEach) and step.repeat.from_ref:
                # load_plan already validated this; emit nothing extra.
                _ = parse_from_ref(step.repeat.from_ref)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    print(f"ok {qid} ({elapsed_ms:.1f} ms)")
    return 0


def _format_repeat(repeat) -> list[str]:
    lines: list[str] = []
    if isinstance(repeat, RepeatUntil):
        lines.append(f"repeat.until={repeat.condition}")
        lines.append(f"max_iterations={repeat.max_iterations}")
        lines.append(f"on_exhaust={repeat.on_exhaust}")
        if repeat.quorum_n is not None:
            lines.append(f"quorum_n={repeat.quorum_n}")
    elif isinstance(repeat, RepeatForEach):
        if repeat.items_source == "static":
            lines.append(f"for_each items={list(repeat.items)}")
        else:
            lines.append(f"requires: {repeat.from_ref}")
    return lines


def _describe_plan(plan: TaskPlan, builder_costs: dict[str, float]) -> tuple[list[str], float]:
    out: list[str] = []
    total_cost = 0.0
    for path, step in iter_steps_with_path(plan):
        depth = len(path) - 1
        indent = "  " * depth
        out.append(f"{indent}{step.id} [{step.kind}]")
        # produces (sorted by name for determinism)
        for entry in sorted(step.produces, key=lambda e: e.name):
            out.append(
                f"{indent}  produces: {entry.name} -> {entry.path} ({entry.check.check_id})"
            )
        # repeat
        for line in _format_repeat(step.repeat):
            out.append(f"{indent}  {line}")
        # cost hint (looked up by step id; collisions across nested trees are
        # rare and the lookup is best-effort for the footer summary)
        cost = builder_costs.get(step.id)
        if cost is not None:
            total_cost += float(cost)
    return out, total_cost


def _collect_costs(builder: _PlanBuilder, packs_root: Optional[Path]) -> dict[str, float]:
    costs: dict[str, float] = {}
    visiting: set = set()

    def _walk(b: _PlanBuilder) -> None:
        if b.plan_id in visiting:
            return
        visiting.add(b.plan_id)
        for step in b.steps:
            if step.cost_hint_usd is not None:
                costs[step.id] = float(step.cost_hint_usd)
            child = step.plan
            if isinstance(child, _PlanBuilder):
                _walk(child)
            elif isinstance(child, str):
                try:
                    sub = resolve_orchestrator(child, packs_root=packs_root)
                except OrchestrateDefinitionError:
                    return
                _walk(sub)

    _walk(builder)
    return costs


def _cmd_describe(qid: str, packs_root: Optional[Path]) -> int:
    try:
        builder = resolve_orchestrator(qid, packs_root=packs_root)
        plan = _resolved_plan(qid, packs_root)
    except (OrchestrateDefinitionError, TaskPlanError) as exc:
        _print_err(f"author describe {qid}: {exc}")
        return 1
    costs = _collect_costs(builder, packs_root)
    lines, total = _describe_plan(plan, costs)
    print(f"plan {plan.plan_id} (version {plan.version})")
    for line in lines:
        print(line)
    if costs:
        print(f"estimated cost ceiling: ${total:.2f}")
    return 0


def _cmd_new(qid: str, packs_root: Optional[Path]) -> int:
    if not _QID_RE.fullmatch(qid):
        _print_err(
            f"author new: qualified id {qid!r} must be '<pack>.<name>' "
            "with letters/digits/underscore"
        )
        return 1
    pack, name = _qualified_split(qid)
    root = _packs_root_arg(packs_root)
    pack_root = root / pack
    if not pack_root.is_dir():
        _print_err(
            f"author new: pack directory not found at {pack_root}; "
            "create the pack before scaffolding an orchestrator"
        )
        return 1
    module_path = pack_root / f"{name}.py"
    folder_collision = pack_root / name
    if module_path.exists():
        _print_err(f"author new: refuse to overwrite existing {module_path}")
        return 1
    if folder_collision.exists() and folder_collision.is_dir():
        # FLAG-003: a same-stem folder shadows the .py module on import.
        _print_err(
            f"author new: cannot scaffold {module_path} because folder "
            f"{folder_collision} exists; rename the folder-orchestrator first"
        )
        return 1

    fixtures_dir = pack_root / "fixtures" / name
    golden_dir = pack_root / "golden"
    fixtures_keep = fixtures_dir / ".keep"
    golden_events = golden_dir / f"{name}.events.jsonl"

    fixtures_dir.mkdir(parents=True, exist_ok=True)
    golden_dir.mkdir(parents=True, exist_ok=True)

    module_text = _NEW_TEMPLATE.format(qualified_id=qid, fn_name=name)
    module_path.write_text(module_text, encoding="utf-8")
    fixtures_keep.write_text("", encoding="utf-8")
    golden_events.write_text("", encoding="utf-8")

    for created in (module_path, fixtures_keep, golden_events):
        try:
            rel = created.relative_to(root.parent)
        except ValueError:
            rel = created
        print(f"created {rel}")
    return 0


def _fixture_dir_for_run(pack_root: Path, fixture_name: str) -> Optional[Path]:
    """Return the fixture seed directory if it exists and has any payload.

    A bare ``.keep`` placeholder (only ``.keep`` inside the directory, no real
    inputs) is treated as no fixture — ``run_fixture`` is given ``None`` so it
    skips the copytree and runs against an empty scratch project.
    """
    fixture_dir = pack_root / "fixtures" / fixture_name
    if not fixture_dir.is_dir():
        return None
    payload = [p for p in fixture_dir.iterdir() if p.name != ".keep"]
    if not payload:
        return None
    return fixture_dir


def _cmd_test(
    qid: str,
    fixture_name: str,
    packs_root: Optional[Path],
    *,
    regenerate: bool = False,
) -> int:
    """Phase 9 author-test: replay the orchestrator's compiled plan against the
    fixture inside a scratch projects root with auto-approval ON, then diff or
    regenerate the canonical golden events.jsonl.
    """
    try:
        pack, name = _qualified_split(qid)
    except OrchestrateDefinitionError as exc:
        _print_err(f"author test {qid}: {exc}")
        return 1

    root = _packs_root_arg(packs_root)
    pack_root = root / pack
    build_path = pack_root / "build" / f"{name}.json"
    if not build_path.is_file():
        try:
            compile_to_path(qid, packs_root=root)
        except (OrchestrateDefinitionError, TaskPlanError) as exc:
            _print_err(f"author test {qid}: compile failed: {exc}")
            return 1

    golden_path = pack_root / "golden" / f"{fixture_name}.events.jsonl"
    fixture_dir = _fixture_dir_for_run(pack_root, fixture_name)

    with tempfile.TemporaryDirectory() as scratch:
        projects_root = Path(scratch)
        try:
            events_path = run_fixture(
                qualified_id=qid,
                fixture_dir=fixture_dir,
                packs_root=root,
                projects_root=projects_root,
            )
        except RuntimeError as exc:
            _print_err(f"author test {qid} --fixture {fixture_name}: {exc}")
            return 1
        run_dir = events_path.parent
        events = read_events(events_path)
        normalized = normalize_events(events, run_dir=run_dir)

        if regenerate:
            dump_events_jsonl(normalized, golden_path)
            print(f"wrote {golden_path} — commit if intentional")
            return 0

        if not golden_path.is_file() or golden_path.stat().st_size == 0:
            _print_err(
                f"author test {qid} --fixture {fixture_name}: no committed "
                f"golden at {golden_path}; rerun with --regenerate to create one"
            )
            return 1

        actual_path = run_dir / "normalized.events.jsonl"
        dump_events_jsonl(normalized, actual_path)
        actual_lines = actual_path.read_text(encoding="utf-8").splitlines()
        golden_lines = golden_path.read_text(encoding="utf-8").splitlines()

        if actual_lines == golden_lines:
            print(f"ok {qid} --fixture {fixture_name} ({len(actual_lines)} events)")
            return 0

        diff = difflib.unified_diff(
            golden_lines,
            actual_lines,
            fromfile=f"golden/{fixture_name}.events.jsonl",
            tofile="actual",
            lineterm="",
        )
        for line in diff:
            print(line)
        return 1


def _format_step_explain(
    step,
    indent: str,
    *,
    parent_repeat_chain: tuple[str, ...] = (),
) -> list[str]:
    lines: list[str] = []
    kind = step.kind
    if isinstance(step, CodeStep):
        lines.append(
            f"{indent}Step `{step.id}` ({kind}) runs `{step.command}`."
        )
    elif isinstance(step, AttestedStep):
        ack = step.ack.kind
        lines.append(
            f"{indent}Step `{step.id}` ({kind}) waits for {ack} attestation; "
            f"the runner prints: {step.instructions!r}"
        )
    elif isinstance(step, NestedStep):
        lines.append(
            f"{indent}Step `{step.id}` ({kind}) delegates to sub-orchestrator "
            f"`{step.plan.plan_id}`. Children:"
        )
    if step.produces:
        names = sorted(p.name for p in step.produces)
        lines.append(
            f"{indent}  Produces: {', '.join(names)}. If any inline check "
            f"fails, the gate rewinds to `{step.id}` so it redispatches."
        )
    repeat = getattr(step, "repeat", None)
    if isinstance(repeat, RepeatUntil):
        lines.append(
            f"{indent}  Iterates with repeat.until.condition="
            f"{repeat.condition!r}, max_iterations={repeat.max_iterations}, "
            f"on_exhaust={repeat.on_exhaust!r}. Each failed iteration writes "
            "iteration_failed and the next `next` enters iteration N+1."
        )
    elif isinstance(repeat, RepeatForEach):
        if repeat.items_source == "static":
            lines.append(
                f"{indent}  Fans out across static items {list(repeat.items)} "
                "via repeat.for_each; each item runs the body independently."
            )
        else:
            lines.append(
                f"{indent}  Fans out across items resolved from "
                f"`{repeat.from_ref}` via repeat.for_each."
            )
    if isinstance(step, NestedStep):
        for child in step.plan.steps:
            lines.extend(
                _format_step_explain(
                    child, indent + "  ",
                    parent_repeat_chain=parent_repeat_chain + (step.id,),
                )
            )
    return lines


def _cmd_explain(qid: str, packs_root: Optional[Path]) -> int:
    """Emit a natural-language description of the plan DAG.

    Mentions step ids, kinds, repeat semantics in plain English, and the
    rewind-on-failure behavior so an LLM can verify its compiled plan
    matches a request without parsing the JSON manifest.
    """
    try:
        plan = _resolved_plan(qid, packs_root)
    except (OrchestrateDefinitionError, TaskPlanError) as exc:
        _print_err(f"author explain {qid}: {exc}")
        return 1
    print(f"plan {plan.plan_id} (version {plan.version})")
    print("Steps execute top-to-bottom. Each step waits for the previous one "
          "to complete before the gate advances the cursor.")
    for step in plan.steps:
        print()
        for line in _format_step_explain(step, ""):
            print(line)
    print()
    print(
        "Failure semantics: when a step's inline produces check fails, the "
        "gate appends produces_check_failed and rewinds the cursor to that "
        "step so it redispatches. Inside a repeat.until the iteration count "
        "advances; outside, the same step retries."
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="astrid author", description="Phase 4-5 author CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for verb in ("compile", "check", "describe", "new", "explain"):
        sp = sub.add_parser(verb, help=f"author {verb} <pack>.<name>")
        sp.add_argument("qualified_id", help="qualified id of the form <pack>.<name>")
    test_p = sub.add_parser("test", help="author test <pack>.<name> --fixture <name>")
    test_p.add_argument("qualified_id", help="qualified id of the form <pack>.<name>")
    test_p.add_argument("--fixture", required=True, help="fixture name (under <pack>/fixtures/)")
    test_p.add_argument(
        "--regenerate",
        action="store_true",
        help="write the current normalized events.jsonl as the new golden",
    )
    return parser


def main(argv: Optional[list] = None, *, packs_root: Optional[Path] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)
    qid = args.qualified_id
    if args.cmd == "compile":
        return _cmd_compile(qid, packs_root)
    if args.cmd == "check":
        return _cmd_check(qid, packs_root)
    if args.cmd == "describe":
        return _cmd_describe(qid, packs_root)
    if args.cmd == "new":
        return _cmd_new(qid, packs_root)
    if args.cmd == "test":
        return _cmd_test(
            qid,
            args.fixture,
            packs_root,
            regenerate=args.regenerate,
        )
    if args.cmd == "explain":
        return _cmd_explain(qid, packs_root)
    parser.print_usage(file=sys.stderr)
    return 2
