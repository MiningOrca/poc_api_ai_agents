"""Gate B — Contract conformance validation.

Validates that every endpoint reference in a skill-produced artifact maps to
a real operation in ``open_api.json``, and that methods, paths, parameters,
request body fields, status codes, and assertion targets are consistent with
the documented contract.

Applied after Stage 2 (test_cases.json) and Stage 3 (execution_plan.json).

Entry points
------------
validate_test_cases(data, contract)      -- output/test_cases.json    (Stage 2)
validate_execution_plan(data, contract)  -- output/execution_plan.json (Stage 3)

Both functions raise :class:`GateFailure` on rejection.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Set

from src.contract.loader import ContractLoader, Operation
from src.validators.errors import GateFailure, ValidationError

GATE = "Gate B — Contract conformance"

# Matches the root field name of a JSONPath like $.field or $.field.nested
_JSONPATH_ROOT_FIELD_RE = re.compile(r"^\$\.([A-Za-z_][A-Za-z0-9_]*)")
# Template variable in a path segment: {{key}}
_TEMPLATE_VAR_RE = re.compile(r"\{\{[^}]+\}\}")
# OpenAPI path parameter: {param}
_OPENAPI_PARAM_RE = re.compile(r"\{[^}]+\}")


def _err(artifact: str, field: str, reason: str) -> ValidationError:
    return ValidationError(gate=GATE, artifact=artifact, field=field, reason=reason)


def _normalize_path_template(path: str) -> str:
    """Replace both ``{param}`` and ``{{param}}`` with a fixed placeholder."""
    path = _TEMPLATE_VAR_RE.sub("{_}", path)
    path = _OPENAPI_PARAM_RE.sub("{_}", path)
    return path


def _jsonpath_root_field(jpath: str) -> Optional[str]:
    m = _JSONPATH_ROOT_FIELD_RE.match(jpath)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# test_cases.json
# ---------------------------------------------------------------------------

def validate_test_cases(data: Any, contract: ContractLoader) -> None:
    """Validate output/test_cases.json contract conformance (Gate B)."""
    errors: List[ValidationError] = []
    artifact = "test_cases.json"
    valid_ops = contract.operation_ids()

    items = data if isinstance(data, list) else [data]

    for idx, item in enumerate(items):
        prefix = f"[{idx}]" if isinstance(data, list) else "<root>"
        if not isinstance(item, dict):
            continue

        ep_id = item.get("endpointId", "")
        if ep_id not in valid_ops:
            errors.append(_err(artifact, f"{prefix}.endpointId",
                               f"'{ep_id}' is not a known operationId in open_api.json"))

        for ci, case in enumerate(item.get("cases", [])):
            if not isinstance(case, dict):
                continue
            for si, step in enumerate(case.get("steps", [])):
                if not isinstance(step, dict):
                    continue
                step_ep = step.get("endpointId", "")
                if step_ep not in valid_ops:
                    errors.append(_err(
                        artifact,
                        f"{prefix}.cases[{ci}].steps[{si}].endpointId",
                        f"'{step_ep}' is not a known operationId in open_api.json",
                    ))

    if errors:
        raise GateFailure(errors)


# ---------------------------------------------------------------------------
# execution_plan.json
# ---------------------------------------------------------------------------

def validate_execution_plan(data: Any, contract: ContractLoader) -> None:
    """Validate output/execution_plan.json contract conformance (Gate B)."""
    errors: List[ValidationError] = []
    artifact = "execution_plan.json"
    valid_ops = contract.operation_ids()

    scenarios = data if isinstance(data, list) else [data]

    for idx, scenario in enumerate(scenarios):
        prefix = f"[{idx}]"
        if not isinstance(scenario, dict):
            continue

        ep_id = scenario.get("endpointId", "")
        if ep_id not in valid_ops:
            errors.append(_err(artifact, f"{prefix}.endpointId",
                               f"'{ep_id}' is not a known operationId in open_api.json"))

        expected_sc: Optional[int] = scenario.get("expectedStatusCode")

        for si, step in enumerate(scenario.get("steps", [])):
            if not isinstance(step, dict):
                continue
            step_prefix = f"{prefix}.steps[{si}]"

            step_ep = step.get("endpointId", "")
            op = contract.get_operation(step_ep)
            if op is None:
                errors.append(_err(artifact, f"{step_prefix}.endpointId",
                                   f"'{step_ep}' is not a known operationId in open_api.json"))
                continue  # can't validate further without an operation

            _validate_method(errors, artifact, step_prefix, step, op)
            _validate_path(errors, artifact, step_prefix, step, op)
            _validate_path_params(errors, artifact, step_prefix, step, op)
            _validate_query_params(errors, artifact, step_prefix, step, op)
            _validate_body_fields(errors, artifact, step_prefix, step, op)
            _validate_status_code(errors, artifact, step_prefix, step, op, expected_sc)
            _validate_assertion_targets(errors, artifact, step_prefix, step, op, expected_sc)

    if errors:
        raise GateFailure(errors)


def _validate_method(errors, artifact, path, step, op: Operation):
    method = step.get("method", "").upper()
    if method != op.method:
        errors.append(_err(artifact, f"{path}.method",
                           f"expected '{op.method}' for operation '{op.operation_id}', got '{method}'"))


def _validate_path(errors, artifact, path, step, op: Operation):
    actual = step.get("path", "")
    if _normalize_path_template(actual) != _normalize_path_template(op.path):
        errors.append(_err(artifact, f"{path}.path",
                           f"expected '{op.path}' for operation '{op.operation_id}', got '{actual}'"))


def _validate_path_params(errors, artifact, path, step, op: Operation):
    params = step.get("pathParams", {})
    if not isinstance(params, dict):
        return
    for key in params:
        if key not in op.path_param_names:
            errors.append(_err(artifact, f"{path}.pathParams.{key}",
                               f"'{key}' is not a path parameter of '{op.operation_id}' in open_api.json"))


def _validate_query_params(errors, artifact, path, step, op: Operation):
    params = step.get("queryParams", {})
    if not isinstance(params, dict):
        return
    for key in params:
        if key not in op.query_param_names:
            errors.append(_err(artifact, f"{path}.queryParams.{key}",
                               f"'{key}' is not a query parameter of '{op.operation_id}' in open_api.json"))


def _validate_body_fields(errors, artifact, path, step, op: Operation):
    body = step.get("body", {})
    if not isinstance(body, dict) or not body:
        return
    if op.request_body_fields is None:
        errors.append(_err(artifact, f"{path}.body",
                           f"operation '{op.operation_id}' has no request body in open_api.json"))
        return
    for key in body:
        if key not in op.request_body_fields:
            errors.append(_err(artifact, f"{path}.body.{key}",
                               f"'{key}' is not a documented request body field of '{op.operation_id}'"))


def _validate_status_code(errors, artifact, path, step, op: Operation,
                           scenario_expected_sc: Optional[int]):
    role = step.get("stepRole", "")
    if role != "target":
        return
    if scenario_expected_sc is None:
        return
    if scenario_expected_sc not in op.responses:
        errors.append(_err(artifact, f"{path}.expectedStatusCode (scenario)",
                           f"status code {scenario_expected_sc} is not documented for "
                           f"operation '{op.operation_id}' in open_api.json; "
                           f"documented: {sorted(op.responses.keys())}"))


def _validate_assertion_targets(errors, artifact, path, step, op: Operation,
                                  scenario_expected_sc: Optional[int]):
    assertions = step.get("assertions", [])
    if not isinstance(assertions, list) or not assertions:
        return

    role = step.get("stepRole", "")
    if role == "target":
        check_sc = scenario_expected_sc
    else:
        # For setup steps use the first documented 2xx response
        check_sc = next(
            (sc for sc in sorted(op.responses.keys()) if 200 <= sc < 300),
            None,
        )

    if check_sc is None or check_sc not in op.responses:
        return
    response_fields = op.responses[check_sc]
    if not response_fields:
        # Schema has no documented properties — skip plausibility check
        return

    for ai, assertion in enumerate(assertions):
        if not isinstance(assertion, dict):
            continue
        jpath = assertion.get("path", "")
        root_field = _jsonpath_root_field(jpath)
        if root_field and root_field not in response_fields:
            errors.append(_err(
                artifact,
                f"{path}.assertions[{ai}].path",
                f"'{jpath}' references field '{root_field}' which is not in the "
                f"response schema for status {check_sc} of '{op.operation_id}'; "
                f"documented fields: {sorted(response_fields)}",
            ))
