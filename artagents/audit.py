"""Run-local provenance ledger and audit report rendering."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|authorization|bearer|credential)", re.I)
SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|hf_[A-Za-z0-9]{12,}|AIza[0-9A-Za-z_-]{12,})"
)
MAX_TEXT_PREVIEW = 500


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "item"


def stable_id(*parts: object) -> str:
    raw = "|".join(json.dumps(part, sort_keys=True, default=str) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    label = _slug(str(parts[0])) if parts else "audit"
    return f"{label}-{digest}"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                redacted[str(key)] = "<redacted>"
            else:
                redacted[str(key)] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if SECRET_VALUE_RE.search(value):
            return SECRET_VALUE_RE.sub("<redacted>", value)
        return value
    return value


def _file_metadata(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    stat = path.stat()
    metadata: dict[str, Any] = {
        "size_bytes": stat.st_size,
        "mtime": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }
    if stat.st_size <= 16 * 1024 * 1024:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        metadata["sha256"] = digest.hexdigest()
    return metadata


def _text_preview(path: Path) -> str | None:
    if not path.is_file() or path.stat().st_size > 256 * 1024:
        return None
    if path.suffix.lower() not in {".txt", ".json", ".jsonl", ".md", ".srt", ".csv", ".log"}:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text[:MAX_TEXT_PREVIEW] if text else None


@dataclass
class AuditContext:
    run_dir: Path
    enabled: bool = True

    def __post_init__(self) -> None:
        self.run_dir = self.run_dir.resolve()
        self.audit_dir = self.run_dir / "audit"
        self.ledger_path = self.audit_dir / "ledger.jsonl"
        if self.enabled:
            self.audit_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_run(cls, run_dir: Path | str, *, enabled: bool = True) -> "AuditContext":
        return cls(Path(run_dir), enabled=enabled)

    @classmethod
    def from_env(cls) -> "AuditContext | None":
        if os.environ.get("ARTAGENTS_AUDIT_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
            return None
        run_dir = os.environ.get("ARTAGENTS_AUDIT_RUN_DIR", "").strip()
        if not run_dir:
            return None
        return cls.for_run(run_dir)

    def _relative(self, path: Path | str | None) -> str | None:
        if path is None:
            return None
        path_obj = Path(path)
        try:
            resolved = path_obj.resolve()
        except OSError:
            resolved = path_obj
        try:
            return str(resolved.relative_to(self.run_dir))
        except ValueError:
            return str(path)

    def append(self, event: dict[str, Any]) -> None:
        if not self.enabled:
            return
        payload = {
            "schema_version": 1,
            "created_at": _utc_now(),
            **redact(event),
        }
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def register_asset(
        self,
        *,
        kind: str,
        path: Path | str | None = None,
        label: str | None = None,
        asset_id: str | None = None,
        parents: Iterable[str] = (),
        stage: str | None = None,
        metadata: dict[str, Any] | None = None,
        preview: dict[str, Any] | None = None,
        registration_source: str = "creation",
    ) -> str:
        rel_path = self._relative(path)
        produced_id = asset_id or stable_id(kind, rel_path, label, sorted(parents), stage)
        path_obj = Path(path) if path is not None else None
        merged_metadata = dict(metadata or {})
        if path_obj is not None:
            merged_metadata.update(_file_metadata(path_obj))
        merged_preview = dict(preview or {})
        if path_obj is not None and "text" not in merged_preview:
            text = _text_preview(path_obj)
            if text:
                merged_preview["text"] = text
        self.append(
            {
                "event": "asset.created",
                "asset_id": produced_id,
                "kind": kind,
                "label": label or rel_path or kind,
                "path": rel_path,
                "parents": list(parents),
                "stage": stage,
                "metadata": merged_metadata,
                "preview": merged_preview,
                "registration_source": registration_source,
            }
        )
        return produced_id

    def register_node(
        self,
        *,
        stage: str,
        kind: str = "step",
        label: str | None = None,
        node_id: str | None = None,
        parents: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
        outputs: Iterable[str] = (),
        registration_source: str = "creation",
    ) -> str:
        produced_id = node_id or stable_id(stage, kind, label, sorted(parents), sorted(outputs))
        self.append(
            {
                "event": "node.created",
                "node_id": produced_id,
                "kind": kind,
                "label": label or stage,
                "stage": stage,
                "parents": list(parents),
                "outputs": list(outputs),
                "metadata": metadata or {},
                "registration_source": registration_source,
            }
        )
        return produced_id

    def register_decision(
        self,
        *,
        stage: str,
        label: str,
        selected: Iterable[str] = (),
        rejected: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> str:
        decision_id = stable_id("decision", stage, label, sorted(selected), sorted(rejected))
        self.append(
            {
                "event": "decision.created",
                "decision_id": decision_id,
                "stage": stage,
                "label": label,
                "selected": list(selected),
                "rejected": list(rejected),
                "metadata": metadata or {},
            }
        )
        return decision_id

    def register_prompt_ref(
        self,
        *,
        prompt: str | None = None,
        path: Path | str | None = None,
        label: str = "Prompt",
        parents: Iterable[str] = (),
        stage: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        preview: dict[str, Any] = {}
        if prompt:
            preview["text"] = prompt[:MAX_TEXT_PREVIEW]
        return self.register_asset(
            kind="prompt",
            path=path,
            label=label,
            parents=parents,
            stage=stage,
            metadata=metadata,
            preview=preview,
        )


def load_ledger(run_dir: Path | str) -> list[dict[str, Any]]:
    ledger_path = Path(run_dir).resolve() / "audit" / "ledger.jsonl"
    if not ledger_path.is_file():
        raise FileNotFoundError(f"audit ledger not found: {ledger_path}")
    events = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def build_graph(events: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    decisions: list[dict[str, Any]] = []
    for event in events:
        event_type = event.get("event")
        if event_type == "asset.created":
            node_id = str(event["asset_id"])
            nodes[node_id] = {**event, "id": node_id, "node_type": "asset"}
            for parent in event.get("parents") or []:
                edges.append({"from": str(parent), "to": node_id})
        elif event_type == "node.created":
            node_id = str(event["node_id"])
            nodes[node_id] = {**event, "id": node_id, "node_type": "node"}
            for parent in event.get("parents") or []:
                edges.append({"from": str(parent), "to": node_id})
            for output in event.get("outputs") or []:
                edges.append({"from": node_id, "to": str(output)})
        elif event_type == "decision.created":
            decisions.append(event)
    return {"nodes": list(nodes.values()), "edges": edges, "decisions": decisions, "events": events}


def _render_preview(node: dict[str, Any], run_dir: Path) -> str:
    path = node.get("path")
    kind = str(node.get("kind", ""))
    if isinstance(path, str) and path:
        suffix = Path(path).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            return f'<img src="../{html.escape(path)}" alt="">'
        if suffix in {".mp4", ".webm", ".mov"}:
            return f'<video src="../{html.escape(path)}" controls muted></video>'
    preview = node.get("preview") if isinstance(node.get("preview"), dict) else {}
    text = preview.get("text")
    if isinstance(text, str) and text:
        return f"<pre>{html.escape(text)}</pre>"
    return f"<span>{html.escape(kind)}</span>"


def render_html(run_dir: Path | str, graph: dict[str, Any]) -> str:
    run_path = Path(run_dir).resolve()
    nodes = graph["nodes"]
    edges = graph["edges"]
    decisions = graph["decisions"]
    cards = []
    for node in nodes:
        label = html.escape(str(node.get("label") or node.get("id")))
        stage = html.escape(str(node.get("stage") or ""))
        kind = html.escape(str(node.get("kind") or node.get("node_type") or ""))
        path = html.escape(str(node.get("path") or ""))
        parents = ", ".join(html.escape(str(parent)) for parent in node.get("parents") or [])
        cards.append(
            f"""
            <article class="card">
              <header><strong>{label}</strong><small>{kind} {stage}</small></header>
              <div class="preview">{_render_preview(node, run_path)}</div>
              <dl>
                <dt>ID</dt><dd>{html.escape(str(node.get("id")))}</dd>
                <dt>Path</dt><dd>{path}</dd>
                <dt>Parents</dt><dd>{parents}</dd>
              </dl>
            </article>
            """
        )
    edge_rows = "\n".join(f"<tr><td>{html.escape(e['from'])}</td><td>{html.escape(e['to'])}</td></tr>" for e in edges)
    decision_rows = "\n".join(
        f"<tr><td>{html.escape(str(d.get('stage')))}</td><td>{html.escape(str(d.get('label')))}</td><td>{html.escape(', '.join(map(str, d.get('selected') or [])))}</td></tr>"
        for d in decisions
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>ArtAgents Audit - {html.escape(run_path.name)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #1d1f23; background: #f7f7f4; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    .summary {{ display: flex; gap: 16px; margin: 18px 0 24px; }}
    .metric {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 12px 14px; min-width: 120px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }}
    .card {{ background: white; border: 1px solid #d9d9d2; border-radius: 8px; padding: 12px; }}
    .card header {{ display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }}
    small {{ color: #63655f; }}
    .preview {{ min-height: 90px; background: #f0f0eb; border-radius: 6px; display: grid; place-items: center; overflow: hidden; }}
    img, video {{ max-width: 100%; max-height: 190px; display: block; }}
    pre {{ white-space: pre-wrap; font-size: 12px; padding: 10px; margin: 0; width: 100%; box-sizing: border-box; }}
    dl {{ font-size: 12px; display: grid; grid-template-columns: 64px 1fr; gap: 4px 8px; overflow-wrap: anywhere; }}
    dt {{ color: #666; }}
    table {{ width: 100%; border-collapse: collapse; background: white; margin: 16px 0 28px; }}
    th, td {{ text-align: left; border-bottom: 1px solid #e3e3dc; padding: 8px; font-size: 13px; overflow-wrap: anywhere; }}
  </style>
</head>
<body>
<main>
  <h1>{html.escape(run_path.name)} Audit</h1>
  <p>Generated from <code>audit/ledger.jsonl</code>. Lineage comes from registered ids and parent ids.</p>
  <section class="summary">
    <div class="metric"><strong>{len(nodes)}</strong><br>Nodes</div>
    <div class="metric"><strong>{len(edges)}</strong><br>Edges</div>
    <div class="metric"><strong>{len(decisions)}</strong><br>Decisions</div>
  </section>
  <h2>Asset Journey</h2>
  <div class="grid">{''.join(cards)}</div>
  <h2>Edges</h2>
  <table><thead><tr><th>From</th><th>To</th></tr></thead><tbody>{edge_rows}</tbody></table>
  <h2>Decisions</h2>
  <table><thead><tr><th>Stage</th><th>Decision</th><th>Selected</th></tr></thead><tbody>{decision_rows}</tbody></table>
</main>
</body>
</html>
"""


