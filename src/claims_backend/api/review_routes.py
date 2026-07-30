import re
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status

from claims_backend.api.dependencies import (
    CurrentPrincipalDependency,
    ReviewApplicationDependency,
)
from claims_backend.api.schemas import (
    OcrObservationResponse,
    ReviewCommandRequest,
    ReviewResolutionResponse,
    ReviewTaskDetailResponse,
    ReviewTaskSummaryResponse,
)
from claims_backend.application.reviews import (
    ReviewCommandIdempotencyConflictError,
    ReviewCommandInvalidError,
    ReviewForbiddenError,
    ReviewStaleClaimVersionError,
    ReviewTaskNotFoundError,
    ReviewTaskNotOpenError,
)
from claims_backend.domain.reviews import (
    ReviewCommand,
    ReviewResolution,
    ReviewTaskDetail,
    ReviewTaskSummary,
)

router = APIRouter(prefix="/v1/review-tasks", tags=["review"])
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@router.get("", response_model=list[ReviewTaskSummaryResponse])
async def list_review_tasks(
    application: ReviewApplicationDependency,
    principal: CurrentPrincipalDependency,
) -> list[ReviewTaskSummaryResponse]:
    try:
        tasks = await application.list_tasks(principal)
    except ReviewForbiddenError as error:
        raise _forbidden() from error
    return [_summary(task) for task in tasks]


@router.get("/{task_id}", response_model=ReviewTaskDetailResponse)
async def get_review_task(
    task_id: UUID,
    application: ReviewApplicationDependency,
    principal: CurrentPrincipalDependency,
) -> ReviewTaskDetailResponse:
    try:
        detail = await application.get_task(task_id, principal)
    except ReviewForbiddenError as error:
        raise _forbidden() from error
    except ReviewTaskNotFoundError as error:
        raise _not_found() from error
    return _detail(detail)


@router.post(
    "/{task_id}/commands",
    response_model=ReviewResolutionResponse,
)
async def resolve_review_task(
    task_id: UUID,
    request: ReviewCommandRequest,
    application: ReviewApplicationDependency,
    principal: CurrentPrincipalDependency,
    idempotency_key_header: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
) -> ReviewResolutionResponse:
    idempotency_key = _idempotency_key(idempotency_key_header)
    try:
        resolution = await application.resolve(
            task_id,
            ReviewCommand(
                action=request.action,
                expected_claim_version=request.expected_claim_version,
                reason_code=request.reason_code,
                reason_note=request.reason_note,
                amended_paise=(
                    None if request.amended_amount is None else int(request.amended_amount * 100)
                ),
            ),
            principal,
            idempotency_key,
        )
    except ReviewForbiddenError as error:
        raise _forbidden() from error
    except ReviewTaskNotFoundError as error:
        raise _not_found() from error
    except ReviewStaleClaimVersionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "STALE_CLAIM_VERSION",
                "message": "The claim changed before review resolution.",
                "details": [],
                "current_version": error.current_version,
            },
        ) from error
    except ReviewTaskNotOpenError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REVIEW_TASK_NOT_OPEN",
                "message": "The review task cannot accept this command.",
                "details": [],
            },
        ) from error
    except ReviewCommandIdempotencyConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REVIEW_IDEMPOTENCY_KEY_REUSED",
                "message": "The idempotency key was used for another command.",
                "details": [],
            },
        ) from error
    except ReviewCommandInvalidError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVALID_REVIEW_COMMAND",
                "message": "The review command is invalid.",
                "details": [],
            },
        ) from error
    return _resolution(resolution)


def _summary(task: ReviewTaskSummary) -> ReviewTaskSummaryResponse:
    return ReviewTaskSummaryResponse(
        id=task.id,
        claim_id=task.claim_id,
        claim_version=task.claim_version,
        status=task.status.value,
        signal_codes=list(task.signal_codes),
        machine_recommendation=task.machine_recommendation,
        machine_approved_amount=Decimal(task.machine_approved_paise) / 100,
        currency=task.currency,
        allowed_actions=[action.value for action in task.allowed_actions],
        created_at=task.created_at,
        resolved_at=task.resolved_at,
    )


def _detail(detail: ReviewTaskDetail) -> ReviewTaskDetailResponse:
    return ReviewTaskDetailResponse(
        task=_summary(detail.summary),
        evidence=detail.evidence,
        conflicts=list(detail.conflicts),
        rules=list(detail.rules),
        calculations=list(detail.calculations),
        failures=list(detail.failures),
        ocr_observations={
            key: OcrObservationResponse(**value)
            for key, value in detail.ocr_observations.items()
        },
    )


def _resolution(value: ReviewResolution) -> ReviewResolutionResponse:
    return ReviewResolutionResponse(
        id=value.id,
        task_id=value.task_id,
        action=value.action.value,
        reason_code=value.reason_code,
        reason_note=value.reason_note,
        before=value.before,
        after=value.after,
        actor_user_id=value.actor_user_id,
        actor_username=value.actor_username,
        created_at=value.created_at,
        replayed=value.replayed,
    )


def _idempotency_key(value: str | None) -> str:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "An Idempotency-Key header is required.",
                "details": [],
            },
        )
    if _IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_IDEMPOTENCY_KEY",
                "message": "The Idempotency-Key header is invalid.",
                "details": [],
            },
        )
    return value


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "REVIEW_FORBIDDEN",
            "message": "The identity cannot access review tasks.",
            "details": [],
        },
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "REVIEW_TASK_NOT_FOUND",
            "message": "The review task was not found.",
            "details": [],
        },
    )
