from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class LlmStepDraftBuilder:
    """
    Builds input payloads for LLM step generation.

    Responsibilities:
    - validate raw step dependency graph
    - compact adjacent identical non-target steps into nodes
    - resolve contract fragment for each node
    - build current_step / output_context_plan / test_case payload
    """

    def prepare_scenario(
            self,
            *,
            test_case_idea: dict[str, Any],
            contract_fragments: dict[str, dict[str, Any] | None],
    ) -> dict[str, Any]:
        raw_steps = test_case_idea["steps"]

        self._validate_step_graph(raw_steps)
        compacted_nodes = self._compact_repeated_steps(raw_steps)

        prepared_nodes: list[dict[str, Any]] = []
        for node in compacted_nodes:
            step = node["step"]
            step_endpoint_id = str(step["endpointId"]).strip()
            contract_for_step = contract_fragments.get(step_endpoint_id)

            if contract_for_step is None:
                raise ValueError(
                    f"Contract fragment not found for step endpointId={step_endpoint_id}"
                )

            prepared_nodes.append(
                {
                    **node,
                    "endpointId": step_endpoint_id,
                    "contract": contract_for_step,
                }
            )

        return {
            "rawSteps": raw_steps,
            "testCasePayload": self._build_test_case_payload(test_case_idea),
            "nodes": prepared_nodes,
        }

    def build_step_request(
            self,
            *,
            prepared_scenario: dict[str, Any],
            node: dict[str, Any],
            node_index: int,
            available_context: dict[str, dict[str, Any]],
            prior_step_summary: list[str],
    ) -> dict[str, Any]:
        step = node["step"]
        raw_steps = prepared_scenario["rawSteps"]

        current_step = self._build_current_step_payload(
            step=step,
            step_index=node_index,
        )

        output_context_plan = self._build_output_context_plan(
            step=step,
            remaining_steps=raw_steps[node["endIndex"] + 1:],
        )
        resolved_contract_context = self._build_contract_context_for_step(step=step, contract_for_step=node["contract"])
        return {
            "endpointId": node["endpointId"],
            "contractContext": resolved_contract_context,
            "testCase": prepared_scenario["testCasePayload"],
            "currentStep": current_step,
            "outputContextPlan": output_context_plan,
            "availableContext": {
                key: dict(value) for key, value in available_context.items()
            },
            "priorStepSummary": list(prior_step_summary),
        }

    @staticmethod
    def _build_test_case_payload(test_case_idea: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "title": test_case_idea["title"],
            "category": test_case_idea["category"],
            "mode": test_case_idea["mode"],
            "sourceRefs": test_case_idea["sourceRefs"],
        }
        if test_case_idea.get("setupReason") is not None:
            payload["setupReason"] = test_case_idea["setupReason"]
        return payload

    @staticmethod
    def _build_current_step_payload(
            *,
            step: dict[str, Any],
            step_index: int,
    ) -> dict[str, Any]:
        return {
            "endpointId": step["endpointId"],
            "stepRole": step["stepRole"],
            "stepName": f"{step['stepRole']}_{step_index + 1}_{step['endpointId']}",
            "consumesContext": step.get("consumesContext") or [],
        }

    @staticmethod
    def _build_output_context_plan(
            *,
            step: dict[str, Any],
            remaining_steps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        future_consumes: set[str] = set()
        for next_step in remaining_steps:
            future_consumes.update(next_step.get("consumesContext") or [])

        plan: list[dict[str, Any]] = []
        for context_key in step.get("producesContext") or []:
            plan.append(
                {
                    "contextKey": context_key,
                    "requiredForNextSteps": context_key in future_consumes,
                }
            )
        return plan

    @staticmethod
    def _validate_step_graph(steps: list[dict[str, Any]]) -> None:
        produced_so_far: set[str] = set()
        produced_once: set[str] = set()

        for index, step in enumerate(steps):
            consumes = [str(x) for x in (step.get("consumesContext") or [])]
            produces = [str(x) for x in (step.get("producesContext") or [])]

            for context_key in consumes:
                if context_key not in produced_so_far:
                    raise ValueError(
                        f"Step {index} consumes context before it is produced: {context_key}"
                    )

            for context_key in produces:
                if context_key in produced_once:
                    raise ValueError(
                        f"Context key is produced more than once across scenario steps: {context_key}"
                    )
                produced_once.add(context_key)
                produced_so_far.add(context_key)

    @classmethod
    def _compact_repeated_steps(
            cls,
            steps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        i = 0

        while i < len(steps):
            current = steps[i]

            if str(current.get("stepRole")) == "target":
                result.append(
                    {
                        "kind": "single",
                        "times": 1,
                        "step": current,
                        "startIndex": i,
                        "endIndex": i,
                    }
                )
                i += 1
                continue

            current_signature = cls._step_signature(current)

            j = i + 1
            # todo this is an interesting idea, but how to provide proper context to llm?
            # while j < len(steps):
            #     next_step = steps[j]
            #     if str(next_step.get("stepRole")) == "target":
            #         break
            #     if cls._step_signature(next_step) != current_signature:
            #         break
            #     j += 1

            times = j - i
            result.append(
                {
                    "kind": "repeat" if times > 1 else "single",
                    "times": times,
                    "step": current,
                    "startIndex": i,
                    "endIndex": j - 1,
                }
            )
            i = j

        return result

    @staticmethod
    def _step_signature(step: dict[str, Any]) -> str:
        return json.dumps(step, ensure_ascii=False, sort_keys=True)

    def _build_contract_context_for_step(
            self,
            *,
            step: dict[str, Any],
            contract_for_step: dict[str, Any],
    ) -> dict[str, Any]:
        expected_status_code = step["stepStatusCode"]
        return {
            "method": contract_for_step.get("method"),
            "path": contract_for_step.get("path"),
            "pathParameters": self._extract_parameters_by_location(
                contract_for_step=contract_for_step,
                location="path",
            ),
            "queryParameters": self._extract_parameters_by_location(
                contract_for_step=contract_for_step,
                location="query",
            ),
            "requestBody": self._extract_request_body_schema(contract_for_step),
            "expectedResponseBody": self._extract_response_body_schema(
                contract_for_step=contract_for_step,
                status_code=expected_status_code,
            ),
            "expectedStatusCode": expected_status_code,
        }

    @staticmethod
    def _extract_parameters_by_location(
            *,
            contract_for_step: dict[str, Any],
            location: str,
    ) -> list[dict[str, Any]]:
        parameters = contract_for_step.get(f"{location}Params") or []
        result: list[dict[str, Any]] = []

        for parameter in parameters:
            if not isinstance(parameter, dict):
                continue

            result.append(
                {
                    "name": parameter.get("name"),
                    "required": bool(parameter.get("required")),
                    "schema": parameter.get("schema") or {},
                    "description": parameter.get("description"),
                }
            )

        return result

    @staticmethod
    def _extract_request_body_schema(
            contract_for_step: dict[str, Any],
    ) -> dict[str, Any]:
        request_body = contract_for_step.get("requestBody") or {}
        content = request_body.get("content") or {}
        app_json = content.get("application/json") or {}
        schema = app_json.get("schema") or {}

        if isinstance(schema, dict):
            return schema
        return {}

    @staticmethod
    def _extract_response_body_schema(
            *,
            contract_for_step: dict[str, Any],
            status_code: int | None,
    ) -> dict[str, Any]:
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
