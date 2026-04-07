from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agent.runner.test_runner import StepRunResult, AttemptRunResult, ScenarioRunResult


class AuditRoute(StrEnum):
    SEND_TO_LLM = "send_to_llm"
    SKIP_CLEAN = "skip_clean"
    SKIP_INFRA = "skip_infra"


class AuditCategory(StrEnum):
    FAILED_SCENARIO = "failed_scenario"
    CHAIN_PASS = "chain_pass"
    WEAK_ASSERTIONS = "weak_assertions"
    CLEAN_PASS = "clean_pass"
    INFRA_FAILURE = "infra_failure"


class AuditPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class AuditFilterDecision:
    route: AuditRoute
    category: AuditCategory
    priority: AuditPriority
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)


class ScenarioAuditFilter:
    """
    Deterministic triage before LLM Run Auditor.

    Routing:
    - SKIP_INFRA: environment/mock/reset failure, not useful for LLM auditing
    - SEND_TO_LLM: failed scenario or suspicious pass
    - SKIP_CLEAN: clean deterministic pass
    """

    def decide(self, scenario: ScenarioRunResult) -> AuditFilterDecision:
        signals = self._collect_signals(scenario)

        infra_reasons = self._infra_reasons(scenario, signals)
        if infra_reasons:
            return AuditFilterDecision(
                route=AuditRoute.SKIP_INFRA,
                category=AuditCategory.INFRA_FAILURE,
                priority=AuditPriority.HIGH,
                reasons=infra_reasons,
                signals=signals,
            )

        fail_reasons = self._failure_reasons(scenario, signals)
        if fail_reasons:
            return AuditFilterDecision(
                route=AuditRoute.SEND_TO_LLM,
                category=AuditCategory.FAILED_SCENARIO,
                priority=AuditPriority.HIGH,
                reasons=fail_reasons,
                signals=signals,
            )

        suspicious_reasons = self._suspicious_pass_reasons(scenario, signals)
        if suspicious_reasons:
            category = (
                AuditCategory.CHAIN_PASS
                if signals["has_setup_steps"]
                else AuditCategory.WEAK_ASSERTIONS
            )
            priority = (
                AuditPriority.HIGH
                if "target_has_no_content_checks" in suspicious_reasons
                else AuditPriority.MEDIUM
            )
            return AuditFilterDecision(
                route=AuditRoute.SEND_TO_LLM,
                category=category,
                priority=priority,
                reasons=suspicious_reasons,
                signals=signals,
            )

        return AuditFilterDecision(
            route=AuditRoute.SKIP_CLEAN,
            category=AuditCategory.CLEAN_PASS,
            priority=AuditPriority.LOW,
            reasons=["clean_deterministic_pass"],
            signals=signals,
        )

    def _infra_reasons(
        self,
        scenario: ScenarioRunResult,
        signals: dict[str, Any],
    ) -> list[str]:
        reasons: list[str] = []

        if scenario.test_state_reset_attempted and not scenario.test_state_reset_passed:
            reasons.append("test_state_reset_failed")

        if signals["attempts_with_missing_status"] > 0:
            reasons.append("attempt_without_http_status")

        if signals["attempts_with_error_and_missing_status"] > 0:
            reasons.append("attempt_error_without_http_status")

        return reasons

    def _failure_reasons(
        self,
        scenario: ScenarioRunResult,
        signals: dict[str, Any],
    ) -> list[str]:
        reasons: list[str] = []

        if not scenario.passed:
            reasons.append("scenario_failed")

        if scenario.failed_step_index is not None:
            reasons.append("failed_step_index_present")

        if signals["failed_steps"] > 0:
            reasons.append("failed_step_present")

        if signals["failed_target_steps"] > 0:
            reasons.append("failed_target_step_present")

        if signals["attempts_with_status_mismatch"] > 0:
            reasons.append("http_status_mismatch")

        if signals["attempts_with_error_and_status"] > 0:
            reasons.append("attempt_error_with_http_status")

        if scenario.error is not None:
            reasons.append("scenario_error_present")

        return reasons

    def _suspicious_pass_reasons(
        self,
        scenario: ScenarioRunResult,
        signals: dict[str, Any],
    ) -> list[str]:
        if not scenario.passed:
            return []

        reasons: list[str] = []

        if signals["has_setup_steps"]:
            reasons.append("has_setup_steps")

        # Смотрим именно на target steps, а не на setup
        if signals["target_steps_count"] == 0:
            reasons.append("no_target_step_detected")
            return reasons

        if signals["target_steps_with_any_content_checks"] == 0:
            reasons.append("target_has_no_content_checks")

        elif signals["target_steps_with_field_assertions"] == 0:
            reasons.append("target_has_no_field_assertions")

        if (
            signals["target_steps_with_bindings"] > 0
            and signals["target_steps_with_any_content_checks"] == 0
        ):
            reasons.append("bindings_produced_without_target_validation")

        return reasons

    def _collect_signals(self, scenario: ScenarioRunResult) -> dict[str, Any]:
        total_steps = len(scenario.steps)
        setup_steps_count = 0
        target_steps_count = 0
        failed_steps = 0
        failed_target_steps = 0

        total_attempts = 0
        attempts_with_missing_status = 0
        attempts_with_error_and_missing_status = 0
        attempts_with_error_and_status = 0
        attempts_with_status_mismatch = 0

        target_steps_with_any_content_checks = 0
        target_steps_with_field_assertions = 0
        target_steps_with_bindings = 0

        for step in scenario.steps:
            if step.step_role == "setup":
                setup_steps_count += 1
            elif step.step_role == "target":
                target_steps_count += 1

            if not step.passed:
                failed_steps += 1
                if step.step_role == "target":
                    failed_target_steps += 1

            attempt = self._get_primary_attempt(step)
            if attempt is None:
                continue

            total_attempts += 1

            if attempt.actual_status_code is None:
                attempts_with_missing_status += 1

            if attempt.error is not None and attempt.actual_status_code is None:
                attempts_with_error_and_missing_status += 1

            if attempt.error is not None and attempt.actual_status_code is not None:
                attempts_with_error_and_status += 1

            if (
                attempt.actual_status_code is not None
                and attempt.actual_status_code != attempt.expected_status_code
            ):
                attempts_with_status_mismatch += 1

            if step.step_role == "target":
                has_content_checks = bool(
                    attempt.required_fields_checked or attempt.field_assertions_checked
                )
                has_field_assertions = bool(attempt.field_assertions_checked)
                has_bindings = bool(attempt.produced_bindings)

                if has_content_checks:
                    target_steps_with_any_content_checks += 1

                if has_field_assertions:
                    target_steps_with_field_assertions += 1

                if has_bindings:
                    target_steps_with_bindings += 1

        return {
            "total_steps": total_steps,
            "setup_steps_count": setup_steps_count,
            "target_steps_count": target_steps_count,
            "has_setup_steps": setup_steps_count > 0,
            "failed_steps": failed_steps,
            "failed_target_steps": failed_target_steps,
            "total_attempts": total_attempts,
            "attempts_with_missing_status": attempts_with_missing_status,
            "attempts_with_error_and_missing_status": attempts_with_error_and_missing_status,
            "attempts_with_error_and_status": attempts_with_error_and_status,
            "attempts_with_status_mismatch": attempts_with_status_mismatch,
            "target_steps_with_any_content_checks": target_steps_with_any_content_checks,
            "target_steps_with_field_assertions": target_steps_with_field_assertions,
            "target_steps_with_bindings": target_steps_with_bindings,
        }

    @staticmethod
    def _get_primary_attempt(step: StepRunResult) -> AttemptRunResult | None:
        if not step.attempts:
            return None
        return step.attempts[0]