from typing import Protocol

from claims_backend.application.failure_policy import FailureComponent
from claims_backend.domain.adjudication import AdjudicationProposal, ClaimCasefile


class ExpectedNoncriticalComponentFailure(Exception):
    def __init__(
        self,
        *,
        component: FailureComponent,
        failure_code: str,
        attempts: int,
    ) -> None:
        if attempts <= 0:
            raise ValueError("attempts must be positive")
        self.component = component
        self.failure_code = failure_code
        self.attempts = attempts
        super().__init__(failure_code)


class AnomalyEnricher(Protocol):
    async def enrich(
        self,
        casefile: ClaimCasefile,
        proposal: AdjudicationProposal,
    ) -> None: ...


class EngineeringEventSink(Protocol):
    async def emit(self, event: dict[str, object]) -> None: ...


class NoOpAnomalyEnricher:
    async def enrich(
        self,
        casefile: ClaimCasefile,
        proposal: AdjudicationProposal,
    ) -> None:
        return None


class ConfiguredAnomalyFailureInjector:
    """Local-only deterministic fault injection for resilience verification.

    It is selected solely by process configuration, never by a claim request,
    document, member, or claim identifier.
    """

    async def enrich(
        self,
        casefile: ClaimCasefile,
        proposal: AdjudicationProposal,
    ) -> None:
        del casefile, proposal
        raise ExpectedNoncriticalComponentFailure(
            component=FailureComponent.ANOMALY_ENRICHMENT,
            failure_code="ANOMALY_ENRICHMENT_UNAVAILABLE",
            attempts=1,
        )


class NoOpEngineeringEventSink:
    async def emit(self, event: dict[str, object]) -> None:
        return None
