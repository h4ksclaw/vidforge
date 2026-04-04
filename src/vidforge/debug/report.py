"""HTML report builder for vidforge debug previews.

Generates self-contained dark-themed HTML pages with embedded media
(hosted on s.h4ks.com) for visual inspection of live test results.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from vidforge.debug.upload import upload_file

# ── Theme ────────────────────────────────────────────────────────────────────

BASE_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #0a0a14;
  color: #e0e0e0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  padding: 40px 20px;
  max-width: 1600px;
  margin: 0 auto;
  line-height: 1.5;
}
h1 { font-size: 28px; margin-bottom: 6px; color: #ff9900; }
h2 { font-size: 20px; font-weight: 600; color: #ff9900; margin-bottom: 12px; }
.sub { color: #888; margin-bottom: 30px; font-size: 14px; }
a { color: #ff9900; text-decoration: none; }
a:hover { text-decoration: underline; }

.section {
  background: #12121e;
  border: 1px solid #1e1e30;
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 18px;
}
.section:hover { border-color: #ff990033; }

.meta-grid {
  display: flex; flex-wrap: wrap; gap: 8px 20px;
  margin-bottom: 30px; padding: 14px 20px;
  background: #12121e; border: 1px solid #1e1e30; border-radius: 12px;
  font-size: 14px;
}
.meta-key { color: #888; }
.meta-val { color: #e0e0e0; font-weight: 600; }

.stats-grid {
  display: flex; flex-wrap: wrap; gap: 6px 16px; margin-bottom: 10px;
  font-size: 13px;
}
.stat-key { color: #888; }
.stat-val { color: #ccc; font-weight: 600; }

/* Small image grid (thumbnails) */
.img-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 14px;
  margin-top: 10px;
}
.img-card {
  background: #0e0e1a; border: 1px solid #1e1e30; border-radius: 10px;
  padding: 10px; text-align: center;
}
.img-card img {
  max-height: 200px; max-width: 100%; object-fit: contain;
  margin-bottom: 6px;
}
.img-label { font-size: 12px; color: #aaa; }

/* Full-width image (for strips, large previews) */
.full-img {
  width: 100%;
  border-radius: 10px;
  margin: 12px 0;
  border: 1px solid #1e1e30;
}
.full-img img {
  width: 100%;
  height: auto;
  display: block;
  border-radius: 10px;
}
.full-img-label {
  font-size: 13px;
  color: #888;
  margin-top: 4px;
}

.status-ok {
  color: #4caf50; font-size: 13px;
  padding: 10px 14px; background: #0a1a0a;
  border-radius: 8px; margin-bottom: 8px;
}
.status-fail {
  color: #ff4444; font-size: 13px;
  padding: 10px 14px; background: #1a0a0a;
  border-radius: 8px; margin-bottom: 8px;
}

.table-wrap { overflow-x: auto; margin-top: 10px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; padding: 8px 12px; background: #1a1a2e; color: #ff9900; font-weight: 600; }
td { padding: 7px 12px; border-bottom: 1px solid #1e1e30; }
tr:hover td { background: #1a1a2e22; }

.summary {
  margin-top: 30px; padding: 16px 20px;
  background: #12121e; border: 1px solid #1e1e30; border-radius: 12px;
}
.summary-line { font-size: 14px; color: #aaa; margin: 4px 0; }
.summary-line strong { color: #ff9900; }

audio { width: 100%; height: 36px; border-radius: 8px; margin-top: 6px; }

pre, code {
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  font-size: 13px;
}
pre {
  background: #0e0e1a;
  border: 1px solid #1e1e30;
  border-radius: 8px;
  padding: 12px 16px;
  overflow-x: auto;
  margin: 8px 0;
  color: #c8c8d0;
  white-space: pre-wrap;
  word-break: break-word;
}
.code-label { font-size: 12px; color: #888; margin-bottom: 4px; }
"""


# ── Section ──────────────────────────────────────────────────────────────────


