"""Scenario executor.

Iterates the steps of a single scenario in index order.  After each step:

- If the step passed, its produced bindings are merged into the shared context
  for subsequent steps.
- If the step failed, execution stops immediately (the scenario is aborted).
  All step results collected so far — including the failed step — are preserved
  in the scenario result so downstream review has full evidence.

The scenario is marked ``passed: true`` only when every step passes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.executor.step_executor import execute_step


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def execute_scenario(scenario: dict, base_url: str) -> dict:
    """Execute all steps in *scenario* and return a scenario result dict.

    The returned dict matches the execution_report.json scenario shape:
        scenarioId, title, endpointId, passed, startedAtUtc, finishedAtUtc,
        failedStepIndex, steps
    """
    started_at = _utc_now()
    context: dict = {"runId": uuid.uuid4().hex[:8]}
    step_results: list = []
    failed_step_index: int | None = None
    scenario_expected_status: int = scenario.get("expectedStatusCode", 200)

    for step in scenario.get("steps", []):
        step_result, context = execute_step(
            step=step,
            scenario_expected_status=scenario_expected_status,
            context=context,
            base_url=base_url,
        )
        step_results.append(step_result)

        if not step_result["passed"]:
            failed_step_index = step_result["index"]
            break  # abort scenario — do not execute subsequent steps

    finished_at = _utc_now()
    scenario_passed = failed_step_index is None and bool(step_results)

    return {
        "scenarioId": scenario["scenarioId"],
        "title": scenario.get("title", ""),
        "endpointId": scenario.get("endpointId", ""),
        "category": scenario.get("category", ""),
        "sourceRefs": scenario.get("sourceRefs", []),
        "expectedStatusCode": scenario_expected_status,
        "passed": scenario_passed,
        "startedAtUtc": started_at,
        "finishedAtUtc": finished_at,
        "failedStepIndex": failed_step_index,
        "steps": step_results,
    }
