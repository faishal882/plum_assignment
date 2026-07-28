import json
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from claims_backend.domain.setup_data import (
    ClaimHistoryRecord,
    FindingSeverity,
    ImportFinding,
    MemberInspection,
    MemberRecord,
    SetupImportBundle,
    SetupImportReceipt,
    UtilizationRecord,
)


class InvalidSetupSourceError(ValueError):
    pass


class SetupImportRepository(Protocol):
    async def import_bundle(self, bundle: SetupImportBundle) -> SetupImportReceipt: ...

    async def inspect_member(
        self,
        policy_id: str,
        member_id: str,
    ) -> MemberInspection | None: ...

    async def get_import(self, import_id: UUID) -> SetupImportReceipt | None: ...


class _PolicyMember(BaseModel):
    model_config = ConfigDict(extra="allow")

    member_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    date_of_birth: str
    gender: str = Field(min_length=1, max_length=32)
    relationship: str = Field(min_length=1, max_length=32)
    join_date: str | None = None
    primary_member_id: str | None = None
    dependents: list[str] = Field(default_factory=list)


class _PolicySource(BaseModel):
    model_config = ConfigDict(extra="allow")

    policy_id: str = Field(min_length=1, max_length=64)
    members: list[_PolicyMember]


class _HistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_claim_id: str = Field(min_length=1, max_length=128)
    member_id: str = Field(min_length=1, max_length=64)
    treatment_date: str
    amount: str
    currency: str = Field(min_length=3, max_length=3)
    provider: str | None = Field(default=None, max_length=255)


class _UtilizationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: str = Field(min_length=1, max_length=64)
    period_start: str
    period_end: str
    used_amount: str
    currency: str = Field(min_length=3, max_length=3)
    as_of_date: str


class _MemberDataSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1, max_length=64)
    as_of_date: str
    claim_history: list[_HistoryItem] = Field(default_factory=list)
    utilization: list[_UtilizationItem] = Field(default_factory=list)


class SetupDataApplication:
    def __init__(self, repository: SetupImportRepository) -> None:
        self._repository = repository

    async def import_sources(
        self,
        policy_source_bytes: bytes,
        *,
        source_name: str,
        member_data_bytes: bytes | None = None,
        member_data_source_name: str | None = None,
    ) -> SetupImportReceipt:
        policy = _parse_model(_PolicySource, policy_source_bytes, "policy source")
        member_data = (
            None
            if member_data_bytes is None
            else _parse_model(_MemberDataSource, member_data_bytes, "member data source")
        )
        if member_data is not None and member_data.policy_id != policy.policy_id:
            raise InvalidSetupSourceError("Member data policy_id does not match the policy source.")
        if member_data_bytes is not None and not member_data_source_name:
            raise InvalidSetupSourceError(
                "member_data_source_name is required when member data bytes are supplied."
            )

        policy_hash = sha256(policy_source_bytes).hexdigest()
        member_data_hash = (
            None if member_data_bytes is None else sha256(member_data_bytes).hexdigest()
        )
        request_hash = sha256(f"{policy_hash}:{member_data_hash or '-'}".encode()).hexdigest()
        members, findings = _members_and_findings(policy)
        history, utilization, data_findings = _member_facts(member_data, members)
        bundle = SetupImportBundle(
            policy_id=policy.policy_id,
            policy_source_bytes=policy_source_bytes,
            policy_source_name=source_name,
            policy_source_sha256=policy_hash,
            member_data_bytes=member_data_bytes,
            member_data_source_name=member_data_source_name,
            member_data_sha256=member_data_hash,
            request_sha256=request_hash,
            members=members,
            claim_history=history,
            utilization=utilization,
            findings=findings + data_findings,
        )
        return await self._repository.import_bundle(bundle)

    async def inspect_member(
        self,
        policy_id: str,
        member_id: str,
    ) -> MemberInspection | None:
        return await self._repository.inspect_member(policy_id, member_id)

    async def inspect_import(self, import_id: UUID) -> SetupImportReceipt | None:
        return await self._repository.get_import(import_id)


