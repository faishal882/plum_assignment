from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from claims_backend.domain.setup_data import (
    FactState,
    FindingSeverity,
    ImportFinding,
    MemberInspection,
    SetupImportBundle,
    SetupImportReceipt,
)
from claims_backend.infrastructure.postgres.models import (
    ClaimHistoryRow,
    ImportFindingRow,
    MemberRow,
    MemberVersionRow,
    PolicySourceRow,
    SetupImportRow,
    UtilizationSnapshotRow,
)


class PostgresSetupImportRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def import_bundle(self, bundle: SetupImportBundle) -> SetupImportReceipt:
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:policy_id))"),
                {"policy_id": bundle.policy_id},
            )
            existing = await session.scalar(
                select(SetupImportRow).where(SetupImportRow.request_sha256 == bundle.request_sha256)
            )
            if existing is not None:
                return await self._receipt(session, existing)

            policy_source_id = await self._get_or_create_policy_source(session, bundle, now)
            import_row = SetupImportRow(
                id=uuid4(),
                policy_id=bundle.policy_id,
                policy_source_id=policy_source_id,
                member_data_source_name=bundle.member_data_source_name,
                member_data_sha256=bundle.member_data_sha256,
                member_data_bytes=bundle.member_data_bytes,
                request_sha256=bundle.request_sha256,
                imported_at=now,
            )
            session.add(import_row)
            await session.flush()

            members = await self._get_or_create_members(session, bundle, now)
            await self._add_member_versions(session, import_row.id, bundle, members, now)
            session.add_all(
                [
                    ImportFindingRow(
                        id=uuid4(),
                        setup_import_id=import_row.id,
                        severity=finding.severity.value,
                        code=finding.code,
                        source_pointer=finding.source_pointer,
                        message=finding.message,
                        subject_id=finding.subject_id,
                        created_at=now,
                    )
                    for finding in bundle.findings
                ]
            )
            session.add_all(
                [
                    ClaimHistoryRow(
                        id=uuid4(),
                        setup_import_id=import_row.id,
                        member_id=members[item.member_id].id,
                        history_claim_id=item.history_claim_id,
                        treatment_date=item.treatment_date,
                        amount_paise=item.amount_paise,
                        currency=item.currency,
                        provider=item.provider,
                        source_pointer=item.source_pointer,
                        created_at=now,
                    )
                    for item in bundle.claim_history
                ]
            )
            session.add_all(
                [
                    UtilizationSnapshotRow(
                        id=uuid4(),
                        setup_import_id=import_row.id,
                        member_id=members[item.member_id].id,
                        period_start=item.period_start,
                        period_end=item.period_end,
                        used_paise=item.used_paise,
                        currency=item.currency,
                        as_of_date=item.as_of_date,
                        source_pointer=item.source_pointer,
                        created_at=now,
                    )
                    for item in bundle.utilization
                ]
            )
            await session.flush()
            return await self._receipt(session, import_row)

    async def inspect_member(
        self,
        policy_id: str,
        member_id: str,
    ) -> MemberInspection | None:
        primary = aliased(MemberRow)
        latest_import_id = (
            select(SetupImportRow.id)
            .where(SetupImportRow.policy_id == policy_id)
            .order_by(SetupImportRow.imported_at.desc(), SetupImportRow.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(MemberRow, MemberVersionRow, PolicySourceRow, primary.external_member_id)
                    .join(MemberVersionRow, MemberVersionRow.member_id == MemberRow.id)
                    .join(
                        SetupImportRow,
                        SetupImportRow.id == MemberVersionRow.setup_import_id,
                    )
                    .join(
                        PolicySourceRow,
                        PolicySourceRow.id == SetupImportRow.policy_source_id,
                    )
                    .outerjoin(primary, primary.id == MemberVersionRow.primary_member_id)
                    .where(
                        MemberRow.policy_id == policy_id,
                        MemberRow.external_member_id == member_id,
                        MemberVersionRow.setup_import_id == latest_import_id,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            member, version, source, primary_external_id = row
            utilization = await session.scalar(
                select(UtilizationSnapshotRow)
                .where(UtilizationSnapshotRow.member_id == member.id)
                .order_by(
                    UtilizationSnapshotRow.as_of_date.desc(),
                    UtilizationSnapshotRow.created_at.desc(),
                )
                .limit(1)
            )
        return MemberInspection(
            policy_id=member.policy_id,
            member_id=member.external_member_id,
            version=version.version,
            name=version.name,
            date_of_birth=version.date_of_birth,
            gender=version.gender,
            relationship=version.relationship,
            join_date=version.join_date,
            primary_member_id=primary_external_id,
            dependent_ids=tuple(version.dependent_ids),
            source_sha256=source.source_sha256,
            source_pointer=version.source_pointer,
            utilization_state=(FactState.UNKNOWN if utilization is None else FactState.KNOWN),
            used_paise=None if utilization is None else utilization.used_paise,
            utilization_as_of_date=(None if utilization is None else utilization.as_of_date),
        )

    async def get_import(self, import_id: UUID) -> SetupImportReceipt | None:
        async with self._session_factory() as session:
            row = await session.get(SetupImportRow, import_id)
            return None if row is None else await self._receipt(session, row)

    async def _get_or_create_policy_source(
        self,
        session: AsyncSession,
        bundle: SetupImportBundle,
        now: datetime,
    ) -> UUID:
        new_id = uuid4()
        inserted_id = await session.scalar(
            insert(PolicySourceRow)
            .values(
                id=new_id,
                policy_id=bundle.policy_id,
                source_name=bundle.policy_source_name,
                source_sha256=bundle.policy_source_sha256,
                source_bytes=bundle.policy_source_bytes,
                imported_at=now,
            )
            .on_conflict_do_nothing(index_elements=[PolicySourceRow.source_sha256])
            .returning(PolicySourceRow.id)
        )
        if inserted_id is not None:
            return inserted_id
        return (
            await session.scalars(
                select(PolicySourceRow.id).where(
                    PolicySourceRow.source_sha256 == bundle.policy_source_sha256
                )
            )
        ).one()

    async def _get_or_create_members(
        self,
        session: AsyncSession,
        bundle: SetupImportBundle,
        now: datetime,
    ) -> dict[str, MemberRow]:
        for item in bundle.members:
            await session.execute(
                insert(MemberRow)
                .values(
                    id=uuid4(),
                    policy_id=bundle.policy_id,
                    external_member_id=item.external_member_id,
                    created_at=now,
                )
                .on_conflict_do_nothing(constraint="members_policy_external_id_uq")
            )
        rows = (
            await session.scalars(
                select(MemberRow).where(
                    MemberRow.policy_id == bundle.policy_id,
                    MemberRow.external_member_id.in_(
                        item.external_member_id for item in bundle.members
                    ),
                )
            )
        ).all()
        return {row.external_member_id: row for row in rows}

    async def _add_member_versions(
        self,
        session: AsyncSession,
        import_id: UUID,
        bundle: SetupImportBundle,
        members: dict[str, MemberRow],
        now: datetime,
    ) -> None:
        for item in bundle.members:
            member = members[item.external_member_id]
            latest_version = await session.scalar(
                select(func.max(MemberVersionRow.version)).where(
                    MemberVersionRow.member_id == member.id
                )
            )
            primary = (
                None if item.primary_member_id is None else members.get(item.primary_member_id)
            )
            session.add(
                MemberVersionRow(
                    id=uuid4(),
                    member_id=member.id,
                    version=(latest_version or 0) + 1,
                    setup_import_id=import_id,
                    primary_member_id=None if primary is None else primary.id,
                    name=item.name,
                    date_of_birth=item.date_of_birth,
                    gender=item.gender,
                    relationship=item.relationship,
                    join_date=item.join_date,
                    dependent_ids=list(item.dependent_ids),
                    source_pointer=item.source_pointer,
                    created_at=now,
                )
            )

    async def _receipt(
        self,
        session: AsyncSession,
        import_row: SetupImportRow,
    ) -> SetupImportReceipt:
        source_hash = (
            await session.scalars(
                select(PolicySourceRow.source_sha256).where(
                    PolicySourceRow.id == import_row.policy_source_id
                )
            )
        ).one()
        findings = (
            await session.scalars(
                select(ImportFindingRow)
                .where(ImportFindingRow.setup_import_id == import_row.id)
                .order_by(ImportFindingRow.created_at, ImportFindingRow.id)
            )
        ).all()
        counts = []
        for model in (MemberVersionRow, ClaimHistoryRow, UtilizationSnapshotRow):
            counts.append(
                await session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.setup_import_id == import_row.id)
                )
                or 0
            )
        return SetupImportReceipt(
            import_id=import_row.id,
            policy_id=import_row.policy_id,
            policy_source_sha256=source_hash,
            member_data_sha256=import_row.member_data_sha256,
            member_versions_created=counts[0],
            history_records_created=counts[1],
            utilization_records_created=counts[2],
            findings=tuple(
                ImportFinding(
                    severity=FindingSeverity(row.severity),
                    code=row.code,
                    source_pointer=row.source_pointer,
                    message=row.message,
                    subject_id=row.subject_id,
                )
                for row in findings
            ),
            imported_at=import_row.imported_at,
        )
