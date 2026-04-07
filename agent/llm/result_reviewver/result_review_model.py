from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AuditVerdict(StrEnum):
    VALID_PASS = "valid_pass"
    SUSPICIOUS_PASS = "suspicious_pass"
    VALID_FAIL = "valid_fail"
    INFRA_FAIL = "infra_fail"


class AuditClassification(StrEnum):
    WEAK_ASSERTIONS = "weak_assertions"
    COMPILER_BUG = "compiler_bug"
    SPEC_CONTRACT_MISMATCH = "spec_contract_mismatch"
    MOCK_INCONSISTENCY = "mock_inconsistency"
    COVERAGE_GAP = "coverage_gap"
    EXECUTION_OK = "execution_ok"
    BUSINESS_RULE_UNDERCHECKED = "business_rule_underchecked"
    SETUP_STATE_UNCERTAIN = "setup_state_uncertain"
    NON_DETERMINISTIC_BEHAVIOR = "non_deterministic_behavior"
    ASSERTION_MISMATCH = "assertion_mismatch"


class RecommendedAction(StrEnum):
    ACCEPT_RESULT = "accept_result"
    STRENGTHEN_ASSERTIONS = "strengthen_assertions"
    RECOMPILE_SCENARIO = "recompile_scenario"
    RERUN_SCENARIO = "rerun_scenario"
    REVIEW_MOCK = "review_mock"
    REVIEW_SPEC_MAPPING = "review_spec_mapping"
    ADD_COVERAGE = "add_coverage"
    ESCALATE_MANUAL_REVIEW = "escalate_manual_review"


class RecommendedPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExecutionAuditItem(BaseModel):
    """
    One LLM audit decision for one executed scenario.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: AuditVerdict
    classification: AuditClassification

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model confidence in the selected verdict/classification.",
    )

    summary: str = Field(
        min_length=1,
        description=(
            "A compact 2-3 sentence summary suitable for passing to another model. "
            "It should explain the verdict, the main weakness or strength of the result, "
            "and the practical implication."
        ),
    )

    reasons: list[str] = Field(
        default_factory=list,
        description=(
            "High-level reasons for the verdict/classification. "
            "These are judgment statements, not raw observations."
        ),
    )

    evidence: list[str] = Field(
        default_factory=list,
        description=(
            "Direct observations from the executed scenario that support the decision. "
            "These should be concrete facts from the input, such as checked fields, "
            "status codes, setup structure, or missing target assertions."
        ),
    )

    missingAssertions: list[str] = Field(
        default_factory=list,
        description=(
            "Assertions that are important for trustworthiness but are absent from the scenario result."
        ),
    )

    suspectedRootCause: str | None = Field(
        default=None,
        description=(
            "Most likely root cause when the result is suspicious or failed. "
            "Use null when there is no meaningful root cause to suggest."
        ),
    )

    recommendedAction: RecommendedAction
    recommendedPriority: RecommendedPriority

    followUpChecks: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete next checks or scenario improvements to confirm the finding "
            "or strengthen the scenario."
        ),
    )


class ExecutionAuditBundle(BaseModel):
    """
    Top-level schema to feed into response_format=json_schema.
    """

    model_config = ConfigDict(extra="forbid")

    audits: list[ExecutionAuditItem] = Field(default_factory=list)