def write_report(run_dir: Path | str, out: Path | None = None) -> Path:
    run_path = Path(run_dir).resolve()
    graph = build_graph(load_ledger(run_path))
    output = out or run_path / "audit" / "report.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(run_path, graph), encoding="utf-8")
    return output


def register_output(
    *,
    kind: str,
    path: Path | str,
    label: str | None = None,
    stage: str | None = None,
    parents: Iterable[str] = (),
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Register one output with the ambient run audit context, if enabled."""
    context = AuditContext.from_env()
    if context is None:
        return None
    return context.register_asset(
        kind=kind,
        path=path,
        label=label,
        stage=stage,
        parents=parents,
        metadata=metadata,
    )


def register_outputs(
    *,
    stage: str,
    outputs: Iterable[tuple[str, Path | str, str]],
    parents: Iterable[str] = (),
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Register several newly-created outputs and a producing node."""
    context = AuditContext.from_env()
    if context is None:
        return []
    parent_ids = list(parents)
    output_ids = [
        context.register_asset(kind=kind, path=path, label=label, parents=parent_ids, stage=stage, metadata=metadata)
        for kind, path, label in outputs
        if Path(path).exists()
    ]
    context.register_node(stage=stage, label=stage, parents=parent_ids, outputs=output_ids, metadata=metadata or {})
    return output_ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render an ArtAgents run audit report.")
    parser.add_argument("--run", type=Path, required=True, help="Run directory containing audit/ledger.jsonl.")
    parser.add_argument("--out", type=Path, help="HTML output path. Defaults to <run>/audit/report.html.")
    parser.add_argument("--json", action="store_true", help="Print graph summary JSON instead of writing HTML.")
    args = parser.parse_args(argv)
    try:
        graph = build_graph(load_ledger(args.run))
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
    if args.json:
        print(json.dumps(graph, indent=2))
        return 0
    output = write_report(args.run, args.out)
    print(f"Wrote {output}")
    return 0


__all__ = [
    "AuditContext",
    "build_graph",
    "load_ledger",
    "redact",
    "register_output",
    "register_outputs",
    "stable_id",
    "write_report",
]
