from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
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


class PolicyOverlayRow(Base):
    __tablename__ = "policy_overlays"
    __table_args__ = (
        CheckConstraint("octet_length(source_bytes) > 0", name="policy_overlays_bytes_nonempty"),
        UniqueConstraint(
            "overlay_id",
            "version",
            name="policy_overlays_identity_version_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    overlay_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_policy_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    approval_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyVersionRow(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (
        CheckConstraint("version > 0", name="policy_versions_version_positive"),
        CheckConstraint(
            "status IN ('INVALID', 'COMPILED', 'ACTIVE', 'RETIRED')",
            name="policy_versions_status_supported",
        ),
        UniqueConstraint(
            "policy_id",
            "version",
            name="policy_versions_policy_version_uq",
        ),
        UniqueConstraint(
            "policy_source_id",
            "policy_overlay_id",
            "compiler_version",
            name="policy_versions_compilation_identity_uq",
        ),
        Index(
            "policy_versions_one_active_uq",
            "policy_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    policy_overlay_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_overlays.id", ondelete="RESTRICT"),
        nullable=False,
    )
    compiler_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ir: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    ir_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    compiled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    activated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class PolicyFindingRow(Base):
    __tablename__ = "policy_findings"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_pointer: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_by_overlay: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyActivationEventRow(Base):
    __tablename__ = "policy_activation_events"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str] = mapped_column(String(16), nullable=False)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    policy_source_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_sources.id", ondelete="RESTRICT"),
        nullable=True,
    )
    policy_overlay_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_overlays.id", ondelete="RESTRICT"),
        nullable=True,
    )
    policy_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    member_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("member_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    treatment_date: Mapped[date] = mapped_column(Date, nullable=False)
    claimed_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    adjudication_recommendation: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    approved_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    member_explanation: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    current_action: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    handling_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    processing_quality: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    review_task_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "review_tasks.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="claims_review_task_fk",
        ),
        nullable=True,
    )
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


