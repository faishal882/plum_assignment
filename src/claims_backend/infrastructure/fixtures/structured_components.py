import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.domain.evidence import (
    DocumentRole,
    IdentityObservation,
    Readability,
    StructuredDocumentEvidence,
    StructuredEvidencePayload,
    TriageDocumentResult,
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
                    readability=Readability.READABLE,
                    identity_observations=(),
                ),
                TriageDocumentResult(
                    client_document_id="F002",
                    role=DocumentRole.PRESCRIPTION,
                    readability=Readability.READABLE,
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
