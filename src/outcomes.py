"""Explicit run outcomes.

A run never ends in an ambiguous ``None``. Every finish is one of these, and
every one carries a human-readable reason that is written to ``run_log``.
"""

from __future__ import annotations

from enum import Enum


class Outcome(str, Enum):
    """Terminal outcome of a pipeline run or stage."""

    PUBLISHED = "PUBLISHED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    DRAFTED = "DRAFTED"
    SKIPPED_THIN = "SKIPPED_THIN"
    SKIPPED_NO_DATA = "SKIPPED_NO_DATA"

    @staticmethod
    def failed(stage: str) -> str:
        """``FAILED_<STAGE>`` for an arbitrary stage name."""
        return f"FAILED_{stage.upper().replace(' ', '_')}"

    @property
    def is_failure(self) -> bool:
        return str(self).startswith("FAILED_")

    @property
    def is_skip(self) -> bool:
        return str(self).startswith("SKIPPED_")


class Stage(str, Enum):
    """Named pipeline stages, used to build ``FAILED_<STAGE>`` outcomes."""

    INGEST = "ingest"
    CLUSTER = "cluster"
    SCORE = "score"
    DRAFT = "draft"
    VALIDATE = "validate"
    PUBLISH = "publish"
    STATE = "state"


#: A run whose outcome is one of these needs no attention.
BENIGN_OUTCOMES = frozenset(
    {
        Outcome.DRAFTED.value,
        Outcome.PENDING_APPROVAL.value,
        Outcome.PUBLISHED.value,
        Outcome.SKIPPED_THIN.value,
        Outcome.SKIPPED_NO_DATA.value,
    }
)


def as_outcome(value: object) -> str:
    """Normalise an :class:`Outcome` member or plain string to its value."""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def is_failure(outcome: object) -> bool:
    """True for ``FAILED_*`` outcomes."""
    return as_outcome(outcome).upper().startswith("FAILED_")
