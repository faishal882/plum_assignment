from claims_backend.application.failure_policy import FailureComponent
from claims_backend.domain.adjudication import AdjudicationProposal, ClaimCasefile
from claims_backend.infrastructure.processing_failures import (
    ExpectedNoncriticalComponentFailure,
)


class EvaluationAnomalyFailureInjector:
    """Evaluation-only adapter; never constructed from an API request."""

    async def enrich(
        self,
        casefile: ClaimCasefile,
        proposal: AdjudicationProposal,
    ) -> None:
        raise ExpectedNoncriticalComponentFailure(
            component=FailureComponent.ANOMALY_ENRICHMENT,
            failure_code="ANOMALY_ENRICHMENT_UNAVAILABLE",
            attempts=1,
        )
