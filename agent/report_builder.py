from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.llm.result_reviewver.result_review_model import ExecutionAuditItem
from agent.llm.result_reviewver.result_review_prefilter import AuditFilterDecision
from agent.runner.test_runner import StepRunResult, AttemptRunResult, ScenarioRunResult


class ReportAssertionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    operator: str
    expected: Any | None = None
    actual: Any | None = None
    passed: bool


class StepDetailReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    method: str | None = None
    url: str | None = None
    request_body: Any | None = None
    expected_status_code: int | None = None
    actual_status_code: int | None = None
    response_json: Any | None = None
    response_text: str | None = None
    error: str | None = None
    assertions: list[ReportAssertionItem] = Field(default_factory=list)


class StepExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    step_summary: str
    step_role: str | None = None
    passed: bool
    detail: StepDetailReport


class ScenarioAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: str
    classification: str
    confidence: float
    summary: str
    reasons: list[str] = Field(default_factory=list)
    missingAssertions: list[str] = Field(default_factory=list)
    suspectedRootCause: str | None = None
    recommendedAction: str
    recommendedPriority: str
    followUpChecks: list[str] = Field(default_factory=list)


class ScenarioExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    endpoint_id: str
    passed: bool
    started_at_utc: str
    caseId: str | None = None
    scenarioId: str | None = None
    id: str | None = None
    finished_at_utc: str | None = None
    steps: list[StepExecutionReport] = Field(default_factory=list)

    audit_status: str
    audit_reasons: list[str] = Field(default_factory=list)
    audit: ScenarioAuditReport | None = None


class ScenarioExecutionReportBuilder:
    def build(
        self,
        scenario: ScenarioRunResult,
        filter_decision: AuditFilterDecision,
        audit_result: ExecutionAuditItem | None = None,
    ) -> ScenarioExecutionReport:
        return ScenarioExecutionReport(
            title=scenario.title,
            endpoint_id=scenario.endpoint_id,
            passed=scenario.passed,
            started_at_utc=scenario.started_at_utc,
            caseId=scenario.caseId,
            scenarioId=scenario.scenarioId,
            id=scenario.id,
            finished_at_utc=scenario.finished_at_utc,
            steps=[self._build_step(step) for step in scenario.steps],
            audit_status=filter_decision.route.value,
            audit_reasons=list(filter_decision.reasons),
            audit=self._build_audit(audit_result),
        )

    def _build_step(self, step: StepRunResult) -> StepExecutionReport:
        attempt = self._get_primary_attempt(step)

        return StepExecutionReport(
            title=step.title,
            step_summary=step.step_summary,
            step_role=step.step_role,
            passed=step.passed,
            detail=self._build_detail(step, attempt),
        )

    def _build_detail(
        self,
        step: StepRunResult,
        attempt: AttemptRunResult | None,
    ) -> StepDetailReport:
        if attempt is None:
            return StepDetailReport(
                passed=step.passed,
                error=step.error,
                assertions=[],
            )

        return StepDetailReport(
            passed=attempt.passed,
            method=attempt.method,
            url=attempt.url,
            request_body=attempt.request_body,
            expected_status_code=attempt.expected_status_code,
            actual_status_code=attempt.actual_status_code,
            response_json=attempt.response_json,
            response_text=attempt.response_text,
            error=attempt.error or step.error,
            assertions=self._build_assertions(attempt),
        )

    def _build_assertions(
        self,
        attempt: AttemptRunResult,
    ) -> list[ReportAssertionItem]:
        items: list[ReportAssertionItem] = []

        for path in attempt.required_fields_checked:
            items.append(
                ReportAssertionItem(
                    path=path,
                    operator="exists",
                    expected=True,
                    actual=True,
                    passed=True,
                )
            )

        for raw in attempt.field_assertions_checked:
            items.append(self._build_field_assertion(raw))

        return items

    def _build_field_assertion(self, raw: dict[str, Any]) -> ReportAssertionItem:
        return ReportAssertionItem(
            path=str(raw.get("path", "")),
            operator=str(raw.get("operator", "unknown")),
            expected=raw.get("expected"),
            actual=raw.get("actual"),
            passed=bool(raw.get("passed", False)),
        )

    def _build_audit(
        self,
        audit_result: ExecutionAuditItem | None,
    ) -> ScenarioAuditReport | None:
        if audit_result is None:
            return None

        verdict = getattr(audit_result.verdict, "value", audit_result.verdict)
        classification = getattr(
            audit_result.classification,
            "value",
            audit_result.classification,
        )
        recommended_action = getattr(
            audit_result.recommendedAction,
            "value",
            audit_result.recommendedAction,
        )
        recommended_priority = getattr(
            audit_result.recommendedPriority,
            "value",
            audit_result.recommendedPriority,
        )

        return ScenarioAuditReport(
            verdict=str(verdict),
            classification=str(classification),
            confidence=float(audit_result.confidence),
            summary=audit_result.summary,
            reasons=list(audit_result.reasons),
            missingAssertions=list(audit_result.missingAssertions),
            suspectedRootCause=audit_result.suspectedRootCause,
            recommendedAction=str(recommended_action),
            recommendedPriority=str(recommended_priority),
            followUpChecks=list(audit_result.followUpChecks),
        )

    @staticmethod
    def _get_primary_attempt(step: StepRunResult) -> AttemptRunResult | None:
        if not step.attempts:
            return None
        return step.attempts[0]