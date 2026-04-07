from __future__ import annotations

import json
import random
import re
import string
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

PLACEHOLDER_PATTERN = re.compile(r"\$\$\{([^}]+)\}")
EXACT_PLACEHOLDER_PATTERN = re.compile(r"^\$\$\{([^}]+)\}$")


class ScenarioRunnerError(Exception):
    pass


class MissingContextValueError(ScenarioRunnerError):
    pass


class JsonPathResolutionError(ScenarioRunnerError):
    pass


@dataclass
class AttemptRunResult:
    attempt: int
    passed: bool
    method: str
    url: str
    request_body: Any
    expected_status_code: int
    actual_status_code: int | None
    required_fields_checked: list[str] = field(default_factory=list)
    field_assertions_checked: list[dict[str, Any]] = field(default_factory=list)
    produced_bindings: list[dict[str, Any]] = field(default_factory=list)
    response_json: Any = None
    response_text: str | None = None
    error: str | None = None


@dataclass
class StepRunResult:
    index: int
    scenario_title: str
    step_name: str
    step_role: str
    step_summary: str
    kind: str
    times: int
    passed: bool
    attempts: list[AttemptRunResult] = field(default_factory=list)
    error: str | None = None


@dataclass
class ScenarioRunResult:
    title: str
    endpoint_id: str
    passed: bool
    started_at_utc: str
    caseId: str | None = None
    scenarioId: str | None = None
    id: str | None = None
    finished_at_utc: str | None = None
    test_state_reset_attempted: bool = False
    test_state_reset_passed: bool = False
    test_state_reset_status_code: int | None = None
    failed_step_index: int | None = None
    shared_context: dict[str, Any] = field(default_factory=dict)
    steps: list[StepRunResult] = field(default_factory=list)
    error: str | None = None