class ProcessingFixtureRow(Base):
    __tablename__ = "processing_fixtures"
    __table_args__ = (
        UniqueConstraint(
            "claim_id",
            "claim_version",
            name="processing_fixtures_claim_version_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False)
    route: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CasefileRow(Base):
    __tablename__ = "casefiles"
    __table_args__ = (
        UniqueConstraint("claim_id", "claim_version", name="casefiles_claim_version_uq"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    member_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("member_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionRecordRow(Base):
    __tablename__ = "decision_records"
    __table_args__ = (
        CheckConstraint(
            "approved_paise >= 0",
            name="decision_records_approved_nonnegative",
        ),
        UniqueConstraint(
            "claim_id",
            "claim_version",
            name="decision_records_claim_version_uq",
        ),
        UniqueConstraint("canonical_hash", name="decision_records_canonical_hash_uq"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False)
    casefile_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("casefiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RuleResultRow(Base):
    __tablename__ = "rule_results"
    __table_args__ = (
        UniqueConstraint(
            "decision_record_id",
            "sequence",
            name="rule_results_decision_sequence_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    decision_record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("decision_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_path: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    inputs: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    amount_before_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adjustment_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_after_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ComponentFailureRow(Base):
    __tablename__ = "component_failures"
    __table_args__ = (
        UniqueConstraint(
            "decision_record_id",
            "component",
            name="component_failures_decision_component_uq",
        ),
        CheckConstraint("attempts > 0", name="component_failures_attempts_positive"),
        CheckConstraint(
            "completeness >= 0 AND completeness <= 1",
            name="component_failures_completeness_ratio",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="component_failures_confidence_ratio",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("decision_records.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    criticality: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_code: Mapped[str] = mapped_column(String(64), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    completeness: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    effect_on_handling: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewTaskRow(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        UniqueConstraint(
            "claim_id",
            "claim_version",
            name="review_tasks_claim_version_uq",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'RESOLVED')",
            name="review_tasks_status_supported",
        ),
        CheckConstraint(
            "machine_approved_paise >= 0",
            name="review_tasks_machine_amount_nonnegative",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_record_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("decision_records.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    signal_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    allowed_actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    machine_recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    machine_approved_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ReviewResolutionRow(Base):
    __tablename__ = "review_resolutions"
    __table_args__ = (
        UniqueConstraint("task_id", name="review_resolutions_task_uq"),
        UniqueConstraint(
            "actor_user_id",
            "task_id",
            "idempotency_key",
            name="review_resolutions_actor_task_key_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("review_tasks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_note: Mapped[str] = mapped_column(Text, nullable=False)
    before: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    actor_user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_username_snapshot: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentTriageResultRow(Base):
    __tablename__ = "document_triage_results"
    __table_args__ = (
        UniqueConstraint(
            "claim_id",
            "claim_version",
            "client_document_id",
            name="document_triage_results_claim_version_document_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    client_document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    readability: Mapped[str] = mapped_column(String(32), nullable=False)
    readability_observation: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )
    identity_observations: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
    )
    model_route: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemberActionRow(Base):
    __tablename__ = "member_actions"
    __table_args__ = (
        UniqueConstraint(
            "claim_id",
            "claim_version",
            name="member_actions_claim_version_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    observed_document_roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    required_document_roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdentityReconciliationRow(Base):
    __tablename__ = "identity_reconciliations"
    __table_args__ = (
        UniqueConstraint(
            "claim_id",
            "claim_version",
            name="identity_reconciliations_claim_version_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False)
    member_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("member_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    member_name: Mapped[str] = mapped_column(String(128), nullable=False)
    candidates: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentPageArtifactRow(Base):
    __tablename__ = "document_page_artifacts"
    __table_args__ = (
        CheckConstraint("page_number > 0", name="page_artifacts_page_positive"),
        CheckConstraint("size_bytes > 0", name="page_artifacts_size_positive"),
        UniqueConstraint(
            "document_version_id",
            "page_number",
            "render_version",
            name="document_page_artifacts_version_page_render_uq",
        ),
        UniqueConstraint(
            "relative_path",
            name="document_page_artifacts_relative_path_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rendered_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    render_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OcrPageResultRow(Base):
    __tablename__ = "ocr_page_results"
    __table_args__ = (
        CheckConstraint("page_number > 0", name="ocr_page_results_page_positive"),
        CheckConstraint(
            "retry_attempts >= 0",
            name="ocr_page_results_retry_attempts_nonnegative",
        ),
        UniqueConstraint(
            "page_artifact_id",
            "provider_name",
            "provider_version",
            name="ocr_page_results_artifact_provider_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    page_artifact_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_page_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(64), nullable=False)
    profile: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    retry_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OcrObservationRow(Base):
    __tablename__ = "ocr_observations"
    __table_args__ = (
        CheckConstraint("page_number > 0", name="ocr_observations_page_positive"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ocr_observations_confidence_range",
        ),
        UniqueConstraint(
            "observation_id",
            name="ocr_observations_observation_id_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    ocr_page_result_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ocr_page_results.id", ondelete="RESTRICT"),
        nullable=False,
    )
    observation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    region: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelExtractionRow(Base):
    __tablename__ = "model_extractions"
    __table_args__ = (
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name="model_extractions_tokens_nonnegative",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="model_extractions_latency_nonnegative",
        ),
        UniqueConstraint(
            "document_version_id",
            "route",
            "model_id",
            "prompt_version",
            "schema_version",
            "input_sha256",
            name="model_extractions_replay_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    route: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceCandidateRow(Base):
    __tablename__ = "evidence_candidates"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="evidence_candidates_confidence_range",
        ),
        UniqueConstraint(
            "candidate_id",
            name="evidence_candidates_candidate_id_uq",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    model_extraction_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("model_extractions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fact_path: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[object] = mapped_column(JSONB, nullable=True)
    normalized_value: Mapped[object] = mapped_column(JSONB, nullable=True)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    producer: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
