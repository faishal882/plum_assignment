import json
from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image, ImageDraw
from sqlalchemy import func, select

from claims_backend.api.app import create_app
from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.infrastructure.fixtures.structured_components import (
    StructuredComponentFixtureAdapter,
)
from claims_backend.infrastructure.langgraph_workflow import LangGraphClaimWorkflow
from claims_backend.infrastructure.postgres.claim_processor import PostgresClaimProcessor
from claims_backend.infrastructure.postgres.models import (
    CasefileRow,
    ClaimVersionRow,
    ClaimWorkItemRow,
    DecisionRecordRow,
    DocumentTriageResultRow,
    IdentityReconciliationRow,
    MemberActionRow,
    RuleResultRow,
)
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)


@pytest.mark.asyncio
async def test_tc003_preserves_both_patient_names_and_requests_correction(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    prescription = _document_jpeg("PRESCRIPTION", "Rajesh Kumar")
    hospital_bill = _document_jpeg("HOSPITAL BILL", "Arjun Mehta")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "tc003-identity-conflict",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("first.jpg", prescription, "image/jpeg")),
                ("files", ("second.jpg", hospital_bill, "image/jpeg")),
            ],
        )
        assert submitted.status_code == 202
        claim_id = UUID(submitted.json()["claim_id"])
        await StructuredComponentFixtureAdapter(app.state.session_factory).seed_tc003_triage(
            claim_id,
            1,
            prescription_preview_sha256=sha256(prescription).hexdigest(),
            bill_preview_sha256=sha256(hospital_bill).hexdigest(),
        )

        workflows = PostgresWorkflowRepository(app.state.session_factory)
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=PostgresClaimProcessor(app.state.session_factory),
        )
        await runtime.setup()
        assert await WorkerService(PostgresWorkScheduler(app.state.session_factory)).run_once(
            "tc003-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp001"},
        )

    assert projection.status_code == 200
    body = projection.json()
    assert body["lifecycle_status"] == "ACTION_REQUIRED"
    assert "adjudication" not in body
    assert body["action"] == {
        "code": "PATIENT_IDENTITY_CONFLICT",
        "message": (
            "Patient names do not match: F005 shows Rajesh Kumar; "
            "F006 shows Arjun Mehta. Please replace the document that "
            "belongs to a different patient."
        ),
        "observed_document_roles": ["PRESCRIPTION", "HOSPITAL_BILL"],
        "required_document_roles": [],
        "identity_conflict": [
            {"client_document_id": "F005", "patient_name": "Rajesh Kumar"},
            {"client_document_id": "F006", "patient_name": "Arjun Mehta"},
        ],
    }

    async with app.state.session_factory() as session:
        reconciliation = (
            await session.scalars(
                select(IdentityReconciliationRow).where(
                    IdentityReconciliationRow.claim_id == claim_id
                )
            )
        ).one()
        triage = (
            await session.scalars(
                select(DocumentTriageResultRow)
                .where(DocumentTriageResultRow.claim_id == claim_id)
                .order_by(DocumentTriageResultRow.client_document_id)
            )
        ).all()
        assert reconciliation.state == "CONFLICT"
        assert reconciliation.member_name == "Rajesh Kumar"
        assert [
            (item["client_document_id"], item["value"]) for item in reconciliation.candidates
        ] == [("F005", "Rajesh Kumar"), ("F006", "Arjun Mehta")]
        assert all(item["producer"] == "fixture-fast-triage" for item in reconciliation.candidates)
        assert all(item["producer_version"] == "v1" for item in reconciliation.candidates)
        assert all(item["document_version_id"] for item in reconciliation.candidates)
        assert all(item["page"] == 1 for item in reconciliation.candidates)
        assert all(item["region"] for item in reconciliation.candidates)
        assert all(item["source_text_sha256"] for item in reconciliation.candidates)
        assert all(item["confidence"] for item in reconciliation.candidates)
        assert [
            observation["value"]
            for result in triage
            for observation in result.identity_observations
        ] == ["Rajesh Kumar", "Arjun Mehta"]
        assert await session.scalar(select(func.count()).select_from(CasefileRow)) == 0
        assert await session.scalar(select(func.count()).select_from(DecisionRecordRow)) == 0
        assert await session.scalar(select(func.count()).select_from(RuleResultRow)) == 0

    workflow_run = await workflows.get_by_work_item(await _work_item_id(app))
    assert workflow_run is not None
    effects = await workflows.list_effects(workflow_run.id)
    assert [effect.effect_type for effect in effects] == [
        "CLAIM_VERSION_LOADED",
        "LOCAL_MEDIA_INSPECTED",
        "DOCUMENT_TRIAGE_COMPLETED",
        "MEMBER_ACTION_COMMITTED",
    ]
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_identity_correction_starts_a_new_attempt_and_preserves_conflict(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    prescription = _document_jpeg("PRESCRIPTION", "Rajesh Kumar")
    hospital_bill = _document_jpeg("HOSPITAL BILL", "Arjun Mehta")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "tc003-before-correction",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("first.jpg", prescription, "image/jpeg")),
                ("files", ("second.jpg", hospital_bill, "image/jpeg")),
            ],
        )
        claim_id = UUID(submitted.json()["claim_id"])
        await StructuredComponentFixtureAdapter(app.state.session_factory).seed_tc003_triage(
            claim_id,
            1,
            prescription_preview_sha256=sha256(prescription).hexdigest(),
            bill_preview_sha256=sha256(hospital_bill).hexdigest(),
        )
        workflows = PostgresWorkflowRepository(app.state.session_factory)
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=PostgresClaimProcessor(app.state.session_factory),
        )
        await runtime.setup()
        assert await WorkerService(PostgresWorkScheduler(app.state.session_factory)).run_once(
            "tc003-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )

        corrected = await client.post(
            f"/v1/claims/{claim_id}/actions",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "tc003-corrected-bill",
            },
            data={
                "command": json.dumps(
                    {
                        "type": "REPLACE_DOCUMENT",
                        "expected_version": 1,
                        "client_document_id": "F006",
                    }
                )
            },
            files={
                "file": (
                    "corrected-hospital-bill.jpg",
                    _document_jpeg("HOSPITAL BILL", "Rajesh Kumar"),
                    "image/jpeg",
                )
            },
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp001"},
        )

    assert corrected.status_code == 200
    assert corrected.json()["version"] == 2
    assert corrected.json()["lifecycle_status"] == "QUEUED"
    assert projection.status_code == 200
    assert projection.json()["version"] == 2
    assert "action" not in projection.json()

    async with app.state.session_factory() as session:
        versions = (
            await session.scalars(
                select(ClaimVersionRow)
                .where(ClaimVersionRow.claim_id == claim_id)
                .order_by(ClaimVersionRow.version)
            )
        ).all()
        work = (
            await session.scalars(
                select(ClaimWorkItemRow)
                .where(ClaimWorkItemRow.claim_id == claim_id)
                .order_by(ClaimWorkItemRow.created_at)
            )
        ).all()
        original_conflict = (
            await session.scalars(
                select(IdentityReconciliationRow).where(
                    IdentityReconciliationRow.claim_id == claim_id,
                    IdentityReconciliationRow.claim_version == 1,
                )
            )
        ).one()
        original_action = (
            await session.scalars(
                select(MemberActionRow).where(
                    MemberActionRow.claim_id == claim_id,
                    MemberActionRow.claim_version == 1,
                )
            )
        ).one()
    assert [version.version for version in versions] == [1, 2]
    assert versions[1].submission["source"] == "DOCUMENT_REPLACEMENT"
    assert versions[1].submission["previous_version"] == 1
    assert [item.status for item in work] == ["COMPLETED", "AVAILABLE"]
    assert original_conflict.state == "CONFLICT"
    assert [item["value"] for item in original_conflict.candidates] == [
        "Rajesh Kumar",
        "Arjun Mehta",
    ]
    assert original_action.code == "PATIENT_IDENTITY_CONFLICT"
    await app.state.engine.dispose()


async def _work_item_id(app) -> UUID:
    async with app.state.session_factory() as session:
        return (await session.scalars(select(ClaimWorkItemRow.id))).one()


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [
            {"upload_index": 0, "client_document_id": "F005"},
            {"upload_index": 1, "client_document_id": "F006"},
        ],
    }


def _document_jpeg(role: str, patient: str) -> bytes:
    image = Image.new("RGB", (320, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 40), role, fill="black")
    draw.text((20, 80), f"Patient: {patient}", fill="black")
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()
