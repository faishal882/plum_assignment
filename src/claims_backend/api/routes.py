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
    AffectedDocumentResponse,
    ClaimActionResponse,
    ClaimMetadataRequest,
    ClaimReceiptResponse,
    ClaimResponse,
    IdentityConflictResponse,
    MemberActionResponse,
    MemberAdjudicationResponse,
    MemberDeductionResponse,
    MemberExplanationResponse,
    MemberLineItemExplanationResponse,
    ProgressResponse,
    ReplaceDocumentCommandRequest,
    ReplacementDocumentResponse,
)
from claims_backend.api.uploads import FastAPIUploadSource
from claims_backend.application.claims import (
    ActionIdempotencyConflictError,
    ActivePolicyUnavailableError,
    ClaimActionForbiddenError,
    ClaimActionNotAllowedError,
    ClaimDocumentNotFoundError,
    ClaimNotFoundError,
    ClaimSubmissionForbiddenError,
    IdempotencyConflictError,
    MemberSnapshotUnavailableError,
    StaleClaimVersionError,
)
from claims_backend.application.documents import (
    ClaimUploadTooLargeError,
    DocumentIngestionError,
    FileTooLargeError,
    UnsupportedDocumentError,
)
from claims_backend.domain.claims import (
    Claim,
    ClaimLifecycle,
    DocumentManifestItem,
    ReplaceDocument,
    SubmitClaim,
)

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
    except ActivePolicyUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ACTIVE_POLICY_UNAVAILABLE",
                "message": "No active compiled policy is available for this claim.",
                "details": [],
            },
        ) from error
    except MemberSnapshotUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "MEMBER_SNAPSHOT_UNAVAILABLE",
                "message": "No member snapshot is available for the active policy.",
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


@router.post("/{claim_id}/actions", response_model=ClaimActionResponse)
async def apply_claim_action(
    claim_id: UUID,
    command: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    application: ClaimsApplicationDependency,
    principal: CurrentPrincipalDependency,
    idempotency_key_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ClaimActionResponse:
    idempotency_key = _validate_idempotency_key(idempotency_key_header)
    request = _parse_action(command)
    try:
        result = await application.replace_document(
            claim_id,
            ReplaceDocument(
                expected_version=request.expected_version,
                client_document_id=request.client_document_id,
            ),
            principal,
            FastAPIUploadSource(file),
            idempotency_key,
        )
    except ClaimNotFoundError as error:
        raise _claim_not_found(error) from error
    except ClaimActionForbiddenError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "CLAIM_ACTION_FORBIDDEN",
                "message": "The identity cannot apply this claim action.",
                "details": [],
            },
        ) from error
    except ClaimDocumentNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CLAIM_DOCUMENT_NOT_FOUND",
                "message": "The claim document was not found.",
                "details": [],
            },
        ) from error
    except StaleClaimVersionError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "STALE_CLAIM_VERSION",
                "message": "The claim changed before this action could be applied.",
                "details": [],
                "current_version": error.current_version,
            },
        ) from error
    except ClaimActionNotAllowedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CLAIM_ACTION_NOT_ALLOWED",
                "message": "This action is not allowed for the current claim lifecycle.",
                "details": [],
            },
        ) from error
    except ActionIdempotencyConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ACTION_IDEMPOTENCY_KEY_REUSED",
                "message": "The Idempotency-Key was already used for a different action.",
                "details": [],
            },
        ) from error
    except DocumentIngestionError as error:
        raise _document_error(error) from error

    return ClaimActionResponse(
        action_id=result.action_id,
        action_type="REPLACE_DOCUMENT",
        claim_id=result.claim.id,
        previous_version=result.previous_version,
        version=result.result_version,
        lifecycle_status=result.result_lifecycle.value,
        document=ReplacementDocumentResponse(
            client_document_id=result.client_document_id,
            version=result.document_version,
        ),
        status_url=f"/v1/claims/{result.claim.id}",
    )


@router.get(
    "/{claim_id}",
    response_model=ClaimResponse,
    response_model_exclude_none=True,
)
async def get_claim(
    claim_id: UUID,
    application: ClaimsApplicationDependency,
    principal: CurrentPrincipalDependency,
) -> ClaimResponse:
    try:
        claim = await application.get(claim_id, principal)
    except ClaimNotFoundError as error:
        raise _claim_not_found(error) from error
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


def _parse_action(command: str) -> ReplaceDocumentCommandRequest:
    try:
        return ReplaceDocumentCommandRequest.model_validate_json(command)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVALID_CLAIM_ACTION",
                "message": "Claim action is invalid.",
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
        progress=ProgressResponse(
            current_stage=claim.lifecycle.value,
            is_terminal=claim.lifecycle is ClaimLifecycle.DECIDED,
        ),
        adjudication=(
            None
            if claim.adjudication is None
            else MemberAdjudicationResponse(
                recommendation=claim.adjudication.recommendation,
                approved_amount=Decimal(claim.adjudication.approved_paise) / 100,
                currency=claim.adjudication.currency,
            )
        ),
        explanation=(
            None
            if claim.explanation is None
            else MemberExplanationResponse(
                summary=claim.explanation.summary,
                deductions=[
                    MemberDeductionResponse(
                        code=deduction.code,
                        label=deduction.label,
                        amount=Decimal(deduction.amount_paise) / 100,
                    )
                    for deduction in claim.explanation.deductions
                ],
                line_items=(
                    [
                        MemberLineItemExplanationResponse(
                            concept=item.concept,
                            label=item.label,
                            claimed_amount=Decimal(item.claimed_paise) / 100,
                            approved_amount=Decimal(item.approved_paise) / 100,
                            status=item.status,
                            reason_code=item.reason_code,
                        )
                        for item in claim.explanation.line_items
                    ]
                    or None
                ),
            )
        ),
        action=(
            None
            if claim.action is None
            else MemberActionResponse(
                code=claim.action.code,
                message=claim.action.message,
                observed_document_roles=list(claim.action.observed_document_roles),
                required_document_roles=list(claim.action.required_document_roles),
                affected_documents=(
                    [
                        AffectedDocumentResponse(
                            client_document_id=document.client_document_id,
                            observed_role=document.observed_role,
                            requested_action=document.requested_action,
                        )
                        for document in claim.action.affected_documents
                    ]
                    or None
                ),
                identity_conflict=(
                    [
                        IdentityConflictResponse(
                            client_document_id=item.client_document_id,
                            patient_name=item.patient_name,
                        )
                        for item in claim.action.identity_conflict
                    ]
                    or None
                ),
            )
        ),
        handling_status=claim.handling_status,
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


def _claim_not_found(error: ClaimNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "CLAIM_NOT_FOUND",
            "message": "Claim was not found.",
            "details": [],
        },
    )
