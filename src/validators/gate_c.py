"""Gate C — Assertion operator validation.

Checks that every assertion in ``execution_plan.json`` uses only the eight
supported operators.  Any other value is a hard rejection.

Supported operators
-------------------
equals, not_equals, exists, not_exists, contains, in, gte, lte

Applied after Stage 3 (execution_plan.json).

Entry point
-----------
validate_execution_plan(data)  -- raises GateFailure on rejection
"""
from __future__ import annotations

from typing import Any, List

from src.validators.errors import GateFailure, ValidationError

GATE = "Gate C — Assertion operators"

ALLOWED_OPERATORS: frozenset = frozenset({
    "equals",
    "not_equals",
    "exists",
    "not_exists",
    "contains",
    "in",
    "gte",
    "lte",
})


def _err(artifact: str, field: str, reason: str) -> ValidationError:
    return ValidationError(gate=GATE, artifact=artifact, field=field, reason=reason)


def validate_execution_plan(data: Any) -> None:
    """Validate assertion operators in output/execution_plan.json (Gate C)."""
    errors: List[ValidationError] = []
    artifact = "execution_plan.json"

    scenarios = data if isinstance(data, list) else [data]

    for idx, scenario in enumerate(scenarios):
        prefix = f"[{idx}]"
        if not isinstance(scenario, dict):
            continue
        for si, step in enumerate(scenario.get("steps", [])):
            if not isinstance(step, dict):
                continue
            for ai, assertion in enumerate(step.get("assertions", [])):
                if not isinstance(assertion, dict):
                    continue
                operator = assertion.get("operator", "")
                if operator not in ALLOWED_OPERATORS:
                    errors.append(_err(
                        artifact,
                        f"{prefix}.steps[{si}].assertions[{ai}].operator",
                        f"'{operator}' is not an allowed operator; "
                        f"allowed: {sorted(ALLOWED_OPERATORS)}",
                    ))

    if errors:
        raise GateFailure(errors)
