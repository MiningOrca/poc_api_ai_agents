"""Gate E — Normalization.

Transforms a validated artifact into its canonical representation:

- Stable field ordering (defined per artifact type below)
- Empty collections defaulted (``[]`` for lists, ``{}`` for objects)
- Optional structures filled with canonical empty values
- Canonical scalar defaults where documented (e.g. ``mode`` → ``"single"``)

All functions accept the raw parsed artifact (dict or list) and return a new,
normalized dict or list.  Input is never mutated.

Normalization is idempotent: normalizing an already-normalized artifact
produces the same result.

Applied after Stage 1 (rules.json), Stage 2 (test_cases.json),
Stage 3 (execution_plan.json), and Stage 5 (review_report.json).

Entry points
------------
normalize_rules(data)           -- output/rules.json
normalize_test_cases(data)      -- output/test_cases.json
normalize_execution_plan(data)  -- output/execution_plan.json
normalize_review_report(data)   -- output/review_report.json
"""
from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Canonical field orderings
# ---------------------------------------------------------------------------

_RULE_ORDER = ["id", "text", "sourceRefs"]

_TEST_CASE_STEP_ORDER = ["endpointId", "summary"]

_TEST_CASE_ORDER = [
    "title",
    "summary",
    "category",
    "mode",
    "expectedStatusCode",
    "expectedOutcome",
    "sourceRefs",
    "steps",
]

_ENDPOINT_TC_ORDER = ["endpointId", "cases"]

_ASSERTION_ORDER = ["path", "operator", "expected"]

_PRODUCE_BINDING_ORDER = ["contextKey", "sourcePath"]

_STEP_ORDER = [
    "index",
    "stepRole",
    "title",
    "endpointId",
    "method",
    "path",
    "pathParams",
    "queryParams",
    "body",
    "assertions",
    "produceBindings",
]

_SCENARIO_ORDER = [
    "scenarioId",
    "isSetupFixture",
    "setupRef",
    "endpointId",
    "title",
    "category",
    "sourceRefs",
    "expectedStatusCode",
    "steps",
]

_FAILURE_CLASSIFICATION_ORDER = ["kind", "confidence"]

_VALIDATION_ASSESSMENT_ORDER = ["isSufficient", "missingChecks"]

_REVIEW_VERDICT_ORDER = [
    "scenarioId",
    "verdict",
    "summary",
    "failureClassification",
    "rootCauseHypotheses",
    "validationAssessment",
    "testDesignIssues",
    "recommendedActions",
    "evidence",
]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _reorder(obj: dict, order: List[str]) -> dict:
    """Return a copy of *obj* with keys in *order* first, then remaining keys."""
    result: Dict[str, Any] = {}
    for key in order:
        if key in obj:
            result[key] = obj[key]
    for key in obj:
        if key not in result:
            result[key] = obj[key]
    return result


# ---------------------------------------------------------------------------
# rules.json
# ---------------------------------------------------------------------------

def normalize_rules(data: Any) -> dict:
    """Normalize output/rules.json (Gate E)."""
    data = dict(data)
    data.setdefault("generalRules", [])
    data.setdefault("rulesByEndpoint", {})

    data["generalRules"] = [_normalize_rule(r) for r in data["generalRules"]]
    data["rulesByEndpoint"] = {
        k: [_normalize_rule(r) for r in v]
        for k, v in sorted(data["rulesByEndpoint"].items())
    }
    return _reorder(data, ["generalRules", "rulesByEndpoint"])


def _normalize_rule(rule: Any) -> dict:
    rule = dict(rule)
    rule.setdefault("sourceRefs", [])
    return _reorder(rule, _RULE_ORDER)


# ---------------------------------------------------------------------------
# test_cases.json
# ---------------------------------------------------------------------------

def normalize_test_cases(data: Any) -> Any:
    """Normalize output/test_cases.json (Gate E)."""
    if isinstance(data, list):
        return [_normalize_endpoint_tc(item) for item in data]
    return _normalize_endpoint_tc(data)


