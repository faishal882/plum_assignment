import json
from io import BytesIO
from os import environ
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from PIL import Image, ImageDraw, ImageFont

from claims_backend.api.app import create_app
from claims_backend.application.setup_import import SetupDataApplication
from claims_backend.config import Settings
from claims_backend.infrastructure.postgres.setup_import_repository import (
    PostgresSetupImportRepository,
)
from claims_backend.observability import (
    ObservabilityConfig,
    create_observability,
)
from claims_backend.runtime.composition import create_process_runtime
from claims_backend.runtime.profiles import ExecutionProfile
from claims_backend.worker.application import create_claim_worker

pytestmark = [
    pytest.mark.live_aws,
    pytest.mark.skipif(
        environ.get("CLAIMS_RUN_LIVE_AWS") != "1",
        reason="Set CLAIMS_RUN_LIVE_AWS=1 to permit the synthetic AWS worker tracer.",
    ),
]
_POLICY_BYTES = Path("problem_statement/policy_terms.json").read_bytes()
_SETTINGS = Settings.from_env()


@pytest.mark.asyncio
async def test_live_tc004_runs_through_public_api_and_standard_worker(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_url=migrated_database_url,
        data_root=tmp_path / "documents",
        log_root=tmp_path / "logs",
        execution_profile=ExecutionProfile.LIVE_INTELLIGENCE,
        run_live_aws=True,
        aws_region=_SETTINGS.aws_region,
        bedrock_region=_SETTINGS.bedrock_region,
        bedrock_model_id=_SETTINGS.bedrock_model_id,
        observability_enabled=False,
    )
    api_exporter = InMemorySpanExporter()
    worker_exporter = InMemorySpanExporter()
    api_observability = create_observability(
        ObservabilityConfig(log_root=settings.log_root),
        process_name="api",
        span_exporter=api_exporter,
    )
    worker_observability = create_observability(
        ObservabilityConfig(log_root=settings.log_root),
        process_name="worker",
        span_exporter=worker_exporter,
    )
    app = create_app(settings, observability=api_observability)
    runtime = create_process_runtime(
        settings,
        process_name="worker",
        observability=worker_observability,
    )
    worker = create_claim_worker(runtime)
    try:
        await _import_member_facts(runtime.session_factory)
        prescription = _image(
            "PRESCRIPTION\nPatient: Rajesh Kumar\nDate: 2024-11-01\nDiagnosis: Viral Fever"
        )
        bill = _image(
            "HOSPITAL BILL\nPatient: Rajesh Kumar\nDate: 2024-11-01\n"
            "Consultation Fee 1000\nCBC Test 300\nDengue NS1 Test 200\nTotal 1500"
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            submitted = await client.post(
                "/v1/claims",
                headers={
                    "X-Dev-Username": "member.emp001",
                    "Idempotency-Key": "live-tc004-worker-v1",
                },
                data={"metadata": json.dumps(_metadata())},
                files=[
                    ("files", ("prescription.jpg", prescription, "image/jpeg")),
                    ("files", ("hospital-bill.jpg", bill, "image/jpeg")),
                ],
            )
            assert submitted.status_code == 202
            claim_id = UUID(submitted.json()["claim_id"])
            await worker.setup()
            assert await worker.run_once()
            projection = await client.get(
                f"/v1/claims/{claim_id}",
                headers={"X-Dev-Username": "member.emp001"},
            )
        assert projection.status_code == 200
        assert projection.json()["lifecycle_status"] == "DECIDED", projection.json().get("action")
        assert projection.json()["adjudication"] == {
            "recommendation": "APPROVED",
            "approved_amount": "1350.00",
            "currency": "INR",
        }
        api_spans = api_exporter.get_finished_spans()
        worker_spans = worker_exporter.get_finished_spans()
        assert any(
            span.name == "api.claim_submitted"
            and (span.attributes or {}).get("session.id") == str(claim_id)
            for span in api_spans
        )
        assert any(
            span.name == "claim.workflow"
            and (span.attributes or {}).get("session.id") == str(claim_id)
            for span in worker_spans
        )
    finally:
        await worker.close()
        api_observability.shutdown()
        worker_observability.shutdown()
        await app.state.engine.dispose()


async def _import_member_facts(factory: Any) -> None:
    await SetupDataApplication(PostgresSetupImportRepository(factory)).import_sources(
        _POLICY_BYTES,
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
        member_data_source_name="live-tc004-worker-facts-v1.json",
    )


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


def _image(text: str) -> bytes:
    image = Image.new("RGB", (1200, 900), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("DejaVuSans.ttf", size=42)
    draw.multiline_text((70, 70), text, fill="black", spacing=24, font=font)
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()
