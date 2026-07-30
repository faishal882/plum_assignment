import { Claim, OcrObservation } from "@/lib/claims-types";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  Fingerprint,
  GitBranch,
  ListChecks,
  SearchCheck,
  ShieldAlert,
} from "lucide-react";
import { AllOcrObservationsRegistry } from "./AllOcrObservationsRegistry";
import { JsonDisclosure } from "./JsonDisclosure";

interface WorkflowEvidencePanelProps {
  claim: Claim;
}

interface EvidenceCard {
  title: string;
  status: "known" | "pending" | "blocked" | "warning";
  body: string;
  details?: string[];
}

const statusStyle = {
  known: "bg-teal/15 text-teal border-teal/30",
  pending: "bg-amber-100 text-amber-800 border-amber-300",
  blocked: "bg-danger/15 text-danger border-danger/30",
  warning: "bg-violet-pale text-violet border-violet/25",
};

const statusLabel = {
  known: "Known",
  pending: "Pending",
  blocked: "Blocked",
  warning: "Needs attention",
};

function observationsList(observations?: Record<string, OcrObservation>): OcrObservation[] {
  return Object.values(observations || {});
}

function findObservationForText(
  observations: OcrObservation[],
  text: string
): OcrObservation | undefined {
  const normalized = text.trim().toLowerCase();
  if (!normalized) return undefined;
  return observations.find((observation) =>
    observation.text.toLowerCase().includes(normalized)
  );
}

function likelyIdentityLines(observations: OcrObservation[]): OcrObservation[] {
  return observations
    .filter((observation) => /\b(patient|name|member)\b/i.test(observation.text))
    .slice(0, 6);
}

function likelyEvidenceLines(observations: OcrObservation[]): OcrObservation[] {
  return observations
    .filter((observation) =>
      /\b(total|amount|paid|diagnosis|condition|illness|treatment|date|patient)\b/i.test(
        observation.text
      )
    )
    .slice(0, 8);
}

function missingEvidenceItems(message?: string): string[] {
  if (!message) return [];
  const afterColon = message.split(":").slice(1).join(":") || message;
  return afterColon
    .split(",")
    .map((part) => part.trim())
    .filter((part) => /^[a-z]+\.[a-z_]+/i.test(part));
}

function buildCards(claim: Claim): EvidenceCard[] {
  const observations = observationsList(claim.ocr_observations);
  const cards: EvidenceCard[] = [
    {
      title: "Claim packet",
      status: "known",
      body: `${claim.claim_category} claim for ${claim.member_id}`,
      details: [
        `Claimed amount: ₹${claim.claimed_amount} ${claim.currency}`,
        `Treatment date: ${claim.treatment_date}`,
        `Workflow stage: ${claim.progress?.current_stage || claim.lifecycle_status}`,
      ],
    },
  ];

  if (observations.length > 0) {
    const docs = new Set(observations.map((observation) => observation.client_document_id));
    cards.push({
      title: "OCR reading",
      status: "known",
      body: `${observations.length} OCR observations captured across ${docs.size} document(s)`,
      details: likelyEvidenceLines(observations).map(
        (observation) => `“${observation.text}” — ${observation.client_document_id}, page ${observation.page_number}`
      ),
    });
  } else {
    cards.push({
      title: "OCR reading",
      status: "pending",
      body: "No OCR observations are available yet.",
      details: ["They will appear after document rendering and OCR complete."],
    });
  }

  if (claim.action?.code === "PATIENT_IDENTITY_CONFLICT") {
    const conflictDetails = (claim.action.identity_conflict || []).map((conflict) => {
      const source = findObservationForText(observations, conflict.patient_name);
      return source
        ? `${conflict.client_document_id}: ${conflict.patient_name} from OCR “${source.text}”`
        : `${conflict.client_document_id}: ${conflict.patient_name}`;
    });
    cards.push({
      title: "Identity evidence",
      status: "blocked",
      body: "Documents contain patient names that do not reconcile to the selected member.",
      details: conflictDetails.length > 0 ? conflictDetails : likelyIdentityLines(observations).map((o) => `“${o.text}”`),
    });
  }

  if (claim.action?.code === "EVIDENCE_RECONCILIATION_REQUIRED") {
    const missing = missingEvidenceItems(claim.action.message);
    cards.push({
      title: "Evidence checklist",
      status: "blocked",
      body: "Required adjudication facts are missing or not confidently grounded.",
      details:
        missing.length > 0
          ? missing.map((item) => `${item} needs correction or upload support`)
          : [claim.action.message],
    });
  }

  if (claim.action && claim.action.code !== "PATIENT_IDENTITY_CONFLICT" && claim.action.code !== "EVIDENCE_RECONCILIATION_REQUIRED") {
    cards.push({
      title: "Member action",
      status: "warning",
      body: claim.action.code,
      details: [claim.action.message],
    });
  }

  if (claim.processing_failure) {
    cards.push({
      title: "Processing failure",
      status: "blocked",
      body: claim.processing_failure.code,
      details: [claim.processing_failure.retry_guidance],
    });
  }

  if (claim.rule_traces && claim.rule_traces.length > 0) {
    const failedRules = claim.rule_traces.filter((rule) =>
      ["FAIL", "FAILED", "VIOLATED"].includes((rule.status || "").toUpperCase())
    );
    cards.push({
      title: "Policy rules",
      status: failedRules.length > 0 ? "blocked" : "known",
      body: `${claim.rule_traces.length} rule step(s) executed`,
      details:
        failedRules.length > 0
          ? failedRules.map((rule) => `${rule.rule_id}: ${rule.reason_code || rule.status}`)
          : claim.rule_traces.slice(0, 5).map((rule) => `${rule.rule_id}: ${rule.status}`),
    });
  } else {
    cards.push({
      title: "Policy rules",
      status: "pending",
      body: "Rule execution has not produced a trace yet.",
      details: ["Rules run after evidence reconciliation creates a safe casefile."],
    });
  }

  return cards;
}

