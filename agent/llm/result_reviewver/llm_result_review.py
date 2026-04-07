from __future__ import annotations

import json
from typing import Any

from agent.llm.client.llm_client import LlmClient, LlmRequest
from agent.llm.prompt_util import extract_json_payload
from agent.llm.result_reviewver.result_review_model import ExecutionAuditItem
from agent.runner.test_runner import StepRunResult, ScenarioRunResult


class LlmExecutionAuditor:
    def __init__(
            self,
            llm_client: LlmClient,
            model: str,
            *,
            temperature: float = 0.0,
            top_p: float = 0.1,
            max_output_tokens: int = 2000,
            max_response_text_chars: int = 1200,
            max_json_preview_chars: int = 4000,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._temperature = temperature
        self._top_p = top_p
        self._max_output_tokens = max_output_tokens
        self._max_response_text_chars = max_response_text_chars
        self._max_json_preview_chars = max_json_preview_chars

    async def audit_scenario(
            self,
            scenario: ScenarioRunResult,
    ) -> ExecutionAuditItem:
        payload = self._project_scenario(scenario)

        request = LlmRequest(
            model=self._model,
            system_prompt=self._build_system_prompt(),
            user_prompt=self._build_user_prompt(payload),
            temperature=self._temperature,
            top_p=self._top_p,
            max_output_tokens=self._max_output_tokens,
            json_schema=ExecutionAuditItem.model_json_schema(),
        )

        response = await self._llm_client.generate(request)
        raw_json = extract_json_payload(response.text)
        return ExecutionAuditItem.model_validate_json(raw_json)

    def _project_scenario(self, scenario: ScenarioRunResult) -> dict[str, Any]:
        projected_steps = [self._project_step(step) for step in scenario.steps]

        return {
            "title": scenario.title,
            "endpointId": scenario.endpoint_id,
            "passed": scenario.passed,
            "failedStepIndex": scenario.failed_step_index,
            "scenarioError": scenario.error,
            "testStateReset": {
                "attempted": scenario.test_state_reset_attempted,
                "passed": scenario.test_state_reset_passed,
                "statusCode": scenario.test_state_reset_status_code,
                "resetFailed": bool(
                    scenario.test_state_reset_attempted and not scenario.test_state_reset_passed
                ),
            },
            "hasSetupSteps": any(step["stepRole"] == "setup" for step in projected_steps),
            "hasTargetSteps": any(step["stepRole"] == "target" for step in projected_steps),
            "steps": projected_steps,
        }

    def _project_step(self, step: StepRunResult) -> dict[str, Any]:
        attempt = step.attempts[0] if step.attempts else None

        result = {
            "index": step.index,
            "stepRole": step.step_role,
            "stepSummary": step.step_summary,
            "passed": step.passed,
            "error": step.error,
        }

        if attempt is not None:
            has_required = bool(attempt.required_fields_checked)
            has_field_assertions = bool(attempt.field_assertions_checked)
            status_matched = attempt.expected_status_code == attempt.actual_status_code

            result["attempt"] = {
                "method": attempt.method,
                "expectedStatusCode": attempt.expected_status_code,
                "actualStatusCode": attempt.actual_status_code,
                "statusMatched": status_matched,
                "requestBody": self._truncate_jsonish(attempt.request_body),
                "requiredFieldsChecked": attempt.required_fields_checked,
                "fieldAssertionsChecked": attempt.field_assertions_checked,
                "hasRequiredFieldChecks": has_required,
                "hasFieldAssertions": has_field_assertions,
                "assertionStrength": self._get_assertion_strength(
                    has_required=has_required,
                    has_field_assertions=has_field_assertions,
                ),
                "responseSummary": self._project_response_summary(attempt.response_json),
                "error": attempt.error,
            }

        return result

    def _get_assertion_strength(self, *, has_required: bool, has_field_assertions: bool) -> str:
        if has_field_assertions:
            return "field_assertions_present"
        if has_required:
            return "required_fields_only"
        return "status_only"

    def _project_response_summary(self, response_json: Any) -> Any:
        if isinstance(response_json, dict):
            summary = {
                "topLevelKeys": sorted(response_json.keys()),
            }

            if "status" in response_json:
                summary["status"] = response_json["status"]

            if "error" in response_json:
                summary["error"] = response_json["error"]

            if "details" in response_json and isinstance(response_json["details"], list):
                summary["detailsCount"] = len(response_json["details"])
                summary["detailsPreview"] = response_json["details"][:2]

            return summary

        if isinstance(response_json, list):
            return {
                "count": len(response_json),
                "preview": response_json[:2],
            }

        return response_json

    def _truncate_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) <= self._max_response_text_chars:
            return value
        return value[: self._max_response_text_chars] + "...<truncated>"

    def _truncate_jsonish(self, value: Any) -> Any:
        if value is None:
            return None

        raw = json.dumps(value, ensure_ascii=False, default=str)
        if len(raw) <= self._max_json_preview_chars:
            return value

        return {
            "_truncated": True,
            "_preview": raw[: self._max_json_preview_chars] + "...<truncated>",
        }

    def _build_system_prompt(self) -> str:
        return """
    You are Execution Run Auditor for API QA automation.

    You audit exactly one executed scenario and return exactly one JSON object matching the schema.

    Your task is to make a compact trust decision, not to retell the scenario.

    Use only facts present in the input.
    Do not invent hidden API behavior.
    Do not invent missing execution details.
    Do not assume assertions existed if they are not shown.

    How to interpret the input:
    - setup steps prepare state
    - target steps are the main verification target
    - failedStepIndex points to the first failed step when present
    - testStateReset.resetFailed means scenario isolation/reset was not clean
    - statusMatched shows whether expected and actual status codes match
    - assertionStrength describes the visible strength of response validation:
      - status_only = only status code matched, with no visible response checks
      - required_fields_only = some required response fields were checked, but no explicit field assertions are visible
      - field_assertions_present = explicit field-level assertions are visible
    - responseSummary is only a compact preview, not full proof of correctness

    Decision rules:
    - a passed scenario can still be suspicious
    - weak target assertions matter more than setup success
    - if target validation is shallow, do not classify the scenario as execution_ok
    - choose one dominant classification only
    - recommendedAction should be the most useful next step
    - recommendedPriority should reflect practical urgency, not exaggerated severity

    Output rules:
    - summary must be 2-3 compact sentences suitable for another model
    - reasons must be short judgment statements
    - evidence must contain concrete observations from the input
    - missingAssertions must include only materially important absent checks
    - suspectedRootCause should be set only when meaningful
    - followUpChecks must contain only the most useful next improvements
    - be concise and specific
    - return valid JSON only
    """.strip()

    def _build_user_prompt(self, payload: dict[str, Any]) -> str:
        return f"""
    Audit this executed scenario.

    Practical guidance:
    - if a target step passed with assertionStrength="status_only", this is usually weak_assertions
    - if a target step passed with assertionStrength="required_fields_only", check whether business outcome is still under-checked
    - if explicit field assertions are visible on the target step, that is stronger evidence of trustworthiness
    - if setup exists but the target step is weakly checked, prefer suspicious_pass over valid_pass
    - if resetFailed is true, consider whether the scenario result is unreliable because of environment or state isolation issues
    - use execution_ok only when the visible target checks make the result reasonably trustworthy
    - use infra_fail only when infrastructure/reset/execution problems dominate the result more than business validation concerns

    Scenario:
    {json.dumps(payload, ensure_ascii=False, indent=2)}
    """.strip()


