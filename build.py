#!/usr/bin/env python3
"""
Render src/**/*.jinja -> dist/ using context.yaml.

Usage:
    python build.py              # fetch assets (if needed) + render all templates
    python build.py --watch      # render + re-render on file changes (requires watchdog)

Templates whose filename starts with '_' are treated as partials/layouts
and are not rendered to output files themselves.

Dependencies:
    pip install jinja2 pyyaml
    pip install watchdog          # optional, only needed for --watch
"""

import argparse
import re
import sys
import urllib.request
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

SRC = Path(__file__).parent / "src"
DIST = Path(__file__).parent / "dist"
CTX = Path(__file__).parent / "context.yaml"
ASSETS = DIST / "assets"

# ── Remote assets to localise ─────────────────────────────────────────────────

TAILWIND_URL = "https://cdn.tailwindcss.com"
TAILWIND_OUT = ASSETS / "tailwind.js"

INTER_URL = (
    "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500&display=swap"
)
INTER_CSS_OUT = ASSETS / "inter.css"
INTER_FONT_DIR = ASSETS / "fonts"

# User-Agent that makes Google Fonts serve modern woff2 files.
_CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


def _download(url: str, dest: Path, headers: dict | None = None) -> None:
    """Download *url* to *dest*, creating parent directories as needed."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req) as resp:
        dest.write_bytes(resp.read())
    print(f"  downloaded {dest.relative_to(DIST.parent)}")


def fetch_assets() -> None:
    """Download remote assets into dist/assets/ if not already present."""
    ASSETS.mkdir(parents=True, exist_ok=True)

    # ── Tailwind play CDN ────────────────────────────────────────────────────
    if not TAILWIND_OUT.exists():
        _download(TAILWIND_URL, TAILWIND_OUT, headers={"User-Agent": _CHROME_UA})
    else:
        print(f"  skipping {TAILWIND_OUT.relative_to(DIST.parent)} (already exists)")

    # ── Inter font (Google Fonts) ────────────────────────────────────────────
    if not INTER_CSS_OUT.exists():
        INTER_FONT_DIR.mkdir(parents=True, exist_ok=True)

        # Fetch the @font-face CSS with a browser UA to get woff2 URLs.
        req = urllib.request.Request(INTER_URL, headers={"User-Agent": _CHROME_UA})
        with urllib.request.urlopen(req) as resp:
            css = resp.read().decode("utf-8")

        # Download each referenced font file and rewrite the URL to a local path.
        for font_url in re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", css):
            font_filename = font_url.rsplit("/", 1)[-1]
            font_dest = INTER_FONT_DIR / font_filename
            if not font_dest.exists():
                _download(font_url, font_dest)
            css = css.replace(font_url, f"fonts/{font_filename}")

        INTER_CSS_OUT.write_text(css, encoding="utf-8")
        print(f"  wrote     {INTER_CSS_OUT.relative_to(DIST.parent)}")
    else:
        print(f"  skipping {INTER_CSS_OUT.relative_to(DIST.parent)} (already exists)")


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
    fetch_assets()
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
            fetch_assets()
            build_all()
        except Exception as exc:
            print(f"Build failed: {exc}", file=sys.stderr)
            sys.exit(1)
