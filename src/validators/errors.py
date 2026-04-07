from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class ValidationError:
    gate: str
    artifact: str
    field: str
    reason: str

    def __str__(self) -> str:
        return f"[{self.gate}] {self.artifact} / {self.field}: {self.reason}"


class GateFailure(Exception):
    """Raised when one or more deterministic gate checks fail.

    ``errors`` is the complete list of :class:`ValidationError` objects that
    caused the rejection.  Downstream callers can inspect it or serialize it
    via :meth:`to_dict`.
    """

    def __init__(self, errors: List[ValidationError]) -> None:
        self.errors = errors
        super().__init__("\n".join(str(e) for e in errors))

    def to_dict(self) -> dict:
        return {
            "gate_failure": True,
            "errors": [
                {
                    "gate": e.gate,
                    "artifact": e.artifact,
                    "field": e.field,
                    "reason": e.reason,
                }
                for e in self.errors
            ],
        }
