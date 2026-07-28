from hashlib import sha256
from io import BytesIO
from os import environ
from pathlib import Path
from uuid import UUID

import boto3
import pytest
from botocore.config import Config
from PIL import Image, ImageDraw

from claims_backend.application.casefiles import CasefileBuildRequest, build_casefile
from claims_backend.application.intelligence import RenderedPage
from claims_backend.config import Settings
from claims_backend.domain.evidence import DocumentRole
from claims_backend.domain.ocr import OcrObservation
from claims_backend.domain.reconciliation import (
    EvidenceCandidateSource,
    EvidenceSourceType,
    ProvenancedEvidenceCandidate,
    reconcile_evidence,
)
from claims_backend.infrastructure.aws.bedrock import ChatBedrockConverseTransport
from claims_backend.infrastructure.aws.textract import TextractAdapter
from claims_backend.model.application import (
    ComplexExtractionResult,
    StructuredModelApplication,
)
from claims_backend.model.routing import ModelRouter
from claims_backend.policy.adjudicator import DeterministicPolicyAdjudicator
from claims_backend.policy.compiler import PolicyCompiler

pytestmark = [
    pytest.mark.live_aws,
    pytest.mark.skipif(
        environ.get("CLAIMS_RUN_LIVE_AWS") != "1",
        reason="Set CLAIMS_RUN_LIVE_AWS=1 to permit the synthetic AWS E2E test.",
    ),
]
_SETTINGS = Settings.from_env()
_POLICY_BYTES = Path("problem_statement/policy_terms.json").read_bytes()
_OVERLAY_BYTES = Path("config/policy/assignment-overlay-v1.json").read_bytes()
_MATERIAL_PATHS = (
    "billing.total",
    "claim.claimed_amount",
    "clinical.condition",
    "member.join_date",
    "patient.name",
    "treatment.date",
)


