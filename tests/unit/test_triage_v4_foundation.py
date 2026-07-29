from uuid import UUID

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from claims_backend.domain.evidence import (
    DocumentRole,
    NormalizedRegion,
    PreviewProvenance,
    Readability,
    TriageEvidenceNormalizationCode,
    TriageProviderOutputV4,
)
from claims_backend.domain.ocr import OcrObservation, OcrObservationKind
from claims_backend.domain.workflow import ExecutionContract
from claims_backend.infrastructure.postgres.claim_processor import PostgresClaimProcessor
from claims_backend.model.application import (
    StructuredModelApplication,
    fast_triage_system_prompt,
    triage_output_schema,
)
from claims_backend.model.evidence_normalization import (
    resolve_evidence_reference_policy,
)
from claims_backend.model.routing import ModelRouter
from claims_backend.model.transport import ModelInvocation
from claims_backend.model.triage import TriageDocumentContext, resolve_triage_with_reports
from claims_backend.observability import ObservabilityConfig, create_observability


def test_default_fast_triage_route_uses_the_versioned_v4_contract() -> None:
    route = ModelRouter.default(
        region="ap-south-1",
        model_id="recorded-model",
    ).resolve_fast_triage()

    assert route.prompt_version == "fast-triage-prompt-v3"
    assert route.schema_version == "triage-provider-output-v4"
    assert triage_output_schema(route) is TriageProviderOutputV4
    assert resolve_evidence_reference_policy(route.evidence_policy_version).version == (
        "triage-evidence-policy-v1"
    )


def test_fast_triage_v3_prompt_requests_ordered_concise_evidence() -> None:
    route = ModelRouter.default(
        region="ap-south-1",
        model_id="recorded-model",
    ).resolve_fast_triage()
    prompt = fast_triage_system_prompt(route)

    assert "1–5" in prompt
    assert "strongest to weakest" in prompt
    assert "Do not cite every OCR line" in prompt
    assert "never create, alter, or infer an ID" in prompt


def test_v4_execution_contract_pins_the_evidence_policy() -> None:
    contract = ExecutionContract(
        schema_version="execution-contract-v1",
        execution_profile="RECORDED_LOCAL",
        ocr_provider_name="RECORDED_DISCOVERY_OCR",
        ocr_provider_version="recorded-discovery-v1",
        model_provider_name="RECORDED_DOCUMENT_MODEL",
        model_provider_version="recorded-document-v1",
        model_routes=(
            (
                "FAST_TRIAGE",
                "recorded-model",
                "ap-south-1",
                "fast-triage-prompt-v3",
                "triage-provider-output-v4",
            ),
            (
                "COMPLEX_EXTRACTION",
                "recorded-model",
                "ap-south-1",
                "complex-extraction-prompt-v4",
                "complex-extraction-v1",
            ),
        ),
        triage_evidence_policy_version="triage-evidence-policy-v1",
    )

    rebuilt = ModelRouter.from_execution_contract(contract).resolve_fast_triage()

    assert contract.as_dict()["triage_evidence_policy_version"] == "triage-evidence-policy-v1"
    assert rebuilt.evidence_policy_version == "triage-evidence-policy-v1"


