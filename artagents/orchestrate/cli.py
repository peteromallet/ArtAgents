"""`artagents author` CLI: compile / check / describe / new (Phase 4)."""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Optional

from artagents.core.task.plan import (
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


_QID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_NEW_TEMPLATE = '''"""Author-scaffolded orchestrator: {qualified_id}.

Edit the steps below to describe your task. Run:
  artagents author check {qualified_id}
  artagents author compile {qualified_id}
  artagents author describe {qualified_id}
"""

from __future__ import annotations

from artagents.orchestrate import (
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
            argv=["python3", "-m", "artagents", "executors", "run", "<pack>.<executor>"],
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
    # `artagents orchestrators run`. We layer a redundant explicit walk so the
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="artagents author", description="Phase 4 author CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for verb in ("compile", "check", "describe", "new"):
        sp = sub.add_parser(verb, help=f"author {verb} <pack>.<name>")
        sp.add_argument("qualified_id", help="qualified id of the form <pack>.<name>")
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
    parser.print_usage(file=sys.stderr)
    return 2
