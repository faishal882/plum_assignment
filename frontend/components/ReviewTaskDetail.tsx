"use client";

import { useState } from "react";
import {
  ReviewTaskDetail as ReviewTaskDetailType,
  ReviewAction,
  ApiErrorResponse,
  ReviewResolution,
} from "@/lib/claims-types";
import { RuleTraceList } from "./RuleTraceList";
import { ExtractedEvidenceChecklist } from "./ExtractedEvidenceChecklist";
import { AllOcrObservationsRegistry } from "./AllOcrObservationsRegistry";
import { JsonDisclosure } from "./JsonDisclosure";
import { ErrorCallout } from "./ErrorCallout";
import {
  ShieldCheck,
  FileSearch,
  CheckCircle2,
  XCircle,
  Edit3,
  FileQuestion,
  RefreshCw,
  AlertTriangle,
  Award,
  History,
  Lock,
} from "lucide-react";

interface ReviewTaskDetailProps {
  taskDetail: ReviewTaskDetailType;
  onRefresh: () => void;
}

export function ReviewTaskDetail({ taskDetail, onRefresh }: ReviewTaskDetailProps) {
  const { task, evidence, conflicts, rules, calculations, failures } = taskDetail;

  const [activeTab, setActiveTab] = useState<"trace" | "evidence" | "failures" | "raw">(
    "trace"
  );

  // Form State
  const [selectedAction, setSelectedAction] = useState<ReviewAction>(
    task.allowed_actions[0] || "ACCEPT"
  );
  const [reasonCode, setReasonCode] = useState<string>("REVIEW_DECISION_APPLIED");
  const [reasonNote, setReasonNote] = useState<string>(
    "Verified supporting evidence and rule calculations for claim resolution."
  );
  const [amendedAmount, setAmendedAmount] = useState<string>(
    task.machine_approved_amount || "0.00"
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<ApiErrorResponse | string | null>(null);
  const [resolutionResult, setResolutionResult] = useState<ReviewResolution | null>(
    null
  );

  const isResolved = task.status === "RESOLVED";

  const handleActionSelect = (act: ReviewAction) => {
    setSelectedAction(act);
    if (act === "ACCEPT") {
      setReasonCode("REVIEW_ACCEPTED");
    } else if (act === "AMEND") {
      setReasonCode("REVIEW_AMOUNT_CORRECTED");
    } else if (act === "REJECT") {
      setReasonCode("POLICY_EXCLUSION_APPLIED");
    } else if (act === "REQUEST_DOCUMENT") {
      setReasonCode("REVIEW_DOCUMENT_REQUIRED");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      const payload: Record<string, unknown> = {
        action: selectedAction,
        expected_claim_version: task.claim_version,
        reason_code: reasonCode,
        reason_note: reasonNote,
      };

      if (selectedAction === "AMEND") {
        payload.amended_amount = amendedAmount;
      }

      const devUsername =
        localStorage.getItem("plum_dev_username") || "reviewer.local";

      const res = await fetch(`/api/review-tasks/${task.id}/commands`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
          "X-Dev-Username": devUsername,
        },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data);
      } else {
        setResolutionResult(data as ReviewResolution);
        onRefresh();
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Network error while submitting resolution.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-8">
      {/* Task Header */}
      <div className="p-6 rounded-card bg-canvas neu-raised border border-hairline flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div className="space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm font-bold text-violet">
              Task #{task.id}
            </span>
            <span
              className={`px-2.5 py-1 rounded-label text-xs font-bold ${
                isResolved
                  ? "bg-teal/20 text-teal border border-teal/30"
                  : "bg-amber-100 text-amber-900 border border-amber-300"
              }`}
            >
              {task.status}
            </span>
          </div>
          <p className="text-xs text-copy font-mono">
            Target Claim ID:{" "}
            <strong className="text-ink">{task.claim_id}</strong> (v
            {task.claim_version})
          </p>
        </div>

        {/* Machine Rec summary */}
        <div className="p-4 rounded-control bg-white/60 border border-hairline neu-inset-sm flex items-center gap-6 text-xs shrink-0">
          <div>
            <span className="text-[10px] font-semibold text-copy uppercase tracking-wider block">
              Machine Rec
            </span>
            <span className="font-display font-bold text-ink text-sm">
              {task.machine_recommendation}
            </span>
          </div>
          <div className="text-right">
            <span className="text-[10px] font-semibold text-copy uppercase tracking-wider block">
              Machine Approved
            </span>
            <span className="font-mono font-bold text-teal text-base">
              ₹{task.machine_approved_amount} {task.currency}
            </span>
          </div>
        </div>
      </div>

      {/* Main Two-Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column: Evidence & Decision Trace (7 cols) */}
        <div className="lg:col-span-7 space-y-6">
          {/* Navigation Tabs */}
          <div className="flex items-center gap-2 border-b border-hairline pb-2">
            {[
              { id: "trace", label: `Rule Trace (${rules.length})` },
              { id: "evidence", label: "Evidence & Conflicts" },
              { id: "failures", label: `Failures (${failures.length})` },
              { id: "raw", label: "Raw Payloads" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as typeof activeTab)}
                className={`px-3 py-1.5 rounded-control text-xs font-semibold transition-all ${
                  activeTab === tab.id
                    ? "bg-violet text-white neu-raised-sm"
                    : "text-copy hover:text-ink hover:bg-violet-pale/40"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          {activeTab === "trace" && (
            <div className="space-y-4">
              <RuleTraceList rules={rules} ocrObservations={taskDetail.ocr_observations} />
            </div>
          )}

          {activeTab === "evidence" && (
            <div className="space-y-6">
              {/* Level 2: Grounded Extracted Structured Facts Checklist */}
              <ExtractedEvidenceChecklist
                evidence={evidence}
                ocrObservations={taskDetail.ocr_observations}
              />

              {conflicts.length > 0 && (
                <div className="p-4 rounded-card bg-rose-50 border border-rose-200 space-y-2">
                  <h4 className="text-xs font-semibold text-rose-900 uppercase tracking-wider">
                    Conflicts Discovered ({conflicts.length})
                  </h4>
                  <JsonDisclosure title="Conflicts JSON" data={conflicts} defaultOpen />
                </div>
              )}

              <JsonDisclosure title="Raw Casefile JSON" data={evidence} />

              {/* Level 4: All Extracted OCR Observations Debug Panel */}
              {taskDetail.ocr_observations && Object.keys(taskDetail.ocr_observations).length > 0 && (
                <AllOcrObservationsRegistry
                  observations={taskDetail.ocr_observations}
                />
              )}
            </div>
          )}

          {activeTab === "failures" && (
            <div className="space-y-4">
              {failures.length === 0 ? (
                <div className="p-4 rounded-card bg-canvas neu-inset border border-hairline text-xs text-copy text-center">
                  No system failures associated with this review task.
                </div>
              ) : (
                <JsonDisclosure title="Task Failures" data={failures} defaultOpen />
              )}
            </div>
          )}

          {activeTab === "raw" && (
            <div className="space-y-4">
              <JsonDisclosure title="Full Review Task Detail" data={taskDetail} defaultOpen />
            </div>
          )}
        </div>

        {/* Right Column: Reviewer Action Panel (5 cols) */}
        <div className="lg:col-span-5 space-y-6">
          {isResolved ? (
            <div className="p-6 rounded-card bg-teal/10 border-2 border-teal/40 neu-raised space-y-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-control bg-teal text-white flex items-center justify-center neu-raised-sm">
                  <CheckCircle2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-display font-bold text-base text-ink">
                    Task Resolved
                  </h3>
                  <p className="text-xs text-copy">
                    This review task is immutable and has been resolved.
                  </p>
                </div>
              </div>

              {resolutionResult && (
                <div className="space-y-2 pt-2 border-t border-teal/20 text-xs">
                  <p className="font-semibold text-ink">Resolution Details:</p>
                  <div className="p-3 rounded-control bg-white/70 border border-hairline space-y-1 font-mono text-[11px]">
                    <div>Action: <strong className="text-violet">{resolutionResult.action}</strong></div>
                    <div>Reason Code: {resolutionResult.reason_code}</div>
                    <div>Actor: {resolutionResult.actor_username}</div>
                    <div>Replayed: {resolutionResult.replayed ? "Yes" : "No"}</div>
                  </div>
                  <JsonDisclosure title="Resolution Before/After Diff" data={{ before: resolutionResult.before, after: resolutionResult.after }} />
                </div>
              )}
            </div>
          ) : (
            <form
              onSubmit={handleSubmit}
              className="p-6 rounded-card bg-canvas neu-raised border-2 border-violet/30 space-y-6"
            >
              <div className="flex items-center justify-between border-b border-hairline pb-3">
                <h3 className="font-display font-semibold text-base text-ink flex items-center gap-2">
                  <ShieldCheck className="w-5 h-5 text-violet" />
                  Reviewer Decision Command
                </h3>
                <span className="text-[10px] font-mono font-semibold bg-violet-pale text-violet px-2 py-0.5 rounded-label">
                  v{task.claim_version} Fence
                </span>
              </div>

              {/* Allowed Action Buttons */}
              <div className="space-y-2">
                <label className="block text-xs font-semibold text-copy uppercase tracking-wider">
                  Select Action (Allowed by Rule Engine)
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {(["ACCEPT", "AMEND", "REJECT", "REQUEST_DOCUMENT"] as ReviewAction[]).map(
                    (act) => {
                      const isAllowed = task.allowed_actions.includes(act);
                      const isSelected = selectedAction === act;

                      return (
                        <button
                          key={act}
                          type="button"
                          disabled={!isAllowed}
                          onClick={() => handleActionSelect(act)}
                          className={`p-2.5 rounded-control text-xs font-semibold border flex items-center justify-center gap-1.5 transition-all ${
                            isSelected
                              ? "bg-violet text-white border-violet neu-raised-sm"
                              : isAllowed
                              ? "bg-white/60 text-ink border-hairline hover:bg-violet-pale"
                              : "opacity-40 bg-gray-200 text-gray-500 border-transparent cursor-not-allowed"
                          }`}
                        >
                          {act === "ACCEPT" && <CheckCircle2 className="w-3.5 h-3.5" />}
                          {act === "AMEND" && <Edit3 className="w-3.5 h-3.5" />}
                          {act === "REJECT" && <XCircle className="w-3.5 h-3.5" />}
                          {act === "REQUEST_DOCUMENT" && <FileQuestion className="w-3.5 h-3.5" />}
                          <span>{act}</span>
                        </button>
                      );
                    }
                  )}
                </div>
              </div>

              {/* Amended Amount (Conditional) */}
              {selectedAction === "AMEND" && (
                <div className="space-y-1.5 p-3 rounded-control bg-violet-pale/40 border border-violet/30 neu-inset-sm">
                  <label className="block text-xs font-semibold text-violet">
                    Amended Amount (INR):
                  </label>
                  <input
                    type="text"
                    required
                    value={amendedAmount}
                    onChange={(e) => setAmendedAmount(e.target.value)}
                    className="w-full px-3 py-2 rounded-control bg-canvas border border-hairline font-mono text-sm font-bold text-ink neu-inset-sm focus:ring-2 focus:ring-violet focus:outline-none"
                    placeholder="1200.00"
                  />
                </div>
              )}

              {/* Reason Code */}
              <div className="space-y-1.5">
                <label className="block text-xs font-semibold text-copy">
                  Reason Code:
                </label>
                <input
                  type="text"
                  required
                  value={reasonCode}
                  onChange={(e) => setReasonCode(e.target.value)}
                  className="w-full px-3 py-2 rounded-control bg-canvas border border-hairline font-mono text-xs text-ink neu-inset-sm focus:ring-2 focus:ring-violet focus:outline-none"
                  placeholder="REVIEW_AMOUNT_CORRECTED"
                />
              </div>

              {/* Reason Note */}
              <div className="space-y-1.5">
                <label className="block text-xs font-semibold text-copy">
                  Reason Note (10–1000 characters):
                </label>
                <textarea
                  required
                  minLength={10}
                  maxLength={1000}
                  rows={3}
                  value={reasonNote}
                  onChange={(e) => setReasonNote(e.target.value)}
                  className="w-full px-3 py-2 rounded-control bg-canvas border border-hairline text-xs text-ink neu-inset-sm focus:ring-2 focus:ring-violet focus:outline-none resize-y"
                  placeholder="Explain why this decision command is being applied..."
                />
              </div>

              <ErrorCallout error={error} title="Resolution Command Failed" />

              {/* Submit Button */}
              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full h-11 px-4 rounded-control bg-violet text-white font-display font-semibold text-sm neu-raised-sm hover:bg-violet-accent disabled:opacity-50 transition-all flex items-center justify-center gap-2"
              >
                {isSubmitting ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Executing Command...
                  </>
                ) : (
                  <>
                    <ShieldCheck className="w-4 h-4" />
                    Execute {selectedAction} Command
                  </>
                )}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
