"""Execution report builder.

Assembles the final ``execution_report.json`` from a list of scenario result
dicts produced by :func:`scenario_executor.execute_scenario`.

The builder is kept separate from transport and assertion code so the report
shape can be audited and modified independently.

Output format
-------------
The report is a list when the execution plan contained multiple scenarios, or a
single object when the plan was a single scenario — matching the input cardinality
so downstream consumers (review skill, diff tools) see a consistent structure.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# Canonical field orderings for diff-friendly, stable output
_SCENARIO_RESULT_ORDER = [
    "scenarioId",
    "title",
    "endpointId",
    "category",
    "sourceRefs",
    "expectedStatusCode",
    "passed",
    "startedAtUtc",
    "finishedAtUtc",
    "failedStepIndex",
    "steps",
]

_STEP_RESULT_ORDER = [
    "index",
    "title",
    "stepRole",
    "passed",
    "method",
    "path",
    "requestBody",
    "expectedStatusCode",
    "actualStatusCode",
    "assertionResults",
    "responseBody",
    "error",
    "startedAtUtc",
    "finishedAtUtc",
]

_ASSERTION_RESULT_ORDER = [
    "path",
    "operator",
    "expected",
    "actual",
    "passed",
    "error",
]


def _reorder(obj: dict, order: list) -> dict:
    result = {}
    for key in order:
        if key in obj:
            result[key] = obj[key]
    for key in obj:
        if key not in result:
            result[key] = obj[key]
    return result


def _normalise_assertion_result(ar: dict) -> dict:
    return _reorder(ar, _ASSERTION_RESULT_ORDER)


def _normalise_step_result(sr: dict) -> dict:
    sr = dict(sr)
    sr["assertionResults"] = [_normalise_assertion_result(a) for a in sr.get("assertionResults", [])]
    return _reorder(sr, _STEP_RESULT_ORDER)


def _normalise_scenario_result(sc: dict) -> dict:
    sc = dict(sc)
    sc["steps"] = [_normalise_step_result(s) for s in sc.get("steps", [])]
    return _reorder(sc, _SCENARIO_RESULT_ORDER)


def build_report(scenario_results: list[dict], plan_was_list: bool) -> Any:
    """Build the execution report from *scenario_results*.

    If *plan_was_list* is True the report is returned as a list; otherwise as a
    single object — preserving the cardinality of the source plan.
    """
    normalised = [_normalise_scenario_result(sc) for sc in scenario_results]
    if plan_was_list:
        return normalised
    return normalised[0] if normalised else {}
