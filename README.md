# Plum Claims Backend

Backend-first implementation of an explainable health-insurance claim processing system.

The current implementation follows the phased plan in
[`plans/backend-claim-processing.md`](plans/backend-claim-processing.md).

## Local prerequisites

- Python 3.12
- `uv`
- Docker with Docker Compose

## Environment configuration

All local runtime configuration is declared in the root `.env`. The real `.env` is ignored by
Git; `.env.example` is the committed, non-secret configuration contract. For a fresh checkout:

```bash
cp .env.example .env
```

The API, CLI, Alembic, Docker Compose, and AWS integration tests consume this configuration.
Explicit process environment variables take precedence over values in `.env`, which makes
one-command overrides possible without editing the file. Application startup fails with a list
of missing keys instead of silently selecting a database, region, or model.

The configured keys are:

- PostgreSQL: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`,
  `CLAIMS_DATABASE_URL`, and `CLAIMS_TEST_DATABASE_URL`.
- Local storage and upload bounds: `CLAIMS_DATA_ROOT`, `CLAIMS_MAX_DOCUMENTS`,
  `CLAIMS_MAX_FILE_BYTES`, `CLAIMS_MAX_CLAIM_BYTES`, `CLAIMS_MAX_DOCUMENT_PAGES`, and
  `CLAIMS_UPLOAD_CHUNK_BYTES`.
- Rendering and Textract: `CLAIMS_MAX_TEXTRACT_PAGE_BYTES`, `CLAIMS_PAGE_RENDER_DPI`,
  `CLAIMS_AWS_REGION`, `CLAIMS_TEXTRACT_TIMEOUT_SECONDS`, and
  `CLAIMS_TEXTRACT_CONCURRENCY_LIMIT`.
- Bedrock: `CLAIMS_BEDROCK_REGION`, `CLAIMS_BEDROCK_MODEL_ID`,
  `CLAIMS_BEDROCK_TIMEOUT_SECONDS`, and `CLAIMS_BEDROCK_CONCURRENCY_LIMIT`.
- Provider retry policy: `CLAIMS_PROVIDER_MAX_ATTEMPTS`, `CLAIMS_RETRY_BASE_SECONDS`,
  `CLAIMS_RETRY_MAX_SECONDS`, and `CLAIMS_RETRY_JITTER_RATIO`.
- Local diagnostics: `CLAIMS_OBSERVABILITY_ENABLED`, `CLAIMS_PHOENIX_ENDPOINT`,
  `CLAIMS_PHOENIX_PROJECT`, `CLAIMS_LOG_ROOT`, `CLAIMS_LOG_MAX_BYTES`,
  `CLAIMS_LOG_BACKUP_COUNT`, and `CLAIMS_EXECUTION_PROFILE`.
- Synthetic-only content controls: `CLAIMS_OBSERVABILITY_CAPTURE_CONTENT` and
  `CLAIMS_OBSERVABILITY_SYNTHETIC_ONLY`; both remain disabled for normal development.
- Explicit paid-test gate: `CLAIMS_RUN_LIVE_AWS`, disabled by default.

Do not put AWS access keys in `.env`. Boto3 and the AWS CLI use the standard credential chain.
If a named local profile is needed, set `AWS_PROFILE` in the shell or uncomment its placeholder
in `.env`.

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

## Local agent observability

Phoenix is an optional local development process. Install and start it with:

```bash
uv sync --group observability
uv run --group observability phoenix serve
```

Then set `CLAIMS_OBSERVABILITY_ENABLED=1` before starting the API or worker. The application
exports OpenTelemetry/OpenInference spans to
`http://127.0.0.1:6006/v1/traces` and writes separate rotating JSONL files under
`data/logs/api.jsonl`, `data/logs/worker.jsonl`, and `data/logs/evaluation.jsonl`.

Default spans and logs contain identifiers, versions, durations, outcomes, sanitized exception
classes, provider request IDs, and token counts. They reject patient names, diagnoses, OCR text,
document bytes, local paths, raw prompts/responses, and credential fields. Rich content capture
requires both an explicit `LIVE_INTELLIGENCE` profile and a synthetic-only assertion. Phoenix and
JSONL logs are diagnostic copies; PostgreSQL workflow events and decision records remain the
reconstruction authority.

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

## Resumable claim workflow

The backend runs one fixed typed LangGraph behind the project-owned `WorkflowRuntime` boundary.
Every claim first loads its immutable claim-version snapshot and verifies locally sealed media.
It then follows one of three explicit routes:

