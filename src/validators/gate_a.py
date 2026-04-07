"""Gate A — Artifact shape validation.

Checks that required fields are present, types are correct, and nested objects
are well-formed.  Applied after every skill-driven stage (1, 2, 3, 5).

Entry points
------------
validate_rules(data)           -- output/rules.json         (Stage 1)
validate_test_cases(data)      -- output/test_cases.json    (Stage 2)
validate_execution_plan(data)  -- output/execution_plan.json (Stage 3)
validate_review_report(data)   -- output/review_report.json (Stage 5)

All functions raise :class:`GateFailure` on rejection.
"""
from __future__ import annotations

from typing import Any, List

from src.validators.errors import GateFailure, ValidationError

GATE = "Gate A — Artifact shape"


def _err(artifact: str, field: str, reason: str) -> ValidationError:
    return ValidationError(gate=GATE, artifact=artifact, field=field, reason=reason)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _check_str(errors: List[ValidationError], artifact: str, path: str, obj: dict, key: str) -> bool:
    if key not in obj:
        errors.append(_err(artifact, f"{path}.{key}", "required field missing"))
        return False
    if not isinstance(obj[key], str):
        errors.append(_err(artifact, f"{path}.{key}",
                           f"must be a string, got {type(obj[key]).__name__}"))
        return False
    return True


def _check_int(errors: List[ValidationError], artifact: str, path: str, obj: dict, key: str) -> bool:
    if key not in obj:
        errors.append(_err(artifact, f"{path}.{key}", "required field missing"))
        return False
    # JSON numbers without decimals deserialize as int; also accept bool subclass guard
    if not isinstance(obj[key], int) or isinstance(obj[key], bool):
        errors.append(_err(artifact, f"{path}.{key}",
                           f"must be an integer, got {type(obj[key]).__name__}"))
        return False
    return True


def _check_bool(errors: List[ValidationError], artifact: str, path: str, obj: dict, key: str) -> bool:
    if key not in obj:
        errors.append(_err(artifact, f"{path}.{key}", "required field missing"))
        return False
    if not isinstance(obj[key], bool):
        errors.append(_err(artifact, f"{path}.{key}",
                           f"must be a boolean, got {type(obj[key]).__name__}"))
        return False
    return True


def _check_list(errors: List[ValidationError], artifact: str, path: str, obj: dict, key: str,
                nonempty: bool = False) -> bool:
    if key not in obj:
        errors.append(_err(artifact, f"{path}.{key}", "required field missing"))
        return False
    if not isinstance(obj[key], list):
        errors.append(_err(artifact, f"{path}.{key}",
                           f"must be a list, got {type(obj[key]).__name__}"))
        return False
    if nonempty and len(obj[key]) == 0:
        errors.append(_err(artifact, f"{path}.{key}", "must be a non-empty list"))
        return False
    return True


def _check_dict(errors: List[ValidationError], artifact: str, path: str, obj: dict, key: str) -> bool:
    if key not in obj:
        errors.append(_err(artifact, f"{path}.{key}", "required field missing"))
        return False
    if not isinstance(obj[key], dict):
        errors.append(_err(artifact, f"{path}.{key}",
                           f"must be an object, got {type(obj[key]).__name__}"))
        return False
    return True


# ---------------------------------------------------------------------------
# rules.json
# ---------------------------------------------------------------------------

def validate_rules(data: Any) -> None:
    """Validate output/rules.json shape (Gate A)."""
    errors: List[ValidationError] = []
    artifact = "rules.json"

    if not isinstance(data, dict):
        raise GateFailure([_err(artifact, "<root>", "must be a JSON object")])

    if _check_list(errors, artifact, "<root>", data, "generalRules"):
        for i, rule in enumerate(data["generalRules"]):
            _validate_rule(errors, artifact, f"generalRules[{i}]", rule)

    if "rulesByEndpoint" not in data:
        errors.append(_err(artifact, "rulesByEndpoint", "required field missing"))
    elif not isinstance(data["rulesByEndpoint"], dict):
        errors.append(_err(artifact, "rulesByEndpoint",
                           f"must be an object, got {type(data['rulesByEndpoint']).__name__}"))
    else:
        for ep_id, rules in data["rulesByEndpoint"].items():
            if not isinstance(rules, list):
                errors.append(_err(artifact, f"rulesByEndpoint.{ep_id}",
                                   "must be a list"))
                continue
            for i, rule in enumerate(rules):
                _validate_rule(errors, artifact, f"rulesByEndpoint.{ep_id}[{i}]", rule)

    if errors:
        raise GateFailure(errors)


def _validate_rule(errors: List[ValidationError], artifact: str, path: str, rule: Any) -> None:
    if not isinstance(rule, dict):
        errors.append(_err(artifact, path, "must be an object"))
        return
    _check_str(errors, artifact, path, rule, "id")
    _check_str(errors, artifact, path, rule, "text")
    _check_list(errors, artifact, path, rule, "sourceRefs", nonempty=True)


# ---------------------------------------------------------------------------
# test_cases.json
# ---------------------------------------------------------------------------

def validate_test_cases(data: Any) -> None:
    """Validate output/test_cases.json shape (Gate A)."""
    errors: List[ValidationError] = []
    artifact = "test_cases.json"

    items = data if isinstance(data, list) else [data]

    for idx, item in enumerate(items):
        prefix = f"[{idx}]" if isinstance(data, list) else "<root>"
        if not isinstance(item, dict):
            errors.append(_err(artifact, prefix, "must be a JSON object"))
            continue
        _check_str(errors, artifact, prefix, item, "endpointId")
        if _check_list(errors, artifact, prefix, item, "cases"):
            for ci, case in enumerate(item["cases"]):
                _validate_test_case(errors, artifact, f"{prefix}.cases[{ci}]", case)

    if errors:
        raise GateFailure(errors)