@pytest.mark.asyncio
async def test_live_tc004_intelligence_preserves_exact_policy_result() -> None:
    textract = TextractAdapter(
        boto3.client(
            "textract",
            region_name=_SETTINGS.aws_region,
            config=Config(
                connect_timeout=30,
                read_timeout=30,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
    )
    prescription = _page(
        "PRESCRIPTION\nPatient: Rajesh Kumar\nDate: 2024-11-01\nDiagnosis: Viral Fever",
        7,
    )
    bill = _page(
        (
            "HOSPITAL BILL\nPatient: Rajesh Kumar\nDate: 2024-11-01\n"
            "Consultation Fee 1000\nCBC Test 300\nDengue NS1 Test 200\nTotal 1500"
        ),
        8,
    )
    prescription_ocr = textract.analyze(prescription, DocumentRole.PRESCRIPTION)
    bill_ocr = textract.analyze(bill, DocumentRole.HOSPITAL_BILL)
    repository = _MemoryModelRepository()
    model = StructuredModelApplication(
        ModelRouter.default(
            region=_SETTINGS.bedrock_region,
            model_id=_SETTINGS.bedrock_model_id,
        ),
        ChatBedrockConverseTransport(),
        repository,
    )
    extracted = (
        await model.extract_complex(
            prescription.document_version_id,
            prescription_ocr.observations,
        ),
        await model.extract_complex(
            bill.document_version_id,
            bill_ocr.observations,
        ),
    )
    candidates = [
        candidate
        for result, observations in (
            (extracted[0], prescription_ocr.observations),
            (extracted[1], bill_ocr.observations),
        )
        for candidate in _provenanced(result, observations)
    ]
    candidates.extend(
        (
            _trusted("claim.claimed_amount", 150_000, "claim:tc004"),
            _trusted("treatment.date", "2024-11-01", "claim:tc004"),
            _trusted("patient.name", "Rajesh Kumar", "member:EMP001"),
            _trusted("member.join_date", "2024-04-01", "member:EMP001"),
        )
    )
    reconciliation = reconcile_evidence(
        tuple(candidates),
        material_fact_paths=_MATERIAL_PATHS,
    )
    assert reconciliation.sufficiency.sufficient
    compilation = PolicyCompiler().compile(_POLICY_BYTES, _OVERLAY_BYTES)
    assert compilation.ir is not None
    casefile = build_casefile(
        CasefileBuildRequest(
            claim_id=UUID("00000000-0000-0000-0000-000000000404"),
            claim_version=1,
            member_id="EMP001",
            member_version_id=UUID("00000000-0000-0000-0000-000000000401"),
            member_snapshot_sha256="a" * 64,
            policy_version_id=UUID("00000000-0000-0000-0000-000000000402"),
            category="CONSULTATION",
            claimed_paise=150_000,
            currency="INR",
            eligibility_evidence_ref="member:EMP001",
            document_roles=("PRESCRIPTION", "HOSPITAL_BILL"),
            document_role_evidence_refs=("live:F007", "live:F008"),
            ytd_used_paise=500_000,
            utilization_evidence_ref="utilization:tc004",
            reconciliation=reconciliation,
        )
    )

    proposal = DeterministicPolicyAdjudicator().evaluate(casefile, compilation.ir)

    assert proposal.recommendation.value == "APPROVED"
    assert proposal.approved_paise == 135_000
    assert proposal.rule_results[-1].reason_code == "CATEGORY_COPAY_APPLIED"


class _MemoryModelRepository:
    def __init__(self) -> None:
        self.results: dict[UUID, ComplexExtractionResult] = {}

    async def find(self, document_version_id, config, input_sha256):
        del config, input_sha256
        return self.results.get(document_version_id)

    async def save(self, result: ComplexExtractionResult) -> ComplexExtractionResult:
        self.results[result.document_version_id] = result
        return result


def _page(text: str, suffix: int) -> RenderedPage:
    content = _image(text)
    digest = sha256(content).hexdigest()
    return RenderedPage(
        document_id=UUID(f"00000000-0000-0000-0000-{suffix:012d}"),
        document_version_id=UUID(f"10000000-0000-0000-0000-{suffix:012d}"),
        page_number=1,
        original_sha256=digest,
        media_type="image/jpeg",
        content=content,
        sha256=digest,
        size_bytes=len(content),
        width=1200,
        height=900,
        render_version="live-tc004-v1",
    )


def _image(text: str) -> bytes:
    image = Image.new("RGB", (1200, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text((70, 70), text, fill="black", spacing=24)
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


def _provenanced(
    result: ComplexExtractionResult,
    observations: tuple[OcrObservation, ...],
) -> tuple[ProvenancedEvidenceCandidate, ...]:
    by_id = {observation.observation_id: observation for observation in observations}
    return tuple(
        ProvenancedEvidenceCandidate(
            candidate_id=candidate.candidate_id,
            fact_path=candidate.fact_path,
            value=candidate.value,
            normalized_value=candidate.normalized_value,
            producer=candidate.producer,
            producer_version=f"{candidate.model_id}:{candidate.prompt_version}",
            schema_version=candidate.schema_version,
            confidence=candidate.confidence,
            sources=tuple(
                EvidenceCandidateSource(
                    source_type=EvidenceSourceType.DOCUMENT,
                    source_ref=f"ocr:{observation_id}",
                    source_sha256=sha256(by_id[observation_id].text.encode()).hexdigest(),
                    observation_id=observation_id,
                    document_version_id=by_id[observation_id].document_version_id,
                    page=by_id[observation_id].page_number,
                    region=by_id[observation_id].region,
                )
                for observation_id in candidate.evidence_refs
            ),
        )
        for candidate in result.candidates
    )


def _trusted(
    fact_path: str,
    value: str | int,
    source_ref: str,
) -> ProvenancedEvidenceCandidate:
    source_hash = sha256(source_ref.encode()).hexdigest()
    candidate_id = sha256(f"{fact_path}:{value}:{source_ref}".encode()).hexdigest()
    source_type = (
        EvidenceSourceType.CLAIM_SNAPSHOT
        if source_ref.startswith("claim:")
        else EvidenceSourceType.MEMBER_SNAPSHOT
    )
    return ProvenancedEvidenceCandidate(
        candidate_id=candidate_id,
        fact_path=fact_path,
        value=value,
        normalized_value=value,
        producer=source_type.value,
        producer_version="live-synthetic-v1",
        schema_version="trusted-snapshot-v1",
        confidence=1,
        sources=(
            EvidenceCandidateSource(
                source_type=source_type,
                source_ref=source_ref,
                source_sha256=source_hash,
            ),
        ),
    )