def _normalize_endpoint_tc(item: Any) -> dict:
    item = dict(item)
    item.setdefault("cases", [])
    item["cases"] = [_normalize_test_case(c) for c in item["cases"]]
    return _reorder(item, _ENDPOINT_TC_ORDER)


def _normalize_test_case(case: Any) -> dict:
    case = dict(case)
    case.setdefault("summary", "")
    case.setdefault("mode", "single")
    case.setdefault("expectedStatusCode", None)
    case.setdefault("expectedOutcome", "")
    case.setdefault("sourceRefs", [])
    case.setdefault("steps", [])
    case["steps"] = [_normalize_test_case_step(s) for s in case["steps"]]
    # Remove None expectedStatusCode to stay compact
    if case["expectedStatusCode"] is None:
        del case["expectedStatusCode"]
    return _reorder(case, _TEST_CASE_ORDER)


def _normalize_test_case_step(step: Any) -> dict:
    step = dict(step)
    step.setdefault("summary", "")
    return _reorder(step, _TEST_CASE_STEP_ORDER)


# ---------------------------------------------------------------------------
# execution_plan.json
# ---------------------------------------------------------------------------

def normalize_execution_plan(data: Any) -> Any:
    """Normalize output/execution_plan.json (Gate E)."""
    if isinstance(data, list):
        return [_normalize_scenario(s) for s in data]
    return _normalize_scenario(data)


def _normalize_scenario(scenario: Any) -> dict:
    scenario = dict(scenario)
    scenario.setdefault("sourceRefs", [])
    scenario.setdefault("steps", [])
    scenario["steps"] = [_normalize_step(s) for s in scenario["steps"]]
    return _reorder(scenario, _SCENARIO_ORDER)


def _normalize_step(step: Any) -> dict:
    step = dict(step)
    step.setdefault("title", "")
    step.setdefault("pathParams", {})
    step.setdefault("queryParams", {})
    step.setdefault("body", {})
    step.setdefault("assertions", [])
    step.setdefault("produceBindings", [])
    step["assertions"] = [_normalize_assertion(a) for a in step["assertions"]]
    step["produceBindings"] = [_normalize_produce_binding(b) for b in step["produceBindings"]]
    return _reorder(step, _STEP_ORDER)


def _normalize_assertion(assertion: Any) -> dict:
    assertion = dict(assertion)
    return _reorder(assertion, _ASSERTION_ORDER)


def _normalize_produce_binding(binding: Any) -> dict:
    binding = dict(binding)
    return _reorder(binding, _PRODUCE_BINDING_ORDER)


# ---------------------------------------------------------------------------
# review_report.json
# ---------------------------------------------------------------------------

def normalize_review_report(data: Any) -> Any:
    """Normalize output/review_report.json (Gate E)."""
    if isinstance(data, list):
        return [_normalize_verdict(v) for v in data]
    return _normalize_verdict(data)


def _normalize_verdict(verdict: Any) -> dict:
    verdict = dict(verdict)
    verdict.setdefault("scenarioId", "")
    verdict.setdefault("rootCauseHypotheses", [])
    verdict.setdefault("testDesignIssues", [])
    verdict.setdefault("recommendedActions", [])
    verdict.setdefault("evidence", [])

    if isinstance(verdict.get("failureClassification"), dict):
        verdict["failureClassification"] = _reorder(
            dict(verdict["failureClassification"]),
            _FAILURE_CLASSIFICATION_ORDER,
        )

    if isinstance(verdict.get("validationAssessment"), dict):
        va = dict(verdict["validationAssessment"])
        va.setdefault("missingChecks", [])
        verdict["validationAssessment"] = _reorder(va, _VALIDATION_ASSESSMENT_ORDER)

    return _reorder(verdict, _REVIEW_VERDICT_ORDER)
