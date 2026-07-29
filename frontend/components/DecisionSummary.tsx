import { Claim } from "@/lib/claims-types";
import { CheckCircle2, DollarSign, FileCheck, ShieldAlert, Award } from "lucide-react";
import { DeductionList } from "./DeductionList";

interface DecisionSummaryProps {
  claim: Claim;
}

export function DecisionSummary({ claim }: DecisionSummaryProps) {
  const adjudication = claim.adjudication;
  const explanation = claim.explanation;

  if (!adjudication) {
    return (
      <div className="p-4 rounded-card bg-canvas neu-inset border border-hairline text-xs text-copy">
        Claim is decided, but adjudication payload is omitted.
      </div>
    );
  }

  const isApproved =
    adjudication.recommendation.includes("APPROVE") ||
    adjudication.recommendation === "ACCEPT";

  return (
    <div className="space-y-6">
      {/* Visual Adjudication Banner */}
      <div
        className={`p-6 rounded-card border-2 neu-raised space-y-4 ${
          isApproved
            ? "bg-teal/10 border-teal/40"
            : "bg-danger/10 border-danger/40"
        }`}
      >
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div
              className={`w-12 h-12 rounded-control flex items-center justify-center neu-raised-sm text-white ${
                isApproved ? "bg-teal" : "bg-danger"
              }`}
            >
              {isApproved ? (
                <Award className="w-6 h-6" />
              ) : (
                <ShieldAlert className="w-6 h-6" />
              )}
            </div>
            <div>
              <span className="text-[11px] font-semibold text-copy uppercase tracking-widest">
                Machine Recommendation
              </span>
              <h3 className="font-display font-bold text-xl text-ink">
                {adjudication.recommendation}
              </h3>
            </div>
          </div>

          <div className="text-right">
            <span className="text-[11px] font-semibold text-copy uppercase tracking-widest">
              Approved Amount
            </span>
            <div className="text-2xl font-display font-extrabold text-ink">
              ₹{adjudication.approved_amount}{" "}
              <span className="text-xs font-normal text-copy">
                {adjudication.currency}
              </span>
            </div>
            <div className="text-xs text-copy">
              Claimed: ₹{claim.claimed_amount} {claim.currency}
            </div>
          </div>
        </div>

        {explanation?.summary && (
          <div className="pt-3 border-t border-hairline/60">
            <p className="text-xs font-semibold text-copy uppercase tracking-wider mb-1">
              Adjudication Explanation
            </p>
            <p className="text-sm text-ink leading-relaxed font-medium">
              {explanation.summary}
            </p>
          </div>
        )}
      </div>

      {/* Itemized Deductions & Line Items */}
      {explanation && (
        <DeductionList
          deductions={explanation.deductions || []}
          lineItems={explanation.line_items || []}
        />
      )}
    </div>
  );
}
