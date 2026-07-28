import json
from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image, ImageDraw
from sqlalchemy import func, select

from claims_backend.api.app import create_app
from claims_backend.api.dependencies import get_identity_provider
from claims_backend.application.identity import IdentityProvider
from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.domain.identity import Principal, Role
from claims_backend.infrastructure.fixtures.document_quality import (
    degrade_to_unreadable_jpeg,
)
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
    RuleResultRow,
)
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)


class Emp004IdentityProvider(IdentityProvider):
    async def resolve(self, username: str) -> Principal | None:
        return Principal(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            username=username,
            roles=frozenset({Role.MEMBER}),
            member_id="EMP004",
        )


def emp004_identity_provider() -> IdentityProvider:
    return Emp004IdentityProvider()


@pytest.mark.asyncio
async def test_tc002_requests_replacement_of_the_unreadable_pharmacy_bill(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    app.dependency_overrides[get_identity_provider] = emp004_identity_provider
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id, unreadable_bill, workflows = await _reach_tc002_action_required(
            app,
            client,
            migrated_database_url,
            idempotency_key="tc002-readability-gate",
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp004"},
        )

    assert projection.status_code == 200
    body = projection.json()
    assert body["lifecycle_status"] == "ACTION_REQUIRED"
    assert "adjudication" not in body
    assert "explanation" not in body
    assert body["action"] == {
        "code": "UNREADABLE_DOCUMENT",
        "message": (
            "The pharmacy bill (F004) could not be read. "
            "Please replace that document with a clearer image."
        ),
        "observed_document_roles": ["PRESCRIPTION", "PHARMACY_BILL"],
        "required_document_roles": ["PHARMACY_BILL"],
        "affected_documents": [
            {
                "client_document_id": "F004",
                "observed_role": "PHARMACY_BILL",
                "requested_action": "REPLACE",
            }
        ],
    }

    async with app.state.session_factory() as session:
        triage = (
            await session.scalars(
                select(DocumentTriageResultRow).order_by(
                    DocumentTriageResultRow.client_document_id
                )
            )
        ).all()
        bill_result = triage[1]
        assert bill_result.client_document_id == "F004"
        assert bill_result.readability == "UNREADABLE"
        assert bill_result.readability_observation == {
            "status": "UNREADABLE",
            "document_version_id": str(bill_result.document_version_id),
            "preview": {
                "page": 1,
                "sha256": sha256(unreadable_bill).hexdigest(),
                "transform_version": "fixture-preview-v1",
            },
        }
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
    assert not {
        "TEXTRACT_STARTED",
        "EXTRACTION_STARTED",
        "CASEFILE_FROZEN",
        "ADJUDICATION_PROPOSED",
        "DECISION_COMMITTED",
    } & {effect.effect_type for effect in effects}
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_readable_replacement_creates_a_resumable_new_claim_version(
    migrated_database_url: str,
    tmp_path,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    app.dependency_overrides[get_identity_provider] = emp004_identity_provider
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id, _, _ = await _reach_tc002_action_required(
            app,
            client,
            migrated_database_url,
            idempotency_key="tc002-before-replacement",
        )
        replacement = await client.post(
            f"/v1/claims/{claim_id}/actions",
            headers={
                "X-Dev-Username": "member.emp004",
                "Idempotency-Key": "tc002-readable-replacement",
            },
            data={
                "command": json.dumps(
                    {
                        "type": "REPLACE_DOCUMENT",
                        "expected_version": 1,
                        "client_document_id": "F004",
                    }
                )
            },
            files={
                "file": (
                    "clear-pharmacy-bill.jpg",
                    _document_jpeg("PHARMACY BILL", "Sneha Reddy"),
                    "image/jpeg",
                )
            },
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp004"},
        )

    assert replacement.status_code == 200
    assert replacement.json()["version"] == 2
    assert replacement.json()["lifecycle_status"] == "QUEUED"
    assert projection.status_code == 200
    assert projection.json()["version"] == 2
    assert projection.json()["lifecycle_status"] == "QUEUED"
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
        original_triage = (
            await session.scalars(
                select(DocumentTriageResultRow).where(
                    DocumentTriageResultRow.claim_id == claim_id,
                    DocumentTriageResultRow.claim_version == 1,
                )
            )
        ).all()
    assert [version.version for version in versions] == [1, 2]
    assert versions[1].submission["source"] == "DOCUMENT_REPLACEMENT"
    assert versions[1].submission["previous_version"] == 1
    assert [item.status for item in work] == ["COMPLETED", "AVAILABLE"]
    assert len(original_triage) == 2
    assert any(item.readability == "UNREADABLE" for item in original_triage)
    await app.state.engine.dispose()


async def _reach_tc002_action_required(
    app,
    client: AsyncClient,
    migrated_database_url: str,
    *,
    idempotency_key: str,
) -> tuple[UUID, bytes, PostgresWorkflowRepository]:
    prescription = _document_jpeg("PRESCRIPTION", "Sneha Reddy")
    unreadable_bill = degrade_to_unreadable_jpeg(
        _document_jpeg("PHARMACY BILL", "Sneha Reddy")
    )
    submitted = await client.post(
        "/v1/claims",
        headers={
            "X-Dev-Username": "member.emp004",
            "Idempotency-Key": idempotency_key,
        },
        data={"metadata": json.dumps(_metadata())},
        files=[
            ("files", ("first.jpg", prescription, "image/jpeg")),
            ("files", ("second.jpg", unreadable_bill, "image/jpeg")),
        ],
    )
    assert submitted.status_code == 202, submitted.text
    claim_id = UUID(submitted.json()["claim_id"])
    await StructuredComponentFixtureAdapter(app.state.session_factory).seed_tc002_triage(
        claim_id,
        1,
        prescription_preview_sha256=sha256(prescription).hexdigest(),
        bill_preview_sha256=sha256(unreadable_bill).hexdigest(),
    )
    workflows = PostgresWorkflowRepository(app.state.session_factory)
    runtime = LangGraphClaimWorkflow(
        migrated_database_url,
        workflows,
        processor=PostgresClaimProcessor(app.state.session_factory),
    )
    await runtime.setup()
    assert await WorkerService(PostgresWorkScheduler(app.state.session_factory)).run_once(
        "tc002-worker",
        ClaimWorkflowProcessor(workflows, runtime).process,
    )
    return claim_id, unreadable_bill, workflows


async def _work_item_id(app) -> UUID:
    async with app.state.session_factory() as session:
        return (await session.scalars(select(ClaimWorkItemRow.id))).one()


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP004",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "PHARMACY",
        "treatment_date": "2024-10-25",
        "claimed_amount": "800.00",
        "currency": "INR",
        "documents": [
            {"upload_index": 0, "client_document_id": "F003"},
            {"upload_index": 1, "client_document_id": "F004"},
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
