"""Render the example repository's scan as an SVG and sample reports (maintainer tool).

    uv run python scripts/render_demo.py

Builds examples/conflicting-worktrees in a temporary directory, scans it statically
(running processes on the maintainer's machine would make the picture differ from
machine to machine), and writes:

- docs/images/scan.svg and site/assets/scan.svg: the terminal report, as Rich prints it;
- docs/sample-reports/example.{md,json,sarif}: the same scan in the other formats.

The temporary directory is passed to the redactor as the home directory, so its path
shows as ~ like any home path would; nothing else is changed.
"""

from __future__ import annotations

import importlib.util
import io
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from rich.console import Console

from worktree_shield.orchestrator import diagnose, inspect_resources
from worktree_shield.privacy import RedactionContext, redact_snapshot
from worktree_shield.reports.findings import render_scan
from worktree_shield.reports.json_report import render_json
from worktree_shield.reports.markdown import render_markdown
from worktree_shield.reports.sarif import render_sarif
from worktree_shield.runner import SubprocessRunner

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "examples" / "conflicting-worktrees" / "build.py"


def main() -> None:
    spec = importlib.util.spec_from_file_location("build", BUILDER)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {BUILDER}")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    os.environ.setdefault("GIT_CONFIG_GLOBAL", os.devnull)
    with tempfile.TemporaryDirectory() as temp:
        main_worktree = builder.build(Path(temp, "demo"), fixed=False)
        snapshot = diagnose(
            inspect_resources(SubprocessRunner(), main_worktree, include_runtime=False)
        )
        # created_at is fixed so the samples change only when the output does
        snapshot = replace(snapshot, created_at="2026-11-04T12:00:00Z")
        context = RedactionContext(home=str(Path(temp, "demo")), user=None)
        redacted = redact_snapshot(snapshot, context)
        console = Console(
            record=True, width=104, color_system="truecolor", highlight=False, file=io.StringIO()
        )
        render_scan(redacted, console)
        svg = console.export_svg(title="worktree-shield scan --scope static")
        for target in (
            ROOT / "docs" / "images" / "scan.svg",
            ROOT / "site" / "assets" / "scan.svg",
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(svg, encoding="utf-8")
        samples = ROOT / "docs" / "sample-reports"
        samples.mkdir(parents=True, exist_ok=True)
        (samples / "example.md").write_text(render_markdown(redacted), encoding="utf-8")
        (samples / "example.json").write_text(render_json(redacted), encoding="utf-8")
        (samples / "example.sarif").write_text(render_sarif(redacted), encoding="utf-8")


if __name__ == "__main__":
    main()