function StatusIcon({ status }: { status: EvidenceCard["status"] }) {
  if (status === "known") return <CheckCircle2 className="w-4 h-4 text-teal" />;
  if (status === "blocked") return <ShieldAlert className="w-4 h-4 text-danger" />;
  if (status === "warning") return <AlertTriangle className="w-4 h-4 text-violet" />;
  return <FileSearch className="w-4 h-4 text-amber-700" />;
}

export function WorkflowEvidencePanel({ claim }: WorkflowEvidencePanelProps) {
  const cards = buildCards(claim);
  const observations = claim.ocr_observations || {};
  const hasObservations = Object.keys(observations).length > 0;

  const proofJson = {
    claim_id: claim.claim_id,
    lifecycle_status: claim.lifecycle_status,
    progress: claim.progress,
    action: claim.action || null,
    processing_failure: claim.processing_failure || null,
    rule_traces: claim.rule_traces || [],
    ocr_observation_count: Object.keys(observations).length,
    sampled_ocr_observations: Object.values(observations).slice(0, 12),
  };

  return (
    <div className="p-6 rounded-card bg-canvas neu-raised border border-hairline space-y-4">
      <div className="flex items-start justify-between gap-4 border-b border-hairline pb-3">
        <div>
          <h3 className="text-xs font-semibold text-ink uppercase tracking-wider flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-violet" />
            Workflow Evidence Snapshot
          </h3>
          <p className="mt-1 text-[11px] text-copy leading-relaxed">
            What the system knows so far, what supports it, and what is still blocking the next step.
          </p>
        </div>
        <ClipboardCheck className="w-5 h-5 text-violet/70 shrink-0" />
      </div>

      <div className="space-y-2.5">
        {cards.map((card) => (
          <div
            key={card.title}
            className="p-3 rounded-control bg-white/60 border border-hairline neu-inset-sm text-xs space-y-2"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-semibold text-ink flex items-center gap-2">
                <StatusIcon status={card.status} />
                {card.title}
              </span>
              <span className={`px-2 py-0.5 rounded-label border text-[10px] font-bold ${statusStyle[card.status]}`}>
                {statusLabel[card.status]}
              </span>
            </div>
            <p className="text-copy leading-relaxed">{card.body}</p>
            {card.details && card.details.length > 0 && (
              <ul className="space-y-1 pl-5 list-disc text-[11px] text-ink/85">
                {card.details.slice(0, 6).map((detail, index) => (
                  <li key={`${card.title}-${index}`}>{detail}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>

      {hasObservations && (
        <AllOcrObservationsRegistry
          observations={observations}
          title="OCR Evidence Available in This Branch"
        />
      )}

      <JsonDisclosure title="Workflow Evidence Snapshot JSON" data={proofJson} />
    </div>
  );
}
