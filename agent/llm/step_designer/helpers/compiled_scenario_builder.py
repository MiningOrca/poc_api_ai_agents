from typing import Any


class CompiledScenarioBuilder:
    """
    Builds final compiled scenario from step drafts returned by LLM.

    Responsibilities:
    - accumulate compiled steps
    - resolve deterministic expectations from contract
    - update available context from produceBindings
    - keep short prior step summaries
    - return final scenario JSON
    """

    def __init__(self) -> None:
        self._test_case_idea: dict[str, Any] | None = None
        self._compiled_steps: list[dict[str, Any]] = []
        self._available_context: dict[str, dict[str, Any]] = {}
        self._steps_summary: list[str] = []

    def start_scenario(
        self,
        *,
        test_case_idea: dict[str, Any],
    ) -> None:
        self._test_case_idea = test_case_idea
        self._compiled_steps = []
        self._available_context = {}
        self._steps_summary = []

    def get_available_context(self) -> dict[str, dict[str, Any]]:
        self._ensure_started()
        return {key: dict(value) for key, value in self._available_context.items()}

    def get_recent_step_summaries(self, *, limit: int = 3) -> list[str]:
        self._ensure_started()
        if limit <= 0:
            return []
        return list(self._steps_summary[-limit:])

    def accept_step_draft(
        self,
        *,
        node: dict[str, Any],
        step_request: dict[str, Any],
        draft_json: dict[str, Any],
        step_summary: str | None,
    ) -> None:
        self._ensure_started()

        test_case_idea = self._test_case_idea
        if test_case_idea is None:
            raise RuntimeError("Scenario has not been started")

        step = node["step"]
        step_endpoint_id = node["endpointId"]
        contract_for_step = node["contract"]

        if node["kind"] == "repeat" and draft_json.get("produceBindings"):
            raise ValueError(
                f"Repeated step for endpointId={step_endpoint_id} must not produce context"
            )

        expected_status_code = step["stepStatusCode"]

        required_fields = self._extract_required_response_fields(
            contract_for_step=contract_for_step,
            status_code=expected_status_code,
        )

        compiled_step = {
            "kind": node["kind"],
            "times": node["times"],
            "index": node["startIndex"],
            "endIndex": node["endIndex"],
            "endpointId": step_endpoint_id,
            "stepRole": step["stepRole"],
            "contractRef": {
                "method": contract_for_step.get("method"),
                "path": contract_for_step.get("path"),
            },
            "inputStep": step_request["currentStep"],
            "outputContextPlan": step_request["outputContextPlan"],
            "executionDraft": draft_json,
            "expect": {
                "statusCode": expected_status_code,
                "requiredFields": required_fields,
                "fieldAssertions": draft_json.get("fieldAssertions", []),
            },
        }
        self._compiled_steps.append(compiled_step)

        if step_summary:
            self._steps_summary.append(step_summary)

        self._merge_available_context(
            draft=draft_json,
            contract_for_step=contract_for_step,
            status_code=expected_status_code,
        )

    def build_result(self) -> dict[str, Any]:
        self._ensure_started()

        test_case_idea = self._test_case_idea
        if test_case_idea is None:
            raise RuntimeError("Scenario has not been started")

        return {
            "title": test_case_idea["title"],
            "category": test_case_idea["category"],
            "mode": test_case_idea["mode"],
            "expectedStatusCode": test_case_idea["steps"][-1]["stepStatusCode"],
            "sourceRefs": test_case_idea["sourceRefs"],
            "setupReason": test_case_idea.get("setupReason"),
            "steps": self._compiled_steps,
        }

    def _ensure_started(self) -> None:
        if self._test_case_idea is None:
            raise RuntimeError("Call start_scenario(...) before using builder")

    def _resolve_expected_status_code(
        self,
        *,
        test_case_idea: dict[str, Any],
        step: dict[str, Any],
        contract_for_step: dict[str, Any],
    ) -> int | None:
        if step["stepRole"] == "target":
            return int(test_case_idea["expectedStatusCode"])

        return self._resolve_success_status_code(contract_for_step)

    @staticmethod
    def _resolve_success_status_code(contract_for_step: dict[str, Any]) -> int | None:
        responses = contract_for_step.get("responses") or {}

        for code in ("200", "201", "202", "204"):
            if code in responses:
                return int(code)

        supported = contract_for_step.get("supportedStatusCodes") or []
        normalized_codes: list[int] = []
        for code in supported:
            code_str = str(code).strip()
            if code_str.isdigit() and code_str.startswith("2"):
                normalized_codes.append(int(code_str))

        if normalized_codes:
            return min(normalized_codes)

        return None

    def _merge_available_context(
        self,
        *,
        draft: dict[str, Any],
        contract_for_step: dict[str, Any],
        status_code: int | None,
    ) -> None:
        response_properties = self._extract_response_properties(
            contract_for_step=contract_for_step,
            status_code=status_code,
        )

        for produce in draft.get("produceBinding", []):
            context_key = produce["contextKey"]
            source_path = produce["sourcePath"]
            root_field = self._extract_response_root_field(source_path)

            field_schema = response_properties.get(root_field, {})
            field_type = field_schema.get("type", "unknown")

            self._available_context[context_key] = {
                "type": field_type,
                "sourcePath": source_path,
                "fromEndpoint": contract_for_step.get("path"),
            }

    @classmethod
    def _extract_required_response_fields(
        cls,
        *,
        contract_for_step: dict[str, Any],
        status_code: int | None,
    ) -> list[str]:
        schema = cls._extract_response_schema(
            contract_for_step=contract_for_step,
            status_code=status_code,
        )
        if not isinstance(schema, dict):
            return []

        return cls._collect_required_fields(schema)

    @classmethod
    def _collect_required_fields(
        cls,
        schema: dict[str, Any],
        prefix: str = "",
    ) -> list[str]:
        result: list[str] = []

        required = schema.get("required") or []
        properties = schema.get("properties") or {}

        if not isinstance(required, list) or not isinstance(properties, dict):
            return result

        for field_name in required:
            if not isinstance(field_name, str):
                continue

            field_path = f"{prefix}.{field_name}" if prefix else field_name
            result.append(field_path)

            child_schema = properties.get(field_name)
            if isinstance(child_schema, dict) and child_schema.get("type") == "object":
                result.extend(cls._collect_required_fields(child_schema, field_path))

        return result

    @classmethod
    def _extract_response_properties(
        cls,
        *,
        contract_for_step: dict[str, Any],
        status_code: int | None,
    ) -> dict[str, Any]:
        schema = cls._extract_response_schema(
            contract_for_step=contract_for_step,
            status_code=status_code,
        )
        if isinstance(schema, dict):
            properties = schema.get("properties")
            if isinstance(properties, dict):
                return properties
        return {}

    @staticmethod
    def _extract_response_schema(
        *,
        contract_for_step: dict[str, Any],
        status_code: int | None,
    ) -> dict[str, Any]:
        response_schema = contract_for_step.get("responseSchema")
        if isinstance(response_schema, dict):
            return response_schema

        responses = contract_for_step.get("responses") or {}

        if status_code is not None:
            response = responses.get(str(status_code)) or {}
            content = response.get("content") or {}
            app_json = content.get("application/json") or {}
            schema = app_json.get("schema") or {}
            if isinstance(schema, dict):
                return schema

        for code in ("200", "201"):
            response = responses.get(code) or {}
            content = response.get("content") or {}
            app_json = content.get("application/json") or {}
            schema = app_json.get("schema") or {}
            if isinstance(schema, dict):
                return schema

        return {}

    @staticmethod
    def _extract_response_root_field(source_path: str) -> str:
        prefix = ""
        if not source_path.startswith(prefix):
            return ""
        tail = source_path[len(prefix) :]
        return tail.split(".", 1)[0].split("[", 1)[0]