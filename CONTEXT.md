# Claims Processing

This context describes the language used to receive, evaluate, and review health-insurance claims.

## Language

**Claim**:
A member's request for reimbursement under a policy, supported by submitted medical and billing evidence.
_Avoid_: Case, ticket

**User**:
A system identity that can act as a member, reviewer, or operator. A user has an immutable identity even if their unique username changes.
_Avoid_: Account, login

**Member**:
An insured person whose eligibility, policy coverage, and submitted claims are evaluated. A member may later be linked to a user but is not itself an authentication identity.
_Avoid_: User, account

**Policy Terms**:
The immutable source rules governing eligibility, coverage, limits, exclusions, and claim requirements.
_Avoid_: Policy code, test rules

**Policy Overlay**:
A versioned and auditable set of explicit clarifications applied to policy terms when the source rules are contradictory or incomplete.
_Avoid_: Test-case exception, hardcoded override

**Category Limit**:
The maximum amount payable for a claim category. It takes precedence over the general per-claim limit when the policy defines both.
_Avoid_: Global limit, test limit

**Evidence Sufficiency**:
The condition in which the available documents support every material fact required to evaluate a claim. A specific document may be unnecessary when equivalent evidence is already present.
_Avoid_: Document present, extraction confidence

**Pre-authorization**:
Prior approval for a specific treatment, patient, validity period, and applicable amount. It is established from verifiable authorization evidence rather than an unverified member assertion.
_Avoid_: Authorization flag, pre-auth checkbox

**Adjudication Recommendation**:
The policy-derived recommendation to approve, partially approve, or reject a claim, including the calculated eligible amount.
_Avoid_: Workflow status, manual review

**Handling Disposition**:
The operational treatment required after adjudication, such as automatic completion or recommended manual review.
_Avoid_: Decision, adjudication result

**Action Required**:
A non-terminal claim condition that identifies information or evidence the member must provide before processing can continue.
_Avoid_: Rejection, validation error

**Manual Review**:
Human examination required or recommended because evidence, policy application, or workflow completeness is not sufficient for safe automatic handling.
_Avoid_: Rejection, decision

**Degraded Component**:
A workflow capability that did not complete normally and whose failure is preserved in the claim trace with its effect on evidence completeness and handling.
_Avoid_: Skipped error, ignored failure

**Document Role**:
The evidentiary purpose a submitted document serves in a claim, such as prescription, hospital bill, laboratory report, or pre-authorization.
_Avoid_: Filename, upload type

**Claim Trace**:
The ordered, immutable account of evidence, workflow events, policy results, calculations, failures, and human actions that explains a claim's outcome.
_Avoid_: Application log, model transcript