- `STRUCTURED_COMPONENT` freezes privileged test evidence and runs deterministic adjudication.
- `EARLY_TRIAGE` applies bounded document-role/readability classification and can stop with a
  member action before expensive extraction.
- Claims without a seeded component fixture follow the original skeleton route until their
  extraction capabilities are implemented.

Every process work item carries a normalized `claim_version`. Its first execution atomically
creates one `workflow_runs` record pinned to the work item, claim version, graph name, and graph
version. The workflow-run UUID is used unchanged as LangGraph's `thread_id`, while the project
record stores the `claim-processing-v5` graph version independently of LangGraph's reserved root
checkpoint namespace. Graph state is limited to IDs, the operation key, version, booleans, and
small evidence/action summaries—never document bytes, OCR bodies, prompts, or provider responses.

Call `LangGraphClaimWorkflow.setup()` once when initializing a fresh local worker database. The
LangGraph PostgreSQL adapter owns its checkpoint tables, while Alembic owns `workflow_runs`,
`workflow_effects`, and all other application tables. Alembic explicitly ignores the four
framework checkpoint tables during drift detection.

LangGraph checkpoints each completed super-step. If a worker dies after a checkpoint, the
replacement worker reuses the stable run/thread ID and invokes the graph with no new input, so
execution resumes at the next node. If a node commits an effect but dies before its checkpoint,
the node may run again; `(workflow_run_id, effect_key)` uniqueness makes that write idempotent.
The work lease is completed only after both the graph and project-owned workflow run reach
completion.

## Structured adjudication trace

The test-only `StructuredComponentFixtureAdapter` can seed TC004 after a normal multipart
submission. It is an infrastructure fixture boundary, not an HTTP route or request field. The
production claim schema therefore cannot supply eligibility, evidence findings, utilization,
reason codes, decisions, or approved amounts.

The adjudicator reads the frozen casefile, pinned Policy IR, and pinned PostgreSQL member
utilization. It evaluates eligibility, evidence sufficiency, applicable limits, co-pay, and final
recommendation in a fixed order. All money uses integer paise. Each rule result preserves status,
policy path, evidence references, normalized inputs, amount before, adjustment, and amount after.
Canonical JSON hashing makes the complete decision reproducible for identical inputs.

The terminal transaction writes the decision, ordered rule results, member-safe projection,
audit event, workflow completion, and work completion together. A failure in any write rolls back
the entire terminal transition. PostgreSQL also rejects updates and deletes to fixture inputs,
casefiles, decisions, rule results, triage results, identity reconciliations, and member actions.
TC004 consequently exposes an approved ₹1,350 projection and ₹150 co-pay explanation without
fixture payloads or internal provider data.

## Early document-role gate

The `EARLY_TRIAGE` route accepts only schema-constrained per-document outputs: a bounded role
vocabulary including `UNKNOWN`, a typed readability observation with preview provenance, and at
most two bounded identity observations. It requires exactly one result for every submitted
document and persists the exact document-version reference. Unknown values are preserved rather
than guessed.

TC001 proves the short-circuit path with two generic JPEG filenames classified as prescriptions.
The pinned policy requires a hospital bill, so the backend atomically records a
`MISSING_REQUIRED_DOCUMENT` member action and moves the claim to `ACTION_REQUIRED`. The workflow
effect trace ends after local media inspection, triage, and action commit. No Textract,
full-extraction, casefile, policy-adjudication, or financial-decision operation executes.

TC002 uses a deterministic synthetic blur/downsampling transform to produce a repeatable
unreadable pharmacy bill. Its observation links the `UNREADABLE` result to the immutable document
version and to a page preview hash and transform version. The member action identifies `F004` and
requests replacement of that pharmacy bill. A clear replacement creates claim version 2, clears
the satisfied action, and schedules fresh work while the version 1 triage remains immutable.

Patient-name candidates carry producer and producer version, document version, page, normalized
region, source-text hash, and confidence. Deterministic reconciliation compares all candidates
with the pinned member snapshot and records `KNOWN`, `UNKNOWN`, or `CONFLICT`; confidence and
source order cannot erase disagreement. TC003 preserves Rajesh Kumar from `F005` and Arjun Mehta
from `F006`, returns only those relevant conflict details to the member, and stops before
adjudication. Replacing the mismatched document starts a new claim attempt without altering the
original reconciliation or member action.

