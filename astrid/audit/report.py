from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .graph import build_graph, load_ledger


def _render_preview(node: dict[str, Any]) -> str:
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
              <div class="preview">{_render_preview(node)}</div>
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
  <title>Astrid Audit - {html.escape(run_path.name)}</title>
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
