"""Gate D — Binding validity.

Checks the produce/consume binding chain inside each scenario of
``execution_plan.json``:

1. ``produceBindings[*].sourcePath`` must be a valid JSONPath expression
   (must start with ``$.`` followed by at least one identifier segment).
2. Every ``{{contextKey}}`` template reference in ``pathParams``, ``queryParams``,
   or ``body`` of a step must have been produced by an earlier step in the
   same scenario.
3. No step may consume a key that is never produced anywhere in the scenario.

Applied after Stage 3 (execution_plan.json).

Entry point
-----------
validate_execution_plan(data)  -- raises GateFailure on rejection
"""
from __future__ import annotations

import re
from typing import Any, List, Set

from src.validators.errors import GateFailure, ValidationError

GATE = "Gate D — Binding validity"

# Matches {{key}} template references in string values
_TEMPLATE_KEY_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
# Valid JSONPath source: must start with $. and contain only word chars / dots / brackets
_VALID_SOURCE_PATH_RE = re.compile(r"^\$\.[A-Za-z_][A-Za-z0-9_.]*$")

# Keys pre-seeded by the executor before any step runs; always available.
_EXECUTOR_SEEDED_KEYS: Set[str] = {"runId"}


def _err(artifact: str, field: str, reason: str) -> ValidationError:
    return ValidationError(gate=GATE, artifact=artifact, field=field, reason=reason)


def _collect_template_keys(value: Any) -> Set[str]:
    """Recursively find all {{key}} references in a nested dict / list / str."""
    if isinstance(value, str):
        return set(_TEMPLATE_KEY_RE.findall(value))
    if isinstance(value, dict):
        keys: Set[str] = set()
        for v in value.values():
            keys |= _collect_template_keys(v)
        return keys
    if isinstance(value, list):
        keys = set()
        for v in value:
            keys |= _collect_template_keys(v)
        return keys
    return set()


def validate_execution_plan(data: Any) -> None:
    """Validate binding validity in output/execution_plan.json (Gate D)."""
    errors: List[ValidationError] = []
    artifact = "execution_plan.json"

    scenarios = data if isinstance(data, list) else [data]

    for idx, scenario in enumerate(scenarios):
        prefix = f"[{idx}]"
        if not isinstance(scenario, dict):
            continue

        # Keys produced by steps seen so far (in order).
        # Pre-populate with executor-seeded keys so they are always valid to consume.
        produced: Set[str] = set(_EXECUTOR_SEEDED_KEYS)

        for si, step in enumerate(scenario.get("steps", [])):
            if not isinstance(step, dict):
                continue
            step_prefix = f"{prefix}.steps[{si}]"

            # --- Validate produceBindings source paths (before adding to produced set) ---
            for bi, binding in enumerate(step.get("produceBindings", [])):
                if not isinstance(binding, dict):
                    continue
                source_path = binding.get("sourcePath", "")
                if not _VALID_SOURCE_PATH_RE.match(source_path):
                    errors.append(_err(
                        artifact,
                        f"{step_prefix}.produceBindings[{bi}].sourcePath",
                        f"'{source_path}' is not a valid JSONPath source; "
                        "must match $.identifier[.identifier...] (no array indices or wildcards)",
                    ))

            # --- Check consumed keys against keys produced by *earlier* steps ---
            for field_name in ("pathParams", "queryParams", "body"):
                field_val = step.get(field_name)
                if not field_val:
                    continue
                consumed = _collect_template_keys(field_val)
                for key in consumed:
                    if key not in produced:
                        errors.append(_err(
                            artifact,
                            f"{step_prefix}.{field_name}",
                            f"context key '{{{{ {key} }}}}' is consumed but has not been "
                            "produced by any earlier step in this scenario",
                        ))

            # --- Register keys produced by *this* step (available to later steps) ---
            for binding in step.get("produceBindings", []):
                if isinstance(binding, dict):
                    context_key = binding.get("contextKey", "")
                    if context_key:
                        produced.add(context_key)

    if errors:
        raise GateFailure(errors)
