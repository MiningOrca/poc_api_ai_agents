from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class FailureClassification:
    # application_bug | test_issue | contract_mismatch | environment_issue | inconclusive
    kind: str
    # high | medium | low
    confidence: str

    @staticmethod
    def from_dict(data: dict) -> FailureClassification:
        return FailureClassification(
            kind=data["kind"],
            confidence=data["confidence"],
        )


@dataclass
class ValidationAssessment:
    isSufficient: bool
    missingChecks: List[str]

    @staticmethod
    def from_dict(data: dict) -> ValidationAssessment:
        return ValidationAssessment(
            isSufficient=data["isSufficient"],
            missingChecks=data.get("missingChecks", []),
        )


@dataclass
class ReviewVerdict:
    scenarioId: str
    verdict: str  # pass | fail | inconclusive
    summary: str
    failureClassification: FailureClassification
    rootCauseHypotheses: List[str]
    validationAssessment: ValidationAssessment
    testDesignIssues: List[str]
    recommendedActions: List[str]
    evidence: List[str]

    @staticmethod
    def from_dict(data: dict) -> ReviewVerdict:
        return ReviewVerdict(
            scenarioId=data.get("scenarioId", ""),
            verdict=data["verdict"],
            summary=data["summary"],
            failureClassification=FailureClassification.from_dict(data["failureClassification"]),
            rootCauseHypotheses=data.get("rootCauseHypotheses", []),
            validationAssessment=ValidationAssessment.from_dict(data["validationAssessment"]),
            testDesignIssues=data.get("testDesignIssues", []),
            recommendedActions=data.get("recommendedActions", []),
            evidence=data.get("evidence", []),
        )
