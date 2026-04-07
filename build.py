#!/usr/bin/env python3
"""
Render src/**/*.jinja -> dist/ using context.yaml.

Usage:
    python build.py              # render all templates
    python build.py --watch      # render + re-render on file changes (requires watchdog)

Templates whose filename starts with '_' are treated as partials/layouts
and are not rendered to output files themselves.

Dependencies:
    pip install jinja2 pyyaml
    pip install watchdog          # optional, only needed for --watch
"""

import argparse
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

SRC = Path(__file__).parent / "src"
DIST = Path(__file__).parent / "dist"
CTX = Path(__file__).parent / "context.yaml"


def load_context() -> dict:
    with CTX.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_one(env: Environment, context: dict, template_path: Path) -> Path:
    """Render a single template and return the output path."""
    rel = template_path.relative_to(SRC)  # e.g. subdir/page.html.jinja
    out_rel = rel.with_suffix("")  # strip .jinja  → subdir/page.html
    if not out_rel.suffix:  # plain name.jinja → name.html
        out_rel = out_rel.with_suffix(".html")
    out_path = DIST / out_rel

    out_path.parent.mkdir(parents=True, exist_ok=True)
    template = env.get_template(str(rel.as_posix()))
    out_path.write_text(template.render(**context), encoding="utf-8")
    return out_path


def build_all(verbose: bool = True) -> list[Path]:
    context = load_context()
    env = Environment(
        loader=FileSystemLoader(str(SRC)),
        autoescape=False,
        undefined=StrictUndefined,  # raise on missing variables
        keep_trailing_newline=True,
    )

    templates = sorted(
        p
        for p in SRC.rglob("*.jinja")
        if not p.name.startswith("_")  # skip partials / base layouts
    )

    if not templates:
        print("No templates found in", SRC)
        return []

    outputs = []
    for tmpl in templates:
        out = build_one(env, context, tmpl)
        outputs.append(out)
        if verbose:
            print(f"  {tmpl.relative_to(SRC)!s:35s} -> {out}")

    if verbose:
        print(f"\nBuilt {len(outputs)} file(s) into {DIST}/")
    return outputs


# ── Watch mode ────────────────────────────────────────────────────────────────


def watch():
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("watchdog is not installed. Run:  pip install watchdog", file=sys.stderr)
        sys.exit(1)

    import time

    class RebuildHandler(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.suffix in {".jinja", ".yaml"}:
                print(f"\n[changed] {path.name}")
                try:
                    build_all()
                except Exception as exc:
                    print(f"[error] {exc}", file=sys.stderr)

    observer = Observer()
    for watch_dir in (SRC, CTX.parent):
        observer.schedule(RebuildHandler(), str(watch_dir), recursive=True)

    print(f"Watching {SRC} and {CTX} for changes. Press Ctrl+C to stop.\n")
    build_all()
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build the static site from Jinja templates."
    )
    parser.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Re-build automatically when source files change.",
    )
    args = parser.parse_args()

    if args.watch:
        watch()
    else:
        try:
            build_all()
        except Exception as exc:
            print(f"Build failed: {exc}", file=sys.stderr)
            sys.exit(1)
