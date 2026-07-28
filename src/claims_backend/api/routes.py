import re
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status
from pydantic import ValidationError

from claims_backend.api.dependencies import (
    ClaimsApplicationDependency,
    CurrentPrincipalDependency,
)
from claims_backend.api.schemas import (
    ClaimMetadataRequest,
    ClaimReceiptResponse,
    ClaimResponse,
    ProgressResponse,
)
from claims_backend.api.uploads import FastAPIUploadSource
from claims_backend.application.claims import (
    ClaimNotFoundError,
    ClaimSubmissionForbiddenError,
    IdempotencyConflictError,
)
from claims_backend.application.documents import (
    ClaimUploadTooLargeError,
    DocumentIngestionError,
    FileTooLargeError,
    UnsupportedDocumentError,
)
from claims_backend.domain.claims import Claim, DocumentManifestItem, SubmitClaim

router = APIRouter(prefix="/v1/claims", tags=["claims"])
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@router.post(
    "",
    response_model=ClaimReceiptResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_claim(
    metadata: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    application: ClaimsApplicationDependency,
    principal: CurrentPrincipalDependency,
    idempotency_key_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ClaimReceiptResponse:
    idempotency_key = _validate_idempotency_key(idempotency_key_header)
    request = _parse_metadata(metadata)
    if len(files) != len(request.documents):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "DOCUMENT_MANIFEST_MISMATCH",
                "message": "Document manifest must contain exactly one entry per uploaded file.",
                "details": [],
            },
        )

    submission = SubmitClaim(
        member_id=request.member_id,
        policy_id=request.policy_id,
        category=request.claim_category,
        treatment_date=request.treatment_date,
        claimed_paise=_rupees_to_paise(request.claimed_amount),
        currency=request.currency,
        documents=tuple(
            DocumentManifestItem(
                upload_index=document.upload_index,
                client_document_id=document.client_document_id,
            )
            for document in sorted(request.documents, key=lambda item: item.upload_index)
        ),
    )
    try:
        claim = await application.submit(
            submission,
            principal,
            [FastAPIUploadSource(upload) for upload in files],
            idempotency_key,
        )
    except ClaimSubmissionForbiddenError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CLAIM_SUBMISSION_FORBIDDEN",
                "message": "The identity cannot submit a claim for this member.",
                "details": [],
            },
        ) from error
    except IdempotencyConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "The Idempotency-Key was already used for a different request.",
                "details": [],
            },
        ) from error
    except DocumentIngestionError as error:
        raise _document_error(error) from error
    return ClaimReceiptResponse(
        claim_id=claim.id,
        version=claim.version,
        lifecycle_status=claim.lifecycle.value,
        status_url=f"/v1/claims/{claim.id}",
    )


@router.get("/{claim_id}", response_model=ClaimResponse)
async def get_claim(
    claim_id: UUID,
    application: ClaimsApplicationDependency,
    principal: CurrentPrincipalDependency,
) -> ClaimResponse:
    try:
        claim = await application.get(claim_id, principal)
    except ClaimNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CLAIM_NOT_FOUND",
                "message": "Claim was not found.",
                "details": [],
            },
        ) from error
    return _to_response(claim)


def _validate_idempotency_key(value: str | None) -> str:
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


def _parse_metadata(metadata: str) -> ClaimMetadataRequest:
    try:
        return ClaimMetadataRequest.model_validate_json(metadata)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVALID_CLAIM_METADATA",
                "message": "Claim metadata is invalid.",
                "details": [
                    {
                        "location": [str(item) for item in issue["loc"]],
                        "message": issue["msg"],
                        "type": issue["type"],
                    }
                    for issue in error.errors()
                ],
            },
        ) from error


def _rupees_to_paise(amount: Decimal) -> int:
    return int(amount * 100)


def _to_response(claim: Claim) -> ClaimResponse:
    return ClaimResponse(
        claim_id=claim.id,
        version=claim.version,
        member_id=claim.member_id,
        policy_id=claim.policy_id,
        claim_category=claim.category.value,
        treatment_date=claim.treatment_date,
        claimed_amount=Decimal(claim.claimed_paise) / 100,
        currency=claim.currency,
        lifecycle_status=claim.lifecycle.value,
        progress=ProgressResponse(current_stage=claim.lifecycle.value, is_terminal=False),
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )


def _document_error(error: DocumentIngestionError) -> HTTPException:
    if isinstance(error, (FileTooLargeError, ClaimUploadTooLargeError)):
        status_code = status.HTTP_413_CONTENT_TOO_LARGE
    elif isinstance(error, UnsupportedDocumentError):
        status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT

    details: list[dict[str, object]] = []
    if error.upload_index is not None:
        details.append(
            {
                "location": ["files", error.upload_index],
                "message": error.message,
                "type": error.code,
            }
        )
    return HTTPException(
        status_code=status_code,
        detail={
            "code": error.code,
            "message": error.message,
            "details": details,
        },
    )
