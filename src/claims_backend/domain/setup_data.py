from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class FindingSeverity(StrEnum):
    WARNING = "WARNING"
    ERROR = "ERROR"


class FactState(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ImportFinding:
    severity: FindingSeverity
    code: str
    source_pointer: str
    message: str
    subject_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemberRecord:
    external_member_id: str
    name: str
    date_of_birth: date
    gender: str
    relationship: str
    join_date: date | None
    primary_member_id: str | None
    dependent_ids: tuple[str, ...]
    source_pointer: str


@dataclass(frozen=True, slots=True)
class ClaimHistoryRecord:
    history_claim_id: str
    member_id: str
    treatment_date: date
    amount_paise: int
    currency: str
    provider: str | None
    source_pointer: str


@dataclass(frozen=True, slots=True)
class UtilizationRecord:
    member_id: str
    period_start: date
    period_end: date
    used_paise: int
    currency: str
    as_of_date: date
    source_pointer: str


@dataclass(frozen=True, slots=True)
class SetupImportBundle:
    policy_id: str
    policy_source_bytes: bytes
    policy_source_name: str
    policy_source_sha256: str
    member_data_bytes: bytes | None
    member_data_source_name: str | None
    member_data_sha256: str | None
    request_sha256: str
    members: tuple[MemberRecord, ...]
    claim_history: tuple[ClaimHistoryRecord, ...]
    utilization: tuple[UtilizationRecord, ...]
    findings: tuple[ImportFinding, ...]


@dataclass(frozen=True, slots=True)
class SetupImportReceipt:
    import_id: UUID
    policy_id: str
    policy_source_sha256: str
    member_data_sha256: str | None
    member_versions_created: int
    history_records_created: int
    utilization_records_created: int
    findings: tuple[ImportFinding, ...]
    imported_at: datetime


@dataclass(frozen=True, slots=True)
class MemberInspection:
    policy_id: str
    member_id: str
    version: int
    name: str
    date_of_birth: date
    gender: str
    relationship: str
    join_date: date | None
    primary_member_id: str | None
    dependent_ids: tuple[str, ...]
    source_sha256: str
    source_pointer: str
    utilization_state: FactState
    used_paise: int | None
    utilization_as_of_date: date | None
