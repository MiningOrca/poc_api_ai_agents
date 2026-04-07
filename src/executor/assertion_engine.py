"""Assertion engine.

Evaluates assertions defined in an execution plan step against an actual
HTTP response.  Only the eight operators admitted by Gate C are supported:

    equals | not_equals | exists | not_exists | contains | in | gte | lte

Each assertion targets a ``$.field`` path in the response body.  The engine
extracts the value at that path and applies the operator.

The result is a plain dict (not a dataclass) so it serialises directly to JSON
in the execution report without a conversion step.
"""
from __future__ import annotations

from typing import Any

from src.executor.binding_resolver import BindingError, extract_value, value_exists

_SUPPORTED_OPERATORS = frozenset(
    ["equals", "not_equals", "exists", "not_exists", "contains", "in", "gte", "lte"]
)


class AssertionEngineError(Exception):
    """Raised for assertion configuration errors (unknown operator, etc.)."""


def _make_result(
    assertion: dict,
    actual: Any,
    passed: bool,
    error: str | None = None,
) -> dict:
    return {
        "path": assertion["path"],
        "operator": assertion["operator"],
        "expected": assertion.get("expected"),
        "actual": actual,
        "passed": passed,
        "error": error,
    }


def evaluate_assertion(assertion: dict, response_body: Any) -> dict:
    """Evaluate a single assertion against *response_body*.

    Returns a result dict with keys:
        path, operator, expected, actual, passed, error
    """
    path: str = assertion["path"]
    operator: str = assertion["operator"]
    expected: Any = assertion.get("expected")

    if operator not in _SUPPORTED_OPERATORS:
        return _make_result(
            assertion,
            actual=None,
            passed=False,
            error=f"Unsupported operator '{operator}'",
        )

    # --- exists / not_exists do not require extracting a concrete value ---
    if operator == "exists":
        present = value_exists(response_body, path)
        return _make_result(assertion, actual=present, passed=present)

    if operator == "not_exists":
        present = value_exists(response_body, path)
        return _make_result(assertion, actual=present, passed=not present)

    # --- All other operators need the actual value at the path ---
    try:
        actual = extract_value(response_body, path)
    except BindingError as exc:
        return _make_result(
            assertion,
            actual=None,
            passed=False,
            error=f"Cannot resolve assertion path: {exc}",
        )

    try:
        passed, error = _apply_operator(operator, actual, expected)
    except Exception as exc:  # noqa: BLE001
        return _make_result(assertion, actual=actual, passed=False, error=str(exc))

    return _make_result(assertion, actual=actual, passed=passed, error=error)


def _apply_operator(operator: str, actual: Any, expected: Any) -> tuple[bool, str | None]:
    """Apply *operator* and return ``(passed, error_message_or_None)``."""
    if operator == "equals":
        passed = actual == expected
        return passed, None if passed else f"Expected {expected!r}, got {actual!r}"

    if operator == "not_equals":
        passed = actual != expected
        return passed, None if passed else f"Expected value to differ from {expected!r}"

    if operator == "contains":
        if isinstance(actual, str):
            passed = str(expected) in actual
        elif isinstance(actual, (list, dict)):
            passed = expected in actual
        else:
            return False, f"'contains' not applicable to {type(actual).__name__}"
        return passed, None if passed else f"{actual!r} does not contain {expected!r}"

    if operator == "in":
        if not isinstance(expected, list):
            return False, f"'in' operator requires expected to be a list, got {type(expected).__name__}"
        passed = actual in expected
        return passed, None if passed else f"{actual!r} not in {expected!r}"

    if operator == "gte":
        try:
            passed = actual >= expected
        except TypeError:
            return False, f"Cannot compare {type(actual).__name__} >= {type(expected).__name__}"
        return passed, None if passed else f"{actual!r} < {expected!r}"

    if operator == "lte":
        try:
            passed = actual <= expected
        except TypeError:
            return False, f"Cannot compare {type(actual).__name__} <= {type(expected).__name__}"
        return passed, None if passed else f"{actual!r} > {expected!r}"

    # Unreachable given the guard above, but kept explicit
    raise AssertionEngineError(f"Unhandled operator '{operator}'")


def evaluate_all(assertions: list, response_body: Any) -> tuple[list, bool]:
    """Evaluate all assertions in *assertions* against *response_body*.

    Returns ``(assertion_results, all_passed)``.
    """
    results = [evaluate_assertion(a, response_body) for a in assertions]
    all_passed = all(r["passed"] for r in results)
    return results, all_passed
