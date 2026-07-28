from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PolicySourceRow(Base):
    __tablename__ = "policy_sources"
    __table_args__ = (
        CheckConstraint("octet_length(source_bytes) > 0", name="policy_sources_bytes_nonempty"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SetupImportRow(Base):
    __tablename__ = "setup_imports"
    __table_args__ = (
        CheckConstraint(
            "(member_data_bytes IS NULL) = (member_data_sha256 IS NULL)",
            name="setup_imports_member_data_hash_pair",
        ),
        CheckConstraint(
            "(member_data_bytes IS NULL) = (member_data_source_name IS NULL)",
            name="setup_imports_member_data_name_pair",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    policy_source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    member_data_source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    member_data_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    member_data_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemberRow(Base):
    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint(
            "policy_id",
            "external_member_id",
            name="members_policy_external_id_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_member_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemberVersionRow(Base):
    __tablename__ = "member_versions"
    __table_args__ = (
        CheckConstraint("version > 0", name="member_versions_version_positive"),
        UniqueConstraint("member_id", "version", name="member_versions_member_version_uq"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    member_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("members.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    setup_import_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("setup_imports.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    primary_member_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("members.id", ondelete="RESTRICT"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(String(32), nullable=False)
    relationship: Mapped[str] = mapped_column(String(32), nullable=False)
    join_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dependent_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    source_pointer: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ImportFindingRow(Base):
    __tablename__ = "import_findings"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    setup_import_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("setup_imports.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_pointer: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClaimHistoryRow(Base):
    __tablename__ = "member_claim_history"
    __table_args__ = (
        CheckConstraint("amount_paise >= 0", name="member_claim_history_amount_nonnegative"),
        UniqueConstraint(
            "setup_import_id",
            "history_claim_id",
            name="member_claim_history_import_claim_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    setup_import_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("setup_imports.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    member_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("members.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    history_claim_id: Mapped[str] = mapped_column(String(128), nullable=False)
    treatment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_pointer: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UtilizationSnapshotRow(Base):
    __tablename__ = "member_utilization_snapshots"
    __table_args__ = (
        CheckConstraint(
            "used_paise >= 0",
            name="member_utilization_snapshots_used_nonnegative",
        ),
        CheckConstraint(
            "period_end >= period_start",
            name="member_utilization_snapshots_period_ordered",
        ),
        UniqueConstraint(
            "setup_import_id",
            "member_id",
            "period_start",
            "period_end",
            name="member_utilization_snapshots_import_member_period_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    setup_import_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("setup_imports.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    member_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("members.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    used_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_pointer: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "normalized_username = lower(btrim(username))",
            name="users_username_normalized",
        ),
        CheckConstraint(
            "normalized_username ~ '^[a-z0-9][a-z0-9._-]{2,63}$'",
            name="users_username_supported_characters",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserRoleRow(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(32), primary_key=True)


class UserMemberLinkRow(Base):
    __tablename__ = "user_member_links"

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    member_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class ClaimRow(Base):
    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint("claimed_paise >= 0", name="claims_claimed_paise_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    owner_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    owner_username_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    member_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    treatment_date: Mapped[date] = mapped_column(Date, nullable=False)
    claimed_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdempotencyKeyRow(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "scope_user_id",
            "idempotency_key",
            name="idempotency_keys_user_key_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    scope_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "claims.id",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
        unique=True,
    )
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClaimActionRow(Base):
    __tablename__ = "claim_actions"
    __table_args__ = (
        UniqueConstraint(
            "scope_user_id",
            "claim_id",
            "idempotency_key",
            name="claim_actions_user_claim_key_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    scope_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    replacement_document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    replacement_document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    replacement_document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClaimVersionRow(Base):
    __tablename__ = "claim_versions"
    __table_args__ = (
        UniqueConstraint("claim_id", "version", name="claim_versions_claim_version_uq"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    submission: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("claim_id", "client_document_id", name="documents_claim_client_id_uq"),
        UniqueConstraint("claim_id", "upload_index", name="documents_claim_upload_index_uq"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    client_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    upload_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentVersionRow(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="document_versions_size_positive"),
        CheckConstraint("page_count > 0", name="document_versions_page_count_positive"),
        UniqueConstraint("document_id", "version", name="document_versions_document_version_uq"),
        UniqueConstraint("relative_path", name="document_versions_relative_path_uq"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("claim_id", "sequence", name="audit_claim_sequence_uq"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    actor_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_username_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClaimWorkItemRow(Base):
    __tablename__ = "claim_work_items"
    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts",
            name="claim_work_items_attempt_bounds",
        ),
        CheckConstraint(
            "max_attempts > 0",
            name="claim_work_items_max_attempts_positive",
        ),
        CheckConstraint(
            "claim_version > 0",
            name="claim_work_items_claim_version_positive",
        ),
        CheckConstraint(
            "status IN ('AVAILABLE', 'LEASED', 'COMPLETED', 'SUPERSEDED', 'FAILED')",
            name="claim_work_items_status_supported",
        ),
        CheckConstraint(
            "(status = 'LEASED' AND lease_owner IS NOT NULL "
            "AND lease_token IS NOT NULL AND lease_until IS NOT NULL) OR "
            "(status <> 'LEASED' AND lease_owner IS NULL "
            "AND lease_token IS NULL AND lease_until IS NULL)",
            name="claim_work_items_lease_consistent",
        ),
        Index(
            "ix_claim_work_items_due",
            "status",
            "available_at",
            "created_at",
        ),
        Index("ix_claim_work_items_lease_until", "lease_until"),
        ForeignKeyConstraint(
            ["claim_id", "claim_version"],
            ["claim_versions.claim_id", "claim_versions.version"],
            name="claim_work_items_claim_version_fkey",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
    )
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    last_failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "claim_version > 0",
            name="workflow_runs_claim_version_positive",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED')",
            name="workflow_runs_status_supported",
        ),
        ForeignKeyConstraint(
            ["claim_id", "claim_version"],
            ["claim_versions.claim_id", "claim_versions.version"],
            name="workflow_runs_claim_version_fkey",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "claim_id",
            "claim_version",
            "graph_name",
            "graph_version",
            name="workflow_runs_claim_graph_version_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    work_item_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claim_work_items.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    graph_name: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class WorkflowEffectRow(Base):
    __tablename__ = "workflow_effects"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            "effect_key",
            name="workflow_effects_run_key_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workflow_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    effect_key: Mapped[str] = mapped_column(String(160), nullable=False)
    effect_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
