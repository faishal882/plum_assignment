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
    ResolvedTriageOutput,
    StructuredDocumentEvidence,
    StructuredEvidencePayload,
    TriageDocumentResult,
    TriageIdentityObservation,
)
from claims_backend.infrastructure.postgres.models import ProcessingFixtureRow


class StructuredComponentFixtureAdapter:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def seed_recorded_triage(
        self,
        claim_id: UUID,
        claim_version: int,
        output: ResolvedTriageOutput,
    ) -> None:
        """Seed sanitized provider output for a rendered-recorded evaluation."""
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

    async def seed_recorded_structured(
        self,
        claim_id: UUID,
        claim_version: int,
        payload: StructuredEvidencePayload,
    ) -> None:
        """Seed normalized evidence for the OCR-bypassed component profile."""
        await self._seed_structured(claim_id, claim_version, payload)

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

    async def seed_tc007(self, claim_id: UUID, claim_version: int) -> None:
        await self._seed_structured(
            claim_id,
            claim_version,
            StructuredEvidencePayload(
                documents=(
                    StructuredDocumentEvidence(
                        evidence_id="F012",
                        client_document_id="F012",
                        role=DocumentRole.PRESCRIPTION,
                        readability=Readability.READABLE,
                        identity_observations=(
                            IdentityObservation(
                                kind="PATIENT_NAME",
                                value="Suresh Patil",
                            ),
                        ),
                        treatment_date="2024-11-02",
                        clinical_condition="Suspected Lumbar Disc Herniation",
                        clinical_treatment="MRI",
                    ),
                    StructuredDocumentEvidence(
                        evidence_id="F013",
                        client_document_id="F013",
                        role=DocumentRole.LAB_REPORT,
                        readability=Readability.READABLE,
                        identity_observations=(),
                        clinical_treatment="MRI",
                    ),
                    StructuredDocumentEvidence(
                        evidence_id="F014",
                        client_document_id="F014",
                        role=DocumentRole.HOSPITAL_BILL,
                        readability=Readability.READABLE,
                        identity_observations=(),
                        billed_paise=1_500_000,
                        line_items_paise={"mri": 1_500_000},
                    ),
                )
            ),
        )

    async def seed_tc008(self, claim_id: UUID, claim_version: int) -> None:
        await self._seed_structured(
            claim_id,
            claim_version,
            StructuredEvidencePayload(
                documents=(
                    StructuredDocumentEvidence(
                        evidence_id="F015",
                        client_document_id="F015",
                        role=DocumentRole.PRESCRIPTION,
                        readability=Readability.READABLE,
                        identity_observations=(
                            IdentityObservation(
                                kind="PATIENT_NAME",
                                value="Amit Verma",
                            ),
                        ),
                        treatment_date="2024-10-20",
                        clinical_condition="Gastroenteritis",
                    ),
                    StructuredDocumentEvidence(
                        evidence_id="F016",
                        client_document_id="F016",
                        role=DocumentRole.HOSPITAL_BILL,
                        readability=Readability.READABLE,
                        identity_observations=(),
                        billed_paise=750_000,
                        line_items_paise={
                            "consultation_fee": 200_000,
                            "medicines": 550_000,
                        },
                    ),
                )
            ),
        )

    async def seed_tc010(self, claim_id: UUID, claim_version: int) -> None:
        await self._seed_structured(
            claim_id,
            claim_version,
            StructuredEvidencePayload(
                documents=(
                    StructuredDocumentEvidence(
                        evidence_id="F019",
                        client_document_id="F019",
                        role=DocumentRole.PRESCRIPTION,
                        readability=Readability.READABLE,
                        identity_observations=(
                            IdentityObservation(
                                kind="PATIENT_NAME",
                                value="Deepak Shah",
                            ),
                        ),
                        treatment_date="2024-11-03",
                        clinical_condition="Acute Bronchitis",
                    ),
                    StructuredDocumentEvidence(
                        evidence_id="F020",
                        client_document_id="F020",
                        role=DocumentRole.HOSPITAL_BILL,
                        readability=Readability.READABLE,
                        identity_observations=(
                            IdentityObservation(
                                kind="PATIENT_NAME",
                                value="Deepak Shah",
                            ),
                        ),
                        billed_paise=450_000,
                        provider_name="Apollo Hospitals",
                        line_items_paise={
                            "consultation_fee": 150_000,
                            "medicines": 300_000,
                        },
                    ),
                )
            ),
        )

    async def seed_tc011(self, claim_id: UUID, claim_version: int) -> None:
        await self._seed_structured(
            claim_id,
            claim_version,
            StructuredEvidencePayload(
                documents=(
                    StructuredDocumentEvidence(
                        evidence_id="F021",
                        client_document_id="F021",
                        role=DocumentRole.PRESCRIPTION,
                        readability=Readability.READABLE,
                        identity_observations=(
                            IdentityObservation(
                                kind="PATIENT_NAME",
                                value="Kavita Nair",
                            ),
                        ),
                        treatment_date="2024-10-28",
                        clinical_condition="Chronic Joint Pain",
                        clinical_treatment="Panchakarma Therapy",
                    ),
                    StructuredDocumentEvidence(
                        evidence_id="F022",
                        client_document_id="F022",
                        role=DocumentRole.HOSPITAL_BILL,
                        readability=Readability.READABLE,
                        identity_observations=(
                            IdentityObservation(
                                kind="PATIENT_NAME",
                                value="Kavita Nair",
                            ),
                        ),
                        billed_paise=400_000,
                        provider_name="Ayur Wellness Centre",
                        line_items_paise={
                            "panchakarma_therapy": 300_000,
                            "consultation": 100_000,
                        },
                    ),
                )
            ),
        )

    async def seed_tc009(self, claim_id: UUID, claim_version: int) -> None:
        await self._seed_structured(
            claim_id,
            claim_version,
            StructuredEvidencePayload(
                documents=(
                    StructuredDocumentEvidence(
                        evidence_id="F017",
                        client_document_id="F017",
                        role=DocumentRole.PRESCRIPTION,
                        readability=Readability.READABLE,
                        identity_observations=(
                            IdentityObservation(
                                kind="PATIENT_NAME",
                                value="Ravi Menon",
                            ),
                        ),
                        treatment_date="2024-10-30",
                        clinical_condition="Migraine",
                    ),
                    StructuredDocumentEvidence(
                        evidence_id="F018",
                        client_document_id="F018",
                        role=DocumentRole.HOSPITAL_BILL,
                        readability=Readability.READABLE,
                        identity_observations=(
                            IdentityObservation(
                                kind="PATIENT_NAME",
                                value="Ravi Menon",
                            ),
                        ),
                        billed_paise=480_000,
                    ),
                )
            ),
        )

    async def _seed_structured(
        self,
        claim_id: UUID,
        claim_version: int,
        payload: StructuredEvidencePayload,
    ) -> None:
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
        output = ResolvedTriageOutput(
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
        output = ResolvedTriageOutput(
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
        output = ResolvedTriageOutput(
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
        output = ResolvedTriageOutput(
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
        output = ResolvedTriageOutput(
            documents=(
                TriageDocumentResult(
                    client_document_id="F007",
                    role=DocumentRole.PRESCRIPTION,
                    readability=_readability_from_hash(
                        prescription_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(_identity("Rajesh Kumar", confidence=0.99),),
                ),
                TriageDocumentResult(
                    client_document_id="F008",
                    role=DocumentRole.HOSPITAL_BILL,
                    readability=_readability_from_hash(
                        bill_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(_identity("Rajesh Kumar", confidence=0.99),),
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

    async def seed_rendered_tc005_triage(
        self,
        claim_id: UUID,
        claim_version: int,
        *,
        prescription_preview_sha256: str,
        bill_preview_sha256: str,
    ) -> None:
        output = ResolvedTriageOutput(
            documents=(
                TriageDocumentResult(
                    client_document_id="F009",
                    role=DocumentRole.PRESCRIPTION,
                    readability=_readability_from_hash(
                        prescription_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(_identity("Vikram Joshi", confidence=0.99),),
                ),
                TriageDocumentResult(
                    client_document_id="F010",
                    role=DocumentRole.HOSPITAL_BILL,
                    readability=_readability_from_hash(
                        bill_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(_identity("Vikram Joshi", confidence=0.99),),
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

    async def seed_rendered_tc006_triage(
        self,
        claim_id: UUID,
        claim_version: int,
        *,
        bill_preview_sha256: str,
    ) -> None:
        output = ResolvedTriageOutput(
            documents=(
                TriageDocumentResult(
                    client_document_id="F011",
                    role=DocumentRole.HOSPITAL_BILL,
                    readability=_readability_from_hash(
                        bill_preview_sha256,
                        Readability.READABLE,
                    ),
                    identity_observations=(_identity("Priya Singh", confidence=0.99),),
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

    async def seed_rendered_tc012_triage(
        self,
        claim_id: UUID,
        claim_version: int,
        *,
        prescription_preview_sha256: str,
        bill_preview_sha256: str,
    ) -> None:
        output = ResolvedTriageOutput(
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
                .on_conflict_do_nothing(constraint="processing_fixtures_claim_version_uq")
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
