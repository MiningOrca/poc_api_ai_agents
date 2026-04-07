from __future__ import annotations

from typing import Any, Callable

from agent.llm.step_designer.helpers.compiled_scenario_builder import CompiledScenarioBuilder
from agent.llm.step_designer.helpers.step_draft_builder import LlmStepDraftBuilder
from agent.llm.step_designer.llm_step_designer import LlmStepDesigner


class LlmScenarioBuilder:
    """
    Orchestrates scenario generation.

    Responsibilities:
    - keep old entrypoint: build_endpoint_scenarios(...)
    - for each test case:
      1) prepare LLM step input
      2) call LLM
      3) pass result to compiled scenario builder
    """

    def __init__(
            self,
            step_designer: LlmStepDesigner,
            compiled_scenario_builder_factory: Callable[[], CompiledScenarioBuilder] | None = None,
    ) -> None:
        self.step_designer = step_designer
        self.step_request_builder = LlmStepDraftBuilder()
        self.compiled_scenario_builder_factory = (
                compiled_scenario_builder_factory or CompiledScenarioBuilder
        )

    async def build_endpoint_scenarios(
            self,
            *,
            endpoint_id: str,
            test_cases: dict[str, Any],
            contract_fragments: dict[str, dict[str, Any] | None],
    ) -> dict[str, Any]:
        scenarios: list[dict[str, Any]] = []

        for test_case_idea in test_cases["ideas"]:
            scenario = await self._build_single_scenario(
                test_case_idea=test_case_idea,
                contract_fragments=contract_fragments,
            )
            scenario["parentTestCaseId"] = test_case_idea["id"]
            scenario["id"] = test_case_idea["id"].replace("TC", "TS")
            scenarios.append(scenario)

        return {
            "endpointId": endpoint_id,
            "scenarios": scenarios,
        }

    async def _build_single_scenario(
            self,
            *,
            test_case_idea: dict[str, Any],
            contract_fragments: dict[str, dict[str, Any] | None],
    ) -> dict[str, Any]:
        prepared_scenario = self.step_request_builder.prepare_scenario(
            test_case_idea=test_case_idea,
            contract_fragments=contract_fragments,
        )

        compiled_scenario_builder = self.compiled_scenario_builder_factory()
        compiled_scenario_builder.start_scenario(test_case_idea=test_case_idea)
        nodes = prepared_scenario["nodes"]
        for node_index, node in enumerate(nodes):
            step_request = self.step_request_builder.build_step_request(
                prepared_scenario=prepared_scenario,
                node=node,
                node_index=node_index,
                available_context=compiled_scenario_builder.get_available_context(),
                prior_step_summary=compiled_scenario_builder.get_recent_step_summaries(
                    limit=3
                ),
            )
            remaining_nodes = nodes[node_index + 1:]

            remaining_context = {
                "remainingSetupStepCount": len([
                    n for n in remaining_nodes
                    if (n.get("step") or {}).get("stepRole") == "setup"
                ]),
                "isLastSetupBeforeTarget": (
                        (node.get("step") or {}).get("stepRole") == "setup"
                        and len(remaining_nodes) == 1
                ),
            }

            draft = await self.step_designer.generate_step_execution_draft(
                endpoint_id=step_request["endpointId"],
                test_case=step_request["testCase"],
                current_step=step_request["currentStep"],
                contract_context=step_request["contractContext"],
                available_context=step_request["availableContext"],
                output_context_plan=step_request["outputContextPlan"],
                prior_step_summary=step_request["priorStepSummary"],
                remaining_context=remaining_context
            )

            compiled_scenario_builder.accept_step_draft(
                node=node,
                step_request=step_request,
                draft_json=draft.model_dump(mode="json"),
                step_summary=getattr(draft, "stepSummary", None),
            )

        return compiled_scenario_builder.build_result()
