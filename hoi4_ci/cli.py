"""Command-line interface for HOI4 CI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .checker import Checker
from .models import CheckResult, Diagnostic


CHECK_NAMES = ("encoding", "localisation", "duplicates")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hoi4-ci",
        description="Run dependency-free static checks against a HOI4 mod checkout.",
    )
    parser.add_argument("root", type=Path, help="HOI4 mod root to inspect")
    parser.add_argument(
        "--check",
        action="append",
        choices=CHECK_NAMES,
        dest="checks",
        help="run only this check; repeat to select more than one",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="exclude a root-relative glob; repeat as needed",
    )
    parser.add_argument(
        "--format",
        choices=("human", "github"),
        default="human",
        help="console output format (default: human)",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        help="write the complete machine-readable result to this path",
    )
    parser.add_argument(
        "--max-diagnostics",
        type=int,
        default=100,
        help="maximum console diagnostics; 0 shows all (default: 100)",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")

    args = build_parser().parse_args(argv)
    if args.max_diagnostics < 0:
        print("ERROR [ARGUMENT] --max-diagnostics must be zero or positive", file=sys.stderr)
        return 2

    try:
        result = Checker(args.root, args.exclude).run(args.checks or CHECK_NAMES)
        if args.json_report is not None:
            _write_json_report(args.json_report, result)
    except (OSError, ValueError) as exc:
        print(f"ERROR [FATAL] {exc}", file=sys.stderr)
        return 2

    if args.format == "github":
        _render_github(result, args.max_diagnostics)
    else:
        _render_human(result, args.max_diagnostics)
    return 0 if result.passed else 1


def _limited(
    diagnostics: list[Diagnostic],
    maximum: int,
) -> tuple[list[Diagnostic], int]:
    if maximum == 0 or maximum >= len(diagnostics):
        return diagnostics, 0
    return diagnostics[:maximum], len(diagnostics) - maximum


def _location(item: Diagnostic) -> str:
    if not item.path:
        return ""
    return f"{item.path}:{item.line}" if item.line is not None else item.path


def _render_human(result: CheckResult, maximum: int) -> None:
    shown, hidden = _limited(result.diagnostics, maximum)
    for item in shown:
        location = _location(item)
        prefix = f"{location}: " if location else ""
        print(f"{item.severity.upper()} [{item.code}] {prefix}{item.message}")
    if hidden:
        print(f"... {hidden} additional diagnostic(s) omitted from console output")
    _render_summary(result)


def _render_github(result: CheckResult, maximum: int) -> None:
    shown, hidden = _limited(result.diagnostics, maximum)
    for item in shown:
        properties = [f"title={_escape_property(item.code)}"]
        if item.path:
            properties.append(f"file={_escape_property(item.path)}")
        if item.line is not None:
            properties.append(f"line={item.line}")
        message = _escape_message(item.message)
        print(f"::{item.severity} {','.join(properties)}::{message}")
    if hidden:
        print(f"::warning title=HOI4 CI::{hidden} additional diagnostic(s) omitted")
    _render_summary(result)


def _render_summary(result: CheckResult) -> None:
    stats = ", ".join(
        f"{name}={value}" for name, value in sorted(result.stats.items())
    )
    if stats:
        print(f"Checked: {stats}")
    status = "PASS" if result.passed else "FAIL"
    print(
        f"Summary: {status} - {result.error_count} error(s), "
        f"{result.warning_count} warning(s)."
    )


def _write_json_report(path: Path, result: CheckResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _escape_property(value: str) -> str:
    return (
        value.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


def _escape_message(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


if __name__ == "__main__":
    raise SystemExit(main())