class ScenarioRunner:
    def __init__(
            self,
            *,
            timeout_seconds: float = 30.0,
            reset_path: str = "/__test/reset",
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._reset_path = reset_path

    def run_scenario(
            self,
            *,
            base_url: str,
            scenario: dict[str, Any],
            output_path: str | Path = "run_results.json",
    ) -> ScenarioRunResult:
        started_at = self._utc_now()

        result = ScenarioRunResult(
            title=str(scenario.get("title", "")),
            endpoint_id=str(scenario.get("endpointId", "")),
            passed=False,
            started_at_utc=started_at,
        )

        shared_context: dict[str, Any] = {}
        steps = scenario.get("steps", [])

        with httpx.Client(timeout=self._timeout_seconds) as client:
            reset_url = self._join_url(base_url, self._reset_path)

            try:
                print(f"[scenario] reset -> POST {reset_url}")
                reset_response = client.post(reset_url)

                result.test_state_reset_attempted = True
                result.test_state_reset_status_code = reset_response.status_code
                result.test_state_reset_passed = 200 <= reset_response.status_code < 300

                if not result.test_state_reset_passed:
                    result.error = (
                        f"Scenario reset failed with status {reset_response.status_code}"
                    )
                    self._append_not_executed_steps(
                        result=result,
                        scenario=scenario,
                        start_index=0,
                        reason="Not executed because scenario reset failed",
                    )
                    result.finished_at_utc = self._utc_now()
                    self._write_result(output_path, result)
                    print(f"[scenario] FAILED: {result.error}")
                    return result

                if not isinstance(steps, list):
                    raise ScenarioRunnerError("scenario.steps must be a list")

                for step_index, step in enumerate(steps):
                    step_result = self._run_step(
                        client=client,
                        base_url=base_url,
                        scenario=scenario,
                        step=step,
                        step_index=step_index,
                        shared_context=shared_context,
                    )
                    result.steps.append(step_result)

                    if not step_result.passed:
                        result.failed_step_index = step_index
                        result.error = step_result.error or f"Step {step_index} failed"

                        self._append_not_executed_steps(
                            result=result,
                            scenario=scenario,
                            start_index=step_index + 1,
                            reason=f"Not executed because previous step failed: {step_result.step_name}",
                        )

                        result.shared_context = deepcopy(shared_context)
                        result.finished_at_utc = self._utc_now()
                        self._write_result(output_path, result)
                        print(
                            f"[scenario] FAILED on step {step_index}: "
                            f"{step_result.step_name}"
                        )
                        return result

                result.passed = True
                result.shared_context = deepcopy(shared_context)
                result.finished_at_utc = self._utc_now()
                self._write_result(output_path, result)
                print(f"[scenario] PASSED: {result.title}")
                return result

            except Exception as exc:
                already_recorded = len(result.steps)

                self._append_not_executed_steps(
                    result=result,
                    scenario=scenario,
                    start_index=already_recorded,
                    reason=f"Not executed because scenario aborted with exception: {exc}",
                )

                result.error = str(exc)
                result.shared_context = deepcopy(shared_context)
                result.finished_at_utc = self._utc_now()
                self._write_result(output_path, result)
                print(f"[scenario] FAILED with exception: {exc}")
                return result

    def _run_step(
            self,
            *,
            client: httpx.Client,
            base_url: str,
            scenario: dict[str, Any],
            step: dict[str, Any],
            step_index: int,
            shared_context: dict[str, Any],
    ) -> StepRunResult:
        kind = str(step.get("kind", "single"))
        times = int(step.get("times", 1) or 1)

        step_result = StepRunResult(
            index=step_index,
            scenario_title=str(scenario.get("title", "")),
            step_name=str(step.get("inputStep", {}).get("stepName", f"step_{step_index}")),
            step_role=str(step.get("stepRole", "")),
            step_summary=str(step["executionDraft"]["stepSummary"]),
            kind=kind,
            times=times,
            passed=False,
        )

        if times < 1:
            step_result.error = f"Invalid step.times value: {times}"
            return step_result

        for attempt_index in range(times):
            attempt_number = attempt_index + 1
            step_scope_randoms: dict[str, Any] = {}

            try:
                attempt_result = self._run_step_attempt(
                    client=client,
                    base_url=base_url,
                    step=step,
                    shared_context=shared_context,
                    step_scope_randoms=step_scope_randoms,
                    attempt_number=attempt_number,
                )
                step_result.attempts.append(attempt_result)

                if not attempt_result.passed:
                    step_result.error = (
                            attempt_result.error
                            or f"Attempt {attempt_number} failed"
                    )
                    return step_result

            except Exception as exc:
                attempt_result = AttemptRunResult(
                    attempt=attempt_number,
                    passed=False,
                    method=str(step.get("contractRef", {}).get("method", "")),
                    url="",
                    request_body=None,
                    expected_status_code=int(step.get("expect", {}).get("statusCode", 0)),
                    actual_status_code=None,
                    error=str(exc),
                )
                step_result.attempts.append(attempt_result)
                step_result.error = str(exc)
                return step_result

        step_result.passed = True
        return step_result

    def _run_step_attempt(
            self,
            *,
            client: httpx.Client,
            base_url: str,
            step: dict[str, Any],
            shared_context: dict[str, Any],
            step_scope_randoms: dict[str, Any],
            attempt_number: int,
    ) -> AttemptRunResult:
        contract_ref = step.get("contractRef") or {}
        execution_draft = step.get("executionDraft") or {}
        expect = step.get("expect") or {}

        method = str(contract_ref.get("method", "")).upper()
        raw_path = str(contract_ref.get("path", ""))

        if not method:
            raise ScenarioRunnerError("Missing contractRef.method")
        if not raw_path:
            raise ScenarioRunnerError("Missing contractRef.path")

        resolved_path_params = self._resolve_placeholders(
            deepcopy(execution_draft.get("pathParams", {})),
            shared_context=shared_context,
            step_scope_randoms=step_scope_randoms,
        )
        resolved_query_params = self._resolve_placeholders(
            deepcopy(execution_draft.get("queryParams", {})),
            shared_context=shared_context,
            step_scope_randoms=step_scope_randoms,
        )
        resolved_body = self._resolve_placeholders(
            deepcopy(execution_draft.get("body", {})),
            shared_context=shared_context,
            step_scope_randoms=step_scope_randoms,
        )

        resolved_expected_assertions = self._resolve_placeholders(
            deepcopy(expect.get("fieldAssertions", [])),
            shared_context=shared_context,
            step_scope_randoms=step_scope_randoms,
        )

        rendered_path = self._render_path(raw_path, resolved_path_params)
        url = self._join_url(base_url, rendered_path)

        print(f"[step] {method} {url}")

        response = client.request(
            method=method,
            url=url,
            params=resolved_query_params,
            json=resolved_body if method != "GET" else None,
        )

        response_json: Any = None
        response_text: str | None = None

        try:
            response_json = response.json()
        except Exception as exc:
            print(f"[step] WARNING: failed to parse response as JSON: {exc}")
            response_text = response.text

        expected_status_code = int(expect.get("statusCode", 0))

        attempt_result = AttemptRunResult(
            attempt=attempt_number,
            passed=False,
            method=method,
            url=str(response.request.url),
            request_body=resolved_body if method != "GET" else None,
            expected_status_code=expected_status_code,
            actual_status_code=response.status_code,
            response_json=response_json,
            response_text=response_text,
        )

        if response.status_code != expected_status_code:
            attempt_result.error = (
                f"Expected status {expected_status_code}, got {response.status_code}"
            )
            return attempt_result

        required_fields = expect.get("requiredFields", [])
        self._check_required_fields(
            response_json=response_json,
            required_fields=required_fields,
        )
        attempt_result.required_fields_checked = list(required_fields)

        checked_assertions = self._check_field_assertions(
            response_json=response_json,
            field_assertions=resolved_expected_assertions,
        )
        attempt_result.field_assertions_checked = checked_assertions

        produced_bindings = self._apply_produce_bindings(
            response_json=response_json,
            produce_bindings=execution_draft.get("produceBinding", []),
            shared_context=shared_context,
        )
        attempt_result.produced_bindings = produced_bindings

        attempt_result.passed = True
        return attempt_result

    def _check_required_fields(
            self,
            *,
            response_json: Any,
            required_fields: list[str],
    ) -> None:
        if not required_fields:
            return

        if not isinstance(response_json, dict):
            raise ScenarioRunnerError(
                "requiredFields check requires response JSON object"
            )

        missing = [field for field in required_fields if field not in response_json]
        if missing:
            raise ScenarioRunnerError(
                f"Missing required response fields: {missing}"
            )

    def _check_field_assertions(
            self,
            *,
            response_json: Any,
            field_assertions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        checked: list[dict[str, Any]] = []

        for assertion in field_assertions:
            path = str(assertion.get("path", ""))
            operator = str(assertion.get("operator", ""))

            if operator != "equals":
                raise ScenarioRunnerError(
                    f"Unsupported assertion operator: {operator}"
                )

            expected = assertion.get("expected")
            actual = self._extract_json_path(response_json, path)

            if actual != expected:
                raise ScenarioRunnerError(
                    f"Assertion failed for path {path}: expected={expected!r}, actual={actual!r}"
                )

            checked.append(
                {
                    "path": path,
                    "operator": operator,
                    "expected": expected,
                    "actual": actual,
                    "passed": True,
                }
            )

        return checked

    def _apply_produce_bindings(
            self,
            *,
            response_json: Any,
            produce_bindings: list[dict[str, Any]],
            shared_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        applied: list[dict[str, Any]] = []

        for binding in produce_bindings:
            context_key = str(binding.get("contextKey", ""))
            source_path = str(binding.get("sourcePath", ""))

            if not context_key:
                raise ScenarioRunnerError("produceBinding.contextKey is required")
            if not source_path:
                raise ScenarioRunnerError("produceBinding.sourcePath is required")

            value = self._extract_json_path(response_json, source_path)
            shared_context[context_key] = value

            applied.append(
                {
                    "contextKey": context_key,
                    "sourcePath": source_path,
                    "value": value,
                }
            )

        return applied

    def _resolve_placeholders(
            self,
            value: Any,
            *,
            shared_context: dict[str, Any],
            step_scope_randoms: dict[str, Any],
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: self._resolve_placeholders(
                    item,
                    shared_context=shared_context,
                    step_scope_randoms=step_scope_randoms,
                )
                for key, item in value.items()
            }

        if isinstance(value, list):
            return [
                self._resolve_placeholders(
                    item,
                    shared_context=shared_context,
                    step_scope_randoms=step_scope_randoms,
                )
                for item in value
            ]

        if isinstance(value, str):
            exact_match = EXACT_PLACEHOLDER_PATTERN.match(value)
            if exact_match:
                token = exact_match.group(1)
                return self._resolve_single_token(
                    token,
                    shared_context=shared_context,
                    step_scope_randoms=step_scope_randoms,
                )

            def replacer(match: re.Match[str]) -> str:
                token = match.group(1)
                resolved = self._resolve_single_token(
                    token,
                    shared_context=shared_context,
                    step_scope_randoms=step_scope_randoms,
                )
                return str(resolved)

            return PLACEHOLDER_PATTERN.sub(replacer, value)

        return value

    def _resolve_single_token(
            self,
            token: str,
            *,
            shared_context: dict[str, Any],
            step_scope_randoms: dict[str, Any],
    ) -> Any:
        if token.startswith("random_"):
            if token not in step_scope_randoms:
                step_scope_randoms[token] = self._generate_random_value(token)
            return step_scope_randoms[token]

        if token not in shared_context:
            raise MissingContextValueError(
                f"Shared context value is missing for token: {token}"
            )

        return shared_context[token]

    def _generate_random_value(self, token: str) -> Any:
        if token == "random_str" or token.startswith("random_str_"):
            alphabet = string.ascii_letters + string.digits
            return "".join(random.choices(alphabet, k=12))

        if token == "random_email" or token.startswith("random_email_"):
            suffix = uuid.uuid4().hex[:10]
            return f"qa_{suffix}@example.com"

        if token == "random_int" or token.startswith("random_int_"):
            return random.randint(1, 1000)

        if token == "random_decimal" or token.startswith("random_decimal_"):
            value = Decimal(random.randint(1, 1000)) / Decimal("100")
            return float(value)

        raise ScenarioRunnerError(f"Unsupported random token: {token}")

    def _render_path(self, raw_path: str, path_params: dict[str, Any]) -> str:
        def replacer(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in path_params:
                raise ScenarioRunnerError(
                    f"Missing path param value for '{key}'"
                )
            return str(path_params[key])

        return re.sub(r"\{([^}]+)\}", replacer, raw_path)

    def _extract_json_path(self, data: Any, path: str) -> Any:
        if path == "$":
            return data

        if not path.startswith("$"):
            raise JsonPathResolutionError(
                f"JSONPath must start with '$': {path}"
            )

        tokens = self._parse_json_path(path)
        current = data

        for token in tokens:
            if isinstance(token, str):
                if not isinstance(current, dict):
                    raise JsonPathResolutionError(
                        f"Expected object while resolving key '{token}' in path '{path}'"
                    )
                if token not in current:
                    raise JsonPathResolutionError(
                        f"Missing key '{token}' in path '{path}'"
                    )
                current = current[token]
            else:
                if not isinstance(current, list):
                    raise JsonPathResolutionError(
                        f"Expected list while resolving index [{token}] in path '{path}'"
                    )
                if token < 0 or token >= len(current):
                    raise JsonPathResolutionError(
                        f"Index [{token}] out of range in path '{path}'"
                    )
                current = current[token]

        return current

    def _parse_json_path(self, path: str) -> list[str | int]:
        tokens: list[str | int] = []
        i = 1

        while i < len(path):
            char = path[i]

            if char == ".":
                i += 1
                start = i
                while i < len(path) and path[i] not in ".[":
                    i += 1
                key = path[start:i]
                if not key:
                    raise JsonPathResolutionError(f"Invalid JSONPath: {path}")
                tokens.append(key)
                continue

            if char == "[":
                i += 1
                start = i
                while i < len(path) and path[i] != "]":
                    i += 1
                if i >= len(path):
                    raise JsonPathResolutionError(f"Invalid JSONPath: {path}")
                raw_index = path[start:i]
                if not raw_index.isdigit():
                    raise JsonPathResolutionError(
                        f"Only numeric indexes are supported in JSONPath: {path}"
                    )
                tokens.append(int(raw_index))
                i += 1
                continue

            raise JsonPathResolutionError(f"Invalid JSONPath: {path}")

        return tokens

    def _write_result(
            self,
            output_path: str | Path,
            result: ScenarioRunResult,
    ) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @staticmethod
    def _join_url(base_url: str, path: str) -> str:
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _build_not_executed_step_result(
            self,
            *,
            scenario: dict[str, Any],
            step: dict[str, Any],
            step_index: int,
            reason: str,
    ) -> StepRunResult:
        return StepRunResult(
            index=step_index,
            scenario_title=str(scenario.get("title", "")),
            step_name=str(step.get("inputStep", {}).get("stepName", f"step_{step_index}")),
            step_role=str(step.get("stepRole", "")),
            step_summary=str(step["executionDraft"]["stepSummary"]),
            kind=str(step.get("kind", "single")),
            times=int(step.get("times", 1) or 1),
            passed=False,
            attempts=[],
            error=reason,
        )

    def _append_not_executed_steps(
            self,
            *,
            result: ScenarioRunResult,
            scenario: dict[str, Any],
            start_index: int,
            reason: str,
    ) -> None:
        steps = scenario.get("steps", [])
        if not isinstance(steps, list):
            return

        for step_index in range(start_index, len(steps)):
            step = steps[step_index]
            if not isinstance(step, dict):
                continue

            result.steps.append(
                self._build_not_executed_step_result(
                    scenario=scenario,
                    step=step,
                    step_index=step_index,
                    reason=reason,
                )
            )

    def run_tests(self, input_path, output_dir, base_url="http://localhost:8000") -> list[dict[str, Any]]:
        output_dir.mkdir(parents=True, exist_ok=True)
        bundle = json.loads(input_path.read_text(encoding="utf-8"))
        endpoint_id = str(bundle.get("endpointId", "unknown_endpoint"))
        scenarios = bundle.get("scenarios", [])
        if not isinstance(scenarios, list):
            raise ValueError("Input file must contain 'scenarios' as a list")
        all_results: list[dict[str, Any]] = []
        for index, scenario in enumerate(scenarios, start=1):
            if not isinstance(scenario, dict):
                print(f"[main] skip invalid scenario at index {index}")
                continue

            scenario_payload = {
                "endpointId": scenario.get("endpointId", endpoint_id),
                "caseId": scenario["parentTestCaseId"],
                "scenarioId": scenario["id"],
                "id": f"TR-{scenario['id']}",
                "title": scenario.get("title", f"scenario_{index}"),
                "steps": scenario.get("steps", []),
            }

            scenario_output_path = output_dir / f"{endpoint_id}_{index:03d}.json"

            print("=" * 80)
            print(f"[main] running scenario {index}/{len(scenarios)}: {scenario_payload['title']}")

            run_result = self.run_scenario(
                base_url=base_url,
                scenario=scenario_payload,
                output_path=scenario_output_path,
            )
            all_results.append(asdict(run_result))
        return all_results
