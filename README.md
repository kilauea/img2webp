# img2webp

Convert JPEG and PNG images to **WebP**, lossless by default, with optional
aspect-ratio-preserving downscaling and concurrent processing. Ships with three
interfaces: a command-line tool, a local web GUI, and a native desktop GUI.

## Features

- **JPEG/PNG → WebP**, lossless by default (lossy mode available).
- **Scale, not crop**: cap the max width and/or height while preserving aspect
  ratio. When both are given, the image is scaled to fit inside the box. Images
  are never upscaled.
- **Single file or recursive directory** input; non-image files are ignored.
- **Concurrent** conversion via a process pool (true parallelism for CPU-bound
  encoding).
- **Thumbnails**: optionally emit a small `<name>.thumb.webp` alongside each
  output, sized to fit a square box (longest side), always lossy.
- **Alpha preserved**; existing outputs skipped unless you opt into overwrite.
- Output written next to sources, or mirrored into an output directory.

## Installation

Requires Python 3.8+.

```bash
cd img2webp
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

For development (adds pytest) install editable with the `dev` extra:

```bash
pip install -e ".[dev]"
```

This installs three console commands: `img2webp`, `img2webp-web`,
`img2webp-gui`.

## CLI usage

```bash
# Convert a single file (lossless), output alongside the source
img2webp photo.jpg

# Recursively convert a folder, mirror outputs into ./out
img2webp ./photos -o ./out

# Cap width to 1920px (height scales to keep aspect ratio)
img2webp ./photos -W 1920

# Fit inside a 1920x1080 box (whichever dimension binds wins)
img2webp ./photos -W 1920 -H 1080

# Lossy at quality 85, 8 workers, overwrite existing outputs
img2webp ./photos --lossy -q 85 -j 8 -f

# Also generate 256px thumbnails (photo.webp + photo.thumb.webp)
img2webp ./photos -o ./out -t 256
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `input` | Image file or directory (positional) | — |
| `-o, --output-dir` | Output directory (tree mirrored) | alongside sources |
| `-W, --max-width` | Max width in px (scales, preserves ratio) | none |
| `-H, --max-height` | Max height in px (scales, preserves ratio) | none |
| `--lossy` | Use lossy WebP instead of lossless | lossless |
| `-q, --quality` | Quality 0–100 (lossy mode) | 90 |
| `--method` | Encoder effort 0 (fast) – 6 (best) | 6 |
| `-t, --thumbnail` | Also emit `<name>.thumb.webp`; value is the thumbnail's longest side in px | off |
| `--thumbnail-quality` | Thumbnail quality 0–100 (always lossy) | 80 |
| `-j, --jobs` | Worker processes | CPU count |
| `-f, --overwrite` | Overwrite existing `.webp` outputs | skip |
| `--version` | Print version | — |

Exit codes: `0` all succeeded, `1` some failed or no images found, `2` invalid
arguments.

## Web GUI

```bash
img2webp-web                     # serves http://127.0.0.1:8765 and opens a browser
img2webp-web --port 9000 --no-browser
```

Open the URL, enter an input path (and optional output folder and size bounds),
and click **Convert**. Results are listed per file.

> **Note:** Conversion runs on the machine hosting the server, so the paths you
> type are paths **on that machine**. This is a local tool, not an upload
> service. It binds to `127.0.0.1` by default so it is not exposed on the
> network.

## Desktop GUI

```bash
img2webp-gui
```

A native Tkinter window with file/folder pickers, size and encoding options, a
progress bar, and a log. Conversion runs in a background thread so the window
stays responsive.

Tkinter is part of the Python standard library but is packaged separately on
some systems. If `img2webp-gui` reports it is missing:

- **Debian/Ubuntu:** `sudo apt-get install python3-tk`
- **Fedora:** `sudo dnf install python3-tkinter`
- **macOS/Windows:** included with the python.org installers.

If you cannot install Tkinter, use the web GUI instead.

## Library usage

The conversion logic is importable:

```python
from pathlib import Path
from img2webp import discover_jobs, run_batch
from img2webp.core import Options

jobs = discover_jobs(Path("photos"), Path("out"))
results = run_batch(jobs, Options(max_width=1920, lossless=True), workers=4)
print(sum(r.ok for r in results), "converted")
```

## Development

```bash
pip install -e ".[dev]"
pytest            # run the test suite
```

The suite covers size computation, discovery, conversion (including a
pixel-exact losslessness check and alpha preservation), the concurrent runner,
and the web endpoint (function level plus a real HTTP server).

## Project layout

```
img2webp/
├── pyproject.toml
├── README.md
├── .kiro/specs/img2webp/      # requirements, design, tasks
├── src/img2webp/
│   ├── core.py                # conversion logic (shared by all front ends)
│   ├── __init__.py            # public API + run_batch
│   ├── cli.py                 # command line
│   ├── webgui.py              # local web GUI
│   └── desktop.py             # native Tkinter GUI
└── tests/
```

## How scaling works

Given an image and your max width/height, the tool computes the scale factor
each supplied bound requires and uses the **smaller** one, so the image fits
inside the bounding box with its aspect ratio intact. If the image already fits,
it is left untouched (no upscaling). Example: a 3000×2000 image with
`-W 1024` becomes 1024×683.

## Lossless note

In lossless mode the decoded WebP is pixel-identical to the (optionally resized)
source — verified in the test suite with a pixel-difference check. Lossless WebP
typically produces larger files than lossy; use `--lossy -q <n>` when size
matters more than exactness.

## License

MIT.
