# Plum Claims Demo Video Script

Target length: 9–11 minutes
Assignment requirement: 8–12 minutes
Recommended recording style: screen recording with voice narration

This script is written for the current local application. Replace bracketed values only when the local database uses different identity names or claim IDs.

## Before recording

Start these services in separate terminals:

```bash
docker compose up -d postgres
uv run alembic upgrade head
uv run uvicorn claims_backend.api.app:app --host 127.0.0.1 --port 8000
uv run claims-worker run-loop
cd frontend && npm run dev
```

Open these tabs before recording:

1. `http://127.0.0.1:3000` — the member UI.
2. `http://127.0.0.1:6006` — Arize Phoenix.
3. `http://127.0.0.1:8000/docs` — optional API backup view.

For a reliable approval recording, use the deterministic `RECORDED_LOCAL` profile with observability enabled:

```dotenv
CLAIMS_EXECUTION_PROFILE=RECORDED_LOCAL
CLAIMS_RUN_LIVE_AWS=0
CLAIMS_OBSERVABILITY_ENABLED=1
```

If a live AWS recording is desired, preflight the exact claim once first. Use `LIVE_INTELLIGENCE` and `CLAIMS_RUN_LIVE_AWS=1` only if Textract and Bedrock have already succeeded for the documents. The recorded path is the deterministic evaluation path; live model output can safely end in `PROCESSING_FAILED` because provider output is variable.

Prepare three small document sets:

- **Successful set:** a hospital bill and prescription where the patient name is `Rajesh Kumar`, matching the selected seeded member `member.emp001`.
- **Conflict set:** at least one document with a different patient name, for example `Arjun Mehta`, while the selected member remains `Rajesh Kumar`.
- **Faisal set:** documents where the patient name is exactly `Faisal Khan`.

Keep the Phoenix tab open but do not focus on it until the first claim is processing. The worker should already be running so the processing stages and spans appear naturally.

## 0:00–0:45 — Opening and system purpose

**On screen:** Open the Plum Claims home page and keep the identity selector visible.

**Say:**

> This is Plum Claims, an explainable health-insurance claims processing system. The member submits a treatment claim with medical documents. The backend verifies and renders the files, extracts OCR observations, classifies the documents, grounds structured evidence to those observations, reconciles a casefile, and then applies deterministic policy rules.
>
> The important boundary is that the model does not decide the claim. OCR and models can read and suggest. The backend owns provenance and canonical facts, and deterministic policy code owns money and the final outcome. If the evidence is incomplete or contradictory, the system asks for a document or routes the claim to review instead of inventing a decision.

## 0:45–2:00 — Submit a successful claim and narrate processing

**On screen:** Select `Rajesh Kumar · EMP001` in the local identity selector. Open **New Claim**.

**Say while filling the form:**

> I am selecting the seeded member identity for EMP001. The selected identity is resolved from the backend database; the browser is not the authority for roles or member scope. I am submitting a consultation claim for the treatment date shown here and a claimed amount of 1,500 rupees.
>
> I am attaching two documents: a prescription and a hospital bill. The document manifest records their order and client document IDs, so the backend can preserve exactly which uploaded file produced each downstream observation.

**Action:** Upload the matching Rajesh Kumar prescription and bill. Submit the claim. Immediately switch to the claim status page.

**Say while the status rail is moving:**

> The API has accepted the claim and returned a claim ID. It does not keep the browser request open while OCR and model work runs. The worker leases a durable work item from PostgreSQL and resumes the workflow from its checkpoint.
>
> The status rail is projected from persisted workflow events. I can see the system ingesting the claim, classifying documents, rendering pages, reading OCR, extracting evidence, checking policy, and finalizing the outcome. This is not a frontend animation guessing what the worker is doing; each stage comes from a backend workflow event.
>
> At this point the system is doing three different kinds of work. File and page processing creates durable artifacts. Intelligence adapters return untrusted document understanding. Then reconciliation converts that into a frozen casefile that the policy evaluator can safely consume.

**On screen:** Let the claim move through `QUEUED`. If the UI advances quickly, pause briefly on the stage rail and explain the stages rather than waiting silently.

## 2:00–4:00 — Phoenix trace and exact decision path

**On screen:** Switch to Phoenix. Open the `plum-claims-local` project and locate the newest trace. If filtering is needed, search for the claim ID or select the newest `claim.workflow` trace.

**Say:**

> I am now looking at the execution trace for the same claim. The root workflow span is the correlation point. Under it are the node spans, and below the intelligence nodes are the OCR or structured-model provider spans when the live profile is enabled.

**Action:** Expand the root `claim.workflow` span and then the child spans.

**Say:**

> The first useful thing here is the workflow structure: `load_claim`, `media_inspect`, rendering, discovery or triage, OCR, evidence extraction, reconciliation, adjudication, and the terminal commit. Each node records its outcome, duration, attempt number, workflow run, claim, and trace identifiers.
>
> The provider span is separate from the business decision. For OCR I can inspect the provider request metadata and observation count. For Bedrock I can inspect the route, model ID, prompt version, schema version, token counts, latency, stop reason, and structured output. The provider output is diagnostic evidence; it is not treated as an authoritative decision.
>
> This separation is important for debugging. If a model returns malformed JSON, over-cites evidence, or a provider times out, I can see that exact failure under the provider span while the workflow records a safe processing outcome. A stale worker also cannot commit after its lease expires, because terminal database effects are fenced by the current lease.

**Action:** Open one node span, preferably `triage_documents` or `extract_evidence`, and show its input/output attributes. Then open `adjudicate` and `commit_decision`.

**Say:**

