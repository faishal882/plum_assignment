import asyncio
import json
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from claims_backend.api.app import create_app
from claims_backend.application.setup_import import SetupDataApplication
from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.infrastructure.fixtures.structured_components import (
    StructuredComponentFixtureAdapter,
)
from claims_backend.infrastructure.langgraph_workflow import LangGraphClaimWorkflow
from claims_backend.infrastructure.postgres.claim_processor import (
    PostgresClaimProcessor,
)
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)
from claims_backend.infrastructure.postgres.work_scheduler import (
    PostgresWorkScheduler,
)
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)

POLICY_BYTES = Path("problem_statement/policy_terms.json").read_bytes()


@pytest.mark.asyncio
async def test_tc009_routes_pinned_history_signal_through_durable_review(
    migrated_database_url: str,
    tmp_path,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _import_tc009_history(factory)
    app = create_app(
        Settings(database_url=migrated_database_url, data_root=tmp_path)
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp008",
                "Idempotency-Key": "tc009-structured",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("F017.pdf", _pdf_bytes(), "application/pdf")),
                ("files", ("F018.pdf", _pdf_bytes(), "application/pdf")),
            ],
        )
        assert submitted.status_code == 202, submitted.text
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
        assert await WorkerService(
            PostgresWorkScheduler(app.state.session_factory)
        ).run_once(
            "tc009-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )
        trace = await processor.inspect_trace(claim_id)

        member_projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp008"},
        )
        forbidden = await client.get(
            "/v1/review-tasks",
            headers={"X-Dev-Username": "member.emp008"},
        )
        listed = await client.get(
            "/v1/review-tasks",
            headers={"X-Dev-Username": "reviewer.local"},
        )
        task_id = UUID(listed.json()[0]["id"])
        detail = await client.get(
            f"/v1/review-tasks/{task_id}",
            headers={"X-Dev-Username": "reviewer.local"},
        )
        missing_key = await client.post(
            f"/v1/review-tasks/{task_id}/commands",
            headers={"X-Dev-Username": "reviewer.local"},
            json={
                "action": "ACCEPT",
                "expected_claim_version": 1,
                "reason_code": "HISTORY_VERIFIED",
                "reason_note": "The same-day claims were verified as legitimate.",
            },
        )
        unstructured_reason = await client.post(
            f"/v1/review-tasks/{task_id}/commands",
            headers={
                "X-Dev-Username": "reviewer.local",
                "Idempotency-Key": "tc009-short-reason",
            },
            json={
                "action": "ACCEPT",
                "expected_claim_version": 1,
                "reason_code": "HISTORY_VERIFIED",
                "reason_note": "short",
            },
        )
        resolved = await client.post(
            f"/v1/review-tasks/{task_id}/commands",
            headers={
                "X-Dev-Username": "reviewer.local",
                "Idempotency-Key": "tc009-accept",
            },
            json={
                "action": "ACCEPT",
                "expected_claim_version": 1,
                "reason_code": "HISTORY_VERIFIED",
                "reason_note": "The same-day claims were verified as legitimate.",
            },
        )
        replay = await client.post(
            f"/v1/review-tasks/{task_id}/commands",
            headers={
                "X-Dev-Username": "reviewer.local",
                "Idempotency-Key": "tc009-accept",
            },
            json={
                "action": "ACCEPT",
                "expected_claim_version": 1,
                "reason_code": "HISTORY_VERIFIED",
                "reason_note": "The same-day claims were verified as legitimate.",
            },
        )
        conflicting = await client.post(
            f"/v1/review-tasks/{task_id}/commands",
            headers={
                "X-Dev-Username": "reviewer.local",
                "Idempotency-Key": "tc009-reject-after-accept",
            },
            json={
                "action": "REJECT",
                "expected_claim_version": 1,
                "reason_code": "UNSUPPORTED_PATTERN",
                "reason_note": "A competing resolution must not be accepted.",
            },
        )
        reused_key = await client.post(
            f"/v1/review-tasks/{task_id}/commands",
            headers={
                "X-Dev-Username": "reviewer.local",
                "Idempotency-Key": "tc009-accept",
            },
            json={
                "action": "REJECT",
                "expected_claim_version": 1,
                "reason_code": "UNSUPPORTED_PATTERN",
                "reason_note": "This differs from the accepted idempotent command.",
            },
        )
        final_projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp008"},
        )

    assert trace is not None
    assert [
        item.history_claim_id for item in trace.casefile.content.same_day_history
    ] == ["CLM_0081", "CLM_0082", "CLM_0083"]
    assert all(
        item.evidence_ref.startswith("claim-history:")
        for item in trace.casefile.content.same_day_history
    )
    assert member_projection.status_code == 200
    member = member_projection.json()
    assert member["lifecycle_status"] == "IN_REVIEW"
    assert member["handling_status"] == "MANUAL_REVIEW"
    assert member["progress"] == {
        "current_stage": "IN_REVIEW",
        "is_terminal": False,
    }
    assert "adjudication" not in member
    member_json = json.dumps(member).casefold()
    assert "city clinic" not in member_json
    assert "wellness center" not in member_json
    assert "same_day_claim_velocity" not in member_json

    assert forbidden.status_code == 403
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    task = listed.json()[0]
    assert task["signal_codes"] == ["SAME_DAY_CLAIM_VELOCITY"]
    assert task["machine_recommendation"] == "APPROVED"
    assert task["machine_approved_amount"] == "4320.00"
    assert task["allowed_actions"] == [
        "ACCEPT",
        "AMEND",
        "REJECT",
        "REQUEST_DOCUMENT",
    ]

    assert detail.status_code == 200
    reviewer_detail = detail.json()
    assert reviewer_detail["evidence"]
    assert reviewer_detail["rules"]
    assert reviewer_detail["calculations"]
    assert "conflicts" in reviewer_detail
    assert "failures" in reviewer_detail
    signal = next(
        rule
        for rule in reviewer_detail["rules"]
        if rule["reason_code"] == "SAME_DAY_CLAIM_VELOCITY"
    )
    assert signal["inputs"]["prior_same_day_claims"] == 3
    assert len(signal["evidence_refs"]) == 3

    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert unstructured_reason.status_code == 422
    assert resolved.status_code == 200
    assert resolved.json()["replayed"] is False
    assert resolved.json()["before"]["machine_approved_paise"] == 432_000
    assert resolved.json()["after"]["approved_paise"] == 432_000
    assert resolved.json()["actor_username"] == "reviewer.local"
    assert replay.status_code == 200
    assert replay.json()["id"] == resolved.json()["id"]
    assert replay.json()["replayed"] is True
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "REVIEW_TASK_NOT_OPEN"
    assert reused_key.status_code == 409
    assert reused_key.json()["error"]["code"] == (
        "REVIEW_IDEMPOTENCY_KEY_REUSED"
    )

    final = final_projection.json()
    assert final["lifecycle_status"] == "DECIDED"
    assert final["handling_status"] == "HUMAN_REVIEW_RESOLVED"
    assert final["adjudication"] == {
        "recommendation": "APPROVED",
        "approved_amount": "4320.00",
        "currency": "INR",
    }
    await app.state.engine.dispose()
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "extra", "expected_lifecycle", "expected_recommendation", "expected_amount"),
    [
        ("AMEND", {"amended_amount": "3000.00"}, "DECIDED", "PARTIAL", "3000.00"),
        ("REJECT", {}, "DECIDED", "REJECTED", "0.00"),
        ("REQUEST_DOCUMENT", {}, "ACTION_REQUIRED", None, None),
    ],
)
async def test_review_actions_apply_only_their_allowed_transition(
    migrated_database_url: str,
    tmp_path,
    action: str,
    extra: dict[str, str],
    expected_lifecycle: str,
    expected_recommendation: str | None,
    expected_amount: str | None,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _import_tc009_history(factory)
    app = create_app(
        Settings(database_url=migrated_database_url, data_root=tmp_path)
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id, task_id = await _create_tc009_review(
            app,
            client,
            factory,
            migrated_database_url,
            suffix=action.casefold(),
        )
        stale = await client.post(
            f"/v1/review-tasks/{task_id}/commands",
            headers={
                "X-Dev-Username": "reviewer.local",
                "Idempotency-Key": f"{action.casefold()}-stale",
            },
            json={
                "action": action,
                "expected_claim_version": 2,
                "reason_code": "REVIEW_VERIFIED",
                "reason_note": "The reviewer verified the complete claim evidence.",
                **extra,
            },
        )
        resolved = await client.post(
            f"/v1/review-tasks/{task_id}/commands",
            headers={
                "X-Dev-Username": "reviewer.local",
                "Idempotency-Key": f"{action.casefold()}-resolve",
            },
            json={
                "action": action,
                "expected_claim_version": 1,
                "reason_code": "REVIEW_VERIFIED",
                "reason_note": "The reviewer verified the complete claim evidence.",
                **extra,
            },
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp008"},
        )
        closed = await client.get(
            f"/v1/review-tasks/{task_id}",
            headers={"X-Dev-Username": "reviewer.local"},
        )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_CLAIM_VERSION"
    assert resolved.status_code == 200
    assert resolved.json()["action"] == action
    assert resolved.json()["before"]["machine_recommendation"] == "APPROVED"
    assert resolved.json()["before"]["machine_approved_paise"] == 432_000
    body = projection.json()
    assert body["lifecycle_status"] == expected_lifecycle
    if expected_recommendation is None:
        assert "adjudication" not in body
        assert body["action"]["code"] == "REVIEW_DOCUMENT_REQUIRED"
    else:
        assert body["adjudication"]["recommendation"] == expected_recommendation
        assert body["adjudication"]["approved_amount"] == expected_amount
    assert closed.json()["task"]["status"] == "RESOLVED"
    assert closed.json()["task"]["allowed_actions"] == []
    await app.state.engine.dispose()
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_review_commands_produce_one_resolution(
    migrated_database_url: str,
    tmp_path,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _import_tc009_history(factory)
    app = create_app(
        Settings(database_url=migrated_database_url, data_root=tmp_path)
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        claim_id, task_id = await _create_tc009_review(
            app,
            client,
            factory,
            migrated_database_url,
            suffix="concurrent",
        )

        async def command(action: str):
            return await client.post(
                f"/v1/review-tasks/{task_id}/commands",
                headers={
                    "X-Dev-Username": "reviewer.local",
                    "Idempotency-Key": f"concurrent-{action.casefold()}",
                },
                json={
                    "action": action,
                    "expected_claim_version": 1,
                    "reason_code": "CONCURRENT_VERIFIED",
                    "reason_note": "This concurrent command has a structured reason.",
                },
            )

        first, second = await asyncio.gather(
            command("ACCEPT"),
            command("REJECT"),
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp008"},
        )

    assert sorted([first.status_code, second.status_code]) == [200, 409]
    winner = first if first.status_code == 200 else second
    final = projection.json()["adjudication"]
    if winner.json()["action"] == "ACCEPT":
        assert final["recommendation"] == "APPROVED"
        assert final["approved_amount"] == "4320.00"
    else:
        assert final["recommendation"] == "REJECTED"
        assert final["approved_amount"] == "0.00"
    await app.state.engine.dispose()
    await engine.dispose()


async def _create_tc009_review(
    app,
    client: AsyncClient,
    factory: async_sessionmaker,
    migrated_database_url: str,
    *,
    suffix: str,
) -> tuple[UUID, UUID]:
    submitted = await client.post(
        "/v1/claims",
        headers={
            "X-Dev-Username": "member.emp008",
            "Idempotency-Key": f"tc009-{suffix}",
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
    runtime = LangGraphClaimWorkflow(
        migrated_database_url,
        workflows,
        processor=PostgresClaimProcessor(app.state.session_factory),
    )
    await runtime.setup()
    assert await WorkerService(
        PostgresWorkScheduler(app.state.session_factory)
    ).run_once(
        f"tc009-{suffix}-worker",
        ClaimWorkflowProcessor(workflows, runtime).process,
    )
    listed = await client.get(
        "/v1/review-tasks",
        headers={"X-Dev-Username": "reviewer.local"},
    )
    assert listed.status_code == 200
    return claim_id, UUID(listed.json()[0]["id"])


async def _import_tc009_history(
    factory: async_sessionmaker,
) -> None:
    await SetupDataApplication(PostgresSetupImportRepository(factory)).import_sources(
        POLICY_BYTES,
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