## Local page OCR

The document-intelligence route renders each immutable document version into stable, numbered
JPEG page artifacts beneath `CLAIMS_DATA_ROOT`. PDFs are rendered with pypdfium2; JPEG and PNG
inputs become a single normalized page. Rendering is bounded by `CLAIMS_PAGE_RENDER_DPI` and
`CLAIMS_MAX_TEXTRACT_PAGE_BYTES` (5 MiB by default). The renderer progressively reduces quality
and dimensions, then raises a typed error if a safe page still cannot be produced. The workflow
turns that error into a targeted `PAGE_TOO_LARGE_FOR_OCR` replacement action instead of silently
dropping a page.

PostgreSQL stores immutable page provenance: source and rendered hashes, document-version ID,
page number, render version, dimensions, media type, size, and local relative path. The OCR
adapter sends page bytes directly to synchronous Amazon Textract—S3 is not part of this local
architecture. Hospital and pharmacy bills use expense analysis; forms and reports use forms and
tables analysis; unknown/free-text documents use text detection. Provider blocks are converted
to project-owned observations containing kind, text, confidence, page, normalized geometry,
source block ID, and deterministic observation ID.

Page processing is replay-safe at two layers. Rendered artifacts are unique by document version,
page, and render version. OCR results are unique by page artifact, provider, and provider version.
Retries therefore read stored observations, and cross-page results are returned in page and
geometry order. Provider request IDs and retry counts are retained, but raw provider responses
are not stored.

Relevant configuration:

- `CLAIMS_AWS_REGION` (`ap-south-1` in `.env.example`)
- `CLAIMS_PAGE_RENDER_DPI` (`180` in `.env.example`)
- `CLAIMS_MAX_TEXTRACT_PAGE_BYTES` (`5242880` in `.env.example`)

The default suite uses recorded and Botocore-stubbed responses. A real synthetic page can be
tested explicitly with:

```bash
CLAIMS_RUN_LIVE_AWS=1 CLAIMS_AWS_REGION=us-east-1 \
  uv run pytest tests/live/test_textract_live.py -q
```

This call may incur AWS charges. It uses generated text only and requires credentials with
`textract:DetectDocumentText`.

## Bedrock structured extraction

All model calls pass through the project-owned `StructuredModelTransport` boundary. The default
router independently configures `FAST_TRIAGE` and `COMPLEX_EXTRACTION`, including route, model ID,
AWS region, prompt version, schema version, enablement, evaluation approval, and temperature.
Both currently resolve to `qwen.qwen3-235b-a22b-2507-v1:0`, with temperature zero and
function-calling structured output. Bedrock uses its own `CLAIMS_BEDROCK_REGION` setting
(`us-west-2` in `.env.example`) because this Qwen model is not available in the Textract region.
Override the identifier locally through `CLAIMS_BEDROCK_MODEL_ID`.

`ChatBedrockConverseTransport` uses Bedrock Converse through LangChain AWS native structured
output via the model-compatible function-calling method. It returns only the parsed project
schema plus request ID, token counts, latency, and stop reason. Prompts, raw responses,
chain-of-thought, and document bytes are not persisted.
`RecordedStructuredModelTransport` supplies the default no-network test path using sanitized,
version-controlled fixtures.

Complex extraction receives a bounded, canonical list of OCR observations. Its output is
untrusted and passes four separate validation boundaries:

1. Authority validation recursively rejects decision, recommendation, payable/approved amount,
   reason-code, and policy-outcome fields before application use.
2. Pydantic rejects undeclared fields and schema/type/version mismatches.
3. Semantic validation permits only declared clinical, billing, patient, treatment, and document
   fact namespaces.
4. Grounding validation requires every candidate to cite an available OCR observation ID.

Validated evidence candidates receive deterministic IDs derived from candidate content and the
model, route, prompt, and schema versions. PostgreSQL stores an immutable extraction envelope for
each document/input hash and immutable candidate rows. The envelope retains the route
configuration and provider metadata required to reconstruct which model contract produced a
candidate. Replaying identical observations reads that record without another model call. These
candidates are evidence only: the model boundary has no method that can commit a policy or
financial decision.

The recorded integration suite exercises routing and persistence without AWS. The live schema
contract is opt-in:

```bash
CLAIMS_RUN_LIVE_AWS=1 \
CLAIMS_BEDROCK_REGION=us-west-2 \
CLAIMS_BEDROCK_MODEL_ID=qwen.qwen3-235b-a22b-2507-v1:0 \
  uv run pytest tests/live/test_bedrock_live.py -q
```

