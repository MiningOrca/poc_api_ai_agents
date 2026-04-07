from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class Assertion:
    path: str
    operator: str
    expected: Any

    @staticmethod
    def from_dict(data: dict) -> Assertion:
        return Assertion(
            path=data["path"],
            operator=data["operator"],
            expected=data.get("expected"),
        )


@dataclass
class ProduceBinding:
    contextKey: str
    sourcePath: str

    @staticmethod
    def from_dict(data: dict) -> ProduceBinding:
        return ProduceBinding(
            contextKey=data["contextKey"],
            sourcePath=data["sourcePath"],
        )


@dataclass
class Step:
    index: int
    stepRole: str  # setup | target
    title: str
    endpointId: str
    method: str
    path: str
    pathParams: Dict[str, Any]
    queryParams: Dict[str, Any]
    body: Dict[str, Any]
    assertions: List[Assertion]
    produceBindings: List[ProduceBinding]

    @staticmethod
    def from_dict(data: dict) -> Step:
        return Step(
            index=data["index"],
            stepRole=data["stepRole"],
            title=data.get("title", ""),
            endpointId=data["endpointId"],
            method=data["method"],
            path=data["path"],
            pathParams=data.get("pathParams", {}),
            queryParams=data.get("queryParams", {}),
            body=data.get("body", {}),
            assertions=[Assertion.from_dict(a) for a in data.get("assertions", [])],
            produceBindings=[ProduceBinding.from_dict(b) for b in data.get("produceBindings", [])],
        )


@dataclass
class Scenario:
    scenarioId: str
    endpointId: str
    title: str
    category: str
    sourceRefs: List[str]
    expectedStatusCode: int
    steps: List[Step]

    @staticmethod
    def from_dict(data: dict) -> Scenario:
        return Scenario(
            scenarioId=data["scenarioId"],
            endpointId=data["endpointId"],
            title=data["title"],
            category=data["category"],
            sourceRefs=data["sourceRefs"],
            expectedStatusCode=data["expectedStatusCode"],
            steps=[Step.from_dict(s) for s in data.get("steps", [])],
        )
