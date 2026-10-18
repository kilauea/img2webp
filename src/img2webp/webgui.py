"""
Optional local web UI for img2webp (standard library only).

Serves a small HTML form and a JSON ``/convert`` endpoint. Conversion runs on the machine hosting
the server, so the paths entered are server-side paths - this is a local tool, not an upload
service.

"""

from __future__ import annotations

import argparse
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import run_batch
from . import report as report_mod
from .core import (
    DEFAULT_THUMBNAIL_QUALITY,
    FORMAT_WEBP,
    Options,
    discover_jobs,
    parse_optional_dim,
)

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>img2webp</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         max-width: 640px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
  h1 { font-size: 1.4rem; }
  label { display: block; margin: 0.75rem 0 0.2rem; font-weight: 600; }
  input[type=text], input[type=number] { width: 100%; padding: 0.5rem;
         box-sizing: border-box; font-size: 1rem; }
  .row { display: flex; gap: 1rem; } .row > div { flex: 1; }
  .inline { display: flex; align-items: center; gap: 0.5rem; font-weight: 400; }
  .inline input { width: auto; }
  button { margin-top: 1.2rem; padding: 0.6rem 1.4rem; font-size: 1rem;
           cursor: pointer; border-radius: 6px; border: 1px solid #888; }
  button:disabled { opacity: 0.5; cursor: default; }
  #out { white-space: pre-wrap; margin-top: 1.2rem; padding: 0.75rem;
         border: 1px solid #ccc; border-radius: 6px; min-height: 2rem;
         font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.85rem; }
  .ok { color: #2e7d32; } .fail { color: #c62828; }
  .hint { font-weight: 400; font-size: 0.8rem; opacity: 0.75; }
</style>
</head>
<body>
<h1>img2webp &mdash; JPEG/PNG &rarr; WebP / AVIF</h1>
<p class="hint">Paths are resolved on the machine running this server.</p>
<label>Input file or directory
  <input type="text" id="input" placeholder="/path/to/images"></label>
<label>Output directory <span class="hint">(optional &mdash; blank writes next to sources)</span>
  <input type="text" id="output" placeholder="/path/to/output"></label>
<div class="row">
  <div><label>Output format
    <select id="format">
      <option value="webp" selected>WebP</option>
      <option value="avif">AVIF</option>
    </select></label></div>
  <div><label>Concurrent jobs
    <input type="number" id="jobs" min="1" value="4"></label></div>
</div>
<div class="row">
  <div><label>Max width (px) <span class="hint">optional</span>
    <input type="number" id="max_width" min="1" placeholder="e.g. 1920"></label></div>
  <div><label>Max height (px) <span class="hint">optional</span>
    <input type="number" id="max_height" min="1" placeholder="e.g. 1080"></label></div>
</div>
<div class="row">
  <div><label>Thumbnail size (px) <span class="hint">optional &mdash; longest side</span>
    <input type="number" id="thumbnail" min="1" placeholder="e.g. 256"></label></div>
  <div><label>Thumbnail quality <span class="hint">(0-100)</span>
    <input type="number" id="thumbnail_quality" min="0" max="100" value="80"></label></div>
</div>
<label>Encoding</label>
<div class="inline"><input type="checkbox" id="lossless" checked>
  <span>Lossless (uncheck for lossy)</span></div>
<label>Quality <span class="hint">(lossy only, 0-100)</span>
  <input type="number" id="quality" min="0" max="100" value="90"></label>
<label>Save report to <span class="hint">(optional &mdash; .csv for CSV, else text)</span>
  <input type="text" id="report_path" placeholder="/path/to/report.txt"></label>
<div class="inline" style="margin-top:0.75rem"><input type="checkbox" id="overwrite">
  <span>Overwrite existing outputs</span></div>
<div class="inline"><input type="checkbox" id="strip_metadata">
  <span>Strip EXIF/ICC/XMP metadata</span></div>
<button id="go" onclick="convert()">Convert</button>
<div id="out"></div>
<script>
async function convert() {
  const btn = document.getElementById('go'), out = document.getElementById('out');
  const payload = {
    input: document.getElementById('input').value.trim(),
    output: document.getElementById('output').value.trim(),
    format: document.getElementById('format').value,
    max_width: document.getElementById('max_width').value,
    max_height: document.getElementById('max_height').value,
    thumbnail: document.getElementById('thumbnail').value,
    thumbnail_quality: Number(document.getElementById('thumbnail_quality').value),
    lossless: document.getElementById('lossless').checked,
    quality: Number(document.getElementById('quality').value),
    jobs: Number(document.getElementById('jobs').value),
    overwrite: document.getElementById('overwrite').checked,
    strip_metadata: document.getElementById('strip_metadata').checked,
    report_path: document.getElementById('report_path').value.trim(),
  };
  if (!payload.input) { out.textContent = 'Please enter an input path.'; return; }
  btn.disabled = true; out.textContent = 'Converting...';
  try {
    const resp = await fetch('/convert', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const data = await resp.json();
    if (!data.ok) { out.innerHTML = '<span class="fail">Error: ' +
        escapeHtml(data.error) + '</span>'; return; }
    let lines = data.results.map(r => '<span class="' + (r.ok ? 'ok' : 'fail') +
      '">[' + (r.ok ? 'OK ' : 'FAIL') + '] ' + escapeHtml(r.src) + ' -> ' +
      escapeHtml(r.dst) + ' (' + escapeHtml(r.message) + ')</span>');
    lines.push(''); lines.push('Done. ' + data.succeeded + ' succeeded, ' +
      data.failed + ' failed.');
    const rep = data.report;
    if (rep && rep.rows && rep.rows.length) {
      lines.push(''); lines.push('Size report:');
      rep.rows.forEach(row => {
        lines.push('  ' + escapeHtml(fileName(row.output)) + ': ' +
          humanSize(row.original_bytes) + ' -> ' + humanSize(row.new_bytes) +
          ' (' + row.reduction_pct.toFixed(1) + '%)');
      });
      lines.push('  TOTAL: ' + humanSize(rep.total_original_bytes) + ' -> ' +
        humanSize(rep.total_new_bytes) + ' (' +
        rep.total_reduction_pct.toFixed(1) + '%)');
      if (rep.saved_to) { lines.push(''); lines.push('Report saved to ' +
        escapeHtml(rep.saved_to)); }
    }
    out.innerHTML = lines.join('\\n');
  } catch (e) {
    out.innerHTML = '<span class="fail">Request failed: ' + escapeHtml(String(e)) + '</span>';
  } finally { btn.disabled = false; }
}
function fileName(p) { return String(p).split('/').pop(); }
function humanSize(n) {
  let s = Number(n), u = ['B','KB','MB','GB','TB'], i = 0;
  while (s >= 1024 && i < u.length - 1) { s /= 1024; i++; }
  return (i === 0 ? s.toFixed(0) : s.toFixed(1)) + ' ' + u[i];
}
function escapeHtml(s) { return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;',
  '>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
</script>
</body>
</html>
"""


def _parse_dim(value) -> int | None:
    """Parse an optional positive-int dimension (delegates to the core helper)."""
    return parse_optional_dim(value)


def run_conversion(payload: dict) -> dict:
    """
    Validate a request payload, run the conversion, return a JSON-able dict.

    This is deliberately separate from the HTTP handler so it can be unit tested directly.

    """
    input_path = Path(payload["input"]).expanduser()
    out_raw = (payload.get("output") or "").strip()
    output_dir = Path(out_raw).expanduser() if out_raw else None
    fmt = (payload.get("format") or FORMAT_WEBP).strip() or FORMAT_WEBP

    options = Options(
        max_width=_parse_dim(payload.get("max_width")),
        max_height=_parse_dim(payload.get("max_height")),
        lossless=bool(payload.get("lossless", True)),
        quality=int(payload.get("quality", 90)),
        overwrite=bool(payload.get("overwrite", False)),
        fmt=fmt,
        strip_metadata=bool(payload.get("strip_metadata", False)),
        thumbnail=_parse_dim(payload.get("thumbnail")),
        thumbnail_quality=int(payload.get("thumbnail_quality", DEFAULT_THUMBNAIL_QUALITY)),
    )
    options.validate()
    workers = max(1, int(payload.get("jobs", 1)))

    jobs = discover_jobs(input_path, output_dir, fmt)
    if not jobs:
        raise ValueError("No supported images (.jpg/.jpeg/.png) found at that path.")

    results = run_batch(jobs, options, workers=workers)
    failed = sum(1 for r in results if not r.ok)

    rep = report_mod.build_report(results)
    saved_report = None
    report_raw = (payload.get("report_path") or "").strip()
    if report_raw:
        report_path = Path(report_raw).expanduser()
        report_fmt = payload.get("report_format") or report_mod.infer_format(report_path)
        saved_report = str(report_mod.save_report(rep, report_path, report_fmt))

    return {
        "ok": True,
        "results": [
            {"src": str(r.src), "dst": str(r.dst), "ok": r.ok, "message": r.message}
            for r in results
        ],
        "succeeded": len(results) - failed,
        "failed": failed,
        "report": {
            "rows": report_mod.to_dicts(rep),
            "total_original_bytes": rep.total_original,
            "total_new_bytes": rep.total_new,
            "total_reduction_pct": round(rep.total_reduction_pct, 2),
            "summary": report_mod.summary_line(rep) if rep.rows else "",
            "saved_to": saved_report,
        },
    }


class Handler(BaseHTTPRequestHandler):
    """HTTP request handler serving the form and the conversion endpoint."""

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        """Write a complete HTTP response with the given status and body."""
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # http.server requires these exact method names.
    def do_GET(self) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Serve the HTML form at the root path."""
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(404, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802  # pylint: disable=invalid-name
        """Handle a JSON conversion request at ``/convert``."""
        if self.path != "/convert":
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            body = json.dumps(run_conversion(payload)).encode("utf-8")
            self._send(200, body, "application/json")
        # Any failure is reported to the UI as a JSON error, not a 500.
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            self._send(200, body, "application/json")

    def log_message(self, *args) -> None:
        """Silence the default per-request console logging."""


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the web GUI entry point."""
    p = argparse.ArgumentParser(
        prog="img2webp-web",
        description="Optional local web UI for the img2webp converter.",
    )
    p.add_argument(
        "--host", default="127.0.0.1", help="Interface to bind. Default: 127.0.0.1 (local only)."
    )
    p.add_argument("--port", type=int, default=8765, help="Port. Default: 8765.")
    p.add_argument(
        "--no-browser", action="store_true", help="Do not try to open a browser automatically."
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Start the local web server and serve until interrupted."""
    args = build_parser().parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"img2webp web GUI serving at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        # Opening a browser is best-effort and must not stop the server.
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            print(f"(could not open a browser automatically: {exc})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
