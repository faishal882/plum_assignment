import json
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select

from claims_backend.api.app import create_app
from claims_backend.config import Settings
from claims_backend.domain.evidence import (
    DocumentRole,
    PreviewProvenance,
    Readability,
    ReadabilityObservation,
    ResolvedTriageOutput,
    TriageDocumentResult,
    TriageEvidenceField,
    TriageEvidenceFieldNormalization,
    TriageEvidenceNormalizationCode,
    TriageEvidenceNormalizationReport,
)
from claims_backend.domain.workflow import ExecutionContract, WorkflowRun, WorkflowRunStatus
from claims_backend.infrastructure.postgres.claim_processor import PostgresClaimProcessor
from claims_backend.infrastructure.postgres.models import (
    DocumentTriageResultRow,
    DocumentVersionRow,
)
from claims_backend.infrastructure.postgres.reconstruction import PostgresClaimReconstructor


@pytest.mark.asyncio
async def test_v4_triage_audit_is_persisted_with_canonical_evidence_and_reconstruction(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "triage-normalization-audit",
            },
            data={"metadata": json.dumps(_metadata())},
            files={"files": ("hospital-bill.jpg", _image(), "image/jpeg")},
        )
    assert submitted.status_code == 202
    claim_id = UUID(submitted.json()["claim_id"])
    async with app.state.session_factory() as session:
        document_version = await session.scalar(select(DocumentVersionRow))
    assert document_version is not None

    references = tuple(f"{index:064x}" for index in range(30))
    output = ResolvedTriageOutput(
        documents=(
            TriageDocumentResult(
                client_document_id="hospital-bill",
                role=DocumentRole.HOSPITAL_BILL,
                role_evidence_refs=references[:5],
                readability=ReadabilityObservation(
                    status=Readability.READABLE,
                    preview=PreviewProvenance(
                        page=1,
                        sha256=document_version.sha256,
                        transform_version="pymupdf-v1",
                    ),
                ),
                readability_evidence_refs=references[:5],
                identity_observations=(),
            ),
        )
    )
    report = _report(references)
    now = datetime.now(UTC)
    workflow_run = WorkflowRun(
        id=uuid4(),
        work_item_id=uuid4(),
        claim_id=claim_id,
        claim_version=1,
        operation_key="PROCESS",
        graph_name="claim-processing",
        graph_version="claim-processing-v7",
        execution_contract=ExecutionContract.unspecified(),
        status=WorkflowRunStatus.RUNNING,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )

    await PostgresClaimProcessor(app.state.session_factory)._commit_triage(
        workflow_run,
        output,
        model_route="FAST_TRIAGE:recorded-model:fast-triage-prompt-v3",
        producer="structured-fast-triage",
        producer_version="fast-triage-prompt-v3",
        normalization_reports={"hospital-bill": report},
        raw_provider_output_sha256="b" * 64,
    )

    async with app.state.session_factory() as session:
        stored = await session.scalar(select(DocumentTriageResultRow))
    assert stored is not None
    assert stored.role_evidence_refs == list(references[:5])
    assert stored.readability_evidence_refs == list(references[:5])
    assert stored.normalization_report == report.model_dump(mode="json")
    assert stored.raw_provider_output_sha256 == "b" * 64

    reconstruction = await PostgresClaimReconstructor(app.state.session_factory).reconstruct(
        claim_id
    )
    assert reconstruction is not None
    assert reconstruction.document_triage[0]["normalization_report"] == report.model_dump(
        mode="json"
    )
    assert reconstruction.document_triage[0]["raw_provider_output_sha256"] == "b" * 64
    await app.state.engine.dispose()


def _report(references: tuple[str, ...]) -> TriageEvidenceNormalizationReport:
    field = TriageEvidenceFieldNormalization(
        field=TriageEvidenceField.ROLE,
        received_refs=references,
        unique_refs=references,
        retained_refs=references[:5],
        duplicate_dropped_refs=(),
        over_citation_dropped_refs=references[5:],
        codes=(TriageEvidenceNormalizationCode.TRUNCATED,),
    )
    return TriageEvidenceNormalizationReport(
        policy_version="triage-evidence-policy-v1",
        role=field,
        readability=field.model_copy(update={"field": TriageEvidenceField.READABILITY}),
    )


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [{"upload_index": 0, "client_document_id": "hospital-bill"}],
    }


def _image() -> bytes:
    image = Image.new("RGB", (48, 48), "white")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()