def test_v4_normal_response_persists_an_unchanged_normalization_report() -> None:
    observation = OcrObservation(
        observation_id="a" * 64,
        document_version_id=UUID("10000000-0000-0000-0000-000000000001"),
        page_number=1,
        kind=OcrObservationKind.LINE,
        text="HOSPITAL BILL",
        confidence=0.98,
        region=NormalizedRegion(x=0.1, y=0.1, width=0.4, height=0.1),
        source_id="source-1",
    )
    output = TriageProviderOutputV4.model_validate(
        {
            "schema_version": 4,
            "documents": [
                {
                    "client_document_id": "document-1",
                    "role": DocumentRole.HOSPITAL_BILL,
                    "role_evidence_refs": [observation.observation_id],
                    "readability": Readability.READABLE,
                    "readability_evidence_refs": [observation.observation_id],
                    "identity_observations": [],
                }
            ],
        }
    )
    policy = resolve_evidence_reference_policy("triage-evidence-policy-v1")

    resolved = resolve_triage_with_reports(
        output,
        (
            TriageDocumentContext(
                client_document_id="document-1",
                document_version_id=observation.document_version_id,
                observations=(observation,),
                previews_by_page={
                    1: PreviewProvenance(
                        page=1,
                        sha256="b" * 64,
                        transform_version="pymupdf-v1",
                    )
                },
            ),
        ),
        policy=policy,
    )

    report = resolved.normalization_reports["document-1"]
    assert resolved.output.schema_version == 3
    assert resolved.output.documents[0].readability.preview.page == 1
    assert report.policy_version == "triage-evidence-policy-v1"
    assert report.role.retained_refs == (observation.observation_id,)
    assert report.readability.retained_refs == (observation.observation_id,)
    assert report.role.codes == ()
    assert report.readability.codes == ()


def test_v4_valid_overcitation_retains_five_and_records_the_complete_audit() -> None:
    document_version_id = UUID("10000000-0000-0000-0000-000000000003")
    observations = tuple(
        OcrObservation(
            observation_id=f"{index:064x}",
            document_version_id=document_version_id,
            page_number=1,
            kind=OcrObservationKind.LINE,
            text=f"Bill line {index}",
            confidence=0.98,
            region=NormalizedRegion(x=0.1, y=0.1, width=0.4, height=0.1),
            source_id=f"source-{index}",
        )
        for index in range(30)
    )
    references = tuple(observation.observation_id for observation in observations)
    output = TriageProviderOutputV4.model_validate(
        {
            "schema_version": 4,
            "documents": [
                {
                    "client_document_id": "document-30",
                    "role": "HOSPITAL_BILL",
                    "role_evidence_refs": references,
                    "readability": "READABLE",
                    "readability_evidence_refs": references,
                    "identity_observations": [],
                }
            ],
        }
    )

    resolved = resolve_triage_with_reports(
        output,
        (
            TriageDocumentContext(
                client_document_id="document-30",
                document_version_id=document_version_id,
                observations=observations,
                previews_by_page={
                    1: PreviewProvenance(
                        page=1,
                        sha256="b" * 64,
                        transform_version="pymupdf-v1",
                    )
                },
            ),
        ),
        policy=resolve_evidence_reference_policy("triage-evidence-policy-v1"),
    )

    document = resolved.output.documents[0]
    report = resolved.normalization_reports["document-30"]
    assert document.role_evidence_refs == references[:5]
    assert document.readability_evidence_refs == references[:5]
    assert document.readability.preview.page == 1
    assert report.role.received_refs == references
    assert report.role.unique_refs == references
    assert report.role.retained_refs == references[:5]
    assert report.role.over_citation_dropped_refs == references[5:]
    assert report.role.duplicate_dropped_refs == ()
    assert report.role.codes == (TriageEvidenceNormalizationCode.TRUNCATED,)
    assert report.readability.over_citation_dropped_refs == references[5:]


async def test_fast_triage_v4_uses_provider_schema_and_stable_raw_output_digest() -> None:
    payload = _provider_payload()
    transport = _Transport(payload)
    application = StructuredModelApplication(
        ModelRouter.default(region="ap-south-1", model_id="recorded-model"),
        transport,
        _Repository(),
    )

    result = await application.fast_triage([("system", "prompt"), ("human", "document")])

    assert transport.schema is TriageProviderOutputV4
    assert transport.calls == 1
    assert result.output.schema_version == 4
    assert (
        result.raw_output_sha256
        == "31898026f8526eb47308dc0ed74fb24ca22c85417db9cad678ae1d52775e8f3e"
    )

    reordered = {"documents": payload["documents"], "schema_version": 4}
    replay = StructuredModelApplication(
        ModelRouter.default(region="ap-south-1", model_id="recorded-model"),
        _Transport(reordered),
        _Repository(),
    )
    replay_result = await replay.fast_triage([("system", "prompt"), ("human", "document")])

    assert replay_result.raw_output_sha256 == result.raw_output_sha256


