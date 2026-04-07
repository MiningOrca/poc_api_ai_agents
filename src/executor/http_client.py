"""HTTP request runner.

Wraps ``urllib.request`` (stdlib only, no third-party dependencies) to send a
single HTTP request and return a structured response.  JSON response bodies are
parsed automatically; non-JSON bodies are returned as raw strings.

Transport errors (connection refused, timeout, DNS failure) are captured in
``HttpResponse.error`` rather than propagated, so the caller can record them in
the step result and continue building the report.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HttpResponse:
    """Result of a single HTTP call."""
    status_code: int | None
    body: Any                  # parsed JSON object/array, plain str, or None
    raw_text: str              # raw response body text (empty string on network error)
    error: str | None          # transport or network error message, or None


def send_request(
    method: str,
    url: str,
    query_params: dict,
    body: dict,
    headers: dict | None = None,
) -> HttpResponse:
    """Send an HTTP request and return an :class:`HttpResponse`.

    Parameters
    ----------
    method:       HTTP verb in uppercase (``"GET"``, ``"POST"``, …)
    url:          Full URL including scheme and path (path params already substituted)
    query_params: Dict of query string parameters; appended to *url* if non-empty
    body:         Request body dict; serialised as JSON and sent when non-empty
    headers:      Additional request headers (merged with Content-Type when body present)
    """
    effective_headers: dict = dict(headers or {})

    if query_params:
        separator = "&" if "?" in url else "?"
        url = url + separator + urllib.parse.urlencode(query_params, doseq=True)

    data: bytes | None = None
    if body:
        data = json.dumps(body).encode("utf-8")
        effective_headers.setdefault("Content-Type", "application/json")

    effective_headers.setdefault("Accept", "application/json")

    request = urllib.request.Request(
        url,
        data=data,
        headers=effective_headers,
        method=method.upper(),
    )

    try:
        with urllib.request.urlopen(request) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return HttpResponse(
                status_code=resp.status,
                body=_parse_body(raw),
                raw_text=raw,
                error=None,
            )
    except urllib.error.HTTPError as exc:
        # HTTPError carries a real HTTP response with a non-2xx status
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            raw = ""
        return HttpResponse(
            status_code=exc.code,
            body=_parse_body(raw),
            raw_text=raw,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 — network / DNS / timeout errors
        return HttpResponse(
            status_code=None,
            body=None,
            raw_text="",
            error=f"{type(exc).__name__}: {exc}",
        )


def _parse_body(text: str) -> Any:
    """Attempt to parse *text* as JSON; return raw string on failure."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
