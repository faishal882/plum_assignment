# Plum Claims Backend

Backend-first implementation of an explainable health-insurance claim processing system.

The current implementation follows the phased plan in
[`plans/backend-claim-processing.md`](plans/backend-claim-processing.md).

## Local prerequisites

- Python 3.12
- `uv`
- Docker with Docker Compose

## Phase 1: run locally

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
