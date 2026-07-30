import hashlib
import json
import re
from datetime import UTC, date, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from claims_backend.domain.identity import Role, normalize_username
from claims_backend.infrastructure.postgres.models import (
    MemberRow,
    MemberVersionRow,
    PolicyVersionRow,
    SetupImportRow,
    UserMemberLinkRow,
    UserRoleRow,
    UserRow,
)
from claims_backend.runtime.profiles import ExecutionProfile

router = APIRouter(prefix="/v1/dev/identities", tags=["development"])


class DevIdentityResponse(BaseModel):
    username: str
    display_name: str
    member_id: str | None
    roles: list[str]


class CreateDevIdentityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=64)
    full_name: str = Field(min_length=1, max_length=255)
    date_of_birth: date
    gender: str = Field(min_length=1, max_length=32)
    join_date: date
    relationship: Literal["SELF"] = "SELF"


@router.get("", response_model=list[DevIdentityResponse])
async def list_dev_identities(request: Request) -> list[DevIdentityResponse]:
    _require_local_dev_profile(request)
    factory = request.app.state.session_factory
    async with factory() as session:
        users = (await session.scalars(select(UserRow).order_by(UserRow.normalized_username))).all()
        result: list[DevIdentityResponse] = []
        for user in users:
            roles = sorted(
                set(
                    (
                        await session.scalars(
                            select(UserRoleRow.role).where(UserRoleRow.user_id == user.id)
                        )
                    ).all()
                )
            )
            if not roles:
                continue
            member_id = await session.scalar(
                select(UserMemberLinkRow.member_id).where(UserMemberLinkRow.user_id == user.id)
            )
            if Role.MEMBER.value in roles and member_id is None:
                continue
            display_name = user.username
            if member_id is not None:
                member = await session.scalar(
                    select(MemberRow).where(
                        MemberRow.policy_id == "PLUM_GHI_2024",
                        MemberRow.external_member_id == member_id,
                    )
                )
                if member is None:
                    if Role.MEMBER.value in roles:
                        continue
                else:
                    version = await session.scalar(
                        select(MemberVersionRow)
                        .where(MemberVersionRow.member_id == member.id)
                        .order_by(MemberVersionRow.version.desc())
                        .limit(1)
                    )
                    if version is None and Role.MEMBER.value in roles:
                        continue
                    if version is not None:
                        display_name = version.name
            result.append(
                DevIdentityResponse(
                    username=user.normalized_username,
                    display_name=display_name,
                    member_id=member_id,
                    roles=roles,
                )
            )
        return result


@router.post("", response_model=DevIdentityResponse, status_code=status.HTTP_201_CREATED)
async def create_dev_identity(
    request: Request,
    command: CreateDevIdentityRequest,
) -> DevIdentityResponse:
    _require_local_dev_profile(request)
    username = normalize_username(command.username)
    now = datetime.now(UTC)
    factory = request.app.state.session_factory
    try:
        async with factory.begin() as session:
            existing_user = await session.scalar(
                select(UserRow.id).where(UserRow.normalized_username == username)
            )
            if existing_user is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "USERNAME_ALREADY_EXISTS",
                        "message": "A local identity with this username already exists.",
                        "details": [],
                    },
                )
            member_id = await _next_employee_id(session)
            policy_source_id = await session.scalar(
                select(PolicyVersionRow.policy_source_id).where(
                    PolicyVersionRow.policy_id == "PLUM_GHI_2024",
                    PolicyVersionRow.status == "ACTIVE",
                )
            )
            if policy_source_id is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "ACTIVE_POLICY_UNAVAILABLE",
                        "message": "No active PLUM_GHI_2024 policy is available.",
                        "details": [],
                    },
                )

            payload = {
                "kind": "LOCAL_DEMO_IDENTITY",
                "username": username,
                "member_id": member_id,
                "full_name": command.full_name,
                "date_of_birth": command.date_of_birth.isoformat(),
                "gender": command.gender,
                "join_date": command.join_date.isoformat(),
                "relationship": command.relationship,
                "policy_id": "PLUM_GHI_2024",
            }
            payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            payload_sha = hashlib.sha256(payload_bytes).hexdigest()

            user_id = uuid4()
            member_row_id = uuid4()
            import_id = uuid4()
            session.add(
                UserRow(
                    id=user_id,
                    username=username,
                    normalized_username=username,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                MemberRow(
                    id=member_row_id,
                    policy_id="PLUM_GHI_2024",
                    external_member_id=member_id,
                    created_at=now,
                )
            )
            session.add(
                SetupImportRow(
                    id=import_id,
                    policy_id="PLUM_GHI_2024",
                    policy_source_id=policy_source_id,
                    member_data_source_name=f"local-demo-identity:{username}",
                    member_data_sha256=payload_sha,
                    member_data_bytes=payload_bytes,
                    request_sha256=hashlib.sha256(
                        b"local-demo-identity:" + payload_bytes
                    ).hexdigest(),
                    imported_at=now,
                )
            )
            await session.flush()
            session.add(UserRoleRow(user_id=user_id, role=Role.MEMBER.value))
            session.add(UserMemberLinkRow(user_id=user_id, member_id=member_id))
            session.add(
                MemberVersionRow(
                    id=uuid4(),
                    member_id=member_row_id,
                    version=1,
                    setup_import_id=import_id,
                    primary_member_id=member_row_id,
                    name=command.full_name,
                    date_of_birth=command.date_of_birth,
                    gender=command.gender,
                    relationship=command.relationship,
                    join_date=command.join_date,
                    dependent_ids=[],
                    source_pointer="/local_demo_identity",
                    created_at=now,
                )
            )
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "LOCAL_IDENTITY_CONFLICT",
                "message": "A local identity with these details already exists.",
                "details": [],
            },
        ) from error

    return DevIdentityResponse(
        username=username,
        display_name=command.full_name,
        member_id=member_id,
        roles=[Role.MEMBER.value],
    )


async def _next_employee_id(session: AsyncSession) -> str:
    member_ids = (
        await session.scalars(
            select(MemberRow.external_member_id).where(MemberRow.policy_id == "PLUM_GHI_2024")
        )
    ).all()
    linked_member_ids = (await session.scalars(select(UserMemberLinkRow.member_id))).all()
    existing_ids = [*member_ids, *linked_member_ids]
    highest = 0
    width = 3
    for existing_id in existing_ids:
        match = re.fullmatch(r"EMP(\d+)", existing_id.upper())
        if match is None:
            continue
        numeric_part = match.group(1)
        highest = max(highest, int(numeric_part))
        width = max(width, len(numeric_part))
    return f"EMP{highest + 1:0{width}d}"


def _require_local_dev_profile(request: Request) -> None:
    if request.app.state.settings.execution_profile not in {
        ExecutionProfile.RECORDED_LOCAL,
        ExecutionProfile.LIVE_INTELLIGENCE,
    }:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
