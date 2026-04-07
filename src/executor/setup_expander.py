"""Setup fixture expansion for execution plans.

Supports the ``setupRef`` pattern in execution plans: a scenario with
``"isSetupFixture": true`` defines shared setup steps; other scenarios
reference it via ``"setupRef": "<scenarioId>"`` and keep only their own
(typically the target) steps.

The expander returns a list of fully-expanded, executable scenarios —
fixture scenarios are stripped, and referenced setup steps are prepended
with correct step indices.

The stored plan stays compact; expansion happens at execution time and
inside gate-D validation.
"""
from __future__ import annotations

import copy
from typing import Any


def expand_setup_refs(data: Any) -> list[dict]:
    """Expand ``setupRef`` in all non-fixture scenarios and return them.

    *data* may be a list of scenario dicts or a single scenario dict.
    Fixture scenarios (``isSetupFixture: true``) are removed from the
    returned list — they are only used as step templates.
    """
    scenarios: list[dict] = data if isinstance(data, list) else [data]

    # Build lookup: scenarioId → deep-copied step list
    fixture_lookup: dict[str, list[dict]] = {
        sc["scenarioId"]: copy.deepcopy(sc.get("steps", []))
        for sc in scenarios
        if isinstance(sc, dict) and sc.get("isSetupFixture")
    }

    return [
        _expand_scenario(sc, fixture_lookup)
        for sc in scenarios
        if isinstance(sc, dict) and not sc.get("isSetupFixture")
    ]


def _expand_scenario(scenario: dict, fixture_lookup: dict[str, list[dict]]) -> dict:
    """Return *scenario* with fixture setup steps prepended if ``setupRef`` is set.

    Own steps are renumbered by adding ``len(setup_steps)`` to each index.
    """
    ref = scenario.get("setupRef")
    if not ref:
        return scenario

    setup_steps: list[dict] = copy.deepcopy(fixture_lookup.get(ref, []))
    if not setup_steps:
        return scenario

    offset = len(setup_steps)
    own_steps = [
        {**step, "index": step["index"] + offset} if "index" in step else step
        for step in scenario.get("steps", [])
    ]

    return {**scenario, "steps": setup_steps + own_steps}
