import json
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.api.app import create_app
from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.domain.reviews import ReviewTaskDetail
from claims_backend.infrastructure.fixtures.structured_components import (
    StructuredComponentFixtureAdapter,
)
from claims_backend.infrastructure.langgraph_workflow import LangGraphClaimWorkflow
from claims_backend.infrastructure.postgres.claim_processor import (
    PostgresClaimProcessor,
)
from claims_backend.infrastructure.postgres.models import (
    DocumentPageArtifactRow,
    DocumentRow,
    DocumentVersionRow,
    OcrObservationRow,
    OcrPageResultRow,
)
from claims_backend.infrastructure.postgres.reviews import PostgresReviewRepository
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)
from claims_backend.infrastructure.postgres.work_scheduler import (
    PostgresWorkScheduler,
)
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)
from claims_backend.application.setup_import import SetupDataApplication

_SETUP_BYTES = json.dumps(
    {
        "members": [
            {
                "member_id": "EMP008",
                "policy_id": "PLUM_GHI_2024",
                "full_name": "Faishal Test Member",
                "date_of_birth": "1990-01-01",
                "gender": "MALE",
                "relationship": "PRIMARY",
                "employee_id": "EMP008",
                "join_date": "2024-01-01",
                "status": "ACTIVE",
            }
        ],
        "history": [],
        "utilization": [],
    }
).encode()


@pytest.mark.asyncio
async def test_get_task_resolves_and_includes_ocr_observations(
    migrated_database_url: str,
    tmp_path,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Import policy setup and member data
    await SetupDataApplication(
        PostgresSetupImportRepository(factory)
    ).import_sources(
        Path("problem_statement/policy_terms.json").read_bytes(),
        source_name="policy_terms.json",
        member_data_bytes=json.dumps(
            {
                "policy_id": "PLUM_GHI_2024",
                "as_of_date": "2024-10-30",
                "claim_history": [
                    {
                        "history_claim_id": "CLM_0081",
                        "member_id": "EMP008",
                        "treatment_date": "2024-10-30",
                        "amount": "1200.00",
                        "currency": "INR",
                        "provider": "City Clinic A",
                    },
                    {
                        "history_claim_id": "CLM_0082",
                        "member_id": "EMP008",
                        "treatment_date": "2024-10-30",
                        "amount": "1800.00",
                        "currency": "INR",
                        "provider": "City Clinic B",
                    },
                    {
                        "history_claim_id": "CLM_0083",
                        "member_id": "EMP008",
                        "treatment_date": "2024-10-30",
                        "amount": "2100.00",
                        "currency": "INR",
                        "provider": "Wellness Center",
                    },
                ],
                "utilization": [
                    {
                        "member_id": "EMP008",
                        "period_start": "2024-04-01",
                        "period_end": "2025-03-31",
                        "used_amount": "0.00",
                        "currency": "INR",
                        "as_of_date": "2024-10-30",
                    }
                ],
            }
        ).encode(),
        member_data_source_name="tc009-member-facts.json",
    )

    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp008",
                "Idempotency-Key": "tc009-explainability-test",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("F017.pdf", _pdf_bytes(), "application/pdf")),
                ("files", ("F018.pdf", _pdf_bytes(), "application/pdf")),
            ],
        )
        assert submitted.status_code == 202
        claim_id = UUID(submitted.json()["claim_id"])
        await StructuredComponentFixtureAdapter(factory).seed_tc009(claim_id, 1)

        workflows = PostgresWorkflowRepository(app.state.session_factory)
        processor = PostgresClaimProcessor(app.state.session_factory)
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=processor,
        )
        await runtime.setup()
        await WorkerService(PostgresWorkScheduler(app.state.session_factory)).run_once(
            "tc009-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )

        # Seed OCR Observation linked to the claim's document version
        now_dt = datetime.now(UTC)
        obs_id = sha256(b"explainability-obs-1").hexdigest()
        async with factory.begin() as session:
            doc_ver = (
                await session.scalars(
                    select(DocumentVersionRow.id)
                    .join(DocumentRow, DocumentRow.id == DocumentVersionRow.document_id)
                    .where(DocumentRow.claim_id == claim_id)
                )
            ).first()
            artifact_id = (
                await session.scalars(
                    select(DocumentPageArtifactRow.id).where(
                        DocumentPageArtifactRow.document_version_id == doc_ver
                    )
                )
            ).first()
            doc_id = (
                await session.scalars(
                    select(DocumentRow.id).where(DocumentRow.claim_id == claim_id)
                )
            ).first()
            if doc_ver is not None and doc_id is not None:
                if artifact_id is None:
                    artifact_id = uuid4()
                    session.add(
                        DocumentPageArtifactRow(
                            id=artifact_id,
                            document_id=doc_id,
                            document_version_id=doc_ver,
                            page_number=1,
                            original_sha256="orig-sha",
                            rendered_sha256="rend-sha",
                            relative_path=f"pages/{doc_ver}_p1.png",
                            media_type="image/png",
                            size_bytes=1024,
                            width=100,
                            height=100,
                            render_version="v1",
                            created_at=now_dt,
                        )
                    )
                    await session.flush()
                ocr_page_id = uuid4()
                session.add(
                    OcrPageResultRow(
                        id=ocr_page_id,
                        page_artifact_id=artifact_id,
                        document_version_id=doc_ver,
                        page_number=1,
                        document_role="CONSULTATION",
                        profile="EXPENSE",
                        provider_name="TEXTRACT",
                        provider_version="v1",
                        provider_request_id="req-exp-1",
                        retry_attempts=0,
                        created_at=now_dt,
                    )
                )
                await session.flush()
                session.add(
                    OcrObservationRow(
                        id=uuid4(),
                        ocr_page_result_id=ocr_page_id,
                        observation_id=obs_id,
                        document_version_id=doc_ver,
                        page_number=1,
                        kind="LINE",
                        text="Total bill INR 1,350.00",
                        confidence=0.98,
                        region={"top": 0.1, "left": 0.2, "width": 0.3, "height": 0.05},
                        source_id="line-1",
                        created_at=now_dt,
                    )
                )

        listed = await client.get(
            "/v1/review-tasks",
            headers={"X-Dev-Username": "reviewer.local"},
        )
        assert listed.status_code == 200
        tasks = listed.json()
        assert len(tasks) > 0
        task_id = tasks[0]["id"]

        detail_res = await client.get(
            f"/v1/review-tasks/{task_id}",
            headers={"X-Dev-Username": "reviewer.local"},
        )
        assert detail_res.status_code == 200
        detail_data = detail_res.json()

        assert "ocr_observations" in detail_data
        assert obs_id in detail_data["ocr_observations"]
        obs_item = detail_data["ocr_observations"][obs_id]
        assert obs_item["text"] == "Total bill INR 1,350.00"
        assert obs_item["confidence"] == 0.98
        assert obs_item["page_number"] == 1


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP008",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-10-30",
        "claimed_amount": "4800.00",
        "currency": "INR",
        "documents": [
            {"upload_index": 0, "client_document_id": "F017"},
            {"upload_index": 1, "client_document_id": "F018"},
        ],
    }


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
