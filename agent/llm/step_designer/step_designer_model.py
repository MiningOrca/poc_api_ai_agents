from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_INJECT_TO_RE = re.compile(r"^\$\.(path|query|body)\.[A-Za-z_][A-Za-z0-9_]*$")
_RESPONSE_PATH_RE = re.compile(
    r"^\$\.response\.body\.[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+\])?)*$"
)


class AssertionOperator(StrEnum):
    EQUALS = "equals"
    # CONTAINS = "contains"
    # EXISTS = "exists"


class FieldAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    operator: AssertionOperator
    expected: Any


# class ConsumeBinding(BaseModel):
#     model_config = ConfigDict(extra="forbid")
#
#     contextKey: str
#     injectTo: str


class ProduceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contextKey: str
    sourcePath: str


class LlmStepExecutionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stepSummary: str = Field(min_length=1)
    pathParams: dict[str, Any] = Field(default_factory=dict)
    queryParams: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None
    fieldAssertions: list[FieldAssertion] = Field(default_factory=list)
    produceBinding: list[ProduceBinding] = Field(default_factory=list)