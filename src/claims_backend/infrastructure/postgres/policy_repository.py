from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from claims_backend.application.policy_admin import PolicySourceArtifact
from claims_backend.domain.policy import (
    FindingCategory,
    PolicyFinding,
    PolicyFindingSeverity,
    PolicyVersionInspection,
    PolicyVersionStatus,
)
from claims_backend.infrastructure.postgres.models import (
    PolicyFindingRow,
    PolicyOverlayRow,
    PolicySourceRow,
    PolicyVersionRow,
)
from claims_backend.policy.compiler import COMPILER_VERSION, PolicyCompilation


class PostgresPolicyRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_source_by_hash(
        self,
        source_sha256: str,
    ) -> PolicySourceArtifact | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(PolicySourceRow).where(PolicySourceRow.source_sha256 == source_sha256)
            )
        if row is None:
            return None
        return PolicySourceArtifact(
            id=row.id,
            policy_id=row.policy_id,
            source_sha256=row.source_sha256,
            source_bytes=row.source_bytes,
        )

    async def save_compilation(
        self,
        source: PolicySourceArtifact,
        compilation: PolicyCompilation,
        overlay_bytes: bytes,
        overlay_source_name: str,
    ) -> PolicyVersionInspection:
        now = datetime.now(UTC)
        async with self._session_factory.begin() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:policy_id))"),
                {"policy_id": source.policy_id},
            )
            overlay_id = await self._get_or_create_overlay(
                session,
                compilation,
                overlay_bytes,
                overlay_source_name,
                now,
            )
            existing = await session.scalar(
                select(PolicyVersionRow).where(
                    PolicyVersionRow.policy_source_id == source.id,
                    PolicyVersionRow.policy_overlay_id == overlay_id,
                    PolicyVersionRow.compiler_version == COMPILER_VERSION,
                )
            )
            if existing is not None:
                return await self._inspection(session, existing)

            latest_version = await session.scalar(
                select(func.max(PolicyVersionRow.version)).where(
                    PolicyVersionRow.policy_id == source.policy_id
                )
            )
            row = PolicyVersionRow(
                id=uuid4(),
                policy_id=source.policy_id,
                version=(latest_version or 0) + 1,
                policy_source_id=source.id,
                policy_overlay_id=overlay_id,
                compiler_version=COMPILER_VERSION,
                ir=(None if compilation.ir is None else compilation.ir.model_dump(mode="json")),
                ir_sha256=compilation.ir_sha256,
                status=(
                    PolicyVersionStatus.INVALID.value
                    if compilation.has_errors or compilation.ir is None
                    else PolicyVersionStatus.COMPILED.value
                ),
                compiled_at=now,
                activated_at=None,
                activated_by=None,
            )
            session.add(row)
            await session.flush((row,))
            session.add_all(
                [
                    PolicyFindingRow(
                        id=uuid4(),
                        policy_version_id=row.id,
                        category=finding.category.value,
                        severity=finding.severity.value,
                        code=finding.code,
                        source_pointer=finding.source_pointer,
                        message=finding.message,
                        resolved_by_overlay=finding.resolved_by_overlay,
                        created_at=now,
                    )
                    for finding in compilation.findings
                ]
            )
            await session.flush()
            return await self._inspection(session, row)

    async def inspect_version(
        self,
        policy_version_id: UUID,
    ) -> PolicyVersionInspection | None:
        async with self._session_factory() as session:
            row = await session.get(PolicyVersionRow, policy_version_id)
            return None if row is None else await self._inspection(session, row)

    async def _get_or_create_overlay(
        self,
        session: AsyncSession,
        compilation: PolicyCompilation,
        overlay_bytes: bytes,
        overlay_source_name: str,
        now: datetime,
    ) -> UUID:
        new_id = uuid4()
        inserted_id = await session.scalar(
            insert(PolicyOverlayRow)
            .values(
                id=new_id,
                overlay_id=compilation.overlay_id,
                version=compilation.overlay_version,
                base_policy_sha256=compilation.overlay_base_policy_sha256,
                source_name=overlay_source_name,
                source_sha256=compilation.overlay_sha256,
                source_bytes=overlay_bytes,
                approval_status=(None if compilation.overlay_id is None else "APPROVED"),
                approved_by=compilation.overlay_approved_by,
                approved_at=compilation.overlay_approved_at,
                imported_at=now,
            )
            .on_conflict_do_nothing(index_elements=[PolicyOverlayRow.source_sha256])
            .returning(PolicyOverlayRow.id)
        )
        if inserted_id is not None:
            return inserted_id
        return (
            await session.scalars(
                select(PolicyOverlayRow.id).where(
                    PolicyOverlayRow.source_sha256 == compilation.overlay_sha256
                )
            )
        ).one()

    async def _inspection(
        self,
        session: AsyncSession,
        version: PolicyVersionRow,
    ) -> PolicyVersionInspection:
        source_hash, overlay = (
            await session.execute(
                select(PolicySourceRow.source_sha256, PolicyOverlayRow)
                .join(
                    PolicyVersionRow,
                    PolicyVersionRow.policy_source_id == PolicySourceRow.id,
                )
                .join(
                    PolicyOverlayRow,
                    PolicyOverlayRow.id == PolicyVersionRow.policy_overlay_id,
                )
                .where(PolicyVersionRow.id == version.id)
            )
        ).one()
        findings = (
            await session.scalars(
                select(PolicyFindingRow)
                .where(PolicyFindingRow.policy_version_id == version.id)
                .order_by(PolicyFindingRow.created_at, PolicyFindingRow.id)
            )
        ).all()
        return PolicyVersionInspection(
            policy_version_id=version.id,
            policy_id=version.policy_id,
            version=version.version,
            source_sha256=source_hash,
            overlay_sha256=overlay.source_sha256,
            overlay_id=overlay.overlay_id,
            overlay_version=overlay.version,
            compiler_version=version.compiler_version,
            ir_sha256=version.ir_sha256,
            status=PolicyVersionStatus(version.status),
            findings=tuple(
                PolicyFinding(
                    category=FindingCategory(finding.category),
                    severity=PolicyFindingSeverity(finding.severity),
                    code=finding.code,
                    source_pointer=finding.source_pointer,
                    message=finding.message,
                    resolved_by_overlay=finding.resolved_by_overlay,
                )
                for finding in findings
            ),
            compiled_at=version.compiled_at,
            activated_at=version.activated_at,
            activated_by=version.activated_by,
        )
