from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from random import random
from typing import Protocol

from claims_backend.domain.extraction import ModelProviderError, ModelValidationError
from claims_backend.domain.ocr import OcrError
from claims_backend.policy.adjudicator import UnsafeCasefileError


class FailureComponent(StrEnum):
    OCR = "OCR"
    IDENTITY = "IDENTITY"
    POLICY = "POLICY"
    AUDIT = "AUDIT"
    EVIDENCE_EXTRACTION = "EVIDENCE_EXTRACTION"
    ANOMALY_ENRICHMENT = "ANOMALY_ENRICHMENT"
    ENGINEERING_LOG = "ENGINEERING_LOG"


class FailureCriticality(StrEnum):
    CRITICAL = "CRITICAL"
    NONCRITICAL = "NONCRITICAL"


@dataclass(frozen=True, slots=True)
class FailureClassification:
    component: FailureComponent
    criticality: FailureCriticality
    code: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class RetrySchedule:
    base_delay: timedelta = timedelta(seconds=2)
    maximum_delay: timedelta = timedelta(seconds=60)
    jitter_ratio: float = 0.25
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    entropy: Callable[[], float] = random

    def __post_init__(self) -> None:
        if self.base_delay <= timedelta(0):
            raise ValueError("base_delay must be positive")
        if self.maximum_delay < self.base_delay:
            raise ValueError("maximum_delay cannot be less than base_delay")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between zero and one")

    def available_at(self, *, attempt_number: int) -> datetime:
        if attempt_number <= 0:
            raise ValueError("attempt_number must be positive")
        entropy = self.entropy()
        if not 0 <= entropy <= 1:
            raise ValueError("retry entropy must be between zero and one")
        exponential_seconds = self.base_delay.total_seconds() * (
            2 ** (attempt_number - 1)
        )
        maximum_seconds = self.maximum_delay.total_seconds()
        bounded_seconds = min(exponential_seconds, maximum_seconds)
        jitter_seconds = bounded_seconds * self.jitter_ratio * entropy
        delay_seconds = min(bounded_seconds + jitter_seconds, maximum_seconds)
        return self.clock() + timedelta(seconds=delay_seconds)


class RetrySettings(Protocol):
    retry_base_seconds: int
    retry_max_seconds: int
    retry_jitter_ratio: float


def retry_schedule_from_settings(
    settings: RetrySettings,
    *,
    clock: Callable[[], datetime] | None = None,
    entropy: Callable[[], float] | None = None,
) -> RetrySchedule:
    return RetrySchedule(
        base_delay=timedelta(seconds=settings.retry_base_seconds),
        maximum_delay=timedelta(seconds=settings.retry_max_seconds),
        jitter_ratio=settings.retry_jitter_ratio,
        clock=clock or (lambda: datetime.now(UTC)),
        entropy=entropy or random,
    )


def classify_processing_failure(error: Exception) -> FailureClassification | None:
    if isinstance(error, OcrError):
        return FailureClassification(
            component=FailureComponent.OCR,
            criticality=FailureCriticality.CRITICAL,
            code=error.code,
            retryable=error.retryable,
        )
    if isinstance(error, ModelValidationError):
        return FailureClassification(
            component=FailureComponent.EVIDENCE_EXTRACTION,
            criticality=FailureCriticality.CRITICAL,
            code=error.code,
            retryable=False,
        )
    if isinstance(error, ModelProviderError):
        return FailureClassification(
            component=FailureComponent.EVIDENCE_EXTRACTION,
            criticality=FailureCriticality.CRITICAL,
            code=error.code,
            retryable=error.retryable,
        )
    if isinstance(error, UnsafeCasefileError):
        return FailureClassification(
            component=FailureComponent.POLICY,
            criticality=FailureCriticality.CRITICAL,
            code="POLICY_CASEFILE_UNSAFE",
            retryable=False,
        )
    return None
