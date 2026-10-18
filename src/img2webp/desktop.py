"""
Native desktop GUI for img2webp using Tkinter.

Tkinter ships with CPython on most platforms, but some minimal installs omit it (on Debian/Ubuntu:
``sudo apt-get install python3-tk``). The import is guarded so the rest of the package keeps working
even when Tkinter is missing; ``main`` prints a helpful message in that case.

The conversion runs in a background thread so the window stays responsive. Per-file results are
passed back to the Tk main loop through a queue that is polled with ``after``; Tk widgets are only
touched from the main thread.

"""

from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

from . import run_batch
from . import report as report_mod
from .core import FORMAT_AVIF, FORMAT_WEBP, Options, discover_jobs, parse_optional_dim

try:
    import tkinter as tk  # pylint: disable=import-error
    from tkinter import filedialog, messagebox, ttk  # pylint: disable=import-error

    _TK_IMPORT_ERROR: Exception | None = None
# Any import failure (missing Tk, no display libs) must degrade gracefully.
except Exception as exc:  # pragma: no cover  # pylint: disable=broad-exception-caught
    tk = None  # type: ignore  # pylint: disable=invalid-name
    _TK_IMPORT_ERROR = exc


class App:
    # A Tk window naturally owns many widget/state variables and exposes its
    # behaviour through callbacks rather than public methods.
    # pylint: disable=too-many-instance-attributes,too-few-public-methods
    """The desktop application window."""

    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        self.root.title("img2webp")
        self.root.minsize(560, 480)

        self._queue: "queue.Queue" = queue.Queue()
        self._worker: threading.Thread | None = None

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.format_var = tk.StringVar(value=FORMAT_WEBP)
        self.width_var = tk.StringVar()
        self.height_var = tk.StringVar()
        self.thumb_var = tk.StringVar()
        self.lossless_var = tk.BooleanVar(value=True)
        self.quality_var = tk.StringVar(value="90")
        self.jobs_var = tk.StringVar(value="4")
        self.overwrite_var = tk.BooleanVar(value=False)
        self.strip_metadata_var = tk.BooleanVar(value=False)
        self.report_var = tk.StringVar()

        self._build_ui()

    # --- UI construction -------------------------------------------------
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Input file or folder").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", **pad)
        bf = ttk.Frame(frm)
        bf.grid(row=0, column=2, **pad)
        ttk.Button(bf, text="File…", command=self._pick_file).pack(side="left")
        ttk.Button(bf, text="Folder…", command=self._pick_dir).pack(side="left")

        ttk.Label(frm, text="Output folder (optional)").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Folder…", command=self._pick_output).grid(row=1, column=2, **pad)

        dims = ttk.Frame(frm)
        dims.grid(row=2, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(dims, text="Max width").pack(side="left")
        ttk.Entry(dims, textvariable=self.width_var, width=8).pack(side="left", padx=(4, 16))
        ttk.Label(dims, text="Max height").pack(side="left")
        ttk.Entry(dims, textvariable=self.height_var, width=8).pack(side="left", padx=4)
        ttk.Label(dims, text="Thumbnail").pack(side="left", padx=(16, 0))
        ttk.Entry(dims, textvariable=self.thumb_var, width=8).pack(side="left", padx=4)

        opts = ttk.Frame(frm)
        opts.grid(row=3, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Label(opts, text="Format").pack(side="left")
        ttk.Combobox(
            opts,
            textvariable=self.format_var,
            values=[FORMAT_WEBP, FORMAT_AVIF],
            width=6,
            state="readonly",
        ).pack(side="left", padx=(4, 16))
        ttk.Checkbutton(
            opts, text="Lossless", variable=self.lossless_var, command=self._toggle_quality
        ).pack(side="left")
        ttk.Label(opts, text="Quality").pack(side="left", padx=(16, 2))
        self.quality_entry = ttk.Entry(opts, textvariable=self.quality_var, width=6)
        self.quality_entry.pack(side="left")
        ttk.Label(opts, text="Jobs").pack(side="left", padx=(16, 2))
        ttk.Entry(opts, textvariable=self.jobs_var, width=6).pack(side="left")
        ttk.Checkbutton(opts, text="Overwrite", variable=self.overwrite_var).pack(
            side="left", padx=16
        )
        ttk.Checkbutton(opts, text="Strip metadata", variable=self.strip_metadata_var).pack(
            side="left"
        )
        self._toggle_quality()

        ttk.Label(frm, text="Save report to (optional)").grid(row=4, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.report_var).grid(row=4, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="File…", command=self._pick_report).grid(row=4, column=2, **pad)

        self.convert_btn = ttk.Button(frm, text="Convert", command=self._start)
        self.convert_btn.grid(row=5, column=0, columnspan=3, pady=(8, 4))

        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=6, column=0, columnspan=3, sticky="ew", **pad)

        ttk.Label(frm, text="Log").grid(row=7, column=0, sticky="w", **pad)
        self.log = tk.Text(frm, height=12, wrap="none")
        self.log.grid(row=8, column=0, columnspan=3, sticky="nsew", **pad)
        frm.rowconfigure(8, weight=1)

    # --- helpers ---------------------------------------------------------
    def _toggle_quality(self) -> None:
        state = "disabled" if self.lossless_var.get() else "normal"
        self.quality_entry.configure(state=state)

    def _pick_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select an image",
            filetypes=[("Images", "*.jpg *.jpeg *.png"), ("All files", "*.*")],
        )
        if path:
            self.input_var.set(path)

    def _pick_dir(self) -> None:
        path = filedialog.askdirectory(title="Select an input folder")
        if path:
            self.input_var.set(path)

    def _pick_output(self) -> None:
        path = filedialog.askdirectory(title="Select an output folder")
        if path:
            self.output_var.set(path)

    def _pick_report(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save report as",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("CSV", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.report_var.set(path)

    def _log(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def _parse_dim(self, value: str) -> int | None:
        """Parse an optional positive-int dimension (delegates to the core helper)."""
        return parse_optional_dim(value)

    # --- conversion flow -------------------------------------------------
    def _start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        try:
            input_path = Path(self.input_var.get().strip()).expanduser()
            if not self.input_var.get().strip():
                raise ValueError("Please choose an input file or folder.")
            out_raw = self.output_var.get().strip()
            output_dir = Path(out_raw).expanduser() if out_raw else None
            fmt = self.format_var.get() or FORMAT_WEBP
            options = Options(
                max_width=self._parse_dim(self.width_var.get()),
                max_height=self._parse_dim(self.height_var.get()),
                lossless=self.lossless_var.get(),
                quality=int(self.quality_var.get() or 90),
                overwrite=self.overwrite_var.get(),
                fmt=fmt,
                strip_metadata=self.strip_metadata_var.get(),
                thumbnail=self._parse_dim(self.thumb_var.get()),
            )
            options.validate()
            workers = max(1, int(self.jobs_var.get() or 1))
            jobs = discover_jobs(input_path, output_dir, fmt)
            if not jobs:
                raise ValueError("No supported images (.jpg/.jpeg/.png) found.")
        except (ValueError, FileNotFoundError) as exc:
            messagebox.showerror("img2webp", str(exc))
            return

        self.log.delete("1.0", "end")
        self._log(f"Converting {len(jobs)} image(s) with {workers} worker(s)...")
        self.progress.configure(maximum=len(jobs), value=0)
        self.convert_btn.configure(state="disabled")

        self._worker = threading.Thread(
            target=self._run, args=(jobs, options, workers), daemon=True
        )
        self._worker.start()
        self.root.after(100, self._drain_queue)

    def _run(self, jobs, options, workers) -> None:
        """Runs in the background thread; pushes events onto the queue."""
        try:
            results = run_batch(
                jobs, options, workers=workers, on_result=lambda r: self._queue.put(("result", r))
            )
            self._queue.put(("done", results))
        # Report any failure to the UI thread rather than killing the worker.
        except Exception as exc:  # pragma: no cover  # pylint: disable=broad-exception-caught
            self._queue.put(("error", str(exc)))

    def _finish(self, results) -> None:
        """Render the size report and optionally save it (Tk main thread)."""
        rep = report_mod.build_report(results)
        if rep.rows:
            self._log("")
            self._log(report_mod.render_text(rep))
            report_raw = self.report_var.get().strip()
            if report_raw:
                path = Path(report_raw).expanduser()
                fmt = report_mod.infer_format(path)
                try:
                    saved = report_mod.save_report(rep, path, fmt)
                    self._log(f"\nReport saved to {saved} ({fmt}).")
                except (OSError, ValueError) as exc:
                    messagebox.showerror("img2webp", f"Could not save report: {exc}")
        self.convert_btn.configure(state="normal")

    def _drain_queue(self) -> None:
        """Runs on the Tk main thread; applies queued events to widgets."""
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "result":
                    r = payload
                    status = "OK " if r.ok else "FAIL"
                    self._log(f"[{status}] {r.src} -> {r.dst} ({r.message})")
                    self.progress.step(1)
                elif kind == "done":
                    self._log("Done.")
                    self._finish(payload)
                    return
                elif kind == "error":
                    messagebox.showerror("img2webp", payload)
                    self.convert_btn.configure(state="normal")
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)


def main(argv: list[str] | None = None) -> int:  # pylint: disable=unused-argument
    """Launch the desktop GUI, or print guidance if Tkinter is unavailable."""
    if tk is None:
        print(
            "The desktop GUI requires Tkinter, which is not available in this "
            "Python environment.\n"
            f"(import error: {_TK_IMPORT_ERROR})\n"
            "On Debian/Ubuntu install it with: sudo apt-get install python3-tk\n"
            "Alternatively use the web GUI:    img2webp-web",
            file=sys.stderr,
        )
        return 1
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
