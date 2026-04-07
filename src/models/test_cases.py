from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TestCaseStep:
    endpointId: str
    summary: str

    @staticmethod
    def from_dict(data: dict) -> TestCaseStep:
        return TestCaseStep(
            endpointId=data["endpointId"],
            summary=data.get("summary", ""),
        )


@dataclass
class TestCase:
    title: str
    category: str  # positive | negative | boundary
    sourceRefs: List[str]
    steps: List[TestCaseStep]
    summary: Optional[str]
    expectedStatusCode: Optional[int]
    expectedOutcome: Optional[str]
    mode: str  # single | chain

    @staticmethod
    def from_dict(data: dict) -> TestCase:
        return TestCase(
            title=data["title"],
            category=data["category"],
            sourceRefs=data["sourceRefs"],
            steps=[TestCaseStep.from_dict(s) for s in data.get("steps", [])],
            summary=data.get("summary"),
            expectedStatusCode=data.get("expectedStatusCode"),
            expectedOutcome=data.get("expectedOutcome"),
            mode=data.get("mode", "single"),
        )


@dataclass
class EndpointTestCases:
    endpointId: str
    cases: List[TestCase]

    @staticmethod
    def from_dict(data: dict) -> EndpointTestCases:
        return EndpointTestCases(
            endpointId=data["endpointId"],
            cases=[TestCase.from_dict(c) for c in data.get("cases", [])],
        )
