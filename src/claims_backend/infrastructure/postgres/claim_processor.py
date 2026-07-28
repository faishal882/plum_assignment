from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.application.intelligence import (
    OcrApplication,
    OcrRepository,
    PageArtifactApplication,
    PageArtifactRepository,
    RenderedPageTooLargeError,
    SourceDocument,
)
from claims_backend.domain.adjudication import (
    AdjudicationProposal,
    ClaimCasefile,
    EvidenceFact,
    FactState,
    RuleResult,
)
from claims_backend.domain.evidence import (
    DocumentRole,
    StructuredEvidencePayload,
    TriageModelOutput,
)
from claims_backend.domain.policy import PolicyIR
from claims_backend.domain.processing import (
    AffectedDocument,
    CasefileTrace,
    ClaimProcessingTrace,
    DecisionTrace,
    EarlyGateResult,
    FrozenCasefileRef,
    IdentityConflictDetail,
    PagePreparationResult,
    ProcessingRoute,
)
from claims_backend.domain.reconciliation import (
    IdentityCandidate,
    IdentityState,
    reconcile_patient_identity,
)
from claims_backend.domain.work import WorkLease
from claims_backend.domain.workflow import WorkflowRun
from claims_backend.infrastructure.postgres.models import (
    AuditEventRow,
    CasefileRow,
    ClaimRow,
    ClaimVersionRow,
    ClaimWorkItemRow,
    DecisionRecordRow,
    DocumentRow,
    DocumentTriageResultRow,
    DocumentVersionRow,
    IdentityReconciliationRow,
    MemberActionRow,
    MemberVersionRow,
    PolicyVersionRow,
    ProcessingFixtureRow,
    RuleResultRow,
    UtilizationSnapshotRow,
    WorkflowEffectRow,
    WorkflowRunRow,
)
from claims_backend.model.application import StructuredModelApplication
from claims_backend.policy.adjudicator import DeterministicPolicyAdjudicator


class ProcessingInvariantError(RuntimeError):
    pass


