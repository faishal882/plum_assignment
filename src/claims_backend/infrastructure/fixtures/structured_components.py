import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.domain.evidence import (
    DocumentRole,
    IdentityObservation,
    NormalizedRegion,
    PreviewProvenance,
    Readability,
    ReadabilityObservation,
    StructuredDocumentEvidence,
    StructuredEvidencePayload,
    TriageDocumentResult,
    TriageIdentityObservation,
    TriageModelOutput,
)
from claims_backend.infrastructure.postgres.models import ProcessingFixtureRow


class StructuredComponentFixtureAdapter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def seed_tc004(self, claim_id: UUID, claim_version: int) -> None:
        payload = StructuredEvidencePayload(
            documents=(
                StructuredDocumentEvidence(
                    evidence_id="F007",
                    client_document_id="F007",
                    role=DocumentRole.PRESCRIPTION,
                    readability=Readability.READABLE,
                    identity_observations=(
                        IdentityObservation(kind="PATIENT_NAME", value="Rajesh Kumar"),
                    ),
                    treatment_date="2024-11-01",
                    clinical_condition="Viral Fever",
                ),
                StructuredDocumentEvidence(
                    evidence_id="F008",
                    client_document_id="F008",
                    role=DocumentRole.HOSPITAL_BILL,
                    readability=Readability.READABLE,
                    identity_observations=(
                        IdentityObservation(kind="PATIENT_NAME", value="Rajesh Kumar"),
                    ),
                    billed_paise=150_000,
                    treatment_date="2024-11-01",
                    line_items_paise={
                        "consultation_fee": 100_000,
                        "cbc": 30_000,
                        "ns1": 20_000,
                    },
                ),
            )
        )
        canonical = json.dumps(
            payload.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(ProcessingFixtureRow)
                .values(
                    id=uuid4(),
                    claim_id=claim_id,
                    claim_version=claim_version,
                    route="STRUCTURED_ADJUDICATION",
                    payload=payload.model_dump(mode="json"),
                    payload_sha256=sha256(canonical).hexdigest(),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(constraint="processing_fixtures_claim_version_uq")
            )

    async def seed_tc001_triage(self, claim_id: UUID, claim_version: int) -> None:
        output = TriageModelOutput(
            documents=(
                TriageDocumentResult(
                    client_document_id="F001",
                    role=DocumentRole.PRESCRIPTION,
                    readability=_readability("tc001:F001", Readability.READABLE),
                    identity_observations=(),
                ),
                TriageDocumentResult(
                    client_document_id="F002",
                    role=DocumentRole.PRESCRIPTION,
                    readability=_readability("tc001:F002", Readability.READABLE),
                    identity_observations=(),
                ),
            )
        )
        canonical = json.dumps(
            output.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(ProcessingFixtureRow)
                .values(
                    id=uuid4(),
                    claim_id=claim_id,
                    claim_version=claim_version,
                    route="EARLY_TRIAGE",
                    payload=output.model_dump(mode="json"),
                    payload_sha256=sha256(canonical).hexdigest(),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(constraint="processing_fixtures_claim_version_uq")
            )

    async def seed_tc002_triage(
        self,
        claim_id: UUID,
        claim_version: int,
        *,
        prescription_preview_sha256: str,
        bill_preview_sha256: str,
    ) -> None:
        output = TriageModelOutput(
            documents=(
                TriageDocumentResult(
                    client_document_id="F003",
                    role=DocumentRole.PRESCRIPTION,
                    readability=_readability_from_hash(
                        prescription_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(),
                ),
                TriageDocumentResult(
                    client_document_id="F004",
                    role=DocumentRole.PHARMACY_BILL,
                    readability=_readability_from_hash(
                        bill_preview_sha256,
                        Readability.UNREADABLE,
                    ),
                    identity_observations=(),
                ),
            )
        )
        canonical = json.dumps(
            output.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(ProcessingFixtureRow)
                .values(
                    id=uuid4(),
                    claim_id=claim_id,
                    claim_version=claim_version,
                    route="EARLY_TRIAGE",
                    payload=output.model_dump(mode="json"),
                    payload_sha256=sha256(canonical).hexdigest(),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(constraint="processing_fixtures_claim_version_uq")
            )

    async def seed_tc003_triage(
        self,
        claim_id: UUID,
        claim_version: int,
        *,
        prescription_preview_sha256: str,
        bill_preview_sha256: str,
    ) -> None:
        output = TriageModelOutput(
            documents=(
                TriageDocumentResult(
                    client_document_id="F005",
                    role=DocumentRole.PRESCRIPTION,
                    readability=_readability_from_hash(
                        prescription_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(_identity("Rajesh Kumar", confidence=0.72),),
                ),
                TriageDocumentResult(
                    client_document_id="F006",
                    role=DocumentRole.HOSPITAL_BILL,
                    readability=_readability_from_hash(
                        bill_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(_identity("Arjun Mehta", confidence=0.99),),
                ),
            )
        )
        canonical = json.dumps(
            output.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(ProcessingFixtureRow)
                .values(
                    id=uuid4(),
                    claim_id=claim_id,
                    claim_version=claim_version,
                    route="EARLY_TRIAGE",
                    payload=output.model_dump(mode="json"),
                    payload_sha256=sha256(canonical).hexdigest(),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(constraint="processing_fixtures_claim_version_uq")
            )

    async def seed_document_intelligence_triage(
        self,
        claim_id: UUID,
        claim_version: int,
        *,
        prescription_preview_sha256: str,
        bill_preview_sha256: str,
    ) -> None:
        output = TriageModelOutput(
            documents=(
                TriageDocumentResult(
                    client_document_id="F101",
                    role=DocumentRole.PRESCRIPTION,
                    readability=_readability_from_hash(
                        prescription_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(),
                ),
                TriageDocumentResult(
                    client_document_id="F102",
                    role=DocumentRole.HOSPITAL_BILL,
                    readability=_readability_from_hash(
                        bill_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(),
                ),
            )
        )
        canonical = json.dumps(
            output.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(ProcessingFixtureRow)
                .values(
                    id=uuid4(),
                    claim_id=claim_id,
                    claim_version=claim_version,
                    route="EARLY_TRIAGE",
                    payload=output.model_dump(mode="json"),
                    payload_sha256=sha256(canonical).hexdigest(),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(constraint="processing_fixtures_claim_version_uq")
            )

    async def seed_rendered_tc004_triage(
        self,
        claim_id: UUID,
        claim_version: int,
        *,
        prescription_preview_sha256: str,
        bill_preview_sha256: str,
    ) -> None:
        output = TriageModelOutput(
            documents=(
                TriageDocumentResult(
                    client_document_id="F007",
                    role=DocumentRole.PRESCRIPTION,
                    readability=_readability_from_hash(
                        prescription_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(
                        _identity("Rajesh Kumar", confidence=0.99),
                    ),
                ),
                TriageDocumentResult(
                    client_document_id="F008",
                    role=DocumentRole.HOSPITAL_BILL,
                    readability=_readability_from_hash(
                        bill_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(
                        _identity("Rajesh Kumar", confidence=0.99),
                    ),
                ),
            )
        )
        canonical = json.dumps(
            output.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(ProcessingFixtureRow)
                .values(
                    id=uuid4(),
                    claim_id=claim_id,
                    claim_version=claim_version,
                    route="EARLY_TRIAGE",
                    payload=output.model_dump(mode="json"),
                    payload_sha256=sha256(canonical).hexdigest(),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(
                    constraint="processing_fixtures_claim_version_uq"
                )
            )

    async def seed_rendered_tc005_triage(
        self,
        claim_id: UUID,
        claim_version: int,
        *,
        prescription_preview_sha256: str,
        bill_preview_sha256: str,
    ) -> None:
        output = TriageModelOutput(
            documents=(
                TriageDocumentResult(
                    client_document_id="F009",
                    role=DocumentRole.PRESCRIPTION,
                    readability=_readability_from_hash(
                        prescription_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(
                        _identity("Vikram Joshi", confidence=0.99),
                    ),
                ),
                TriageDocumentResult(
                    client_document_id="F010",
                    role=DocumentRole.HOSPITAL_BILL,
                    readability=_readability_from_hash(
                        bill_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(
                        _identity("Vikram Joshi", confidence=0.99),
                    ),
                ),
            )
        )
        canonical = json.dumps(
            output.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(ProcessingFixtureRow)
                .values(
                    id=uuid4(),
                    claim_id=claim_id,
                    claim_version=claim_version,
                    route="EARLY_TRIAGE",
                    payload=output.model_dump(mode="json"),
                    payload_sha256=sha256(canonical).hexdigest(),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(
                    constraint="processing_fixtures_claim_version_uq"
                )
            )

    async def seed_rendered_tc006_triage(
        self,
        claim_id: UUID,
        claim_version: int,
        *,
        bill_preview_sha256: str,
    ) -> None:
        output = TriageModelOutput(
            documents=(
                TriageDocumentResult(
                    client_document_id="F011",
                    role=DocumentRole.HOSPITAL_BILL,
                    readability=_readability_from_hash(
                        bill_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(
                        _identity("Priya Singh", confidence=0.99),
                    ),
                ),
            )
        )
        canonical = json.dumps(
            output.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(ProcessingFixtureRow)
                .values(
                    id=uuid4(),
                    claim_id=claim_id,
                    claim_version=claim_version,
                    route="EARLY_TRIAGE",
                    payload=output.model_dump(mode="json"),
                    payload_sha256=sha256(canonical).hexdigest(),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(
                    constraint="processing_fixtures_claim_version_uq"
                )
            )

    async def seed_rendered_tc012_triage(
        self,
        claim_id: UUID,
        claim_version: int,
        *,
        prescription_preview_sha256: str,
        bill_preview_sha256: str,
    ) -> None:
        output = TriageModelOutput(
            documents=(
                TriageDocumentResult(
                    client_document_id="F023",
                    role=DocumentRole.PRESCRIPTION,
                    readability=_readability_from_hash(
                        prescription_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(),
                ),
                TriageDocumentResult(
                    client_document_id="F024",
                    role=DocumentRole.HOSPITAL_BILL,
                    readability=_readability_from_hash(
                        bill_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(),
                ),
            )
        )
        canonical = json.dumps(
            output.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        async with self._session_factory.begin() as session:
            await session.execute(
                insert(ProcessingFixtureRow)
                .values(
                    id=uuid4(),
                    claim_id=claim_id,
                    claim_version=claim_version,
                    route="EARLY_TRIAGE",
                    payload=output.model_dump(mode="json"),
                    payload_sha256=sha256(canonical).hexdigest(),
                    created_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(
                    constraint="processing_fixtures_claim_version_uq"
                )
            )


def _readability(seed: str, status: Readability) -> ReadabilityObservation:
    return _readability_from_hash(sha256(seed.encode()).hexdigest(), status)


def _readability_from_hash(
    preview_sha256: str,
    status: Readability,
) -> ReadabilityObservation:
    return ReadabilityObservation(
        status=status,
        preview=PreviewProvenance(
            page=1,
            sha256=preview_sha256,
            transform_version="fixture-preview-v1",
        ),
    )


def _identity(value: str, *, confidence: float) -> TriageIdentityObservation:
    return TriageIdentityObservation(
        kind="PATIENT_NAME",
        value=value,
        page=1,
        region=NormalizedRegion(x=0.1, y=0.4, width=0.5, height=0.1),
        source_text_sha256=sha256(value.encode()).hexdigest(),
        confidence=confidence,
    )
