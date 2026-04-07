"""Binding resolver.

Two responsibilities:
1. Extract a value from a response body using a JSONPath expression of the form
   ``$.field`` or ``$.field.nested`` (simple dot-navigation only; no wildcards
   or array indices — consistent with what Gate D admits).
2. Apply ``{{contextKey}}`` template substitution to pathParams / queryParams /
   body dicts before a step is sent.

Failures are represented as explicit exceptions so callers can record them in
the step result rather than silently producing wrong data.
"""
from __future__ import annotations

import re
from typing import Any

_TEMPLATE_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_SENTINEL = object()  # marks "key not found" without confusing None values


class BindingError(Exception):
    """Raised when a required binding cannot be resolved."""


# ---------------------------------------------------------------------------
# JSONPath extraction  ($.a.b.c only — no arrays, no wildcards)
# ---------------------------------------------------------------------------

def extract_value(data: Any, jsonpath: str) -> Any:
    """Extract a value from *data* using a ``$.field[.field…]`` path.

    Returns the extracted value (including ``None`` if the field is present
    but null).  Raises :class:`BindingError` if the path cannot be traversed.
    """
    if not jsonpath.startswith("$."):
        raise BindingError(f"Invalid JSONPath '{jsonpath}': must start with '$.'")

    segments = jsonpath[2:].split(".")
    current = data
    traversed = "$"
    for segment in segments:
        if not segment:
            raise BindingError(f"Invalid JSONPath '{jsonpath}': empty segment")
        if not isinstance(current, dict):
            raise BindingError(
                f"Cannot navigate '{traversed}.{segment}': "
                f"expected object, got {type(current).__name__}"
            )
        if segment not in current:
            raise BindingError(
                f"Path '{jsonpath}' not found: key '{segment}' missing at '{traversed}'"
            )
        current = current[segment]
        traversed = f"{traversed}.{segment}"
    return current


def value_exists(data: Any, jsonpath: str) -> bool:
    """Return True if *jsonpath* can be traversed in *data* without error."""
    try:
        extract_value(data, jsonpath)
        return True
    except BindingError:
        return False


# ---------------------------------------------------------------------------
# Template substitution  ({{key}} → context[key])
# ---------------------------------------------------------------------------

def _resolve_value(value: Any, context: dict) -> Any:
    """Recursively substitute ``{{key}}`` references in *value* using *context*.

    - If *value* is exactly ``{{key}}`` (whole string), return the raw context
      value so non-string types (int, bool, …) are preserved.
    - If *value* is a string containing ``{{key}}`` among other characters,
      stringify the context value and splice it in.
    - Dicts and lists are resolved recursively.
    - Other scalar types are returned unchanged.
    """
    if isinstance(value, str):
        keys = _TEMPLATE_RE.findall(value)
        if not keys:
            return value
        # Whole-string reference → preserve native type
        if value == f"{{{{{keys[0]}}}}}":
            key = keys[0]
            if key not in context:
                raise BindingError(
                    f"Context key '{{{{ {key} }}}}' referenced but not present in context; "
                    "check that the producing step ran successfully before this step"
                )
            return context[key]
        # Partial substitution → stringify
        def _replace(match: re.Match) -> str:
            key = match.group(1)
            if key not in context:
                raise BindingError(
                    f"Context key '{{{{ {key} }}}}' referenced but not present in context"
                )
            return str(context[key])
        return _TEMPLATE_RE.sub(_replace, value)

    if isinstance(value, dict):
        return {k: _resolve_value(v, context) for k, v in value.items()}

    if isinstance(value, list):
        return [_resolve_value(item, context) for item in value]

    return value


def resolve_step_fields(
    path_params: dict,
    query_params: dict,
    body: dict,
    context: dict,
) -> tuple[dict, dict, dict]:
    """Resolve all ``{{key}}`` references in a step's transport fields.

    Returns ``(resolved_path_params, resolved_query_params, resolved_body)``.
    Raises :class:`BindingError` if any referenced context key is absent.
    """
    return (
        _resolve_value(path_params, context),
        _resolve_value(query_params, context),
        _resolve_value(body, context),
    )


def apply_path_params(path_template: str, path_params: dict) -> str:
    """Substitute ``{param}`` placeholders in a URL path template.

    Uses single-brace OpenAPI-style ``{param}`` syntax (distinct from the
    double-brace context binding syntax).
    """
    result = path_template
    for key, value in path_params.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


def resolve_assertions(assertions: list, context: dict) -> list:
    """Resolve ``{{key}}`` references in assertion ``expected`` values.

    Returns a new list of assertion dicts with ``expected`` substituted.
    Assertions without an ``expected`` field (e.g. ``exists``/``not_exists``)
    are returned unchanged.  Raises :class:`BindingError` if a referenced key
    is absent from *context*.
    """
    result = []
    for assertion in assertions:
        if "expected" in assertion and assertion["expected"] is not None:
            resolved = _resolve_value(assertion["expected"], context)
            result.append({**assertion, "expected": resolved})
        else:
            result.append(assertion)
    return result


def update_context(context: dict, produce_bindings: list, response_body: Any) -> dict:
    """Extract values from *response_body* per *produce_bindings* and return an
    updated copy of *context*.

    Raises :class:`BindingError` if a source path cannot be resolved.
    """
    updated = dict(context)
    for binding in produce_bindings:
        context_key: str = binding["contextKey"]
        source_path: str = binding["sourcePath"]
        value = extract_value(response_body, source_path)
        updated[context_key] = value
    return updated
