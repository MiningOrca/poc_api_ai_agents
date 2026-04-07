from __future__ import annotations

import json
import re
from typing import Any

from agent.llm.client.llm_client import LlmClient, LlmRequest
from agent.llm.prompt_util import add_section
from agent.llm.step_designer.step_designer_model import LlmStepExecutionDraft


class LlmStepDesigner:
    """
    Second LLM role in the pipeline.

    Input:
    - current step descriptor
    - target test case summary
    - endpoint contract fragment
    - available context keys
    - output context plan
    - optional prior step summary

    Output:
    - schema-validated LlmStepExecutionDraft for exactly one step

    This layer answers:
    - how to fill path/query/body for this step
    - which context values to consume
    - which response fields to produce into context
    - which additional response field assertions make sense for this step

    It does NOT produce:
    - scenario orchestration
    - status code selection
    - repeated execution logic
    - step arrays
    - deterministic required-field checks
    - new business rules
    """

    def __init__(
            self,
            llm_client: LlmClient,
            model: str,
            *,
            temperature: float = 0.2,
            top_p: float = 0.2,
            max_output_tokens: int = 2500,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._temperature = temperature
        self._top_p = top_p
        self._max_output_tokens = max_output_tokens

    async def generate_step_execution_draft(
            self,
            *,
            endpoint_id: str,
            test_case: dict[str, Any],
            current_step: dict[str, Any],
            contractContext: dict[str, Any],
            available_context: dict[str, Any] | None = None,
            output_context_plan: list[dict[str, Any]] | None = None,
            prior_step_summary: list[str] | None = None,
            remaining_context: list[str] | None = None,

    ) -> LlmStepExecutionDraft:
        request = LlmRequest(
            model=self._model,
            system_prompt=self._build_system_prompt(),
            user_prompt=self._build_user_prompt(
                endpoint_id=endpoint_id,
                test_case=test_case,
                current_step=current_step,
                contract=contractContext,
                available_context=available_context or {},
                output_context_plan=output_context_plan or [],
                prior_step_summary=prior_step_summary or [],
                remaining_context=remaining_context
            ),
            temperature=self._temperature,
            top_p=self._top_p,
            max_output_tokens=self._max_output_tokens,
            json_schema=LlmStepExecutionDraft.model_json_schema(),
        )
        print(
            f"[generate_step_execution_draft] "
            f"endpoint={endpoint_id} | "
            f"test={test_case['title']} | "
            f"step={current_step['stepName']} | "
        )
        response = await self._llm_client.generate(request)
        raw_json = self._extract_json_payload(response.text)
        draft = LlmStepExecutionDraft.model_validate_json(raw_json)

        self._post_validate_draft(
            endpoint_id=endpoint_id,
            draft=draft,
            current_step=current_step,
            contract=contractContext,
            available_context=available_context or {},
            output_context_plan=output_context_plan or [],
        )
        return draft

    def _build_system_prompt(self) -> str:
        return """
    You are Step Execution Draft Generator for API test automation.

    Generate exactly one execution draft for one HTTP step.
    Return valid JSON only.
    Do not wrap JSON in markdown.

    Return exactly these top-level fields:
    - stepSummary
    - pathParams
    - queryParams
    - body
    - fieldAssertions
    - produceBinding

    Use only data explicitly provided in the user prompt.

    Hard rules:
    - Do not invent endpoints, methods, paths, request fields, response fields, status codes, business rules, or context keys.
    - Use only request fields present in the provided request contract.
    - Use only response fields present in the provided expected response contract.
    - Do not generate consumeBindings.
    - Do not generate extra top-level fields.
    - Keep stepSummary short and specific to this step.

    Context rules:
    - Available context keys are input values that may be consumed by this step.
    - Output context plan contains output keys that must be produced by this step.
    - Use "$${contextKey}" only for keys listed in Available context keys.
    - Do not use an Output context plan key as an input placeholder unless that key is also listed in Available context keys.
    - If an output context key must be produced and no input value exists for it, generate a valid request value and map it in produceBinding.

    Body rules:
    - For GET requests, body must be null.
    - For POST, PUT, and PATCH requests:
      - if a request body contract is provided, body must not be null
      - body must include all required request fields
      - body must not be an empty object when required request fields exist
    - If no request body contract is provided, body must be null.
    - Do not move request data into fieldAssertions when it belongs in the request body.
    - A response assertion does not satisfy a missing request field.
    
    Value rules:
    - First infer which request field or fields are being tested from the test case title and current step summary.
    - A tested field is a field whose validity, invalidity, boundary, equality, format, existence, uniqueness, or limit behavior is the subject of the case.
    - Tested fields must use concrete non-random values that directly realize the intended condition.
    - Do not use random placeholders for tested fields.
    - Use named random placeholders only for supportive fields whose exact value is not important for the tested condition.
    - Do not use unnamed random placeholders such as "$${random_email}" or "$${random_str}".
    - Reuse the exact same placeholder name when the same generated value must appear in multiple places.
    - Use different placeholder names when different generated values are needed.

    Allowed random placeholder types:
    - random_str
    - random_email
    - random_int
    - random_decimal

    Random placeholder format:
    - "$${random_<type>_<name>}"

    fieldAssertions rules:
    - Generate only useful exact assertions with operator "equals".
    - Do not generate assertions with any other operator.
    - Generate a fieldAssertion only if:
      - the asserted response field is explicitly present in the expected response contract, and
      - the expected value is explicitly grounded in the prompt or is a direct echo of request data.
    - The presence of a response field in the expected response contract does not by itself justify generating an assertion for that field.
    - If a response field clearly echoes a request value, you may assert it with "equals".
    - Do not invent exact literals for response fields such as status, type, result, state, message, or code.
    - Never invent generic error fields such as "$.error", "$.message", "$.code", or similar.
    - If the expected response contract does not define a stable exact response field for this step, return fieldAssertions as [].
    - For error responses without a documented exact response field, fieldAssertions must be [].
    - fieldAssertions.path must use JSONPath starting with "$.", for example "$.email".

    produceBinding rules:
    - Generate produceBinding only for keys listed in Output context plan.
    - Each produceBinding entry must map one contextKey to one response field path.
    - Use simple JSONPath starting with "$.".
    
    Interpretation priority rules:
        - When generating request values, use this priority order:
          1. Test case title
          2. Current step summary
          3. Explicit request contract constraints
          4. Available context values
          5. Random placeholders for supportive fields only
        - If a higher-priority source implies a concrete invalid, boundary, or special-condition value, lower-priority rules must not weaken it.
        - If the title or step summary implies a specific failure or boundary condition, the request must encode that condition directly.
    
    Before producing the final JSON, silently verify:
    - Which request field is under test?
    - Does the generated value for that field directly realize the condition described in the title and step summary?
    - Did any random placeholder get used for the tested field? If yes, replace it with a concrete value.
    - Would this request still test the intended condition if executed as written?
    """.strip()

    def _build_user_prompt(
            self,
            *,
            endpoint_id: str,
            test_case: dict[str, Any],
            current_step: dict[str, Any],
            contract: dict[str, Any],
            available_context: dict[str, Any],
            output_context_plan: list[dict[str, Any]],
            prior_step_summary: list[str], remaining_context: list[str]
    ) -> str:
        consumes_context = current_step['consumesContext']

        parts: list[str] = [
            f'Generate one step execution draft for endpointId="{endpoint_id}".'
        ]

        add_section(parts, "Test case summary:", {
            "title": test_case.get("title"),
            "category": test_case.get("category"),
        })

        add_section(parts, "Current step:", self._build_prompt_current_step(current_step))
        add_section(parts, "Request method:", contract["method"])
        add_section(parts, "Request path:", contract["path"])

        if consumes_context:
            add_section(parts, "Consumed context:", consumes_context)
        if contract.get("requestBody"):
            add_section(parts, "Request body contract:", contract["requestBody"])

        if contract.get("pathParameters"):
            add_section(parts, "Path parameters contract:", contract["pathParameters"])

        if contract.get("queryParameters"):
            add_section(parts, "Query parameters contract:", contract["queryParameters"])

        add_section(parts, "Expected response body contract:", contract.get("expectedResponseBody"))

        add_section(parts, "Remaining scenario context:", remaining_context)
        add_section(
            parts,
            "Available context keys:",
            sorted(available_context.keys()) or [],
        )

        if output_context_plan:
            add_section(
                parts,
                "Output context plan:",
                output_context_plan,
            )

        if prior_step_summary:
            add_section(
                parts,
                "Prior step summaries:",
                prior_step_summary,
            )

        parts.extend([
            "",
            "Important reminders:",
            '- Use "$${contextKey}" only for available context keys.',
            "- Put required request fields into body when a request body is required.",
            "- Do not move request fields into fieldAssertions.",
            "- stepSummary must state the action and the key concrete parameters of this step. Include important values such as user identifiers, amount, currency, limit, offset, or exact boundary value when relevant.",
            "- If a non-context value is needed and the exact literal is not important, prefer an allowed named random placeholder.",
            "- Setup steps must not already trigger the tested failure condition unless the test case explicitly requires setup failure.",
            "- If isLastSetupBeforeTarget is true, prepare the state as close as needed to the boundary but do not cross it.",
            '- If no stable exact response field is available, return "fieldAssertions": [].',
        ])

        if "deposit" in str(contract.get("path", "")):
            parts.append(
                '- For deposit-like requests: if body contains "amount" and no exact amount is required by context or test summary or Test case summary , use a fixed safe amount 1000.00.'
            )

        if consumes_context:
            parts.append(
                "Consumed context enforcement: every consumed context key must be used at least once in pathParams, queryParams, or body unless the request contract makes that impossible."
            )

        return "\n".join(self._normalize_section_value(x) for x in parts).strip()

    @staticmethod
    def _build_prompt_current_step(current_step: dict[str, Any]) -> dict[str, Any]:
        # todo         "stepGoal": current_step.get("goal") ?
        return {
            "endpointId": current_step["endpointId"],
            "stepRole": current_step["stepRole"],
            "stepName": current_step["stepName"],
            "consumesContext": current_step.get("consumesContext") or [],
        }

    _CONTEXT_PLACEHOLDER_RE = re.compile(r"^\$\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
    _RESPONSE_ASSERTION_RE = re.compile(
        r"^\$\.([A-Za-z_][A-Za-z0-9_]*)(?:\[[0-9]+\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+\])?)*$"
    )

    def _post_validate_draft(
            self,
            *,
            endpoint_id: str,
            draft: LlmStepExecutionDraft,
            current_step: dict[str, Any],
            contract: dict[str, Any],
            available_context: dict[str, Any],
            output_context_plan: list[dict[str, Any]],
    ) -> None:
        _ = output_context_plan  # compatibility only

        method = str(contract.get("method", "")).upper()

        allowed_path_fields = set(
            self._extract_parameter_names(
                contract.get("pathParams") or contract.get("pathParameters")
            )
        )
        allowed_query_fields = set(
            self._extract_parameter_names(
                contract.get("queryParams") or contract.get("queryParameters")
            )
        )
        allowed_body_fields = set(self._extract_request_body_field_names(contract))

        expected_status_code = (
                current_step.get("expectedStatusCode")
                or current_step.get("statusCode")
                or contract.get("expectedStatusCode")
        )

        allowed_response_fields = set(
            self._extract_response_field_names(
                contract,
                status_code=expected_status_code,
            )
        )

        if method == "GET" and draft.body:
            raise ValueError(f"{endpoint_id}: GET step must not contain body")

        extra_path = set(draft.pathParams.keys()) - allowed_path_fields
        if extra_path:
            raise ValueError(
                f"{endpoint_id}: pathParams contains undocumented fields: {sorted(extra_path)}"
            )

        extra_query = set(draft.queryParams.keys()) - allowed_query_fields
        if extra_query:
            raise ValueError(
                f"{endpoint_id}: queryParams contains undocumented fields: {sorted(extra_query)}"
            )
        if draft.body:
            extra_body = set(draft.body.keys()) - allowed_body_fields
            if extra_body:
                raise ValueError(
                    f"{endpoint_id}: body contains undocumented fields: {sorted(extra_body)}"
                )

        context_references = []
        context_references.extend(
            self._collect_context_placeholders(draft.pathParams, section="pathParams")
        )
        context_references.extend(
            self._collect_context_placeholders(draft.queryParams, section="queryParams")
        )
        context_references.extend(
            self._collect_context_placeholders(draft.body, section="body")
        )

        for index, assertion in enumerate(draft.fieldAssertions):
            root_field = self._parse_response_assertion_root(assertion.path)
            if allowed_response_fields and root_field not in allowed_response_fields:
                raise ValueError(
                    f"{endpoint_id}: fieldAssertions references undocumented response field: {assertion.path}"
                )

            context_references.extend(
                self._collect_context_placeholders(
                    assertion.expected,
                    section=f"fieldAssertions[{index}].expected",
                )
            )

        available_context_keys = set(available_context.keys())

        for location, context_key in context_references:
            if context_key.startswith("random"): continue
            if context_key not in available_context_keys:
                raise ValueError(
                    f"{endpoint_id}: value at '{location}' references unavailable context key: {context_key}. "
                    f"Available keys: {sorted(available_context_keys)}"
                )
        self._check_no_duplicate_assertions(endpoint_id, draft)

    @staticmethod
    def _extract_parameter_names(raw: Any) -> list[str]:
        if isinstance(raw, list):
            names: list[str] = []
            for item in raw:
                if isinstance(item, dict) and "name" in item:
                    names.append(str(item["name"]))
            return names

        if isinstance(raw, dict):
            properties = raw.get("properties")
            if isinstance(properties, dict):
                return [str(key) for key in properties.keys()]
            return [str(key) for key in raw.keys()]

        return []

    @staticmethod
    def _extract_request_body_field_names(contract: dict[str, Any]) -> list[str]:
        candidates = [
            contract.get("requestSchema"),
            (contract.get("schemas") or {}).get("request"),
            contract.get("requestBody"),  # current compact format
            ((((contract.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema")),
        ]

        for schema in candidates:
            if isinstance(schema, dict):
                properties = schema.get("properties")
                if isinstance(properties, dict):
                    return [str(name) for name in properties.keys()]

        return []

    @staticmethod
    def _extract_response_field_names(
            contract: dict[str, Any],
            *,
            status_code: Any | None = None,
    ) -> list[str]:
        field_names: set[str] = set()

        candidates: list[dict[str, Any]] = []

        direct_candidates = [
            contract.get("expectedResponseBody"),  # current compact format
            contract.get("responseSchema"),
            (contract.get("schemas") or {}).get("response"),
        ]

        for candidate in direct_candidates:
            if isinstance(candidate, dict):
                candidates.append(candidate)

        responses = contract.get("responses") or {}
        if isinstance(responses, dict):
            if status_code is not None and str(status_code) in responses:
                response_items = [responses[str(status_code)]]
            else:
                response_items = list(responses.values())

            for response in response_items:
                if not isinstance(response, dict):
                    continue

                content = response.get("content") or {}
                app_json = content.get("application/json") or {}
                schema = app_json.get("schema")
                if isinstance(schema, dict):
                    candidates.append(schema)

        for schema in candidates:
            properties = schema.get("properties")
            if isinstance(properties, dict):
                field_names.update(str(name) for name in properties.keys())

        return sorted(field_names)

    def _parse_response_assertion_root(self, value: str) -> str:
        match = self._RESPONSE_ASSERTION_RE.fullmatch(value.strip())
        if not match:
            raise ValueError(f"Invalid assertion path: {value}")
        return match.group(1)

    def _collect_context_placeholders(
            self,
            value: Any,
            *,
            section: str,
    ) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []

        if isinstance(value, dict):
            for key, item in value.items():
                child_section = f"{section}.{key}"
                refs.extend(self._collect_context_placeholders(item, section=child_section))
            return refs

        if isinstance(value, list):
            for index, item in enumerate(value):
                child_section = f"{section}[{index}]"
                refs.extend(self._collect_context_placeholders(item, section=child_section))
            return refs

        if isinstance(value, str):
            stripped = value.strip()
            match = self._CONTEXT_PLACEHOLDER_RE.fullmatch(stripped)
            if match:
                refs.append((section, match.group(1)))
                return refs

            if "$${" in stripped:
                raise ValueError(
                    f"Invalid context placeholder format at '{section}': {value}"
                )

        return refs

    @staticmethod
    def _check_no_duplicate_assertions(
            endpoint_id: str,
            draft: LlmStepExecutionDraft,
    ) -> None:
        seen: set[tuple[str, str, str]] = set()

        for item in draft.fieldAssertions:
            key = (
                item.path,
                item.operator.value,
                item.expected,
            )
            if key in seen:
                raise ValueError(
                    f"{endpoint_id}: duplicate field assertion detected: {key}"
                )
            seen.add(key)

    @staticmethod
    def _normalize_section_value(value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    @staticmethod
    def _extract_json_payload(text: str) -> str:
        stripped = text.strip()

        if stripped.startswith("```"):
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
            if match:
                return match.group(1).strip()

        return stripped
