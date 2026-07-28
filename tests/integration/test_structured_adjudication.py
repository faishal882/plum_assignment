import json
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from claims_backend.api.app import create_app
from claims_backend.application.setup_import import SetupDataApplication
from claims_backend.application.work import WorkerService
from claims_backend.application.workflow import ClaimWorkflowProcessor
from claims_backend.config import Settings
from claims_backend.infrastructure.fixtures.structured_components import (
    StructuredComponentFixtureAdapter,
)
from claims_backend.infrastructure.langgraph_workflow import LangGraphClaimWorkflow
from claims_backend.infrastructure.postgres.claim_processor import PostgresClaimProcessor
from claims_backend.infrastructure.postgres.models import (
    AuditEventRow,
    ClaimRow,
    ClaimWorkItemRow,
    DecisionRecordRow,
    RuleResultRow,
    WorkflowRunRow,
)
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)
from claims_backend.infrastructure.postgres.work_scheduler import PostgresWorkScheduler
from claims_backend.infrastructure.postgres.workflow_repository import (
    PostgresWorkflowRepository,
)

POLICY_BYTES = Path("problem_statement/policy_terms.json").read_bytes()


@pytest.mark.asyncio
async def test_tc004_structured_fixture_commits_exact_member_decision(
    migrated_database_url: str,
    tmp_path,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    setup = SetupDataApplication(PostgresSetupImportRepository(factory))
    await setup.import_sources(
        POLICY_BYTES,
        source_name="policy_terms.json",
        member_data_bytes=json.dumps(
            {
                "policy_id": "PLUM_GHI_2024",
                "as_of_date": "2024-11-01",
                "claim_history": [],
                "utilization": [
                    {
                        "member_id": "EMP001",
                        "period_start": "2024-04-01",
                        "period_end": "2025-03-31",
                        "used_amount": "5000.00",
                        "currency": "INR",
                        "as_of_date": "2024-11-01",
                    }
                ],
            }
        ).encode(),
        member_data_source_name="tc004-member-facts.json",
    )
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp001",
                "Idempotency-Key": "tc004-structured",
            },
            data={"metadata": json.dumps(_metadata())},
            files=[
                ("files", ("prescription.pdf", _pdf_bytes(), "application/pdf")),
                ("files", ("hospital-bill.pdf", _pdf_bytes(), "application/pdf")),
            ],
        )
        claim_id = UUID(submitted.json()["claim_id"])
        fixtures = StructuredComponentFixtureAdapter(factory)
        await fixtures.seed_tc004(claim_id, claim_version=1)

        scheduler = PostgresWorkScheduler(app.state.session_factory)
        workflows = PostgresWorkflowRepository(app.state.session_factory)
        processor = PostgresClaimProcessor(app.state.session_factory)
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=processor,
        )
        await runtime.setup()
        worker = WorkerService(scheduler)
        assert await worker.run_once(
            "tc004-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )

        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp001"},
        )

    assert projection.status_code == 200
    body = projection.json()
    assert body["lifecycle_status"] == "DECIDED"
    assert body["progress"] == {"current_stage": "DECIDED", "is_terminal": True}
    assert body["adjudication"] == {
        "recommendation": "APPROVED",
        "approved_amount": "1350.00",
        "currency": "INR",
    }
    assert body["explanation"] == {
        "summary": "₹1,350.00 approved after a 10% consultation co-pay.",
        "deductions": [
            {
                "code": "CATEGORY_COPAY_APPLIED",
                "label": "10% consultation co-pay",
                "amount": "150.00",
            }
        ],
    }
    assert "fixture" not in json.dumps(body).casefold()
    assert "provider" not in json.dumps(body).casefold()

    trace = await processor.inspect_trace(claim_id)
    assert trace is not None
    assert trace.decision.canonical_hash
    assert trace.casefile.content_hash
    assert trace.decision.approved_paise == 135_000
    assert [result.amount_after_paise for result in trace.rule_results][-1] == 135_000
    assert all(result.policy_path for result in trace.rule_results)
    assert all(result.evidence_refs for result in trace.rule_results)
    assert trace.work_status == "COMPLETED"
    assert trace.workflow_status == "COMPLETED"

    for table_name in ("processing_fixtures", "casefiles", "decision_records", "rule_results"):
        with pytest.raises(DBAPIError):
            async with factory.begin() as session:
                await session.execute(
                    text(f"DELETE FROM {table_name} WHERE claim_id = :claim_id"),
                    {"claim_id": claim_id},
                )

    await app.state.engine.dispose()
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "case_id",
        "username",
        "member_id",
        "category",
        "treatment_date",
        "claimed_amount",
        "document_ids",
        "expected_reason",
        "summary_fragments",
    ),
    [
        (
            "tc007",
            "member.emp007",
            "EMP007",
            "DIAGNOSTIC",
            "2024-11-02",
            "15000.00",
            ("F012", "F013", "F014"),
            "PRE_AUTH_MISSING",
            ("₹15,000.00", "₹10,000.00", "resubmit"),
        ),
        (
            "tc008",
            "member.emp003",
            "EMP003",
            "CONSULTATION",
            "2024-10-20",
            "7500.00",
            ("F015", "F016"),
            "PER_CLAIM_EXCEEDED",
            ("₹7,500.00", "₹5,000.00"),
        ),
    ],
)
async def test_tc007_and_tc008_structured_tracers(
    migrated_database_url: str,
    tmp_path,
    case_id: str,
    username: str,
    member_id: str,
    category: str,
    treatment_date: str,
    claimed_amount: str,
    document_ids: tuple[str, ...],
    expected_reason: str,
    summary_fragments: tuple[str, ...],
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await SetupDataApplication(PostgresSetupImportRepository(factory)).import_sources(
        POLICY_BYTES,
        source_name="policy_terms.json",
        member_data_bytes=json.dumps(
            {
                "policy_id": "PLUM_GHI_2024",
                "as_of_date": treatment_date,
                "claim_history": [],
                "utilization": [
                    {
                        "member_id": member_id,
                        "period_start": "2024-04-01",
                        "period_end": "2025-03-31",
                        "used_amount": "0.00",
                        "currency": "INR",
                        "as_of_date": treatment_date,
                    }
                ],
            }
        ).encode(),
        member_data_source_name=f"{case_id}-member-facts.json",
    )
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": username,
                "Idempotency-Key": f"{case_id}-structured",
            },
            data={
                "metadata": json.dumps(
                    {
                        "member_id": member_id,
                        "policy_id": "PLUM_GHI_2024",
                        "claim_category": category,
                        "treatment_date": treatment_date,
                        "claimed_amount": claimed_amount,
                        "currency": "INR",
                        "documents": [
                            {
                                "upload_index": index,
                                "client_document_id": document_id,
                            }
                            for index, document_id in enumerate(document_ids)
                        ],
                    }
                )
            },
            files=[
                (
                    "files",
                    (f"{document_id}.pdf", _pdf_bytes(), "application/pdf"),
                )
                for document_id in document_ids
            ],
        )
        assert submitted.status_code == 202
        claim_id = UUID(submitted.json()["claim_id"])
        fixtures = StructuredComponentFixtureAdapter(factory)
        if case_id == "tc007":
            await fixtures.seed_tc007(claim_id, 1)
        else:
            await fixtures.seed_tc008(claim_id, 1)

        scheduler = PostgresWorkScheduler(app.state.session_factory)
        workflows = PostgresWorkflowRepository(app.state.session_factory)
        processor = PostgresClaimProcessor(app.state.session_factory)
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=processor,
        )
        await runtime.setup()
        assert await WorkerService(scheduler).run_once(
            f"{case_id}-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": username},
        )

    assert projection.status_code == 200
    body = projection.json()
    assert body["lifecycle_status"] == "DECIDED"
    assert body["adjudication"] == {
        "recommendation": "REJECTED",
        "approved_amount": "0.00",
        "currency": "INR",
    }
    assert body["explanation"]["deductions"][0]["code"] == expected_reason
    assert all(fragment in body["explanation"]["summary"] for fragment in summary_fragments)
    trace = await processor.inspect_trace(claim_id)
    assert trace is not None
    assert trace.rule_results[-1].reason_code == expected_reason
    assert trace.rule_results[-1].status == "FAIL"
    assert trace.decision.approved_paise == 0

    await app.state.engine.dispose()
    await engine.dispose()


