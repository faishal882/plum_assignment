export type UUID = string;
export type IsoDate = string;
export type IsoDateTime = string;
export type Money = string;

export type ClaimCategory =
  | "ALTERNATIVE_MEDICINE"
  | "CONSULTATION"
  | "DENTAL"
  | "DIAGNOSTIC"
  | "PHARMACY";

export type ClaimLifecycle =
  | "RECEIVED"
  | "QUEUED"
  | "ACTION_REQUIRED"
  | "IN_REVIEW"
  | "DECIDED"
  | "PROCESSING_FAILED";

export interface DocumentManifestItem {
  upload_index: number;
  client_document_id: string;
}

export interface ClaimMetadata {
  member_id: string;
  policy_id: string;
  claim_category: ClaimCategory;
  treatment_date: IsoDate;
  claimed_amount: Money;
  currency: "INR";
  documents: DocumentManifestItem[];
}

export interface ClaimReceipt {
  claim_id: UUID;
  version: number;
  lifecycle_status: ClaimLifecycle;
  status_url: string;
}

export interface Claim {
  claim_id: UUID;
  version: number;
  member_id: string;
  policy_id: string;
  claim_category: ClaimCategory;
  treatment_date: IsoDate;
  claimed_amount: Money;
  currency: string;
  lifecycle_status: ClaimLifecycle;
  progress: {
    current_stage: string;
    is_terminal: boolean;
  };
  adjudication?: {
    recommendation: string;
    approved_amount: Money;
    currency: string;
  };
  explanation?: {
    summary: string;
    deductions: Array<{
      code: string;
      label: string;
      amount: Money;
    }>;
    line_items?: Array<{
      concept: string;
      label: string;
      claimed_amount: Money;
      approved_amount: Money;
      status: string;
      reason_code: string;
    }>;
  };
  action?: {
    code: string;
    message: string;
    observed_document_roles: string[];
    required_document_roles: string[];
    affected_documents?: Array<{
      client_document_id: string;
      observed_role: string;
      requested_action: string;
    }>;
    identity_conflict?: Array<{
      client_document_id: string;
      patient_name: string;
    }>;
  };
  handling_status?: string;
  processing_quality?: {
    completeness: number;
    confidence: number;
    degraded_components: Array<{
      component: string;
      criticality: string;
      attempts: number;
      failure_code: string;
      retryable: boolean;
      effect_on_handling: string;
    }>;
  };
  processing_failure?: {
    code: string;
    retry_guidance: string;
  };
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export type ReviewAction =
  | "ACCEPT"
  | "AMEND"
  | "REJECT"
  | "REQUEST_DOCUMENT";

export interface ReviewTaskSummary {
  id: UUID;
  claim_id: UUID;
  claim_version: number;
  status: "OPEN" | "RESOLVED";
  signal_codes: string[];
  machine_recommendation: string;
  machine_approved_amount: Money;
  currency: string;
  allowed_actions: ReviewAction[];
  created_at: IsoDateTime;
  resolved_at: IsoDateTime | null;
}

export interface RuleTrace {
  sequence?: number;
  rule_id?: string;
  status?: string;
  reason_code?: string;
  policy_path?: string;
  evidence_refs?: string[];
  inputs?: Record<string, unknown>;
  amount_before_paise?: number;
  adjustment_paise?: number;
  amount_after_paise?: number;
}

export interface ReviewTaskDetail {
  task: ReviewTaskSummary;
  evidence: Record<string, unknown>;
  conflicts: Array<Record<string, unknown>>;
  rules: RuleTrace[];
  calculations: Array<Record<string, unknown>>;
  failures: Array<Record<string, unknown>>;
}

export interface ReviewCommand {
  action: ReviewAction;
  expected_claim_version: number;
  reason_code: string;
  reason_note: string;
  amended_amount?: Money;
}

export interface ReviewResolution {
  id: UUID;
  task_id: UUID;
  action: ReviewAction;
  reason_code: string;
  reason_note: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  actor_user_id: UUID;
  actor_username: string;
  created_at: IsoDateTime;
  replayed: boolean;
}

export interface ApiErrorDetail {
  location?: Array<string | number>;
  message: string;
  type?: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details: ApiErrorDetail[];
  current_version?: number;
}

export interface ApiErrorResponse {
  error: ApiErrorBody;
}

export interface HealthCheckResponse {
  status: string;
  service?: string;
  environment?: string;
  details?: Record<string, unknown>;
}
