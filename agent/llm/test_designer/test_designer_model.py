from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

_CONTEXT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class TestCategory(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"


class ExecutionMode(StrEnum):
    SINGLE = "single"
    CHAIN = "chain"


class ChainStepRole(StrEnum):
    SETUP = "setup"
    TARGET = "target"


class PlannedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpointId: str
    stepRole: ChainStepRole
    stepStatusCode: int
    producesContext: list[str] = Field(default_factory=list)
    consumesContext: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_step(self) -> "PlannedStep":
        if not self.endpointId.strip():
            raise ValueError("endpointId must not be empty")

        if self.stepStatusCode < 100 or self.stepStatusCode > 599:
            raise ValueError("stepStatusCode must be a valid HTTP status code")

        if len(set(self.producesContext)) != len(self.producesContext):
            raise ValueError("producesContext must be unique")
        if len(set(self.consumesContext)) != len(self.consumesContext):
            raise ValueError("consumesContext must be unique")

        for item in self.producesContext:
            if not item.strip():
                raise ValueError("producesContext must not contain empty values")
            if not _CONTEXT_RE.fullmatch(item):
                raise ValueError(f"invalid producesContext key: {item}")

        for item in self.consumesContext:
            if not item.strip():
                raise ValueError("consumesContext must not contain empty values")
            if not _CONTEXT_RE.fullmatch(item):
                raise ValueError(f"invalid consumesContext key: {item}")

        return self


class TestIdea(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    endpointId: str
    title: str
    category: TestCategory
    mode: ExecutionMode
    sourceRefs: list[str] = Field(min_length=1)
    setupReason: str | None = None
    steps: list[PlannedStep] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_idea(self) -> "TestIdea":
        if not self.endpointId.strip():
            raise ValueError("endpointId must not be empty")

        if not self.title.strip():
            raise ValueError("title must not be empty")

        if any(not ref.strip() for ref in self.sourceRefs):
            raise ValueError("sourceRefs must not contain empty values")

        target_steps = [
            step for step in self.steps
            if step.stepRole == ChainStepRole.TARGET
        ]
        if len(target_steps) != 1:
            raise ValueError("steps must contain exactly one target step")

        target_index = next(
            i for i, step in enumerate(self.steps)
            if step.stepRole == ChainStepRole.TARGET
        )
        target_step = self.steps[target_index]

        if target_step.endpointId != self.endpointId:
            raise ValueError("target step endpointId must match the main endpointId")

        if target_index != len(self.steps) - 1:
            raise ValueError("target step must be the last step")

        setup_steps = [
            step for step in self.steps
            if step.stepRole == ChainStepRole.SETUP
        ]

        non_target_before_last = [
            step for step in self.steps[:-1]
            if step.stepRole != ChainStepRole.SETUP
        ]
        if non_target_before_last:
            raise ValueError("all non-last steps must have stepRole='setup'")

        if self.mode == ExecutionMode.SINGLE:
            if len(self.steps) != 1:
                raise ValueError("single mode must contain exactly one target step")
            if setup_steps:
                raise ValueError("single mode must not contain setup steps")
            if self.setupReason is not None and not self.setupReason.strip():
                raise ValueError("setupReason must not be blank")

        if self.mode == ExecutionMode.CHAIN:
            if not setup_steps:
                raise ValueError("chain mode must contain at least one setup step")
            if len(self.steps) < 2:
                raise ValueError("chain mode must contain setup step(s) plus target step")
            if self.setupReason is None or not self.setupReason.strip():
                raise ValueError("setupReason is required when mode='chain'")

        return self

    @property
    def target_step(self) -> PlannedStep:
        return next(step for step in self.steps if step.stepRole == ChainStepRole.TARGET)

    @property
    def target_status_code(self) -> int:
        return self.target_step.stepStatusCode


class TestIdeaBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpointId: str
    ideas: list[TestIdea] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bundle(self) -> "TestIdeaBundle":
        if not self.endpointId.strip():
            raise ValueError("endpointId must not be empty")

        for index, idea in enumerate(self.ideas):
            if idea.endpointId != self.endpointId:
                raise ValueError(
                    f"ideas[{index}].endpointId mismatch: "
                    f"expected {self.endpointId}, got {idea.endpointId}"
                )

        return self