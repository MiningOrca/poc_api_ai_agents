from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class LlmRequest:
    system_prompt: str
    user_prompt: str
    model: str
    top_p: float = 0.2
    temperature: float = 0.0
    max_output_tokens: int | None = None
    json_schema: dict[str, Any] | None = None


@dataclass
class LlmUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class LlmResponse:
    text: str
    model: str
    usage: LlmUsage
    raw: dict[str, Any]


class LlmClient(Protocol):
    async def generate(self, request: LlmRequest) -> LlmResponse: ...