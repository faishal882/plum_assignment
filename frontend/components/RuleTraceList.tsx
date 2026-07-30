import { RuleTrace, OcrObservation } from "@/lib/claims-types";
import { AmountTrace } from "./AmountTrace";
import { resolvePolicyPath, resolveFactRefLabel } from "@/lib/policy-dictionary";
import { CheckCircle, XCircle, AlertCircle, ArrowRight, Shield, FileText, Sparkles, ScrollText, Bookmark } from "lucide-react";

interface RuleTraceListProps {
  rules: RuleTrace[];
  ocrObservations?: Record<string, OcrObservation>;
}

export function RuleTraceList({ rules, ocrObservations }: RuleTraceListProps) {
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
          const clause = resolvePolicyPath(rule.policy_path, rule.inputs);

          return (
            <div
              key={idx}
              className="p-4 rounded-card bg-white/70 border border-hairline neu-raised-sm space-y-3 text-xs"
            >
              {/* Header: Sequence & Rule ID & Status */}
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

              {/* Humanized Policy Clause Banner */}
              {clause ? (
                <div className="p-3.5 rounded-card bg-violet-pale/40 border border-violet/20 neu-inset-sm space-y-1.5">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <span className="text-[11px] font-bold text-violet uppercase tracking-wider flex items-center gap-1.5">
                      <ScrollText className="w-3.5 h-3.5 text-violet" />
                      {clause.title}
                    </span>
                    {clause.configured_value_label && (
                      <span className="px-2 py-0.5 rounded-label bg-white font-mono text-[10px] font-bold text-ink border border-hairline">
                        {clause.configured_value_label}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-ink/90 font-medium leading-relaxed">
                    {clause.clause_text}
                  </p>
                  <div className="text-[10px] text-copy/70 font-mono pt-1 border-t border-violet/10 truncate">
                    Pointer: <code>{rule.policy_path}</code>
                  </div>
                </div>
              ) : rule.policy_path ? (
                <div className="text-[11px] text-copy font-mono bg-canvas p-2 rounded-control neu-inset-sm truncate">
                  Policy Path: <span className="text-ink">{rule.policy_path}</span>
                </div>
              ) : null}

              {/* Evidence References & Grounded OCR Section */}
              {rule.evidence_refs && rule.evidence_refs.length > 0 && (
                <div className="space-y-2 pt-1 border-t border-hairline/50">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-semibold text-copy flex items-center gap-1.5">
                      <Sparkles className="w-3.5 h-3.5 text-violet" />
                      Used Evidence & Verified Facts ({rule.evidence_refs.length})
                    </span>
                  </div>

                  <div className="space-y-2">
                    {rule.evidence_refs.map((ref, rIdx) => {
                      const obs = ocrObservations?.[ref];

                      if (!obs) {
                        const factInfo = resolveFactRefLabel(ref);

                        return (
                          <div
                            key={rIdx}
                            className="p-3 rounded-card bg-teal/10 border border-teal/30 text-teal-950 text-xs neu-inset-sm space-y-1"
                          >
                            <div className="flex items-center justify-between gap-2 flex-wrap">
                              <span className="font-semibold text-teal-900 flex items-center gap-1.5">
                                <Bookmark className="w-3.5 h-3.5 text-teal shrink-0" />
                                {factInfo.label}
                              </span>
                              <span className="px-2 py-0.5 rounded-label bg-teal/20 text-teal font-mono text-[10px] font-bold">
                                Verified Fact
                              </span>
                            </div>
                            {factInfo.details && (
                              <p className="text-[11px] text-teal-900/80 font-sans font-medium">
                                {factInfo.details}
                              </p>
                            )}
                            <div className="text-[10px] text-teal-800/70 font-mono truncate pt-0.5 border-t border-teal/20">
                              Ref: <code>{ref}</code>
                            </div>
                          </div>
                        );
                      }

                      const regionStr = obs.region && Object.keys(obs.region).length > 0
                        ? JSON.stringify(obs.region)
                        : null;

                      return (
                        <div
                          key={rIdx}
                          className="p-3 rounded-card bg-canvas border border-violet/20 neu-inset-sm space-y-2 text-xs"
                        >
                          <div className="flex items-center justify-between gap-2 flex-wrap text-[11px]">
                            <div className="flex items-center gap-1.5 font-semibold text-ink">
                              <FileText className="w-3.5 h-3.5 text-violet shrink-0" />
                              <span>{obs.client_document_id}</span>
                              <span className="px-1.5 py-0.5 rounded-label bg-violet-pale text-violet font-mono text-[10px]">
                                Page {obs.page_number}
                              </span>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="px-2 py-0.5 rounded-label bg-teal/15 text-teal font-mono text-[10px] font-bold">
                                {(obs.confidence * 100).toFixed(0)}% confidence
                              </span>
                              {obs.kind && (
                                <span className="px-1.5 py-0.5 rounded-label bg-white font-mono text-[10px] text-copy border border-hairline uppercase">
                                  {obs.kind}
                                </span>
                              )}
                            </div>
                          </div>

                          <blockquote className="p-2.5 rounded-control bg-white border border-hairline font-serif italic text-ink text-xs leading-relaxed neu-inset-sm">
                            "{obs.text}"
                          </blockquote>

                          <div className="flex items-center justify-between text-[10px] font-mono text-copy/70 pt-0.5">
                            <span className="truncate">
                              Observation ID: <code className="text-violet font-semibold">{obs.observation_id}</code>
                            </span>
                            {regionStr && (
                              <span className="text-copy/60 shrink-0 ml-2">
                                Region: {regionStr}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
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

