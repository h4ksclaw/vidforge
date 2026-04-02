"""Build the GitHub Pages site from pipeline output."""

import json
import sys
from pathlib import Path


def build_site(output_dir: Path, site_dir: Path, recipe_name: str = "VidForge"):
    """Generate the interactive DAG viewer HTML page."""
    site_dir.mkdir(parents=True, exist_ok=True)

    # Copy output files
    for f in output_dir.iterdir():
        if f.is_file():
            import shutil
            shutil.copy2(f, site_dir / f.name)

    # Read recipe name
    recipe_file = output_dir / "recipe.txt"
    if recipe_file.exists():
        recipe_name = recipe_file.read_text().strip().split("/")[-1].replace(".yaml", "")

    # Read DAG SVG if present
    dag_svg = ""
    dag_file = output_dir / "dag.svg"
    if dag_file.exists():
        dag_svg = json.dumps(dag_file.read_text())

    has_video = (site_dir / "scroll.mp4").exists()
    has_strip = (site_dir / "strip.png").exists()
    has_dag = bool(dag_svg)

    # Pipeline function metadata
    fn_meta = {
        "skip_bg_removal": {"line": None, "type": "config", "desc": "Skip background removal flag"},
        "load_recipe": {"line": 20, "type": "source", "desc": "Load recipe YAML configuration"},
        "load_characters": {"line": 28, "type": "source", "desc": "Load character list from recipe"},
        "build_items": {"line": 42, "type": "transform", "desc": "Convert raw character dicts to Item models"},
        "build_target": {"line": 51, "type": "transform", "desc": "Build Target from recipe (youtube/tiktok/reels)"},
        "fetch_images": {"line": 64, "type": "fetch", "desc": "Find best images via Fandom API"},
        "process_images": {"line": 87, "type": "process", "desc": "Download images, remove backgrounds, apply quality filters"},
        "sorted_items": {"line": 102, "type": "transform", "desc": "Sort items by value (height) ascending"},
        "render_strip": {"line": 110, "type": "render", "desc": "Build the wide character strip image"},
        "render_video": {"line": 294, "type": "render", "desc": "Render scrolling video from strip using ffmpeg"},
        "run_pipeline": {"line": 353, "type": "orchestrator", "desc": "Run the Hamilton DAG pipeline"},
    }
    fn_meta_json = json.dumps(fn_meta)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VidForge — {recipe_name} Pipeline</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #0d1117; color: #c9d1d9; min-height: 100vh;
  display: flex; flex-direction: column;
}}
header {{
  background: linear-gradient(135deg, #161b22, #1a1e2e);
  padding: 1rem 1.5rem; border-bottom: 1px solid #30363d;
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 0.5rem; position: sticky; top: 0; z-index: 100;
}}
.header-left {{ display: flex; align-items: center; gap: 1rem; }}
header h1 {{ font-size: 1.3rem; color: #f0f6fc; }}
header h1 a {{ color: inherit; text-decoration: none; }}
header h1 a:hover {{ color: #58a6ff; }}
.badge {{
  background: #1f6feb22; border: 1px solid #1f6feb44;
  color: #58a6ff; padding: 0.2rem 0.6rem; border-radius: 12px; font-size: 0.75rem;
}}
.header-right {{ display: flex; align-items: center; gap: 0.5rem; }}
.btn {{
  background: #21262d; border: 1px solid #30363d; color: #c9d1d9;
  padding: 0.4rem 0.8rem; border-radius: 6px; cursor: pointer; font-size: 0.85rem;
}}
.btn:hover {{ background: #30363d; color: #f0f6fc; }}
#dag-container {{
  flex: 1; overflow: hidden; cursor: grab; position: relative;
}}
#dag-container:active {{ cursor: grabbing; }}
#dag-container svg {{ position: absolute; top: 0; left: 0; }}
#dag-container .node-group {{ cursor: pointer; transition: filter 0.15s; }}
#dag-container .node-group:hover {{
  filter: brightness(1.3) drop-shadow(0 0 8px rgba(31, 111, 235, 0.5));
}}
#dag-container .node-group:hover path,
#dag-container .node-group:hover polygon {{ stroke: #58a6ff; stroke-width: 2; }}
#dag-container .edge-group {{ transition: opacity 0.15s; }}
#dag-container .node-group.dimmed,
#dag-container .edge-group.dimmed {{ opacity: 0.15; }}
#dag-container .node-group.highlighted path,
#dag-container .node-group.highlighted polygon {{ stroke: #58a6ff; stroke-width: 2.5; }}
#dag-container .edge-group.highlighted path {{ stroke: #58a6ff; stroke-width: 2; }}
#dag-tooltip {{
  display: none; position: fixed; background: #1c2128;
  border: 1px solid #30363d; border-radius: 8px;
  padding: 0.6rem 0.9rem; font-size: 0.85rem; color: #f0f6fc;
  pointer-events: none; z-index: 200; box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  max-width: 300px;
}}
#dag-tooltip .fn-name {{ font-weight: 600; color: #58a6ff; margin-bottom: 0.3rem; }}
#dag-tooltip .fn-type {{ font-size: 0.75rem; color: #8b949e; margin-bottom: 0.3rem; }}
#dag-tooltip .fn-link {{ font-size: 0.8rem; color: #58a6ff; text-decoration: none; }}
#zoom-controls {{
  position: absolute; bottom: 1.5rem; right: 1.5rem;
  display: flex; flex-direction: column; gap: 0.4rem; z-index: 50;
}}
#zoom-controls button {{
  width: 36px; height: 36px; background: #21262d; border: 1px solid #30363d;
  color: #c9d1d9; border-radius: 8px; cursor: pointer; font-size: 1.1rem;
  display: flex; align-items: center; justify-content: center;
}}
#zoom-controls button:hover {{ background: #30363d; }}
</style>
</head>
<body>
<header>
  <div class="header-left">
    <h1>\U0001f3ac <a href="https://github.com/h4ksclaw/vidforge">VidForge</a> — {recipe_name}</h1>
    <span class="badge" id="node-count"></span>
  </div>
  <div class="header-right">
    <button class="btn" id="btn-fit">\u229e Fit</button>
    <button class="btn" id="btn-reset">\u21ba Reset</button>
  </div>
