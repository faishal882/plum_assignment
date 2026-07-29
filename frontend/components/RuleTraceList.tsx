import { RuleTrace } from "@/lib/claims-types";
import { AmountTrace } from "./AmountTrace";
import { CheckCircle, XCircle, AlertCircle, ArrowRight, Shield, FileText } from "lucide-react";

interface RuleTraceListProps {
  rules: RuleTrace[];
}

export function RuleTraceList({ rules }: RuleTraceListProps) {
  if (!rules || rules.length === 0) {
    return (
      <div className="p-4 rounded-card bg-canvas neu-inset border border-hairline text-xs text-copy text-center">
        No rule trace steps recorded for this task.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h4 className="text-xs font-semibold text-ink uppercase tracking-wider flex items-center gap-2">
        <Shield className="w-4 h-4 text-violet" />
        Rule Execution Trace ({rules.length} steps)
      </h4>

      <div className="space-y-3">
        {rules.map((rule, idx) => {
          const status = rule.status || "PASSED";
          const isPassed = status === "PASSED" || status === "APPLIED";
          const isFailed = status === "FAILED" || status === "VIOLATED";

          return (
            <div
              key={idx}
              className="p-4 rounded-card bg-white/70 border border-hairline neu-raised-sm space-y-3 text-xs"
            >
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-violet-pale text-violet font-mono text-[11px] font-bold flex items-center justify-center">
                    {rule.sequence ?? idx + 1}
                  </span>
                  <strong className="font-mono text-sm text-ink">
                    {rule.rule_id || `Rule #${idx + 1}`}
                  </strong>
                  <span
                    className={`px-2 py-0.5 rounded-label font-semibold text-[10px] ${
                      isPassed
                        ? "bg-teal/20 text-teal"
                        : isFailed
                        ? "bg-danger/20 text-danger"
                        : "bg-gray-200 text-gray-700"
                    }`}
                  >
                    {status}
                  </span>
                </div>

                {rule.reason_code && (
                  <span className="font-mono text-[11px] bg-canvas px-2 py-0.5 rounded-label border border-hairline text-copy">
                    Reason: {rule.reason_code}
                  </span>
                )}
              </div>

              {rule.policy_path && (
                <div className="text-[11px] text-copy font-mono bg-canvas p-2 rounded-control neu-inset-sm truncate">
                  Policy Path:{" "}
                  <span className="text-ink">{rule.policy_path}</span>
                </div>
              )}

              {rule.evidence_refs && rule.evidence_refs.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[11px] font-semibold text-copy flex items-center gap-1">
                    <FileText className="w-3.5 h-3.5 text-violet" />
                    Evidence Refs:
                  </span>
                  {rule.evidence_refs.map((ref, rIdx) => (
                    <span
                      key={rIdx}
                      className="px-2 py-0.5 rounded-label bg-violet-pale text-violet font-mono text-[10px]"
                    >
                      {ref}
                    </span>
                  ))}
                </div>
              )}

              {(rule.amount_before_paise !== undefined ||
                rule.adjustment_paise !== undefined ||
                rule.amount_after_paise !== undefined) && (
                <div className="pt-2 border-t border-hairline/60 flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-copy">
                    Amount Adjustment Trace:
                  </span>
                  <AmountTrace
                    beforePaise={rule.amount_before_paise}
                    adjustmentPaise={rule.adjustment_paise}
                    afterPaise={rule.amount_after_paise}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
