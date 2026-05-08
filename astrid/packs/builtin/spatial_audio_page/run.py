#!/usr/bin/env python3
"""Build a self-contained HTML page that plays a video with spatial Foley audio."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{video_name} — spatial Foley</title>
  <style>
    html, body {{ margin: 0; padding: 0; background: #050507; color: #ddd;
                  font: 13px/1.4 system-ui, sans-serif; height: 100%; overflow: hidden; }}
    #stage {{ position: fixed; inset: 0; overflow: hidden; cursor: grab; }}
    #stage.dragging {{ cursor: grabbing; }}
    #scene {{ position: absolute; transform-origin: 0 0; will-change: transform; }}
    #scene video {{ display: block; width: 100%; height: auto; background: #000; }}
    #hud {{ position: fixed; left: 12px; bottom: 12px; background: rgba(0,0,0,0.55);
            padding: 8px 10px; border-radius: 6px; pointer-events: none;
            font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 11px;
            color: #aaa; }}
    #hud b {{ color: #fff; font-weight: 600; }}
    #start {{ position: fixed; inset: 0; display: flex; align-items: center; justify-content: center;
              background: rgba(0,0,0,0.85); z-index: 10; cursor: pointer; }}
    #start div {{ background: #16161b; padding: 22px 28px; border-radius: 10px;
                  border: 1px solid #2a2a32; max-width: 380px; }}
    #start h1 {{ margin: 0 0 8px; font-size: 16px; }}
    #start p {{ margin: 0; color: #aaa; font-size: 12px; }}
  </style>
</head>
<body>
  <div id="stage">
    <div id="scene">
      <video id="video" src="{video_src}" playsinline preload="auto" loop></video>
    </div>
  </div>
  <div id="hud">
    <div>zoom <b id="z">1.00</b> · cursor <b id="cx">0</b>,<b id="cy">0</b></div>
    <div>top track <b id="top">—</b></div>
  </div>
  <div id="start"><div>
    <h1>Tap to start</h1>
    <p>Drag to pan, scroll/pinch to zoom. {tile_count} Foley tracks are anchored to regions of the frame; the closer your view's center is to a region, the louder it plays. Original audio is layered on top.</p>
  </div></div>

  <script id="manifest" type="application/json">{manifest_json}</script>
  <script>
    const M = JSON.parse(document.getElementById('manifest').textContent);
    const stage = document.getElementById('stage');
    const scene = document.getElementById('scene');
    const video = document.getElementById('video');
    const hudZ = document.getElementById('z');
    const hudCx = document.getElementById('cx');
    const hudCy = document.getElementById('cy');
    const hudTop = document.getElementById('top');

    const VIDEO_W = M.video_size[0];
    const VIDEO_H = M.video_size[1];

    // Fit video into viewport at startup.
    let view = {{ x: 0, y: 0, scale: 1 }};
    function fitInitial() {{
      const sx = window.innerWidth / VIDEO_W;
      const sy = window.innerHeight / VIDEO_H;
      view.scale = Math.min(sx, sy);
      view.x = (window.innerWidth - VIDEO_W * view.scale) / 2;
      view.y = (window.innerHeight - VIDEO_H * view.scale) / 2;
      apply();
    }}
    function apply() {{
      scene.style.width = VIDEO_W + 'px';
      scene.style.height = VIDEO_H + 'px';
      scene.style.transform = `translate(${{view.x}}px, ${{view.y}}px) scale(${{view.scale}})`;
      hudZ.textContent = view.scale.toFixed(2);
    }}
    window.addEventListener('resize', fitInitial);
    fitInitial();

    // Pan/zoom interactions
    let dragging = false, lastX = 0, lastY = 0;
    stage.addEventListener('mousedown', (e) => {{ dragging = true; lastX = e.clientX; lastY = e.clientY; stage.classList.add('dragging'); }});
    window.addEventListener('mouseup',   () => {{ dragging = false; stage.classList.remove('dragging'); }});
    window.addEventListener('mousemove', (e) => {{
      if (!dragging) return;
      view.x += e.clientX - lastX;
      view.y += e.clientY - lastY;
      lastX = e.clientX; lastY = e.clientY;
      apply();
    }});
    stage.addEventListener('wheel', (e) => {{
      e.preventDefault();
      const factor = Math.exp(-e.deltaY * 0.0015);
      const cx = e.clientX, cy = e.clientY;
      const wx = (cx - view.x) / view.scale;
      const wy = (cy - view.y) / view.scale;
      view.scale = Math.min(8, Math.max(0.05, view.scale * factor));
      view.x = cx - wx * view.scale;
      view.y = cy - wy * view.scale;
      apply();
    }}, {{ passive: false }});

    // Audio graph
    let audioCtx = null;
    const tracks = []; // {{ tile, audio, source, gain, cx_norm, cy_norm }}

    function buildGraph() {{
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      // Original audio kept on at fixed gain (track the <video>'s own audio).
      const vidSrc = audioCtx.createMediaElementSource(video);
      const vidGain = audioCtx.createGain();
      vidGain.gain.value = 1.0;
      vidSrc.connect(vidGain).connect(audioCtx.destination);

      for (const t of M.tiles) {{
        const a = new Audio(t.foley_audio);
        a.loop = true;
        a.crossOrigin = 'anonymous';
        a.preload = 'auto';
        const src = audioCtx.createMediaElementSource(a);
        const g = audioCtx.createGain();
        g.gain.value = 0;
        src.connect(g).connect(audioCtx.destination);
        const [rx, ry, rw, rh] = t.rect_norm;
        tracks.push({{
          tile: t,
          audio: a,
          gain: g,
          cx_norm: rx + rw / 2,
          cy_norm: ry + rh / 2,
        }});
      }}
    }}

    function updateGains() {{
      // Cursor in video-space (where is the center of the viewport pointing on the original frame?)
      const vcx_screen = window.innerWidth / 2;
      const vcy_screen = window.innerHeight / 2;
      const vx = (vcx_screen - view.x) / view.scale;
      const vy = (vcy_screen - view.y) / view.scale;
      const vx_norm = Math.max(0, Math.min(1, vx / VIDEO_W));
      const vy_norm = Math.max(0, Math.min(1, vy / VIDEO_H));
      hudCx.textContent = vx_norm.toFixed(2);
      hudCy.textContent = vy_norm.toFixed(2);

      // Gaussian falloff in normalized coords. Sigma scales with zoom — the more
      // zoomed-in, the tighter the spatial focus.
      const sigma = Math.max(0.08, 0.35 / Math.max(1, view.scale));
      const two_s2 = 2 * sigma * sigma;

      let topId = '—', topGain = 0;
      for (const tr of tracks) {{
        const dx = tr.cx_norm - vx_norm;
        const dy = tr.cy_norm - vy_norm;
        const g = Math.exp(-(dx*dx + dy*dy) / two_s2);
        tr.gain.gain.value = g;
        if (g > topGain) {{ topGain = g; topId = tr.tile.id; }}
      }}
      hudTop.textContent = topId + ' (' + topGain.toFixed(2) + ')';
      requestAnimationFrame(updateGains);
    }}

    document.getElementById('start').addEventListener('click', async () => {{
      document.getElementById('start').remove();
      buildGraph();
      await audioCtx.resume();
      // Sync: start everything at t=0 together. Browsers do best-effort.
      video.currentTime = 0;
      for (const tr of tracks) tr.audio.currentTime = 0;
      await video.play();
      for (const tr of tracks) await tr.audio.play().catch(() => {{}});
      updateGains();
    }}, {{ once: true }});
  </script>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build a static spatial-Foley page.")
    p.add_argument("--manifest", type=Path, required=True, help="tiles.json with foley_audio paths.")
    p.add_argument("--out", type=Path, required=True, help="Output directory.")
    p.add_argument("--no-copy-assets", action="store_true",
                   help="Reference video/audio in place instead of copying into the output dir (page won't be portable).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_path = args.manifest.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out_dir = args.out.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    video_src = Path(manifest["video"])
    if args.no_copy_assets:
        video_rel = str(video_src)
    else:
        target = out_dir / "video" / video_src.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(video_src, target)
        video_rel = f"video/{video_src.name}"

    manifest_dir = manifest_path.parent
    page_tiles: list[dict[str, Any]] = []
    for tile in manifest.get("tiles", []):
        audio_rel = tile.get("foley_audio")
        if not audio_rel:
            continue
        audio_src = (manifest_dir / audio_rel).resolve()
        if args.no_copy_assets:
            audio_out_rel = str(audio_src)
        else:
            audio_target = out_dir / "audio" / f"{tile['id']}{audio_src.suffix}"
            audio_target.parent.mkdir(parents=True, exist_ok=True)
            if not audio_target.exists():
                shutil.copy2(audio_src, audio_target)
            audio_out_rel = f"audio/{audio_target.name}"
        page_tiles.append({
            "id": tile["id"],
            "rect_norm": tile["rect_norm"],
            "foley_audio": audio_out_rel,
        })

    page_manifest = {
        "video_size": manifest["video_size"],
        "duration": manifest.get("trimmed_duration") or manifest.get("duration"),
        "tiles": page_tiles,
    }
    page = PAGE_TEMPLATE.format(
        video_name=video_src.name,
        video_src=video_rel,
        tile_count=len(page_tiles),
        manifest_json=json.dumps(page_manifest),
    )
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    print(f"wrote_page={out_dir / 'index.html'}")
    print(f"tiles={len(page_tiles)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
