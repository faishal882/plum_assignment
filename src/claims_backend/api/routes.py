from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
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
from claims_backend.application.claims import (
    ClaimNotFoundError,
    ClaimSubmissionForbiddenError,
)
from claims_backend.domain.claims import Claim, DocumentManifestItem, SubmitClaim

router = APIRouter(prefix="/v1/claims", tags=["claims"])


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
) -> ClaimReceiptResponse:
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
            for document in request.documents
        ),
    )
    try:
        claim = await application.submit(submission, principal)
    except ClaimSubmissionForbiddenError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CLAIM_SUBMISSION_FORBIDDEN",
                "message": "The identity cannot submit a claim for this member.",
                "details": [],
            },
        ) from error
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
