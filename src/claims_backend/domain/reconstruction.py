import json
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ClaimReconstruction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: UUID
    claim_version: int
    claim: dict[str, object]
    submission: dict[str, object]
    policy: dict[str, object] | None
    work_item: dict[str, object] | None
    workflow: dict[str, object] | None
    workflow_events: tuple[dict[str, object], ...]
    workflow_effects: tuple[dict[str, object], ...]
    audit_events: tuple[dict[str, object], ...]
    casefile: dict[str, object] | None
    evidence_references: tuple[str, ...]
    model_extractions: tuple[dict[str, object], ...]
    decision: dict[str, object] | None
    rule_results: tuple[dict[str, object], ...]
    component_failures: tuple[dict[str, object], ...]
    member_actions: tuple[dict[str, object], ...]
    review_task: dict[str, object] | None
    review_resolutions: tuple[dict[str, object], ...]

    @property
    def canonical_sha256(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return sha256(canonical).hexdigest()