@dataclass
class Section:
    """A named group of results within a report."""

    title: str
    stats: list[tuple[str, str]] = field(default_factory=list)
    images: list[tuple[str, str]] = field(default_factory=list)  # (url, label)
    full_images: list[tuple[str, str]] = field(default_factory=list)  # (url, label)
    audio: list[tuple[str, str]] = field(default_factory=list)  # (url, label)
    statuses: list[tuple[str, bool]] = field(default_factory=list)  # (msg, ok)
    table_rows: list[list[str]] = field(default_factory=list)
    table_headers: list[str] = field(default_factory=list)
    raw_html: str = ""
    code_blocks: list[tuple[str, str]] = field(default_factory=list)  # (label, code)

    def add_stat(self, key: str, value: str) -> None:
        self.stats.append((key, value))

    def add_image(self, url: str, label: str = "") -> None:
        self.images.append((url, label))

    def add_full_image(self, url: str, label: str = "") -> None:
        """Add a full-width image (for strips, large previews)."""
        self.full_images.append((url, label))

    def add_audio(self, url: str, label: str = "") -> None:
        self.audio.append((url, label))

    def add_status(self, msg: str, ok: bool = True) -> None:
        self.statuses.append((msg, ok))

    def add_table(self, headers: list[str], rows: list[list[str]]) -> None:
        self.table_headers = headers
        self.table_rows = rows

    def add_code(self, code: str, label: str = "") -> None:
        """Add a code block (useful for showing raw API responses or input values)."""
        self.code_blocks.append((label, code))

    def _render(self) -> str:
        parts: list[str] = [f'<div class="section"><h2>{escape(self.title)}</h2>']

        # Stats
        if self.stats:
            stats_html = " ".join(
                f'<span class="stat-key">{escape(k)}:</span> '
                f'<span class="stat-val">{escape(v)}</span>'
                for k, v in self.stats
            )
            parts.append(f'<div class="stats-grid">{stats_html}</div>')

        # Statuses
        for msg, ok in self.statuses:
            cls = "status-ok" if ok else "status-fail"
            icon = "✅" if ok else "❌"
            parts.append(f'<div class="{cls}">{icon} {escape(msg)}</div>')

        # Full-width images (strips, large previews)
        for url, label in self.full_images:
            parts.append('<div class="full-img">')
            parts.append(f'<img src="{escape(url)}" alt="{escape(label)}" loading="lazy">')
            if label:
                parts.append(f'<div class="full-img-label">{escape(label)}</div>')
            parts.append("</div>")

        # Images (thumbnails)
        if self.images:
            parts.append('<div class="img-grid">')
            for url, label in self.images:
                parts.append(
                    f'<div class="img-card">'
                    f'<img src="{escape(url)}" alt="{escape(label)}" loading="lazy">'
                    f'<div class="img-label">{escape(label)}</div>'
                    f"</div>"
                )
            parts.append("</div>")

        # Audio
        for url, label in self.audio:
            parts.append(
                f'<div style="margin-bottom:10px">'
                f'<div style="font-size:14px;margin-bottom:2px">{escape(label)}</div>'
                f'<audio controls preload="none"><source src="{escape(url)}"></audio>'
                f"</div>"
            )

        # Table
        if self.table_headers and self.table_rows:
            parts.append('<div class="table-wrap"><table>')
            parts.append("<thead><tr>")
            for h in self.table_headers:
                parts.append(f"<th>{escape(h)}</th>")
            parts.append("</tr></thead><tbody>")
            for row in self.table_rows:
                parts.append("<tr>")
                for cell in row:
                    parts.append(f"<td>{escape(cell)}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table></div>")

        # Raw HTML
        if self.raw_html:
            parts.append(self.raw_html)

        # Code blocks
        for lbl, code in self.code_blocks:
            if lbl:
                parts.append(f'<div class="code-label">{escape(lbl)}</div>')
            parts.append(f"<pre><code>{escape(code)}</code></pre>")

        parts.append("</div>")
        return "\n".join(parts)


# ── Report Builder ───────────────────────────────────────────────────────────


class ReportBuilder:
    """Build a visual debug report from live test results.

    Usage:
        report = ReportBuilder("Character Pipeline Debug", "dragonball.fandom.com")
        report.add_meta("wiki", "dragonball.fandom.com")
        report.add_meta("max_chars", "15")

        section = report.add_section("Goku")
        section.add_stat("height", "175cm")
        section.add_image("https://s.h4ks.com/goku.png", "Goku processed")

        url = report.upload()  # → "https://s.h4ks.com/XXX.html"
    """

    def __init__(self, title: str, description: str = "") -> None:
        self.title = title
        self.description = description
        self.meta: dict[str, str] = {}
        self.sections: list[Section] = []
        self._timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    def add_meta(self, key: str, value: str) -> None:
        """Add a metadata field shown at the top of the report."""
        self.meta[key] = value

    def add_section(self, title: str) -> Section:
        """Create and return a new section for grouping results."""
        section = Section(title=title)
        self.sections.append(section)
        return section

    def add_summary(self, stats: dict[str, str]) -> None:
        """Add a summary block at the bottom (key → value pairs)."""
        self._summary = stats

    def build(self) -> str:
        """Render the full report as an HTML string."""
        parts: list[str] = [
            "<!DOCTYPE html>",
            "<html lang='en'><head>",
            '<meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
            f"<title>{escape(self.title)}</title>",
            f"<style>{BASE_CSS}</style>",
            "</head><body>",
            f"<h1>{escape(self.title)}</h1>",
            f'<p class="sub">{escape(self.description)} &middot; {self._timestamp}</p>',
        ]

        # Meta grid
        if self.meta:
            meta_html = " ".join(
                f'<span class="meta-key">{escape(k)}:</span> '
                f'<span class="meta-val">{escape(v)}</span>'
                for k, v in self.meta.items()
            )
            parts.append(f'<div class="meta-grid">{meta_html}</div>')

        # Sections
        for section in self.sections:
            parts.append(section._render())

        # Summary
        summary = getattr(self, "_summary", None)
        if summary:
            parts.append('<div class="summary">')
            for k, v in summary.items():
                parts.append(
                    f'<div class="summary-line"><strong>{escape(k)}:</strong> {escape(v)}</div>'
                )
            parts.append("</div>")

        parts.append("</body></html>")
        return "\n".join(parts)

    def save(self, path: str | Path) -> Path:
        """Save the HTML report to a local file. Returns the path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.build(), encoding="utf-8")
        return path

    def upload(self) -> str | None:
        """Build, save to temp, upload to s.h4ks.com, return the URL."""
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False
        ) as f:
            f.write(self.build())
            tmp = f.name

        try:
            return upload_file(tmp)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def save_json(self, path: str | Path) -> Path:
        """Save structured report data as JSON for programmatic access."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "title": self.title,
            "description": self.description,
            "timestamp": self._timestamp,
            "meta": self.meta,
            "sections": [],
        }

        for s in self.sections:
            section_data: dict[str, Any] = {"title": s.title}
            if s.stats:
                section_data["stats"] = dict(s.stats)
            if s.images:
                section_data["images"] = [{"url": u, "label": lbl} for u, lbl in s.images]
            if s.audio:
                section_data["audio"] = [{"url": u, "label": lbl} for u, lbl in s.audio]
            if s.statuses:
                section_data["statuses"] = [{"msg": m, "ok": ok} for m, ok in s.statuses]
            if s.table_headers:
                section_data["table"] = {"headers": s.table_headers, "rows": s.table_rows}
            data["sections"].append(section_data)

        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
