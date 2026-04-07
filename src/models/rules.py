from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Rule:
    id: str
    text: str
    sourceRefs: List[str]

    @staticmethod
    def from_dict(data: dict) -> Rule:
        return Rule(
            id=data["id"],
            text=data["text"],
            sourceRefs=data["sourceRefs"],
        )


@dataclass
class RulesArtifact:
    generalRules: List[Rule]
    rulesByEndpoint: Dict[str, List[Rule]]

    @staticmethod
    def from_dict(data: dict) -> RulesArtifact:
        return RulesArtifact(
            generalRules=[Rule.from_dict(r) for r in data.get("generalRules", [])],
            rulesByEndpoint={
                k: [Rule.from_dict(r) for r in v]
                for k, v in data.get("rulesByEndpoint", {}).items()
            },
        )
