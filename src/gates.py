"""Pipeline gate runner.

Exposes one function per pipeline stage boundary that runs the required
deterministic gates in order.  Each function:

1. Runs the required gates (A, B, C, D, E as per workflow.md).
2. Returns the normalized artifact on success.
3. Raises :class:`GateFailure` on the first gate that rejects the artifact.

Usage
-----
from src.gates import run_stage1_gates, run_stage2_gates, run_stage3_gates, run_stage5_gates
from src.contract.loader import ContractLoader

contract = ContractLoader.from_file("agent/input/open_api.json")

# After Stage 1 (rules.json)
normalized_rules = run_stage1_gates(rules_data)

# After Stage 2 (test_cases.json)
normalized_tc = run_stage2_gates(test_cases_data, contract)

# After Stage 3 (execution_plan.json)
normalized_plan = run_stage3_gates(execution_plan_data, contract)

# After Stage 5 (review_report.json)
normalized_report = run_stage5_gates(review_report_data)
"""
from __future__ import annotations

from typing import Any

from src.contract.loader import ContractLoader
from src.executor.setup_expander import expand_setup_refs
from src.normalizers.gate_e import (
    normalize_execution_plan,
    normalize_review_report,
    normalize_rules,
    normalize_test_cases,
)
from src.validators import gate_a, gate_b, gate_c, gate_d


def run_stage1_gates(data: Any) -> Any:
    """Gates A + E after Stage 1 (rules.json).

    Raises GateFailure if the artifact is invalid.
    Returns the normalized artifact.
    """
    gate_a.validate_rules(data)
    return normalize_rules(data)


def run_stage2_gates(data: Any, contract: ContractLoader) -> Any:
    """Gates A + B + E after Stage 2 (test_cases.json).

    Raises GateFailure if the artifact is invalid.
    Returns the normalized artifact.
    """
    gate_a.validate_test_cases(data)
    gate_b.validate_test_cases(data, contract)
    return normalize_test_cases(data)


def run_stage3_gates(data: Any, contract: ContractLoader) -> Any:
    """Gates A + B + C + D + E after Stage 3 (execution_plan.json).

    Raises GateFailure if the artifact is invalid.
    Returns the normalized artifact (compact form, setupRef not expanded).

    Gate D validates binding chains against the expanded form so that
    ``setupRef`` scenarios are checked with their full step sequence.
    """
    gate_a.validate_execution_plan(data)
    gate_b.validate_execution_plan(data, contract)
    gate_c.validate_execution_plan(data)
    gate_d.validate_execution_plan(expand_setup_refs(data))
    return normalize_execution_plan(data)


def run_stage5_gates(data: Any) -> Any:
    """Gates A + E after Stage 5 (review_report.json).

    Raises GateFailure if the artifact is invalid.
    Returns the normalized artifact.
    """
    gate_a.validate_review_report(data)
    return normalize_review_report(data)
