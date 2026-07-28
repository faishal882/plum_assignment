# Plum Claims Backend

Backend-first implementation of an explainable health-insurance claim processing system.

The current implementation follows the phased plan in
[`plans/backend-claim-processing.md`](plans/backend-claim-processing.md).

## Local prerequisites

- Python 3.12
- `uv`
- Docker with Docker Compose

## Run locally

Install the locked dependencies and start PostgreSQL:

```bash
uv sync
docker compose up -d postgres
uv run alembic upgrade head
```

Start the API:

```bash
uv run uvicorn claims_backend.api.app:app --reload
```

The OpenAPI document is available at `http://127.0.0.1:8000/docs`.

Submit a claim as multipart form data:

- `metadata`: JSON containing `member_id`, `policy_id`, `claim_category`,
  `treatment_date`, `claimed_amount`, `currency`, and a document manifest.
- `files`: one file part for each manifest item.

The accepted response contains a claim ID and status URL. Phase 1 leaves the claim in `QUEUED`;
worker processing begins in later phases.

## Submission idempotency

`POST /v1/claims` requires an `Idempotency-Key` header containing 1–128 characters from
letters, digits, `.`, `_`, `:`, or `-`; the first character must be alphanumeric. Keys are scoped
to the immutable user UUID, so two members can independently use the same value.

The first accepted request atomically stores the key, canonical request hash, original response
status, claim, documents, audit events, and initial work item. An identical retry returns the
original `202 Accepted` receipt without creating another claim, work item, document reference, or
artifact. A retry using the same member and key with different metadata, manifest identifiers, or
document content returns `409 IDEMPOTENCY_KEY_REUSED`.

The canonical request identity includes normalized claim fields and server-derived document media
type, size, page count, and SHA-256 hash. It excludes untrusted filenames, declared MIME types,
generated storage identifiers, and local paths. PostgreSQL arbitrates concurrent retries through a
unique member/key constraint; a rolled-back acceptance also rolls back its key reservation.

## Versioned document replacement

Members replace an existing claim document through
`POST /v1/claims/{claim_id}/actions`. The multipart request contains:

- `command`: JSON with `type: "REPLACE_DOCUMENT"`, the current `expected_version`, and the
  existing `client_document_id`.
- `file`: one validated PDF, JPEG, or PNG replacement.
- `Idempotency-Key`: a key scoped to the immutable user and claim.

The action takes a PostgreSQL row lock on the owned claim and checks the expected version before
changing state. A successful replacement creates a new immutable document version, claim version,
action record, audit event, and version-specific work item in one transaction. The old document
and claim versions remain unchanged, while obsolete available work is marked `SUPERSEDED`.

Identical retries return the action's original `200` receipt even after the claim advances again.
Reusing the key for different action data returns `409 ACTION_IDEMPOTENCY_KEY_REUSED`; a different
action based on an old version returns `409 STALE_CLAIM_VERSION` with the current version. Only the
owning member can replace documents, and an `ACTION_REQUIRED` claim returns to `QUEUED` after a
valid replacement. Failed transactions remove the new artifact and do not reserve the action key.

## PostgreSQL work scheduler

`claim_work_items` is the durable local queue. Claim acceptance and document replacement create
version-specific operation keys in the same transaction as the corresponding claim state. A
project-owned `WorkScheduler` port keeps worker code independent of SQL, while
`PostgresWorkScheduler` provides enqueue, lease, complete, and retry operations.

The scheduler state transitions are:

```text
AVAILABLE (due) -> LEASED -> COMPLETED
                         -> AVAILABLE (future retry)
                         -> FAILED (attempt budget exhausted)
AVAILABLE/LEASED        -> SUPERSEDED (newer claim version)
```

Leasing orders work by `available_at`, uses `FOR UPDATE SKIP LOCKED`, increments the attempt, and
commits a worker ID, expiry, and unique fencing token before returning. Expired leases can be
reclaimed with a new token; the prior worker can no longer complete or retry them. A default worker
lease lasts five minutes. Retry failures use bounded sanitized codes and persist a future
`available_at` instead of sleeping in memory or inside a transaction.

`WorkerService` invokes its typed handler only after the lease transaction has committed, then
completes or reschedules through a separate scheduler transaction. The table remains authoritative
across worker crashes; no FastAPI background task, SQS, Redis, or in-memory queue is involved.

## Local identities

Claim routes require the `X-Dev-Username` header. The migrated local database seeds:

| Username | Role | Member |
|---|---|---|
| `member.emp001` | Member | `EMP001` |
| `member.emp002` | Member | `EMP002` |
| `reviewer.local` | Reviewer | — |
| `operator.local` | Operator | — |

Username lookup is case-insensitive. Claims are owned by immutable user UUIDs, so renaming a
username does not change ownership. The username used for each mutation remains preserved in its
claim and audit snapshots.

This header is intentionally a local-development identity mechanism, not authentication. Route
authorization depends on a replaceable identity-provider contract so a JWT or OAuth/OIDC adapter
can replace it later without changing claim application behavior.

## Local document storage

Claim uploads are streamed into a content-addressed store beneath `CLAIMS_DATA_ROOT`, which
defaults to `data/documents`. The backend determines the actual format from file signatures and
structural validation; request MIME types and filenames are never trusted.

Supported formats and default limits:

- PDF, JPEG, and PNG.
- 10 documents per claim.
- 20 MiB per document.
- 50 MiB across one claim.
- 10 pages per document.
- 1 MiB streaming chunks.

The corresponding configuration variables are:

- `CLAIMS_MAX_DOCUMENTS`
- `CLAIMS_MAX_FILE_BYTES`
- `CLAIMS_MAX_CLAIM_BYTES`
- `CLAIMS_MAX_DOCUMENT_PAGES`
- `CLAIMS_UPLOAD_CHUNK_BYTES`

Encrypted, corrupt, unsupported, oversized, and over-page-limit documents produce stable,
document-specific API errors before a claim is created. Valid artifacts are atomically sealed
under generated hash-based paths with read-only permissions. PostgreSQL stores only immutable
document metadata and relative paths. If claim persistence fails, the newly sealed artifacts are
removed.

## Verification

The default tests use the PostgreSQL container:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run alembic check
```

Stop the local database without deleting its volume:

```bash
docker compose stop postgres
```
