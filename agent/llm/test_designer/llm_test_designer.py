from __future__ import annotations

import re

from agent.llm.client.llm_client import LlmClient, LlmRequest
from agent.llm.prompt_util import add_section, extract_json_payload
from agent.llm.test_designer.test_designer_model import TestIdeaBundle


class LlmTestDesigner:
    """
    First LLM role in the pipeline.

    Input:
    - general_rules_view
    - endpoint_rules_view
    - endpoint_id
    - optional quotas

    Output:
    - human-readable, schema-validated design JSON

    This layer answers:
    - what should be tested
    - why it should be tested
    - whether it is single or chain
    - what state is needed
    - what outcome is expected in business terms

    It does NOT produce:
    - ids
    - executable step arrays
    - HTTP orchestration
    - method/path transport details
    """

    def __init__(
            self,
            llm_client: LlmClient,
            model: str,
            *,
            temperature: float = 0.1,
            top_p: float = 0.2,
            max_output_tokens: int = 4000,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._temperature = temperature
        self._top_p = top_p
        self._max_output_tokens = max_output_tokens

    async def generate_endpoint_design_cases(
            self,
            *,
            endpoint_id: str,
            general_rules_view: str,
            endpoint_rules_view: str,
            available_operations: str,
            quotas: dict[str, int] | None = None,
    ) -> TestIdeaBundle:
        request = LlmRequest(
            model=self._model,
            system_prompt=self._build_system_prompt(),
            user_prompt=self._build_user_prompt(
                endpoint_id=endpoint_id,
                general_rules=general_rules_view,
                endpoint_rules_view=endpoint_rules_view,
                available_operations=available_operations,
                quotas=quotas or {},
            ),
            temperature=self._temperature,
            top_p=self._top_p,
            max_output_tokens=self._max_output_tokens,
            json_schema=TestIdeaBundle.model_json_schema(),
        )

        response = await self._llm_client.generate(request)
        raw_json = extract_json_payload(response.text)
        bundle = TestIdeaBundle.model_validate_json(raw_json)
        # should be some retrie mechanism but not for poc
        self._post_validate_bundle(
            bundle=bundle,
            expected_endpoint_id=endpoint_id,
        )
        for index, test_idea in enumerate(bundle.ideas, start=1):
            test_idea.id = f"tc-{endpoint_id.replace('_', '-')}-{index}".upper()
        return bundle

    def _build_system_prompt(self) -> str:
        return """You are Test Designer for API QA automation.

    Generate concise, human-readable test ideas in valid JSON.

    Return design-level cases only.
    Do not generate ids.
    Do not generate executable request payloads, detailed setup steps, or full execution plans.
    Do not include method, path, or other transport-level HTTP details in titles.
    Do not invent unsupported fields, validations, status codes, business rules, endpoints, dependencies, or hidden assumptions.
    Use only facts explicitly present in the provided input.
    Prefer omission over speculation.
    Do not merge distinct variants into one case.
    Do not produce duplicate or near-duplicate cases.

    Each case must contain:
    - endpointId
    - title
    - category
    - mode
    - sourceRefs
    - steps

    Each case may contain:
    - setupReason

    Mode rules:
    - Use mode="single" when the target case does not require prior API-created state.
    - Use mode="chain" when prior API-created state is required before the target step.

    State selection rules:
    - Prefer documented sample data when it already satisfies the target preconditions.
    - Use chain mode only when the required target state cannot be obtained directly from the provided sample data.
    - Do not introduce setup steps when an equivalent single-case design is already supported by the documented initial state.
    - When chain mode is necessary, include all setup steps needed to establish the target preconditions, but do not include unrelated preparation.

    Step rules:
    - steps is a compact dependency hint, not an execution plan.
    - Each step must contain:
      - endpointId
      - stepRole
      - stepStatusCode
    - Each step may contain:
      - producesContext
      - consumesContext
    - stepRole must be either "setup" or "target".
    - Include exactly one target step.
    - The target step must be the last step.
    - The target step endpointId must match the case endpointId.
    - Use only endpointIds from the provided endpoint catalog.
    - Use only the minimum necessary number of setup steps needed to establish the required target preconditions.
    - producesContext and consumesContext must contain only short snake_case keys.
    - Do not include prose explanations, request bodies, assertions, or orchestration details inside steps.

    Single mode rules:
    - steps must contain exactly one step.
    - That step must be the target step.
    - Do not include setup steps.
    - setupReason should be null or omitted.

    Chain mode rules:
    - steps must contain at least one setup step before the target step.
    - setupReason is required.
    - setupReason must be short, specific, and grounded in the provided facts.

    Status code rules:
    - stepStatusCode is the expected outcome of that step.
    - The target step stepStatusCode must be explicitly supported by the provided facts for the target endpoint.
    - Setup step stepStatusCode values must also be explicitly supported by the provided facts for their respective endpoints.
    - Do not invent undocumented status codes for any step.

    Other field rules:
    - sourceRefs must be non-empty and relevant.
    - Titles must be short, concrete, and human-readable.
    - Titles must describe the business test idea, not transport details.

    Output rules:
    - Return JSON only.
    - Do not wrap JSON in markdown.
    - Keep the response compact.
    - Prefer a smaller complete response over a broader incomplete one.
    - Never return partial or cut-off JSON.
    """.strip()

    def _build_user_prompt(
            self,
            *,
            endpoint_id: str,
            general_rules: str,
            available_operations: str,
            endpoint_rules_view: dict,
            quotas: dict[str, int],
    ) -> str:
        parts: list[str] = [
            f'Generate test ideas for endpointId="{endpoint_id}".',
            f'Title: {endpoint_rules_view["title"]}',
            f'Method: {endpoint_rules_view["method"]}',
            f'Path: {endpoint_rules_view["path"]}',
        ]

        add_section(parts, "Parameters:", endpoint_rules_view.get("parameters") or None)
        add_section(parts, "Category quotas:", quotas or None)
        add_section(parts, "General rules:", general_rules)
        add_section(parts, "Endpoint rules:", endpoint_rules_view.get("endpoint_rules"))
        add_section(parts, "Error responses:", endpoint_rules_view.get("error_responses"))
        add_section(parts, "Success response code:", endpoint_rules_view.get("success_status_code"))
        add_section(parts, "Endpoint catalog:", available_operations)

        parts.extend([
            "",
            "Endpoint-specific notes:",
            "- This endpoint must be the target endpoint for every generated case.",
            "- Prefer this endpoint's own rules and documented responses over broader general rules.",
            "- Use general rules only when they clearly apply here.",
            "- When prior API-created state is required, include all necessary setup steps to reach the target preconditions.",
            "- Setup may involve other endpoints when they are needed to build valid prerequisite state for the target case.",
            "- Keep setup justified and relevant: include everything necessary, but nothing unrelated to the target case.",
            "- Do not return expectedStatusCode at the case level.",
            "- Represent expected outcomes only through steps[*].stepStatusCode.",
            "- The target case outcome is defined by the target step stepStatusCode.",
            "- For single-mode cases, the single target step carries the only expected status code for the case.",
            "- For chain cases, setup steps must each have their own stepStatusCode and the final target step must carry the final expected outcome.",
        ])

        return "\n".join(parts).strip()

    # HTTP verbs that should never appear as words in a test case title.
    _HTTP_METHODS: frozenset[str] = frozenset(
        {"get", "post", "put", "patch", "delete", "head", "options"}
    )

    def _normalize_title(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def _title_contains_http_method(self, title: str) -> bool:
        """Return True if the title contains any HTTP verb as a standalone word.

        Titles must describe business intent, not transport-level details.
        """
        padded = f" {title.lower()} "
        return any(f" {method} " in padded for method in self._HTTP_METHODS)

    def _title_contains_api_path(self, title: str) -> bool:
        """Return True if the title contains a raw API path segment.

        Titles must not expose internal URL structure.
        """
        return "/" in title

    def _post_validate_bundle(
            self,
            *,
            bundle: TestIdeaBundle,
            expected_endpoint_id: str,
    ) -> None:
        if bundle.endpointId != expected_endpoint_id:
            raise ValueError(
                f"endpointId mismatch: expected {expected_endpoint_id}, got {bundle.endpointId}"
            )

        seen_fingerprints: set[tuple[str, str]] = set()

        for index, idea in enumerate(bundle.ideas):

            if self._title_contains_http_method(idea.title):
                raise ValueError(f"ideas[{index}] contains HTTP method in title: {idea.title}")

            if self._title_contains_api_path(idea.title):
                raise ValueError(f"ideas[{index}] contains path in title: {idea.title}")

            fingerprint = (
                self._normalize_title(idea.title),
                idea.category.value,
            )

            if fingerprint in seen_fingerprints:
                raise ValueError(
                    f"Potential duplicate test idea detected at ideas[{index}]: {idea.title}"
                )

            seen_fingerprints.add(fingerprint)

