from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import TypeAdapter

from agent.llm.result_reviewver.llm_result_review import LlmExecutionAuditor
from agent.llm.step_designer.llm_step_designer import LlmStepDesigner
from agent.llm.step_designer.scenario_builder import LlmScenarioBuilder
from agent.report_builder import ScenarioExecutionReportBuilder
from agent.runner.test_runner import ScenarioRunner
from agent.llm.result_reviewver.result_review_prefilter import *

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.extractors.build_spec_sections import SpecSectionsBuilder
from agent.extractors.build_rules_views import RulesViewsBuilder
from agent.extractors.openapi_contract_builder import OpenApiContractBuilder

from agent.llm.client.open_router_client import OpenRouterClient
from agent.llm.test_designer.llm_test_designer import LlmTestDesigner

AGENT_DIR = REPO_ROOT / "agent"
INPUT_DIR = AGENT_DIR / "input"
OUTPUT_DIR = AGENT_DIR / "output"

CONTEXT_PATH = INPUT_DIR / "conext.md"
OPENAPI_PATH = INPUT_DIR / "open_api.json"

SPEC_SECTIONS_PATH = INPUT_DIR / "spec_sections.json"
RULES_VIEWS_PATH = INPUT_DIR / "rules_views.json"
CONTRACT_PATH = INPUT_DIR / "contract.json"

DEFAULT_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4.6")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY",
                               "insertKey")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_source_inputs() -> None:
    missing: list[str] = []

    if not CONTEXT_PATH.exists():
        missing.append(str(CONTEXT_PATH))
    if not OPENAPI_PATH.exists():
        missing.append(str(OPENAPI_PATH))

    if missing:
        raise FileNotFoundError(
            "Required source inputs are missing:\n- " + "\n- ".join(missing)
        )


def generate_input_artifacts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ensure_source_inputs()

    spec_builder = SpecSectionsBuilder()
    spec_sections = spec_builder.build(
        input_path=str(CONTEXT_PATH),
        output_path=str(SPEC_SECTIONS_PATH),
    )

    rules_builder = RulesViewsBuilder(
        input_path=str(SPEC_SECTIONS_PATH),
        output_path=str(RULES_VIEWS_PATH),
    )
    rules_views_path = Path(rules_builder.build_and_save())
    rules_views = load_json(rules_views_path)

    contract_builder = OpenApiContractBuilder(
        input_path=str(OPENAPI_PATH),
        output_path=str(CONTRACT_PATH),
    )
    contract_path = Path(contract_builder.build_and_save())
    contract = load_json(contract_path)

    return spec_sections, rules_views, contract