class PostgresClaimProcessor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        page_artifacts: PageArtifactApplication | None = None,
        page_repository: PageArtifactRepository | None = None,
        ocr: OcrApplication | None = None,
        ocr_repository: OcrRepository | None = None,
        structured_model: StructuredModelApplication | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._adjudicator = DeterministicPolicyAdjudicator()
        self._page_artifacts = page_artifacts
        self._page_repository = page_repository
        self._ocr = ocr
        self._ocr_repository = ocr_repository
        self._structured_model = structured_model

    async def route(self, workflow_run: WorkflowRun) -> ProcessingRoute:
        async with self._session_factory() as session:
            route = await session.scalar(
                select(ProcessingFixtureRow.route).where(
                    ProcessingFixtureRow.claim_id == workflow_run.claim_id,
                    ProcessingFixtureRow.claim_version == workflow_run.claim_version,
                )
            )
        return ProcessingRoute.NONE if route is None else ProcessingRoute(route)

    async def inspect_media(self, workflow_run: WorkflowRun) -> dict[str, object]:
        async with self._session_factory() as session:
            claim_version = (
                await session.scalars(
                    select(ClaimVersionRow).where(
                        ClaimVersionRow.claim_id == workflow_run.claim_id,
                        ClaimVersionRow.version == workflow_run.claim_version,
                    )
                )
            ).one()
            documents = claim_version.submission["documents"]
            if not isinstance(documents, list) or not documents:
                raise ProcessingInvariantError("Claim version has no document snapshot.")
            media_types: list[str] = []
            for document in documents:
                if not isinstance(document, dict):
                    raise ProcessingInvariantError
                version_id = UUID(str(document["document_version_id"]))
                stored = await session.get(DocumentVersionRow, version_id)
                if stored is None or stored.sha256 != document["sha256"]:
                    raise ProcessingInvariantError("Sealed document metadata changed.")
                media_types.append(stored.media_type)
        return {
            "document_count": len(media_types),
            "media_types": media_types,
            "status": "SAFE",
        }

    async def freeze_casefile(
        self,
        workflow_run: WorkflowRun,
    ) -> FrozenCasefileRef:
        async with self._session_factory.begin() as session:
            existing = await session.scalar(
                select(CasefileRow).where(
                    CasefileRow.claim_id == workflow_run.claim_id,
                    CasefileRow.claim_version == workflow_run.claim_version,
                )
            )
            if existing is not None:
                return FrozenCasefileRef(existing.id, existing.content_hash)

            claim = (
                await session.scalars(select(ClaimRow).where(ClaimRow.id == workflow_run.claim_id))
            ).one()
            if claim.policy_version_id is None or claim.member_version_id is None:
                raise ProcessingInvariantError("Claim snapshot pins are incomplete.")
            fixture = (
                await session.scalars(
                    select(ProcessingFixtureRow).where(
                        ProcessingFixtureRow.claim_id == workflow_run.claim_id,
                        ProcessingFixtureRow.claim_version == workflow_run.claim_version,
                    )
                )
            ).one()
            evidence = StructuredEvidencePayload.model_validate(fixture.payload)
            member_version = (
                await session.scalars(
                    select(MemberVersionRow).where(MemberVersionRow.id == claim.member_version_id)
                )
            ).one()
            utilization = await session.scalar(
                select(UtilizationSnapshotRow)
                .where(
                    UtilizationSnapshotRow.member_id == member_version.member_id,
                    UtilizationSnapshotRow.setup_import_id == member_version.setup_import_id,
                )
                .order_by(UtilizationSnapshotRow.as_of_date.desc())
                .limit(1)
            )
            billed = [
                document for document in evidence.documents if document.billed_paise is not None
            ]
            if len(billed) != 1:
                raise ProcessingInvariantError(
                    "Structured adjudication requires one reconciled bill."
                )
            casefile = ClaimCasefile(
                claim_id=claim.id,
                claim_version=workflow_run.claim_version,
                member_id=claim.member_id,
                member_version_id=member_version.id,
                policy_version_id=claim.policy_version_id,
                category=claim.category,
                claimed_paise=claim.claimed_paise,
                currency=claim.currency,
                eligibility=EvidenceFact(
                    state=FactState.KNOWN,
                    value=True,
                    evidence_refs=(f"member-version:{member_version.id}",),
                ),
                document_roles=EvidenceFact(
                    state=FactState.KNOWN,
                    value=[document.role.value for document in evidence.documents],
                    evidence_refs=tuple(
                        f"fixture:{document.evidence_id}" for document in evidence.documents
                    ),
                ),
                billed_paise=EvidenceFact(
                    state=FactState.KNOWN,
                    value=billed[0].billed_paise,
                    evidence_refs=(f"fixture:{billed[0].evidence_id}",),
                ),
                ytd_used_paise=EvidenceFact(
                    state=(FactState.UNKNOWN if utilization is None else FactState.KNOWN),
                    value=None if utilization is None else utilization.used_paise,
                    evidence_refs=(
                        ()
                        if utilization is None
                        else (f"utilization:{utilization.as_of_date.isoformat()}",)
                    ),
                ),
            )
            row = CasefileRow(
                id=uuid4(),
                claim_id=claim.id,
                claim_version=workflow_run.claim_version,
                policy_version_id=claim.policy_version_id,
                member_version_id=member_version.id,
                content=casefile.model_dump(mode="json"),
                content_hash=casefile.canonical_hash(),
                created_at=datetime.now(UTC),
            )
            session.add(row)
            await session.flush((row,))
            return FrozenCasefileRef(row.id, row.content_hash)

    async def evaluate_casefile(self, casefile_id: UUID) -> str:
        async with self._session_factory() as session:
            _, proposal = await self._evaluate(session, casefile_id)
        return proposal.canonical_hash

    async def commit_decision(
        self,
        workflow_run: WorkflowRun,
        lease: WorkLease,
        casefile_id: UUID,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            existing = await session.scalar(
                select(DecisionRecordRow).where(
                    DecisionRecordRow.claim_id == workflow_run.claim_id,
                    DecisionRecordRow.claim_version == workflow_run.claim_version,
                )
            )
            if existing is not None:
                return
            work_item = await session.scalar(
                select(ClaimWorkItemRow)
                .where(
                    ClaimWorkItemRow.id == lease.work_item_id,
                    ClaimWorkItemRow.status == "LEASED",
                    ClaimWorkItemRow.lease_owner == lease.worker_id,
                    ClaimWorkItemRow.lease_token == lease.lease_token,
                    ClaimWorkItemRow.lease_until == lease.lease_until,
                    ClaimWorkItemRow.lease_until > now,
                )
                .with_for_update()
            )
            if work_item is None:
                raise ProcessingInvariantError("Work lease was lost before decision commit.")
            run = await session.scalar(
                select(WorkflowRunRow).where(WorkflowRunRow.id == workflow_run.id).with_for_update()
            )
            claim = await session.scalar(
                select(ClaimRow)
                .where(
                    ClaimRow.id == workflow_run.claim_id,
                    ClaimRow.current_version == workflow_run.claim_version,
                )
                .with_for_update()
            )
            if run is None or claim is None:
                raise ProcessingInvariantError
            casefile, proposal = await self._evaluate(session, casefile_id)
            if claim.policy_version_id != casefile.policy_version_id:
                raise ProcessingInvariantError("Pinned policy changed.")

            decision = DecisionRecordRow(
                id=uuid4(),
                claim_id=claim.id,
                claim_version=workflow_run.claim_version,
                casefile_id=casefile.id,
                policy_version_id=casefile.policy_version_id,
                recommendation=proposal.recommendation.value,
                lifecycle_status="DECIDED",
                approved_paise=proposal.approved_paise,
                currency=proposal.currency,
                engine_version="deterministic-adjudicator-v1",
                canonical_hash=proposal.canonical_hash,
                created_at=now,
            )
            session.add(decision)
            await session.flush((decision,))
            session.add_all(
                [
                    RuleResultRow(
                        id=uuid4(),
                        decision_record_id=decision.id,
                        sequence=result.sequence,
                        rule_id=result.rule_id,
                        status=result.status.value,
                        reason_code=result.reason_code,
                        policy_path=result.policy_path,
                        evidence_refs=list(result.evidence_refs),
                        inputs=result.inputs,
                        amount_before_paise=result.amount_before_paise,
                        adjustment_paise=result.adjustment_paise,
                        amount_after_paise=result.amount_after_paise,
                        created_at=now,
                    )
                    for result in proposal.rule_results
                ]
            )
            claim.lifecycle_status = "DECIDED"
            claim.adjudication_recommendation = proposal.recommendation.value
            claim.approved_paise = proposal.approved_paise
            claim.current_action = None
            claim.member_explanation = {
                "summary": "₹1,350.00 approved after a 10% consultation co-pay.",
                "deductions": [
                    {
                        "code": "CATEGORY_COPAY_APPLIED",
                        "label": "10% consultation co-pay",
                        "amount_paise": 15_000,
                    }
                ],
            }
            claim.updated_at = now
            audit_sequence = (
                await session.scalar(
                    select(func.max(AuditEventRow.sequence)).where(
                        AuditEventRow.claim_id == claim.id
                    )
                )
                or 0
            ) + 1
            session.add(
                AuditEventRow(
                    id=uuid4(),
                    actor_user_id=claim.owner_user_id,
                    actor_username_snapshot=claim.owner_username_snapshot,
                    claim_id=claim.id,
                    sequence=audit_sequence,
                    event_type="CLAIM_DECIDED",
                    payload={
                        "decision_record_id": str(decision.id),
                        "casefile_id": str(casefile.id),
                        "recommendation": proposal.recommendation.value,
                        "approved_paise": proposal.approved_paise,
                        "canonical_hash": proposal.canonical_hash,
                    },
                    created_at=now,
                )
            )
            session.add(
                WorkflowEffectRow(
                    id=uuid4(),
                    workflow_run_id=run.id,
                    effect_key=f"decision-committed:v{workflow_run.claim_version}",
                    effect_type="DECISION_COMMITTED",
                    payload={
                        "decision_record_id": str(decision.id),
                        "canonical_hash": proposal.canonical_hash,
                    },
                    created_at=now,
                )
            )
            work_item.status = "COMPLETED"
            work_item.lease_owner = None
            work_item.lease_token = None
            work_item.lease_until = None
            work_item.updated_at = now
            run.status = "COMPLETED"
            run.completed_at = now
            run.updated_at = now
            await session.flush()

    async def triage_documents(
        self,
        workflow_run: WorkflowRun,
    ) -> EarlyGateResult:
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            fixture = (
                await session.scalars(
                    select(ProcessingFixtureRow).where(
                        ProcessingFixtureRow.claim_id == workflow_run.claim_id,
                        ProcessingFixtureRow.claim_version == workflow_run.claim_version,
                        ProcessingFixtureRow.route == ProcessingRoute.EARLY_TRIAGE.value,
                    )
                )
            ).one()
            output = TriageModelOutput.model_validate(fixture.payload)
            claim = (
                await session.scalars(select(ClaimRow).where(ClaimRow.id == workflow_run.claim_id))
            ).one()
            if claim.policy_version_id is None or claim.member_version_id is None:
                raise ProcessingInvariantError
            member_version = (
                await session.scalars(
                    select(MemberVersionRow).where(MemberVersionRow.id == claim.member_version_id)
                )
            ).one()
            policy_version = (
                await session.scalars(
                    select(PolicyVersionRow).where(PolicyVersionRow.id == claim.policy_version_id)
                )
            ).one()
            if policy_version.ir is None:
                raise ProcessingInvariantError
            policy = PolicyIR.model_validate(policy_version.ir)
            claim_version = (
                await session.scalars(
                    select(ClaimVersionRow).where(
                        ClaimVersionRow.claim_id == workflow_run.claim_id,
                        ClaimVersionRow.version == workflow_run.claim_version,
                    )
                )
            ).one()
            snapshot_documents = claim_version.submission["documents"]
            if not isinstance(snapshot_documents, list):
                raise ProcessingInvariantError
            snapshot_by_client_id = {
                str(item["client_document_id"]): item
                for item in snapshot_documents
                if isinstance(item, dict)
            }
            output_ids = [item.client_document_id for item in output.documents]
            if len(output_ids) != len(set(output_ids)) or set(output_ids) != set(
                snapshot_by_client_id
            ):
                raise ProcessingInvariantError(
                    "Triage output must cover each submitted document exactly once."
                )
            documents = (
                await session.scalars(select(DocumentRow).where(DocumentRow.claim_id == claim.id))
            ).all()
            document_by_client_id = {
                document.client_document_id: document for document in documents
            }
            identity_candidates: list[IdentityCandidate] = []
            for item in output.documents:
                snapshot = snapshot_by_client_id[item.client_document_id]
                item_candidates = [
                    IdentityCandidate(
                        producer="fixture-fast-triage",
                        producer_version="v1",
                        client_document_id=item.client_document_id,
                        document_version_id=UUID(str(snapshot["document_version_id"])),
                        page=observation.page,
                        region=observation.region,
                        source_text_sha256=observation.source_text_sha256,
                        confidence=observation.confidence,
                        value=observation.value,
                    )
                    for observation in item.identity_observations
                ]
                identity_candidates.extend(item_candidates)
                await session.execute(
                    insert(DocumentTriageResultRow)
                    .values(
                        id=uuid4(),
                        claim_id=claim.id,
                        claim_version=workflow_run.claim_version,
                        document_id=document_by_client_id[item.client_document_id].id,
                        document_version_id=UUID(str(snapshot["document_version_id"])),
                        client_document_id=item.client_document_id,
                        role=item.role.value,
                        readability=item.readability.status.value,
                        readability_observation={
                            "status": item.readability.status.value,
                            "document_version_id": str(snapshot["document_version_id"]),
                            "preview": item.readability.preview.model_dump(mode="json"),
                        },
                        identity_observations=[
                            candidate.model_dump(mode="json") for candidate in item_candidates
                        ],
                        model_route="fixture-fast-triage-v1",
                        schema_version=output.schema_version,
                        created_at=now,
                    )
                    .on_conflict_do_nothing(
                        constraint=("document_triage_results_claim_version_document_uq")
                    )
                )

            identity = reconcile_patient_identity(
                member_version.name,
                tuple(identity_candidates),
            )
            await session.execute(
                insert(IdentityReconciliationRow)
                .values(
                    id=uuid4(),
                    claim_id=claim.id,
                    claim_version=workflow_run.claim_version,
                    member_version_id=member_version.id,
                    state=identity.state.value,
                    member_name=identity.member_name,
                    candidates=[
                        candidate.model_dump(mode="json") for candidate in identity.candidates
                    ],
                    created_at=now,
                )
                .on_conflict_do_nothing(constraint="identity_reconciliations_claim_version_uq")
            )

            observed = tuple(item.role.value for item in output.documents)
            required = policy.document_requirements[claim.category].required
            missing = tuple(role for role in required if role not in set(observed))
            unreadable = tuple(
                item for item in output.documents if item.readability.status.value == "UNREADABLE"
            )
            message = None
            code = None
            affected_documents: tuple[AffectedDocument, ...] = ()
            identity_conflict: tuple[IdentityConflictDetail, ...] = ()
            if unreadable:
                code = "UNREADABLE_DOCUMENT"
                affected_documents = tuple(
                    AffectedDocument(
                        client_document_id=item.client_document_id,
                        observed_role=item.role.value,
                        requested_action="REPLACE",
                    )
                    for item in unreadable
                )
                required = tuple(dict.fromkeys(item.role.value for item in unreadable))
                first = affected_documents[0]
                role_label = first.observed_role.replace("_", " ").lower()
                message = (
                    f"The {role_label} ({first.client_document_id}) could not be read. "
                    "Please replace that document with a clearer image."
                )
                missing = required
            elif missing:
                code = "MISSING_REQUIRED_DOCUMENT"
                if observed == ("PRESCRIPTION", "PRESCRIPTION") and missing == ("HOSPITAL_BILL",):
                    message = (
                        "You uploaded two prescriptions. Please upload the required hospital bill."
                    )
                else:
                    message = (
                        f"Uploaded roles: {', '.join(observed)}. "
                        f"Please upload: {', '.join(missing)}."
                    )
            elif identity.state is IdentityState.CONFLICT:
                code = "PATIENT_IDENTITY_CONFLICT"
                identity_conflict = tuple(
                    IdentityConflictDetail(
                        client_document_id=candidate.client_document_id,
                        patient_name=candidate.value,
                    )
                    for candidate in identity.candidates
                )
                findings = "; ".join(
                    f"{item.client_document_id} shows {item.patient_name}"
                    for item in identity_conflict
                )
                message = (
                    f"Patient names do not match: {findings}. "
                    "Please replace the document that belongs to a different patient."
                )
            return EarlyGateResult(
                action_required=bool(missing or identity_conflict),
                code=code,
                message=message,
                observed_roles=observed,
                required_roles=missing,
                affected_documents=affected_documents,
                identity_conflict=identity_conflict,
            )

    async def commit_member_action(
        self,
        workflow_run: WorkflowRun,
        lease: WorkLease,
        result: EarlyGateResult,
    ) -> None:
        if not result.action_required or result.code is None or result.message is None:
            raise ProcessingInvariantError("No member action is available to commit.")
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            existing = await session.scalar(
                select(MemberActionRow).where(
                    MemberActionRow.claim_id == workflow_run.claim_id,
                    MemberActionRow.claim_version == workflow_run.claim_version,
                )
            )
            if existing is not None:
                return
            work_item = await session.scalar(
                select(ClaimWorkItemRow)
                .where(
                    ClaimWorkItemRow.id == lease.work_item_id,
                    ClaimWorkItemRow.status == "LEASED",
                    ClaimWorkItemRow.lease_owner == lease.worker_id,
                    ClaimWorkItemRow.lease_token == lease.lease_token,
                    ClaimWorkItemRow.lease_until == lease.lease_until,
                    ClaimWorkItemRow.lease_until > now,
                )
                .with_for_update()
            )
            run = await session.scalar(
                select(WorkflowRunRow).where(WorkflowRunRow.id == workflow_run.id).with_for_update()
            )
            claim = await session.scalar(
                select(ClaimRow)
                .where(
                    ClaimRow.id == workflow_run.claim_id,
                    ClaimRow.current_version == workflow_run.claim_version,
                )
                .with_for_update()
            )
            if work_item is None or run is None or claim is None:
                raise ProcessingInvariantError
            action = MemberActionRow(
                id=uuid4(),
                claim_id=claim.id,
                claim_version=workflow_run.claim_version,
                code=result.code,
                message=result.message,
                observed_document_roles=list(result.observed_roles),
                required_document_roles=list(result.required_roles),
                details={
                    "affected_documents": [
                        {
                            "client_document_id": document.client_document_id,
                            "observed_role": document.observed_role,
                            "requested_action": document.requested_action,
                        }
                        for document in result.affected_documents
                    ],
                    "identity_conflict": [
                        {
                            "client_document_id": item.client_document_id,
                            "patient_name": item.patient_name,
                        }
                        for item in result.identity_conflict
                    ],
                },
                created_at=now,
            )
            session.add(action)
            claim.lifecycle_status = "ACTION_REQUIRED"
            claim.adjudication_recommendation = None
            claim.approved_paise = None
            claim.member_explanation = None
            claim.current_action = {
                "code": result.code,
                "message": result.message,
                "observed_document_roles": list(result.observed_roles),
                "required_document_roles": list(result.required_roles),
                "affected_documents": [
                    {
                        "client_document_id": document.client_document_id,
                        "observed_role": document.observed_role,
                        "requested_action": document.requested_action,
                    }
                    for document in result.affected_documents
                ],
                "identity_conflict": [
                    {
                        "client_document_id": item.client_document_id,
                        "patient_name": item.patient_name,
                    }
                    for item in result.identity_conflict
                ],
            }
            claim.updated_at = now
            audit_sequence = (
                await session.scalar(
                    select(func.max(AuditEventRow.sequence)).where(
                        AuditEventRow.claim_id == claim.id
                    )
                )
                or 0
            ) + 1
            session.add(
                AuditEventRow(
                    id=uuid4(),
                    actor_user_id=claim.owner_user_id,
                    actor_username_snapshot=claim.owner_username_snapshot,
                    claim_id=claim.id,
                    sequence=audit_sequence,
                    event_type="CLAIM_ACTION_REQUIRED",
                    payload={
                        "member_action_id": str(action.id),
                        "code": result.code,
                        "observed_document_roles": list(result.observed_roles),
                        "required_document_roles": list(result.required_roles),
                    },
                    created_at=now,
                )
            )
            session.add(
                WorkflowEffectRow(
                    id=uuid4(),
                    workflow_run_id=run.id,
                    effect_key=f"member-action-committed:v{workflow_run.claim_version}",
                    effect_type="MEMBER_ACTION_COMMITTED",
                    payload={
                        "member_action_id": str(action.id),
                        "code": result.code,
                    },
                    created_at=now,
                )
            )
            work_item.status = "COMPLETED"
            work_item.lease_owner = None
            work_item.lease_token = None
            work_item.lease_until = None
            work_item.updated_at = now
            run.status = "COMPLETED"
            run.completed_at = now
            run.updated_at = now
            await session.flush()

    async def render_documents(
        self,
        workflow_run: WorkflowRun,
    ) -> PagePreparationResult:
        if self._page_artifacts is None:
            raise ProcessingInvariantError("Page artifact pipeline is not configured.")
        async with self._session_factory() as session:
            claim_version = (
                await session.scalars(
                    select(ClaimVersionRow).where(
                        ClaimVersionRow.claim_id == workflow_run.claim_id,
                        ClaimVersionRow.version == workflow_run.claim_version,
                    )
                )
            ).one()
            snapshots = claim_version.submission["documents"]
            if not isinstance(snapshots, list):
                raise ProcessingInvariantError
            triage_rows = (
                await session.scalars(
                    select(DocumentTriageResultRow).where(
                        DocumentTriageResultRow.claim_id == workflow_run.claim_id,
                        DocumentTriageResultRow.claim_version == workflow_run.claim_version,
                    )
                )
            ).all()
            triage_by_client_id = {row.client_document_id: row for row in triage_rows}

        rendered_page_count = 0
        for snapshot in sorted(
            (item for item in snapshots if isinstance(item, dict)),
            key=lambda item: int(str(item["upload_index"])),
        ):
            client_document_id = str(snapshot["client_document_id"])
            triage = triage_by_client_id.get(client_document_id)
            if triage is None:
                raise ProcessingInvariantError("Document triage provenance is incomplete.")
            source = SourceDocument(
                document_id=UUID(str(snapshot["document_id"])),
                document_version_id=UUID(str(snapshot["document_version_id"])),
                relative_path=str(
                    await self._document_relative_path(UUID(str(snapshot["document_version_id"])))
                ),
                media_type=str(snapshot["media_type"]),
                sha256=str(snapshot["sha256"]),
                page_count=int(str(snapshot["page_count"])),
            )
            try:
                artifacts = await self._page_artifacts.process(source)
            except RenderedPageTooLargeError as error:
                role_label = triage.role.replace("_", " ").lower()
                action = EarlyGateResult(
                    action_required=True,
                    code="PAGE_TOO_LARGE_FOR_OCR",
                    message=(
                        f"Page {error.page_number} of the {role_label} "
                        f"({client_document_id}) is too large for OCR. "
                        "Please replace it with a clearer or smaller document."
                    ),
                    observed_roles=tuple(row.role for row in triage_rows),
                    required_roles=(triage.role,),
                    affected_documents=(
                        AffectedDocument(
                            client_document_id=client_document_id,
                            observed_role=triage.role,
                            requested_action="REPLACE",
                        ),
                    ),
                )
                return PagePreparationResult(
                    rendered_page_count=rendered_page_count,
                    action=action,
                )
            rendered_page_count += len(artifacts)
        return PagePreparationResult(rendered_page_count=rendered_page_count)

    async def ocr_documents(self, workflow_run: WorkflowRun) -> int:
        if self._ocr is None or self._page_repository is None:
            raise ProcessingInvariantError("OCR pipeline is not configured.")
        async with self._session_factory() as session:
            triage_rows = (
                await session.scalars(
                    select(DocumentTriageResultRow)
                    .where(
                        DocumentTriageResultRow.claim_id == workflow_run.claim_id,
                        DocumentTriageResultRow.claim_version == workflow_run.claim_version,
                    )
                    .order_by(DocumentTriageResultRow.client_document_id)
                )
            ).all()
        observation_count = 0
        for triage in triage_rows:
            artifacts = await self._page_repository.list_for_document_version(
                triage.document_version_id
            )
            if not artifacts:
                raise ProcessingInvariantError("Rendered page artifacts are missing.")
            observations = await self._ocr.process(
                artifacts,
                DocumentRole(triage.role),
            )
            observation_count += len(observations)
        return observation_count

    async def extract_evidence(self, workflow_run: WorkflowRun) -> int | None:
        if self._structured_model is None:
            return None
        if self._ocr_repository is None:
            raise ProcessingInvariantError("Structured extraction requires the OCR repository.")
        async with self._session_factory() as session:
            document_version_ids = (
                await session.scalars(
                    select(DocumentTriageResultRow.document_version_id)
                    .where(
                        DocumentTriageResultRow.claim_id == workflow_run.claim_id,
                        DocumentTriageResultRow.claim_version == workflow_run.claim_version,
                    )
                    .order_by(DocumentTriageResultRow.client_document_id)
                )
            ).all()
        candidate_count = 0
        for document_version_id in document_version_ids:
            observations = await self._ocr_repository.list_observations(document_version_id)
            result = await self._structured_model.extract_complex(
                document_version_id,
                observations,
            )
            candidate_count += len(result.candidates)
        return candidate_count

    async def _document_relative_path(self, document_version_id: UUID) -> str:
        async with self._session_factory() as session:
            row = await session.get(DocumentVersionRow, document_version_id)
        if row is None:
            raise ProcessingInvariantError("Document version is missing.")
        return row.relative_path

    async def inspect_trace(self, claim_id: UUID) -> ClaimProcessingTrace | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        CasefileRow,
                        DecisionRecordRow,
                        ClaimWorkItemRow.status,
                        WorkflowRunRow.status,
                    )
                    .join(
                        DecisionRecordRow,
                        DecisionRecordRow.casefile_id == CasefileRow.id,
                    )
                    .join(
                        ClaimWorkItemRow,
                        ClaimWorkItemRow.claim_id == CasefileRow.claim_id,
                    )
                    .join(
                        WorkflowRunRow,
                        WorkflowRunRow.work_item_id == ClaimWorkItemRow.id,
                    )
                    .where(CasefileRow.claim_id == claim_id)
                )
            ).one_or_none()
            if row is None:
                return None
            casefile, decision, work_status, workflow_status = row
            rules = (
                await session.scalars(
                    select(RuleResultRow)
                    .where(RuleResultRow.decision_record_id == decision.id)
                    .order_by(RuleResultRow.sequence)
                )
            ).all()
        return ClaimProcessingTrace(
            casefile=CasefileTrace(casefile.id, casefile.content_hash),
            decision=DecisionTrace(
                decision.id,
                decision.recommendation,
                decision.approved_paise,
                decision.canonical_hash,
            ),
            rule_results=tuple(_rule_result(row) for row in rules),
            work_status=work_status,
            workflow_status=workflow_status,
        )

    async def _evaluate(
        self,
        session: AsyncSession,
        casefile_id: UUID,
    ) -> tuple[CasefileRow, AdjudicationProposal]:
        casefile = (
            await session.scalars(select(CasefileRow).where(CasefileRow.id == casefile_id))
        ).one()
        policy_version = (
            await session.scalars(
                select(PolicyVersionRow).where(PolicyVersionRow.id == casefile.policy_version_id)
            )
        ).one()
        if policy_version.ir is None:
            raise ProcessingInvariantError("Pinned policy has no compiled IR.")
        proposal = self._adjudicator.evaluate(
            ClaimCasefile.model_validate(casefile.content),
            PolicyIR.model_validate(policy_version.ir),
        )
        if proposal.policy_ir_sha256 != policy_version.ir_sha256:
            raise ProcessingInvariantError("Compiled policy hash does not match.")
        return casefile, proposal


def _rule_result(row: RuleResultRow) -> RuleResult:
    return RuleResult.model_validate(
        {
            "sequence": row.sequence,
            "rule_id": row.rule_id,
            "status": row.status,
            "reason_code": row.reason_code,
            "policy_path": row.policy_path,
            "evidence_refs": row.evidence_refs,
            "inputs": row.inputs,
            "amount_before_paise": row.amount_before_paise,
            "adjustment_paise": row.adjustment_paise,
            "amount_after_paise": row.amount_after_paise,
        }
    )