class _Transport:
    def __init__(self, raw_output: dict[str, object]) -> None:
        self._raw_output = raw_output
        self.schema: type[object] | None = None
        self.calls = 0

    def invoke(self, config, schema, messages) -> ModelInvocation:
        del config, messages
        self.calls += 1
        self.schema = schema
        return ModelInvocation(
            raw_output=self._raw_output,
            provider_request_id="recorded-request",
            input_tokens=1,
            output_tokens=1,
            latency_ms=0,
            stop_reason="RECORDED",
        )


class _Repository:
    pass


def _provider_payload() -> dict[str, object]:
    return {
        "schema_version": 4,
        "documents": [
            {
                "client_document_id": "document-1",
                "role": "HOSPITAL_BILL",
                "role_evidence_refs": ["a" * 64],
                "readability": "READABLE",
                "readability_evidence_refs": ["a" * 64],
                "identity_observations": [],
            }
        ],
    }


def test_normalization_trace_contains_canonical_audit_attributes(tmp_path) -> None:
    exporter = InMemorySpanExporter()
    observability = create_observability(
        ObservabilityConfig(log_root=tmp_path),
        process_name="worker",
        span_exporter=exporter,
    )
    observation_id = "a" * 64
    report = resolve_triage_with_reports(
        TriageProviderOutputV4.model_validate(
            {
                "schema_version": 4,
                "documents": [
                    {
                        "client_document_id": "document-1",
                        "role": "HOSPITAL_BILL",
                        "role_evidence_refs": [observation_id],
                        "readability": "READABLE",
                        "readability_evidence_refs": [observation_id],
                        "identity_observations": [],
                    }
                ],
            }
        ),
        (_context(observation_id),),
        policy=resolve_evidence_reference_policy("triage-evidence-policy-v1"),
    ).normalization_reports["document-1"]
    processor = PostgresClaimProcessor(None, observability=observability)  # type: ignore[arg-type]

    processor._trace_triage_normalization(  # noqa: SLF001
        reports={"document-1": report},
        raw_output_sha256="b" * 64,
        model_route="FAST_TRIAGE",
        model_id="recorded-model",
        prompt_version="fast-triage-prompt-v3",
        provider_schema_version="triage-provider-output-v4",
    )
    spans = exporter.get_finished_spans()
    observability.shutdown()

    assert len(spans) == 1
    attributes = spans[0].attributes
    assert attributes["triage.normalization.outcome"] == "UNCHANGED"
    assert attributes["triage.normalization.received_count"] == 2
    assert attributes["triage.normalization.retained_count"] == 2
    assert attributes["model.prompt_version"] == "fast-triage-prompt-v3"
    assert attributes["triage.raw_output_sha256"] == "b" * 64
    assert observation_id in str(attributes["triage.normalization.reports"])


def _context(observation_id: str) -> TriageDocumentContext:
    document_version_id = UUID("10000000-0000-0000-0000-000000000002")
    return TriageDocumentContext(
        client_document_id="document-1",
        document_version_id=document_version_id,
        observations=(
            OcrObservation(
                observation_id=observation_id,
                document_version_id=document_version_id,
                page_number=1,
                kind=OcrObservationKind.LINE,
                text="HOSPITAL BILL",
                confidence=0.98,
                region=NormalizedRegion(x=0.1, y=0.1, width=0.4, height=0.1),
                source_id="source-1",
            ),
        ),
        previews_by_page={
            1: PreviewProvenance(
                page=1,
                sha256="b" * 64,
                transform_version="pymupdf-v1",
            )
        },
    )
