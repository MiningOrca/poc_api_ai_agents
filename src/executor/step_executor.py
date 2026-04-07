"""Step executor.

Executes a single scenario step:
1. Resolves ``{{contextKey}}`` bindings in pathParams / queryParams / body.
2. Substitutes ``{param}`` placeholders in the URL path.
3. Sends the HTTP request via :mod:`http_client`.
4. Checks the expected status code (if one is defined for this step).
5. Evaluates all assertions against the response body.
6. Extracts ``produceBindings`` from the response body to update shared context.
7. Returns a step result dict and the updated context.

A step is marked ``passed: false`` if:
- The expected status code is set and doesn't match the actual status code.
- Any assertion fails.
- The request could not be sent (transport error).
- A binding cannot be resolved (either before sending or after).

Partial evidence is always preserved: even a failed step records the actual
request and response data that were available.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.executor.assertion_engine import evaluate_all
from src.executor.binding_resolver import (
    BindingError,
    apply_path_params,
    resolve_assertions,
    resolve_step_fields,
    update_context,
)
from src.executor.http_client import send_request


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _effective_expected_status(step: dict, scenario_expected_status: int) -> int | None:
    """Return the expected status code for *step*.

    Priority:
    1. Step-level ``expectedStatusCode`` (allows plans to override per-step).
    2. Scenario-level ``expectedStatusCode`` for ``target`` steps.
    3. ``None`` for ``setup`` steps with no step-level override (no enforcement).
    """
    if "expectedStatusCode" in step:
        return step["expectedStatusCode"]
    if step.get("stepRole") == "target":
        return scenario_expected_status
    return None


def execute_step(
    step: dict,
    scenario_expected_status: int,
    context: dict,
    base_url: str,
) -> tuple[dict, dict]:
    """Execute *step* and return ``(step_result, updated_context)``.

    *context* is never mutated.  The returned *updated_context* is a new dict
    that includes any bindings produced by this step (only if the step
    succeeded; bindings from failed steps are not propagated).
    """
    started_at = _utc_now()

    # ---- 1. Resolve binding templates in transport fields ------------------
    try:
        resolved_path_params, resolved_query_params, resolved_body = resolve_step_fields(
            step.get("pathParams", {}),
            step.get("queryParams", {}),
            step.get("body", {}),
            context,
        )
    except BindingError as exc:
        finished_at = _utc_now()
        result = _build_result(
            step=step,
            expected_status=_effective_expected_status(step, scenario_expected_status),
            actual_status=None,
            request_body=step.get("body", {}),
            response_body=None,
            assertion_results=[],
            passed=False,
            error=f"Binding resolution failed before request: {exc}",
            started_at=started_at,
            finished_at=finished_at,
        )
        return result, context

    # ---- 2. Substitute {param} in path -------------------------------------
    resolved_path = apply_path_params(step["path"], resolved_path_params)
    url = base_url.rstrip("/") + resolved_path

    # ---- 3. Send HTTP request ----------------------------------------------
    http_resp = send_request(
        method=step["method"],
        url=url,
        query_params=resolved_query_params,
        body=resolved_body,
    )

    finished_at = _utc_now()
    expected_status = _effective_expected_status(step, scenario_expected_status)

    # ---- 4. Transport error (no response received) -------------------------
    if http_resp.error is not None:
        result = _build_result(
            step=step,
            expected_status=expected_status,
            actual_status=None,
            request_body=resolved_body,
            response_body=None,
            assertion_results=[],
            passed=False,
            error=f"Transport error: {http_resp.error}",
            started_at=started_at,
            finished_at=finished_at,
        )
        return result, context

    response_body = http_resp.body if http_resp.body is not None else {}

    # ---- 5. Status code check ----------------------------------------------
    status_error: str | None = None
    status_passed = True
    if expected_status is not None and http_resp.status_code != expected_status:
        status_error = f"Expected {expected_status}, got {http_resp.status_code}"
        status_passed = False

    # ---- 6. Assertion evaluation -------------------------------------------
    try:
        resolved_assertions = resolve_assertions(step.get("assertions", []), context)
    except BindingError as exc:
        result = _build_result(
            step=step,
            expected_status=expected_status,
            actual_status=http_resp.status_code,
            request_body=resolved_body,
            response_body=response_body,
            assertion_results=[],
            passed=False,
            error=f"Assertion binding resolution failed: {exc}",
            started_at=started_at,
            finished_at=finished_at,
        )
        return result, context
    assertion_results, assertions_passed = evaluate_all(
        resolved_assertions,
        response_body,
    )

    step_passed = status_passed and assertions_passed
    step_error = status_error  # status mismatch is the primary error; assertion detail is in results

    result = _build_result(
        step=step,
        expected_status=expected_status,
        actual_status=http_resp.status_code,
        request_body=resolved_body,
        response_body=response_body,
        assertion_results=assertion_results,
        passed=step_passed,
        error=step_error,
        started_at=started_at,
        finished_at=finished_at,
    )

    # ---- 7. Produce bindings (only when step succeeded) --------------------
    if step_passed:
        try:
            updated_context = update_context(context, step.get("produceBindings", []), response_body)
        except BindingError as exc:
            # Binding extraction failed after a seemingly successful request.
            # Mark the step failed and do not update context.
            result["passed"] = False
            result["error"] = f"Binding extraction failed after response: {exc}"
            return result, context
        return result, updated_context

    return result, context


def _build_result(
    step: dict,
    expected_status: int | None,
    actual_status: int | None,
    request_body: Any,
    response_body: Any,
    assertion_results: list,
    passed: bool,
    error: str | None,
    started_at: str,
    finished_at: str,
) -> dict:
    return {
        "index": step["index"],
        "title": step.get("title", ""),
        "stepRole": step.get("stepRole", ""),
        "passed": passed,
        "method": step["method"],
        "path": step["path"],
        "requestBody": request_body,
        "expectedStatusCode": expected_status,
        "actualStatusCode": actual_status,
        "assertionResults": assertion_results,
        "responseBody": response_body,
        "error": error,
        "startedAtUtc": started_at,
        "finishedAtUtc": finished_at,
    }
