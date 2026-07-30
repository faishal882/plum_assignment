import { Claim, OcrObservation, RuleTrace } from "@/lib/claims-types";
import { Calculator, CheckCircle2, Clock3, FileSearch, IndianRupee, ShieldCheck, XCircle } from "lucide-react";
import { JsonDisclosure } from "./JsonDisclosure";

type RowState = "known" | "detected" | "pending" | "blocked" | "applied";

interface AmountProgressPanelProps {
  claim: Claim;
}

interface AmountRow {
  label: string;
  value: string;
  state: RowState;
  detail: string;
}

const stateStyles: Record<RowState, string> = {
  known: "bg-teal/15 text-teal border-teal/30",
  detected: "bg-violet-pale text-violet border-violet/25",
  pending: "bg-amber-100 text-amber-800 border-amber-300",
  blocked: "bg-danger/15 text-danger border-danger/30",
  applied: "bg-blue-100 text-blue-800 border-blue-200",
};

const stateLabels: Record<RowState, string> = {
  known: "Known",
  detected: "Detected",
  pending: "Pending",
  blocked: "Blocked",
  applied: "Applied",
};

function paiseToMoney(value?: number | null): string | null {
  if (value === undefined || value === null) return null;
  return `₹${(value / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function moneyText(value: string, currency: string): string {
  return `₹${value} ${currency}`;
}

function extractAmountPaise(text: string): number | null {
  const match = text.match(/(?:inr|rs\.?|₹)?\s*([0-9][0-9,]*(?:\.\d{1,2})?)/i);
  if (!match) return null;
  const amount = Number.parseFloat(match[1].replace(/,/g, ""));
  if (!Number.isFinite(amount)) return null;
  return Math.round(amount * 100);
}

function findDetectedBillTotal(observations?: Record<string, OcrObservation>): {
  amountPaise: number;
  observation: OcrObservation;
} | null {
  if (!observations) return null;
  const values = Object.values(observations);
  const candidates = values.filter(
    (observation) =>
      observation.field_type === "TOTAL" ||
      /\b(total|amount paid|bill amount|grand total)\b/i.test(observation.text)
  );

  for (const observation of candidates) {
    const amountPaise = extractAmountPaise(observation.text);
    if (amountPaise !== null) {
      return { amountPaise, observation };
    }
  }
  return null;
}

function findCategoryLimitRule(rules?: RuleTrace[]): RuleTrace | undefined {
  return rules?.find(
    (rule) =>
      rule.rule_id?.includes("category_limit") &&
      typeof rule.inputs?.limit_paise === "number"
  );
}

function adjustmentTotal(rules?: RuleTrace[]): number {
  return (rules || []).reduce((total, rule) => total + (rule.adjustment_paise || 0), 0);
}

function isBillingBlocked(claim: Claim): boolean {
  return Boolean(
    claim.action?.code === "EVIDENCE_RECONCILIATION_REQUIRED" &&
      claim.action.message.toLowerCase().includes("billing.total")
  );
}

function amountRows(claim: Claim): { rows: AmountRow[]; debug: Record<string, unknown> } {
  const detectedBill = findDetectedBillTotal(claim.ocr_observations);
  const categoryLimitRule = findCategoryLimitRule(claim.rule_traces);
  const limitPaise = categoryLimitRule?.inputs?.limit_paise as number | undefined;
  const adjustmentPaise = adjustmentTotal(claim.rule_traces);
  const approved = claim.adjudication?.approved_amount;
  const billingBlocked = isBillingBlocked(claim);

  const rows: AmountRow[] = [
    {
      label: "Claimed amount",
      value: moneyText(claim.claimed_amount, claim.currency),
      state: "known",
      detail: "Submitted by the member with the claim packet.",
    },
  ];

  if (detectedBill) {
    rows.push({
      label: "Bill total",
      value: paiseToMoney(detectedBill.amountPaise) || "Detected",
      state: claim.lifecycle_status === "DECIDED" ? "known" : "detected",
      detail: `OCR line: “${detectedBill.observation.text}”`,
    });
  } else {
    rows.push({
      label: "Bill total",
      value: billingBlocked ? "Needs correction" : "Waiting for OCR evidence",
      state: billingBlocked ? "blocked" : "pending",
      detail: billingBlocked
        ? "billing.total was not grounded well enough for adjudication."
        : "The bill amount will appear after OCR/evidence extraction.",
    });
  }

  rows.push({
    label: "Policy limit",
    value: paiseToMoney(limitPaise) || "Waiting for policy check",
    state: limitPaise === undefined ? "pending" : "known",
    detail: categoryLimitRule?.policy_path || "Available after rule evaluation.",
  });

  rows.push({
    label: "Adjustments",
    value: adjustmentPaise === 0 ? "None yet" : paiseToMoney(adjustmentPaise) || "Applied",
    state: adjustmentPaise === 0 ? "pending" : "applied",
    detail:
      adjustmentPaise === 0
        ? "Copay, discounts, or policy deductions have not been applied yet."
        : "Derived from rule execution amount deltas.",
  });

  rows.push({
    label: "Approved amount",
    value: approved ? moneyText(approved, claim.adjudication?.currency || claim.currency) : "Not finalized",
    state: approved
      ? "known"
      : claim.lifecycle_status === "ACTION_REQUIRED" || claim.lifecycle_status === "PROCESSING_FAILED"
        ? "blocked"
        : "pending",
    detail: approved
      ? "Final adjudicated amount."
      : claim.lifecycle_status === "ACTION_REQUIRED"
        ? "Blocked until required evidence is corrected."
        : claim.lifecycle_status === "PROCESSING_FAILED"
          ? "Blocked by a processing failure."
          : "Waiting for evidence and policy adjudication.",
  });

  return {
    rows,
    debug: {
      claim_id: claim.claim_id,
      lifecycle_status: claim.lifecycle_status,
      claimed_amount: claim.claimed_amount,
      detected_bill_total: detectedBill
        ? {
            amount_paise: detectedBill.amountPaise,
            observation_id: detectedBill.observation.observation_id,
            text: detectedBill.observation.text,
            page_number: detectedBill.observation.page_number,
            confidence: detectedBill.observation.confidence,
          }
        : null,
      category_limit_rule: categoryLimitRule || null,
      adjustment_total_paise: adjustmentPaise,
      adjudication: claim.adjudication || null,
      action: claim.action || null,
    },
  };
}

function RowIcon({ state }: { state: RowState }) {
  if (state === "known") return <CheckCircle2 className="w-4 h-4 text-teal" />;
  if (state === "blocked") return <XCircle className="w-4 h-4 text-danger" />;
  if (state === "detected") return <FileSearch className="w-4 h-4 text-violet" />;
  if (state === "applied") return <ShieldCheck className="w-4 h-4 text-blue-700" />;
  return <Clock3 className="w-4 h-4 text-amber-700" />;
}

export function AmountProgressPanel({ claim }: AmountProgressPanelProps) {
  const { rows, debug } = amountRows(claim);

  return (
    <div className="p-6 rounded-card bg-canvas neu-raised border border-hairline space-y-4">
      <div className="flex items-start justify-between gap-4 border-b border-hairline pb-3">
        <div>
          <h3 className="text-xs font-semibold text-ink uppercase tracking-wider flex items-center gap-2">
            <IndianRupee className="w-4 h-4 text-violet" />
            Amount Trail
          </h3>
          <p className="mt-1 text-[11px] text-copy leading-relaxed">
            Progressive money view from submitted claim to OCR evidence and policy outcome.
          </p>
        </div>
        <Calculator className="w-5 h-5 text-violet/70 shrink-0" />
      </div>

      <div className="space-y-2.5">
        {rows.map((row) => (
          <div
            key={row.label}
            className="p-3 rounded-control bg-white/60 border border-hairline neu-inset-sm text-xs space-y-1.5"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-semibold text-ink flex items-center gap-2">
                <RowIcon state={row.state} />
                {row.label}
              </span>
              <span className="font-mono font-bold text-ink">{row.value}</span>
            </div>
            <div className="flex items-center justify-between gap-3 text-[11px]">
              <span className="text-copy leading-relaxed">{row.detail}</span>
              <span className={`px-2 py-0.5 rounded-label border text-[10px] font-bold ${stateStyles[row.state]}`}>
                {stateLabels[row.state]}
              </span>
            </div>
          </div>
        ))}
      </div>

      <JsonDisclosure title="Amount Trail JSON" data={debug} />
    </div>
  );
}