This call may incur AWS charges and requires Bedrock Converse permission plus model/Marketplace
access for the configured model. The synthetic live contract passed against Qwen in `us-west-2`
on 2026-07-28, including schema adherence, grounding, latency, token usage, and request metadata.

## Setup data import

Policy, roster, claim-history, and utilization data enter through the local `claimsctl` command,
not through claim HTTP routes. Apply migrations first, then import the supplied policy:

```bash
uv run claimsctl setup import --policy problem_statement/policy_terms.json
```

The importer hashes and stores the exact policy bytes, versions every member/dependent record,
and returns a durable import UUID plus structured findings. PostgreSQL triggers reject updates or
deletes of policy sources and import envelopes. Repeating the same policy and optional member-data
bytes returns the original receipt without creating new versions.

Claim history and utilization can be supplied in a separate setup-only JSON file:

```json
{
  "policy_id": "PLUM_GHI_2024",
  "as_of_date": "2024-11-03",
  "claim_history": [
    {
      "history_claim_id": "HIST-001",
      "member_id": "EMP008",
      "treatment_date": "2024-10-30",
      "amount": "1200.50",
      "currency": "INR",
      "provider": "City Clinic"
    }
  ],
  "utilization": [
    {
      "member_id": "EMP001",
      "period_start": "2024-04-01",
      "period_end": "2025-03-31",
      "used_amount": "5000.00",
      "currency": "INR",
      "as_of_date": "2024-11-01"
    }
  ]
}
```

Import it alongside the policy and inspect the resulting records:

```bash
uv run claimsctl setup import \
  --policy problem_statement/policy_terms.json \
  --member-data path/to/member-data.json
uv run claimsctl setup inspect-import --import-id <import-uuid>
uv run claimsctl setup inspect-member \
  --policy-id PLUM_GHI_2024 \
  --member-id EMP001
```

Unknown member references are reported and skipped. Missing utilization has no synthetic zero
row; member inspection returns `utilization_state: "UNKNOWN"` and `used_paise: null`. The claim
submission schema forbids these setup facts, keeping PostgreSQL authoritative for later
adjudication snapshots.

## Policy compilation and activation

The reviewed assignment overlay lives at
`config/policy/assignment-overlay-v1.json`. It is an immutable, independently versioned and
SHA-256-addressed artifact bound to the exact source-policy hash. It contains domain
clarifications only—never evaluation case identifiers:

- Category-specific limits take precedence over the general per-claim limit.
- Exceeding a category limit produces `REJECT`, rather than an inferred cap.
- The consultation category limit is ₹5,000 (`500000` paise in Policy IR).
- MRI and CT scans require pre-authorization above ₹10,000.
- PET scans always require pre-authorization.
- Detailed dental line items may satisfy the dental evidence requirement.
- `CHILDREN` is normalized to the canonical `CHILD` relationship vocabulary.

Compile an already imported source using its hash:

```bash
uv run claimsctl policy compile \
  --source-sha <policy-source-sha256> \
  --overlay config/policy/assignment-overlay-v1.json
```

Compilation validates schemas and emits typed `SCHEMA`, `SEMANTIC`, `REFERENTIAL`, `VOCABULARY`,
and `CONTRADICTION` findings. It writes canonical JSON Policy IR using integer paise and stores a
deterministic IR hash. The same source, overlay, and compiler version return the original policy
version.

Inspect and activate a compiled version:

```bash
uv run claimsctl policy inspect --policy-version-id <policy-version-uuid>
uv run claimsctl policy findings --policy-version-id <policy-version-uuid>
uv run claimsctl policy activate \
  --policy-version-id <policy-version-uuid> \
  --actor operator.local
uv run claimsctl policy activation-events \
  --policy-version-id <policy-version-uuid>
```

Activation requires the local `OPERATOR` role and applies a configurable severity gate whose
default blocks unresolved `ERROR` findings. Activation and findings remain CLI-only. Each
successful transition creates an immutable actor-attributed event; PostgreSQL guards the overlay,
compiled IR, findings, and activation events against content mutation.

New claim acceptance requires one active policy version and a member version imported from that
policy source. The claim and immutable claim-version snapshot pin the policy source, overlay,
Policy IR, hashes, member record, member version, and setup import. Later policy activation or
roster imports therefore cannot change the evidence governing an accepted claim.

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