@pytest.mark.asyncio
async def test_tc010_persists_ordered_discount_and_copay_trace(
    migrated_database_url: str,
    tmp_path,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await SetupDataApplication(PostgresSetupImportRepository(factory)).import_sources(
        POLICY_BYTES,
        source_name="policy_terms.json",
        member_data_bytes=json.dumps(
            {
                "policy_id": "PLUM_GHI_2024",
                "as_of_date": "2024-11-03",
                "claim_history": [],
                "utilization": [
                    {
                        "member_id": "EMP010",
                        "period_start": "2024-04-01",
                        "period_end": "2025-03-31",
                        "used_amount": "8000.00",
                        "currency": "INR",
                        "as_of_date": "2024-11-03",
                    }
                ],
            }
        ).encode(),
        member_data_source_name="tc010-member-facts.json",
    )
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/v1/claims",
            headers={
                "X-Dev-Username": "member.emp010",
                "Idempotency-Key": "tc010-structured",
            },
            data={
                "metadata": json.dumps(
                    {
                        "member_id": "EMP010",
                        "policy_id": "PLUM_GHI_2024",
                        "claim_category": "CONSULTATION",
                        "treatment_date": "2024-11-03",
                        "claimed_amount": "4500.00",
                        "currency": "INR",
                        "documents": [
                            {"upload_index": 0, "client_document_id": "F019"},
                            {"upload_index": 1, "client_document_id": "F020"},
                        ],
                    }
                )
            },
            files=[
                ("files", ("F019.pdf", _pdf_bytes(), "application/pdf")),
                ("files", ("F020.pdf", _pdf_bytes(), "application/pdf")),
            ],
        )
        assert submitted.status_code == 202
        claim_id = UUID(submitted.json()["claim_id"])
        await StructuredComponentFixtureAdapter(factory).seed_tc010(claim_id, 1)
        scheduler = PostgresWorkScheduler(app.state.session_factory)
        workflows = PostgresWorkflowRepository(app.state.session_factory)
        processor = PostgresClaimProcessor(app.state.session_factory)
        runtime = LangGraphClaimWorkflow(
            migrated_database_url,
            workflows,
            processor=processor,
        )
        await runtime.setup()
        assert await WorkerService(scheduler).run_once(
            "tc010-worker",
            ClaimWorkflowProcessor(workflows, runtime).process,
        )
        projection = await client.get(
            f"/v1/claims/{claim_id}",
            headers={"X-Dev-Username": "member.emp010"},
        )

    assert projection.status_code == 200
    body = projection.json()
    assert body["adjudication"] == {
        "recommendation": "APPROVED",
        "approved_amount": "3240.00",
        "currency": "INR",
    }
    assert body["explanation"] == {
        "summary": ("₹3,240.00 approved after a 20% network discount and 10% consultation co-pay."),
        "deductions": [
            {
                "code": "NETWORK_DISCOUNT_APPLIED",
                "label": "20% network discount",
                "amount": "900.00",
            },
            {
                "code": "CATEGORY_COPAY_APPLIED",
                "label": "10% consultation co-pay",
                "amount": "360.00",
            },
        ],
    }
    trace = await processor.inspect_trace(claim_id)
    assert trace is not None
    assert trace.casefile.content.provider_name is not None
    assert trace.casefile.content.provider_name.value == "apollo hospitals"
    assert [result.reason_code for result in trace.rule_results[-3:]] == [
        "NETWORK_DISCOUNT_APPLIED",
        "CATEGORY_COPAY_APPLIED",
        "FINAL_APPROVED",
    ]
    assert [result.amount_after_paise for result in trace.rule_results[-3:]] == [
        360_000,
        324_000,
        324_000,
    ]

    await app.state.engine.dispose()
    await engine.dispose()


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_the_entire_terminal_commit(
    migrated_database_url: str,
    tmp_path,
) -> None:
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await _import_tc004_member_facts(factory)
    app = create_app(Settings(database_url=migrated_database_url, data_root=tmp_path))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await _submit_tc004(client, "tc004-audit-rollback")
    claim_id = UUID(submitted.json()["claim_id"])
    await StructuredComponentFixtureAdapter(factory).seed_tc004(claim_id, 1)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                CREATE FUNCTION reject_decision_audit() RETURNS trigger AS $$
                BEGIN
                    IF NEW.event_type = 'CLAIM_DECIDED' THEN
                        RAISE EXCEPTION 'injected decision audit failure'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TRIGGER reject_decision_audit_insert
                BEFORE INSERT ON audit_events
                FOR EACH ROW EXECUTE FUNCTION reject_decision_audit()
                """
            )
        )

    scheduler = PostgresWorkScheduler(app.state.session_factory)
    workflows = PostgresWorkflowRepository(app.state.session_factory)
    runtime = LangGraphClaimWorkflow(
        migrated_database_url,
        workflows,
        processor=PostgresClaimProcessor(app.state.session_factory),
    )
    await runtime.setup()
    try:
        with pytest.raises(DBAPIError):
            await WorkerService(scheduler).run_once(
                "audit-failure-worker",
                ClaimWorkflowProcessor(workflows, runtime).process,
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DROP TRIGGER reject_decision_audit_insert ON audit_events")
            )
            await connection.execute(text("DROP FUNCTION reject_decision_audit()"))

    async with factory() as session:
        claim = (await session.scalars(select(ClaimRow))).one()
        work = (await session.scalars(select(ClaimWorkItemRow))).one()
        workflow = (await session.scalars(select(WorkflowRunRow))).one()
        decision_count = await session.scalar(select(func.count()).select_from(DecisionRecordRow))
        rule_count = await session.scalar(select(func.count()).select_from(RuleResultRow))
        terminal_audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditEventRow)
            .where(AuditEventRow.event_type == "CLAIM_DECIDED")
        )
    assert claim.lifecycle_status == "QUEUED"
    assert claim.adjudication_recommendation is None
    assert claim.approved_paise is None
    assert work.status == "LEASED"
    assert workflow.status == "RUNNING"
    assert decision_count == 0
    assert rule_count == 0
    assert terminal_audit_count == 0
    await app.state.engine.dispose()
    await engine.dispose()


def _metadata() -> dict[str, object]:
    return {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500.00",
        "currency": "INR",
        "documents": [
            {"upload_index": 0, "client_document_id": "F007"},
            {"upload_index": 1, "client_document_id": "F008"},
        ],
    }


async def _import_tc004_member_facts(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await SetupDataApplication(PostgresSetupImportRepository(factory)).import_sources(
        POLICY_BYTES,
        source_name="policy_terms.json",
        member_data_bytes=json.dumps(
            {
                "policy_id": "PLUM_GHI_2024",
                "as_of_date": "2024-11-01",
                "claim_history": [],
                "utilization": [
                    {
                        "member_id": "EMP001",
                        "period_start": "2024-04-01",
                        "period_end": "2025-03-31",
                        "used_amount": "5000.00",
                        "currency": "INR",
                        "as_of_date": "2024-11-01",
                    }
                ],
            }
        ).encode(),
        member_data_source_name="tc004-member-facts.json",
    )


async def _submit_tc004(client: AsyncClient, idempotency_key: str):
    return await client.post(
        "/v1/claims",
        headers={
            "X-Dev-Username": "member.emp001",
            "Idempotency-Key": idempotency_key,
        },
        data={"metadata": json.dumps(_metadata())},
        files=[
            ("files", ("prescription.pdf", _pdf_bytes(), "application/pdf")),
            ("files", ("hospital-bill.pdf", _pdf_bytes(), "application/pdf")),
        ],
    )


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