> Notice that adjudication is deterministic. It receives a reconciled casefile and the activated policy version. It does not call the LLM. The decision span is therefore explainable through persisted rule results rather than a hidden model opinion.

## 4:00–5:45 — Successful outcome, evidence, and OCR registry

**On screen:** Return to the claim page after it reaches `DECIDED`. Scroll through the decision summary and workflow evidence panel.

**Say:**

> The claim is now decided. The member-facing result shows the recommendation, approved amount, and explanation. I will now move from the outcome back to the evidence that supports it.
>
> The workflow evidence panel separates the claim packet, OCR reading, identity evidence, the policy checklist, and the rule trace. This is useful because a reviewer should not have to trust a single final sentence. They can see what the system knew, which fields were grounded, and which policy clauses ran.

**Action:** Expand the OCR registry.

**Say:**

> This registry contains the OCR observations with document ID, page, text, confidence, field type, region, and observation ID. The observation ID is generated by the backend. The model references these IDs; it does not generate hashes, page metadata, or regions.
>
> For example, this line containing the patient name or total amount is an OCR observation. The evidence candidate points back to that observation, and the casefile copies its deterministic provenance. This is how the system can reconstruct the path from uploaded page to fact to policy rule to final amount.

**Action:** Open the rule trace or amount trace.

**Say:**

> Finally, the rule trace shows the ordered policy checks and amount transitions. Each rule has a status, reason code, policy path, inputs, evidence references, and before-and-after amounts. The design uses integer paise internally so monetary calculations do not depend on floating-point rounding.

## 5:45–7:15 — Conflict document stopped early

**On screen:** Start a new claim. Keep the selected identity as `Rajesh Kumar · EMP001`. Upload the conflict set, where one document contains a different patient name such as `Arjun Mehta`.

**Say while submitting:**

> Now I will demonstrate the early document problem path. I have not changed the selected member, but one uploaded document contains a different patient identity. The system should not continue to policy adjudication with contradictory identity evidence.

**Action:** Submit and wait for `ACTION_REQUIRED`.

**Say:**

> The workflow stopped at the document identity gate and returned `ACTION_REQUIRED`. This is not a generic failure and it is not an automatic claim rejection. The response identifies the affected document, the observed patient name, and the corrective action the member needs to take.
>
> The trace shows the triage and reconciliation nodes completing, followed by the member-action terminal path rather than `adjudicate`. That is the safety boundary in action: the system refuses to make a policy decision until the identity evidence is consistent.

**On screen:** Open the identity evidence card and, if useful, the OCR registry for the conflicting name.

**Say:**

> The evidence panel makes the reason inspectable: the conflicting name is shown alongside the OCR line and document ID. A reviewer can therefore distinguish an identity conflict from an unreadable document, missing billing evidence, or a provider failure.

## 7:15–8:45 — Non-demo member flow: Faisal Khan

**On screen:** Open the local identity selector and choose **Create local identity**.

**Say:**

> The seeded users are only assignment fixtures. For a non-demo member, the frontend can create a local identity through the same backend identity boundary. I will use Faisal Khan as the example.

**Action:** Fill the form with:

```text
Username: faisal.khan
Full name: Faisal Khan
Relationship: SELF
Date of birth and join date: valid policy-compatible dates
```

**Say:**

> The username is the stable lookup key and is normalized for identity resolution, so it should be a valid username such as `faisal.khan`. The canonical member full name is `Faisal Khan`. The uploaded documents must contain that exact member name for the identity evidence to reconcile. In other words, the important match is the backend-resolved member's full name against the patient name in OCR; a username with spaces is not required.
>
> After creation, the backend creates the user, member, membership link, member version, and local policy-period utilization snapshot in one transaction. The claim form then uses the selected member context, uploads Faisal's documents, and sends the claim through the same worker, trace, evidence, and policy path. A missing utilization snapshot remains unknown and must block adjudication; it must never be silently treated as zero.

**Action:** If the environment is prepared for a live manual-user flow, briefly show the new identity in the selector and the claim form's selected member context. Do not spend recording time processing a third full claim.

## 8:45–9:45 — Design reflection and closing

**On screen:** Return to either the Phoenix trace or the architecture document.

**Say:**

> The technical decision I am most proud of is the model-to-backend evidence boundary. Models perform semantic work, but the backend owns observation IDs, hashes, regions, page numbers, validation, and normalization. That made live failures diagnosable and prevented a model from inventing cryptographic provenance or deciding a claim directly.
>
> The decision I would change with more time is the local infrastructure boundary. PostgreSQL queueing and filesystem storage are appropriate for this assignment, but at ten times the load I would add measured worker pools, provider rate limiting, object storage, read projections, and likely SSE progress updates. I would also replace the local identity header with verified OIDC or JWT authentication while keeping the same server-resolved `Principal` interface.
>
> The result is a system where a successful decision, an action-required claim, and a provider failure are all explainable through the same durable workflow and evidence records. The final outcome is not just an answer; it is a reconstructable chain from document to OCR observation to grounded fact to policy rule.

## Recording fallback notes

- If Phoenix has no trace, confirm `CLAIMS_OBSERVABILITY_ENABLED=1`, Phoenix is running on port `6006`, and the API/worker were restarted after changing `.env`.
- If the claim reaches `PROCESSING_FAILED` during a live AWS run, do not improvise a successful claim. Explain that the system failed closed and switch to the preflighted recorded run for the successful approval segment.
- If the UI moves too quickly, use the claim status page's workflow rail and then use Phoenix's completed trace; the recorded workflow events remain durable after processing finishes.
- Never show AWS credentials, `.env` contents, database passwords, or unrelated member documents in the recording.