def _validate_test_case(errors: List[ValidationError], artifact: str, path: str, case: Any) -> None:
    if not isinstance(case, dict):
        errors.append(_err(artifact, path, "must be an object"))
        return
    _check_str(errors, artifact, path, case, "title")
    _check_str(errors, artifact, path, case, "category")
    _check_list(errors, artifact, path, case, "sourceRefs", nonempty=True)
    if _check_list(errors, artifact, path, case, "steps"):
        for si, step in enumerate(case["steps"]):
            _validate_test_case_step(errors, artifact, f"{path}.steps[{si}]", step)


def _validate_test_case_step(errors: List[ValidationError], artifact: str, path: str, step: Any) -> None:
    if not isinstance(step, dict):
        errors.append(_err(artifact, path, "must be an object"))
        return
    _check_str(errors, artifact, path, step, "endpointId")


# ---------------------------------------------------------------------------
# execution_plan.json
# ---------------------------------------------------------------------------

def validate_execution_plan(data: Any) -> None:
    """Validate output/execution_plan.json shape (Gate A)."""
    errors: List[ValidationError] = []
    artifact = "execution_plan.json"

    scenarios = data if isinstance(data, list) else [data]

    for idx, scenario in enumerate(scenarios):
        prefix = f"[{idx}]"
        if not isinstance(scenario, dict):
            errors.append(_err(artifact, prefix, "must be a JSON object"))
            continue
        _check_str(errors, artifact, prefix, scenario, "scenarioId")
        _check_str(errors, artifact, prefix, scenario, "endpointId")
        _check_str(errors, artifact, prefix, scenario, "title")
        _check_str(errors, artifact, prefix, scenario, "category")
        _check_list(errors, artifact, prefix, scenario, "sourceRefs")
        _check_int(errors, artifact, prefix, scenario, "expectedStatusCode")
        if _check_list(errors, artifact, prefix, scenario, "steps"):
            for si, step in enumerate(scenario["steps"]):
                _validate_execution_step(errors, artifact, f"{prefix}.steps[{si}]", step)

    if errors:
        raise GateFailure(errors)


def _validate_execution_step(errors: List[ValidationError], artifact: str, path: str, step: Any) -> None:
    if not isinstance(step, dict):
        errors.append(_err(artifact, path, "must be an object"))
        return
    _check_int(errors, artifact, path, step, "index")
    _check_str(errors, artifact, path, step, "stepRole")
    _check_str(errors, artifact, path, step, "endpointId")
    _check_str(errors, artifact, path, step, "method")
    _check_str(errors, artifact, path, step, "path")
    if _check_list(errors, artifact, path, step, "assertions"):
        for ai, assertion in enumerate(step["assertions"]):
            _validate_assertion(errors, artifact, f"{path}.assertions[{ai}]", assertion)
    if _check_list(errors, artifact, path, step, "produceBindings"):
        for bi, binding in enumerate(step["produceBindings"]):
            _validate_produce_binding(errors, artifact, f"{path}.produceBindings[{bi}]", binding)


def _validate_assertion(errors: List[ValidationError], artifact: str, path: str, assertion: Any) -> None:
    if not isinstance(assertion, dict):
        errors.append(_err(artifact, path, "must be an object"))
        return
    _check_str(errors, artifact, path, assertion, "path")
    _check_str(errors, artifact, path, assertion, "operator")
    if "expected" not in assertion:
        errors.append(_err(artifact, f"{path}.expected", "required field missing"))


def _validate_produce_binding(errors: List[ValidationError], artifact: str, path: str, binding: Any) -> None:
    if not isinstance(binding, dict):
        errors.append(_err(artifact, path, "must be an object"))
        return
    _check_str(errors, artifact, path, binding, "contextKey")
    _check_str(errors, artifact, path, binding, "sourcePath")


# ---------------------------------------------------------------------------
# review_report.json
# ---------------------------------------------------------------------------

def validate_review_report(data: Any) -> None:
    """Validate output/review_report.json shape (Gate A)."""
    errors: List[ValidationError] = []
    artifact = "review_report.json"

    items = data if isinstance(data, list) else [data]

    for idx, item in enumerate(items):
        prefix = f"[{idx}]" if isinstance(data, list) else "<root>"
        if not isinstance(item, dict):
            errors.append(_err(artifact, prefix, "must be a JSON object"))
            continue
        _check_str(errors, artifact, prefix, item, "verdict")
        _check_str(errors, artifact, prefix, item, "summary")
        _check_list(errors, artifact, prefix, item, "evidence")
        _check_list(errors, artifact, prefix, item, "recommendedActions")

        if _check_dict(errors, artifact, prefix, item, "failureClassification"):
            fc = item["failureClassification"]
            _check_str(errors, artifact, f"{prefix}.failureClassification", fc, "kind")
            _check_str(errors, artifact, f"{prefix}.failureClassification", fc, "confidence")

        if _check_dict(errors, artifact, prefix, item, "validationAssessment"):
            va = item["validationAssessment"]
            _check_bool(errors, artifact, f"{prefix}.validationAssessment", va, "isSufficient")

    if errors:
        raise GateFailure(errors)
