from __future__ import annotations

import asyncio
import json
import random
from json import JSONDecodeError

import httpx

from agent.llm.client.llm_client import LlmClient, LlmRequest, LlmResponse, LlmUsage


class OpenRouterResponseError(RuntimeError):
    pass


class OpenRouterClient(LlmClient):
    _RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        *,
        timeout_seconds: float = 90.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
        backoff_max_seconds: float = 8.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._backoff_max_seconds = backoff_max_seconds

    async def generate(self, request: LlmRequest) -> LlmResponse:
        body = self._build_request_body(request)
        attempts_total = self._max_retries + 1

        last_error: Exception | None = None

        for attempt in range(attempts_total):
            attempt_no = attempt + 1
            print(
                f"[OpenRouter] request started "
                f"attempt={attempt_no}/{attempts_total} model={request.model}"
            )

            try:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )

                if response.status_code in self._RETRYABLE_STATUS_CODES:
                    if attempt < self._max_retries:
                        delay = self._get_backoff_delay(attempt)
                        print(
                            f"[OpenRouter] retryable HTTP status "
                            f"status={response.status_code} "
                            f"attempt={attempt_no}/{attempts_total} "
                            f"retry_in={delay:.2f}s"
                        )
                        await asyncio.sleep(delay)
                        continue

                response.raise_for_status()

                try:
                    data = response.json()
                except JSONDecodeError as exc:
                    last_error = exc
                    preview = self._truncate_for_log(response.text)

                    if attempt < self._max_retries:
                        delay = self._get_backoff_delay(attempt)
                        print(
                            f"[OpenRouter] invalid HTTP JSON "
                            f"attempt={attempt_no}/{attempts_total} "
                            f"retry_in={delay:.2f}s "
                            f"body_preview={preview!r}"
                        )
                        await asyncio.sleep(delay)
                        continue

                    print(
                        f"[OpenRouter] invalid HTTP JSON on final attempt "
                        f"attempt={attempt_no}/{attempts_total} "
                        f"body_preview={preview!r}"
                    )
                    raise

                try:
                    result = self._parse_response(
                        data,
                        fallback_model=request.model,
                        expect_json=request.json_schema is not None,
                    )
                except OpenRouterResponseError as exc:
                    last_error = exc

                    if attempt < self._max_retries:
                        delay = self._get_backoff_delay(attempt)
                        print(
                            f"[OpenRouter] malformed payload/content "
                            f"attempt={attempt_no}/{attempts_total} "
                            f"retry_in={delay:.2f}s "
                            f"error={exc}"
                        )
                        await asyncio.sleep(delay)
                        continue

                    print(
                        f"[OpenRouter] malformed payload/content on final attempt "
                        f"attempt={attempt_no}/{attempts_total} "
                        f"error={exc}"
                    )
                    raise

                print(
                    f"[OpenRouter] request succeeded "
                    f"attempt={attempt_no}/{attempts_total} "
                    f"requested_model={request.model} "
                    f"actual_model={result.model} "
                    f"total_tokens={result.usage.total_tokens}"
                )
                return result

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc

                if attempt >= self._max_retries:
                    print(
                        f"[OpenRouter] transport error on final attempt "
                        f"attempt={attempt_no}/{attempts_total} "
                        f"model={request.model} "
                        f"error={exc!r}"
                    )
                    raise

                delay = self._get_backoff_delay(attempt)
                print(
                    f"[OpenRouter] transport error "
                    f"attempt={attempt_no}/{attempts_total} "
                    f"model={request.model} "
                    f"retry_in={delay:.2f}s "
                    f"error={exc!r}"
                )
                await asyncio.sleep(delay)

            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code

                if status_code in self._RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                    delay = self._get_backoff_delay(attempt)
                    print(
                        f"[OpenRouter] HTTP error eligible for retry "
                        f"status={status_code} "
                        f"attempt={attempt_no}/{attempts_total} "
                        f"retry_in={delay:.2f}s"
                    )
                    await asyncio.sleep(delay)
                    continue

                print(
                    f"[OpenRouter] non-retryable HTTP error "
                    f"status={status_code} "
                    f"attempt={attempt_no}/{attempts_total} "
                    f"model={request.model}"
                )
                raise

        if last_error is not None:
            raise last_error

        raise RuntimeError("OpenRouter request failed without a captured exception")

    def _build_request_body(self, request: LlmRequest) -> dict:
        body = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
        }

        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens

        if request.top_p is not None:
            body["top_p"] = request.top_p

        if request.json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": request.json_schema,
                },
            }
            body["provider"] = {
                "require_parameters": True
            }

        return body

    def _parse_response(
        self,
        data: dict,
        *,
        fallback_model: str,
        expect_json: bool,
    ) -> LlmResponse:
        try:
            choice = data["choices"][0]
            message = choice["message"]
            text = message["content"]
            usage = data.get("usage", {})
            model = data.get("model", fallback_model)
            finish_reason = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterResponseError(
                f"Malformed OpenRouter response payload: {exc!r}"
            ) from exc

        if finish_reason == "length":
            raise OpenRouterResponseError("Model output was truncated (finish_reason='length')")

        if not isinstance(text, str):
            raise OpenRouterResponseError(
                f"Expected message.content to be str, got {type(text).__name__}"
            )

        if expect_json:
            try:
                json.loads(text)
            except JSONDecodeError as exc:
                preview = self._truncate_for_log(text)
                raise OpenRouterResponseError(
                    f"Model returned invalid JSON: {exc.msg} "
                    f"at line {exc.lineno} column {exc.colno}; "
                    f"content_preview={preview!r}"
                ) from exc

        return LlmResponse(
            text=text,
            model=model,
            usage=LlmUsage(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            ),
            raw=data,
        )

    def _get_backoff_delay(self, attempt: int) -> float:
        base_delay = min(
            self._backoff_base_seconds * (2 ** attempt),
            self._backoff_max_seconds,
        )
        jitter = random.uniform(0, 0.3 * base_delay)
        return base_delay + jitter

    @staticmethod
    def _truncate_for_log(text: str, limit: int = 500) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit] + "..."