def _parse_model[ModelT: BaseModel](
    model: type[ModelT],
    source: bytes,
    label: str,
) -> ModelT:
    try:
        raw: Any = json.loads(source)
        return model.model_validate(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise InvalidSetupSourceError(f"Invalid {label}: {error}") from error


def _members_and_findings(
    policy: _PolicySource,
) -> tuple[tuple[MemberRecord, ...], tuple[ImportFinding, ...]]:
    records: list[MemberRecord] = []
    findings: list[ImportFinding] = []
    seen: set[str] = set()
    for index, source in enumerate(policy.members):
        pointer = f"/members/{index}"
        if source.member_id in seen:
            findings.append(
                ImportFinding(
                    FindingSeverity.ERROR,
                    "DUPLICATE_MEMBER_ID",
                    pointer,
                    f"Member {source.member_id} appears more than once.",
                    source.member_id,
                )
            )
            continue
        seen.add(source.member_id)
        records.append(
            MemberRecord(
                external_member_id=source.member_id,
                name=source.name,
                date_of_birth=_date(source.date_of_birth, f"{pointer}/date_of_birth"),
                gender=source.gender,
                relationship=source.relationship,
                join_date=(
                    None
                    if source.join_date is None
                    else _date(source.join_date, f"{pointer}/join_date")
                ),
                primary_member_id=source.primary_member_id,
                dependent_ids=tuple(source.dependents),
                source_pointer=pointer,
            )
        )

    by_id = {record.external_member_id: record for record in records}
    for record in records:
        for dependent_id in record.dependent_ids:
            dependent = by_id.get(dependent_id)
            pointer = f"{record.source_pointer}/dependents"
            if dependent is None:
                findings.append(
                    ImportFinding(
                        FindingSeverity.WARNING,
                        "MISSING_DEPENDENT_RECORD",
                        pointer,
                        f"Dependent {dependent_id} is referenced but has no member record.",
                        dependent_id,
                    )
                )
            elif dependent.primary_member_id != record.external_member_id:
                findings.append(
                    ImportFinding(
                        FindingSeverity.ERROR,
                        "DEPENDENT_PRIMARY_MISMATCH",
                        pointer,
                        f"Dependent {dependent_id} does not link back to "
                        f"{record.external_member_id}.",
                        dependent_id,
                    )
                )
        if record.primary_member_id is not None:
            primary = by_id.get(record.primary_member_id)
            if primary is None:
                findings.append(
                    ImportFinding(
                        FindingSeverity.ERROR,
                        "MISSING_PRIMARY_MEMBER",
                        f"{record.source_pointer}/primary_member_id",
                        f"Primary member {record.primary_member_id} does not exist.",
                        record.external_member_id,
                    )
                )
            elif record.external_member_id not in primary.dependent_ids:
                findings.append(
                    ImportFinding(
                        FindingSeverity.ERROR,
                        "PRIMARY_DEPENDENT_MISMATCH",
                        f"{record.source_pointer}/primary_member_id",
                        f"Primary member {record.primary_member_id} does not reference "
                        f"{record.external_member_id}.",
                        record.external_member_id,
                    )
                )
    return tuple(records), tuple(findings)


def _member_facts(
    source: _MemberDataSource | None,
    members: tuple[MemberRecord, ...],
) -> tuple[
    tuple[ClaimHistoryRecord, ...],
    tuple[UtilizationRecord, ...],
    tuple[ImportFinding, ...],
]:
    if source is None:
        return (), (), ()
    member_ids = {member.external_member_id for member in members}
    findings: list[ImportFinding] = []
    history: list[ClaimHistoryRecord] = []
    utilization: list[UtilizationRecord] = []
    for index, history_item in enumerate(source.claim_history):
        pointer = f"/claim_history/{index}"
        if history_item.member_id not in member_ids:
            findings.append(_unknown_member_finding(history_item.member_id, pointer))
            continue
        history.append(
            ClaimHistoryRecord(
                history_claim_id=history_item.history_claim_id,
                member_id=history_item.member_id,
                treatment_date=_date(
                    history_item.treatment_date,
                    f"{pointer}/treatment_date",
                ),
                amount_paise=_money(history_item.amount, f"{pointer}/amount"),
                currency=history_item.currency.upper(),
                provider=history_item.provider,
                source_pointer=pointer,
            )
        )
    for index, utilization_item in enumerate(source.utilization):
        pointer = f"/utilization/{index}"
        if utilization_item.member_id not in member_ids:
            findings.append(_unknown_member_finding(utilization_item.member_id, pointer))
            continue
        period_start = _date(utilization_item.period_start, f"{pointer}/period_start")
        period_end = _date(utilization_item.period_end, f"{pointer}/period_end")
        if period_end < period_start:
            raise InvalidSetupSourceError(f"{pointer} has an inverted period.")
        utilization.append(
            UtilizationRecord(
                member_id=utilization_item.member_id,
                period_start=period_start,
                period_end=period_end,
                used_paise=_money(
                    utilization_item.used_amount,
                    f"{pointer}/used_amount",
                ),
                currency=utilization_item.currency.upper(),
                as_of_date=_date(
                    utilization_item.as_of_date,
                    f"{pointer}/as_of_date",
                ),
                source_pointer=pointer,
            )
        )
    return tuple(history), tuple(utilization), tuple(findings)


def _unknown_member_finding(member_id: str, pointer: str) -> ImportFinding:
    return ImportFinding(
        FindingSeverity.ERROR,
        "UNKNOWN_MEMBER_REFERENCE",
        pointer,
        f"Member data references unknown member {member_id}; the record was not imported.",
        member_id,
    )


def _date(value: str, pointer: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise InvalidSetupSourceError(f"{pointer} is not a valid ISO date.") from error


def _money(value: str, pointer: str) -> int:
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise InvalidSetupSourceError(f"{pointer} is not a decimal amount.") from error
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        raise InvalidSetupSourceError(f"{pointer} must be non-negative with at most 2 decimals.")
    return int(amount * 100)
