"""Executor entry point — Stage 4.

Usage (from repository root)::

    python -m src.executor.runner \\
        --plan output/execution_plan.json \\
        --report output/execution_report.json \\
        --base-url http://localhost:8080

Environment variable ``API_BASE_URL`` is used as *base_url* when the
``--base-url`` flag is not supplied.

The runner:
1. Loads and parses ``execution_plan.json``.
2. Iterates scenarios in order, executing each via :mod:`scenario_executor`.
3. Assembles the report via :mod:`report_builder`.
4. Writes ``execution_report.json`` (pretty-printed, UTF-8).

Exit code 0 is returned even when scenarios fail — a failed scenario is a
valid, expected outcome captured in the report.  A non-zero exit code signals
that the runner itself could not complete (I/O error, invalid plan path, etc.).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from src.executor.report_builder import build_report
from src.executor.scenario_executor import execute_scenario
from src.executor.setup_expander import expand_setup_refs


def run(plan_path: str, report_path: str, base_url: str) -> None:
    """Execute the plan at *plan_path* and write the report to *report_path*.

    Raises :class:`FileNotFoundError` if *plan_path* does not exist.
    Raises :class:`json.JSONDecodeError` if the plan is not valid JSON.
    """
    plan_text = Path(plan_path).read_text(encoding="utf-8")
    plan_data = json.loads(plan_text)

    plan_was_list = isinstance(plan_data, list)
    scenarios = expand_setup_refs(plan_data)

    scenario_results: list = []
    for scenario in scenarios:
        result = execute_scenario(scenario, base_url)
        scenario_results.append(result)

    report = build_report(scenario_results, plan_was_list)

    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Print a brief summary to stdout
    total = len(scenario_results)
    passed = sum(1 for sc in scenario_results if sc.get("passed"))
    print(f"Execution complete: {passed}/{total} scenarios passed")
    print(f"Report written to: {report_path}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage 4 executor: run execution_plan.json and produce execution_report.json",
    )
    parser.add_argument(
        "--plan",
        default="output/execution_plan.json",
        help="Path to execution_plan.json (default: output/execution_plan.json)",
    )
    parser.add_argument(
        "--report",
        default="output/execution_report.json",
        help="Path for output execution_report.json (default: output/execution_report.json)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL of the API under test (e.g. http://localhost:8080). "
             "Falls back to $API_BASE_URL environment variable.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    base_url: str | None = args.base_url or os.environ.get("API_BASE_URL")
    if not base_url:
        print(
            "Error: base URL not specified. "
            "Use --base-url or set the API_BASE_URL environment variable.",
            file=sys.stderr,
        )
        return 1

    try:
        run(
            plan_path=args.plan,
            report_path=args.report,
            base_url=base_url,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Error: execution plan is not valid JSON — {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