</header>
<div id="dag-container"></div>
<div id="dag-tooltip"></div>
<div id="zoom-controls">
  <button id="zoom-in">+</button>
  <button id="zoom-out">\u2212</button>
  <button id="zoom-fit">\u2297</button>
</div>
<script>
const DAG_SVG = {dag_svg if dag_svg else 'null'};
const FN_META = {fn_meta_json};
const GITHUB_BASE = "https://github.com/h4ksclaw/vidforge/blob/main/src/vidforge/pipeline.py";
(function() {{
  const container = document.getElementById('dag-container');
  const tooltip = document.getElementById('dag-tooltip');
  if (!DAG_SVG) {{
    container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#484f58;font-size:1.2rem">No DAG available</div>';
    return;
  }}
  const svgEl = new DOMParser().parseFromString(DAG_SVG, 'image/svg+xml').documentElement;
  svgEl.style.background = 'transparent';
  svgEl.querySelectorAll('polygon[fill="white"]').forEach(p => p.setAttribute('fill', 'transparent'));
  svgEl.querySelectorAll('polygon[fill="black"]').forEach(p => p.setAttribute('fill', '#8b949e'));
  svgEl.querySelectorAll('path[stroke="black"]').forEach(p => p.setAttribute('stroke', '#8b949e'));
  svgEl.querySelectorAll('g.node path[stroke="black"], g.node polygon[stroke="black"]').forEach(p => p.setAttribute('stroke', '#484f58'));
  svgEl.querySelectorAll('g.node text[fill="black"]').forEach(t => t.setAttribute('fill', '#c9d1d9'));
  svgEl.querySelectorAll('text[fill="black"]').forEach(t => t.setAttribute('fill', '#8b949e'));
  const typeColors = {{ config: '#da3633', source: '#1f6feb', fetch: '#a371f7', process: '#f0883e', transform: '#3fb950', render: '#58a6ff', orchestrator: '#f778ba' }};
  const internalNodes = ['_load_recipe_inputs', '_process_images_inputs', '_run_pipeline_inputs', 'input', 'function'];
  container.appendChild(svgEl);
  const nodeGroups = {{}};
  let nodeCount = 0;
  svgEl.querySelectorAll('g.node').forEach(g => {{
    const title = g.querySelector('title');
    if (!title) return;
    const name = title.textContent.trim();
    const wrapper = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    wrapper.classList.add('node-group');
    wrapper.dataset.name = name;
    g.parentNode.insertBefore(wrapper, g);
    wrapper.appendChild(g);
    nodeGroups[name] = wrapper;
    if (internalNodes.includes(name)) {{ wrapper.style.opacity = '0.3'; }}
    else {{
      nodeCount++;
      const meta = FN_META[name];
      if (meta) {{
        const color = typeColors[meta.type] || '#58a6ff';
        const path = g.querySelector('path');
        const polygon = g.querySelector('polygon');
        if (path && path.getAttribute('fill') !== 'transparent') path.setAttribute('fill', color + '33');
        if (polygon && polygon.getAttribute('fill') !== 'transparent') polygon.setAttribute('fill', color + '22');
      }}
    }}
    wrapper.addEventListener('click', (e) => {{
      e.stopPropagation();
      const meta = FN_META[name];
      if (meta && meta.line) window.open(GITHUB_BASE + '#L' + meta.line, '_blank');
    }});
    wrapper.addEventListener('mouseenter', () => {{
      if (internalNodes.includes(name)) return;
      const meta = FN_META[name];
      if (!meta) return;
      tooltip.innerHTML = '<div class="fn-name">' + name + '</div><div class="fn-type">' + meta.type + '</div><div style="margin-bottom:0.3rem">' + meta.desc + '</div>' + (meta.line ? '<a class="fn-link" href="' + GITHUB_BASE + '#L' + meta.line + '" target="_blank">\u2192 View source (line ' + meta.line + ')</a>' : '');
      tooltip.style.display = 'block';
      svgEl.querySelectorAll('.node-group').forEach(g => g.classList.add('dimmed'));
      svgEl.querySelectorAll('.edge-group').forEach(g => g.classList.add('dimmed'));
      if (nodeGroups[name]) {{ nodeGroups[name].classList.remove('dimmed'); nodeGroups[name].classList.add('highlighted'); }}
      svgEl.querySelectorAll('g.edge title').forEach(t => {{
        if (t.textContent.trim().includes(name)) {{
          const w = t.closest('.edge-group');
          if (w) {{ w.classList.remove('dimmed'); w.classList.add('highlighted'); }}
        }}
      }});
    }});
    wrapper.addEventListener('mousemove', (e) => {{ tooltip.style.left = (e.clientX + 12) + 'px'; tooltip.style.top = (e.clientY + 12) + 'px'; }});
    wrapper.addEventListener('mouseleave', () => {{
      tooltip.style.display = 'none';
      svgEl.querySelectorAll('.dimmed').forEach(e => e.classList.remove('dimmed'));
      svgEl.querySelectorAll('.highlighted').forEach(e => e.classList.remove('highlighted'));
    }});
  }});
  document.getElementById('node-count').textContent = nodeCount + ' nodes';
  svgEl.querySelectorAll('g.edge').forEach(g => {{
    const wrapper = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    wrapper.classList.add('edge-group');
    g.parentNode.insertBefore(wrapper, g);
    wrapper.appendChild(g);
  }});
  let scale = 1, tx = 0, ty = 0, isPanning = false, startX, startY;
  function applyTransform() {{ svgEl.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')'; svgEl.style.transformOrigin = '0 0'; }}
  container.addEventListener('mousedown', (e) => {{ if (e.target.closest('.node-group')) return; isPanning = true; startX = e.clientX - tx; startY = e.clientY - ty; }});
  window.addEventListener('mousemove', (e) => {{ if (!isPanning) return; tx = e.clientX - startX; ty = e.clientY - startY; applyTransform(); }});
  window.addEventListener('mouseup', () => {{ isPanning = false; }});
  container.addEventListener('wheel', (e) => {{
    e.preventDefault();
    const rect = container.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    const ns = Math.max(0.1, Math.min(5, scale * delta));
    tx = mx - (mx - tx) * (ns / scale); ty = my - (my - ty) * (ns / scale); scale = ns;
    applyTransform();
  }}, {{ passive: false }});
  function fitToScreen() {{
    const svgW = svgEl.viewBox?.baseVal?.width || svgEl.getBBox().width;
    const svgH = svgEl.viewBox?.baseVal?.height || svgEl.getBBox().height;
    const cw = container.clientWidth, ch = container.clientHeight;
    scale = Math.min(cw / svgW, ch / svgH) * 0.9;
    tx = (cw - svgW * scale) / 2; ty = (ch - svgH * scale) / 2;
    applyTransform();
  }}
  document.getElementById('btn-fit').addEventListener('click', fitToScreen);
  document.getElementById('btn-reset').addEventListener('click', () => {{ scale = 1; tx = 0; ty = 0; applyTransform(); }});
  document.getElementById('zoom-in').addEventListener('click', () => {{ const cw = container.clientWidth / 2, ch = container.clientHeight / 2; const ns = Math.min(5, scale * 1.3); tx = cw - (cw - tx) * (ns / scale); ty = ch - (ch - ty) * (ns / scale); scale = ns; applyTransform(); }});
  document.getElementById('zoom-out').addEventListener('click', () => {{ const cw = container.clientWidth / 2, ch = container.clientHeight / 2; const ns = Math.max(0.1, scale * 0.7); tx = cw - (cw - tx) * (ns / scale); ty = ch - (ch - ty) * (ns / scale); scale = ns; applyTransform(); }});
  document.getElementById('zoom-fit').addEventListener('click', fitToScreen);
  setTimeout(fitToScreen, 100);
  window.addEventListener('resize', () => setTimeout(fitToScreen, 100));
  window.addEventListener('keydown', (e) => {{ if (e.key === '+' || e.key === '=') document.getElementById('zoom-in').click(); if (e.key === '-') document.getElementById('zoom-out').click(); if (e.key === '0') fitToScreen(); }});
}})();
</script>
</body>
</html>"""

    (site_dir / "index.html").write_text(html)
    print(f"Built site: {recipe_name}")


if __name__ == "__main__":
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("site-output")
    site_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("site")
    build_site(output_dir, site_dir)