def build_contract_index(contract: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    endpoints = contract["endpoints"]
    if not isinstance(endpoints, list):
        raise ValueError("contract.json must contain 'endpoints' list")

    index: dict[tuple[str, str], dict[str, Any]] = {}

    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue

        method = str(endpoint["method"]).upper().strip()
        path = str(endpoint["path"]).strip()
        key = (method, path)

        if key in index:
            raise ValueError(f"Duplicate contract endpoint: {key}")

        index[key] = endpoint

    return index


def build_endpoint_rules_view(spec_endpoint: dict[str, Any]) -> str:
    views = spec_endpoint.get("views")
    if isinstance(views, dict):
        value = views.get("endpoint_rules")
        if isinstance(value, str) and value.strip():
            return value.strip()

    endpoint_id = str(spec_endpoint["endpoint_id"]).strip()
    title = str(spec_endpoint.get("title", "")).strip()
    method = str(spec_endpoint["method"]).upper().strip()
    path = str(spec_endpoint["path"]).strip()

    endpoint_rules = spec_endpoint.get("endpoint_rules", [])
    parameters = spec_endpoint.get("parameters", [])
    error_responses = spec_endpoint.get("error_responses", [])

    lines: list[str] = [
        f"Endpoint ID: {endpoint_id}",
        f"Endpoint: {method} {path}",
    ]

    if title:
        lines.append(f"Title: {title}")

    if parameters:
        lines.append("")
        lines.append("Parameters:")
        for item in parameters:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            description = str(item.get("description", "")).strip()
            if name and description:
                lines.append(f"- {name}: {description}")
            elif name:
                lines.append(f"- {name}")

    if endpoint_rules:
        lines.append("")
        lines.append("Rules:")
        for rule in endpoint_rules:
            lines.append(f"- {str(rule).strip()}")

    if error_responses:
        lines.append("")
        lines.append("Error responses:")
        for item in error_responses:
            if not isinstance(item, dict):
                continue
            status_code = item.get("status_code")
            description = str(item.get("description", "")).strip()

            if status_code is not None and description:
                lines.append(f"- {status_code}: {description}")
            elif status_code is not None:
                lines.append(f"- {status_code}")

    return "\n".join(lines).strip()


async def run() -> None:
    if not OPENROUTER_API_KEY:
        raise EnvironmentError("OPENROUTER_API_KEY is not set")

    spec_sections, rules_views, contract = generate_input_artifacts()

    general_rules_view = rules_views["general_rules_view"]["items"]
    spec_endpoints = spec_sections["endpoints"]
    available_operations = json.dumps(
        [
            {
                "endpointId": item["endpoint_id"],
                "title": item["title"],
                "method": item["method"],
                "path": item["path"],
                "success_status_code": item["success_status_code"]
            }
            for item in spec_endpoints
        ],
        ensure_ascii=False,
        indent=2,
    )
    contract_index = build_contract_index(contract)

    llm_client = OpenRouterClient(api_key=OPENROUTER_API_KEY)
    test_designer = LlmTestDesigner(
        llm_client=llm_client,
        model=DEFAULT_MODEL,
        temperature=0.0,
        top_p=0.2,
        max_output_tokens=4000,
    )
    step_designer = LlmStepDesigner(
        llm_client=llm_client,
        model="google/gemma-4-26b-a4b-it",
        temperature=0.1,
        top_p=1,
        max_output_tokens=4000,
    )
    result_audit = LlmExecutionAuditor(
        llm_client=llm_client,
        model="google/gemma-4-26b-a4b-it",
        temperature=0.25,
        top_p=1,
        max_output_tokens=2000,
    )

    contract_fragments = {
        str(spec_endpoint["endpoint_id"]).strip(): contract_index.get(
            (str(spec_endpoint["method"]).upper().strip(), urlsplit(str(spec_endpoint["path"]).strip()).path)
        )
        for spec_endpoint in spec_endpoints
    }

    scenario_builder = LlmScenarioBuilder(step_designer=step_designer)

    for spec_endpoint in spec_endpoints:
        endpoint_id = str(spec_endpoint["endpoint_id"]).strip()
        endpoint_rules_view = next(
            item for item in rules_views["endpoint_rules_views"]
            if item["endpoint_id"] == endpoint_id
        )
        method = str(spec_endpoint["method"]).upper().strip()
        test_case_path = OUTPUT_DIR / "test_cases" / f"test_cases_{endpoint_id}.json"
        scenario_path = OUTPUT_DIR / "scenarios" / f"scenarios_{endpoint_id}.json"
        execution_summary_path = OUTPUT_DIR / "run_results" / f"{endpoint_id}_run_results_summary.json"
        report_path = OUTPUT_DIR / f"{endpoint_id}_run_report.json"
        path = str(spec_endpoint["path"]).strip()
        contract_fragment = contract_fragments[endpoint_id]
        if contract_fragment is None:
            raise ValueError(
                f"Contract fragment not found for endpoint_id={endpoint_id}, method={method}, path={path}"
            )

        print(f"[pipeline] designing test cases for {endpoint_id}")

        test_case_bundle = await test_designer.generate_endpoint_design_cases(
            endpoint_id=endpoint_id,
            general_rules_view=general_rules_view,
            endpoint_rules_view=endpoint_rules_view,
            available_operations=available_operations,
            quotas=None,
        )

        save_json(test_case_path, test_case_bundle.model_dump(mode="json"))

        test_cases = load_json(test_case_path)

        print(f"[pipeline] compiling scenarios for {endpoint_id}")

        scenario_bundle = await scenario_builder.build_endpoint_scenarios(
            endpoint_id=endpoint_id,
            test_cases=test_cases,
            contract_fragments=contract_fragments,
        )

        save_json(scenario_path, scenario_bundle)
        print("[pipeline] compiling scenarios done")
        ScenarioRunner().run_tests(scenario_path, summary_path=execution_summary_path)
        print(f"[pipeline] review execution result for {endpoint_id}")
        run_result = TypeAdapter(list[ScenarioRunResult]).validate_python(load_json(execution_summary_path))
        run_report = []
        for scenario in run_result:
            filter_decision = ScenarioAuditFilter().decide(scenario)
            audit_result = None
            if filter_decision.route == AuditRoute.SEND_TO_LLM:
                audit_result = await result_audit.audit_scenario(scenario)
            scenario_report = ScenarioExecutionReportBuilder().build(scenario=scenario, audit_result=audit_result,
                                                                     filter_decision=filter_decision)
            run_report.append(scenario_report)
        save_json(report_path, [item.model_dump(mode="json") for item in run_report])

    print("[pipeline] done")


if __name__ == "__main__":
    asyncio.run(run())
