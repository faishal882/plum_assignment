"use client";

import { use, useEffect, useState, useRef, useCallback } from "react";
import { AppShell } from "@/components/AppShell";
import { ClaimStatusRail } from "@/components/ClaimStatusRail";
import { ClaimStageBadge } from "@/components/ClaimStageBadge";
import { ActionRequiredPanel } from "@/components/ActionRequiredPanel";
import { DecisionSummary } from "@/components/DecisionSummary";
import { ProcessingFailedPanel } from "@/components/ProcessingFailedPanel";
import { AmountProgressPanel } from "@/components/AmountProgressPanel";
import { WorkflowEvidencePanel } from "@/components/WorkflowEvidencePanel";
import { ErrorCallout } from "@/components/ErrorCallout";
import { JsonDisclosure } from "@/components/JsonDisclosure";
import { Claim, ApiErrorResponse } from "@/lib/claims-types";
import {
  Copy,
  Check,
  ExternalLink,
  RefreshCw,
  Clock,
  UserCheck,
  FileText,
  Shield,
} from "lucide-react";
import Link from "next/link";

interface ClaimStatusPageProps {
  params: Promise<{ claimId: string }>;
}

export default function ClaimStatusPage({ params }: ClaimStatusPageProps) {
  const { claimId } = use(params);

  const [claim, setClaim] = useState<Claim | null>(null);
  const [loading, setLoading] = useState(true);
  const [phoenixUrl, setPhoenixUrl] = useState("http://127.0.0.1:6006");
  const [error, setError] = useState<ApiErrorResponse | string | null>(null);
  const [copied, setCopied] = useState(false);
  const [pollCount, setPollCount] = useState(0);

  useEffect(() => {
    setPhoenixUrl(`http://${window.location.hostname}:6006`);
  }, []);

  const isMounted = useRef(true);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);

  const fetchClaim = useCallback(async () => {
    try {
      const devUsername =
        localStorage.getItem("plum_dev_username") || "member.emp001";

      const res = await fetch(`/api/claims/${claimId}`, {
        headers: {
          "X-Dev-Username": devUsername,
        },
        cache: "no-store",
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data);
      } else {
        setClaim(data as Claim);
        setError(null);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to fetch claim status");
    } finally {
      if (isMounted.current) {
        setLoading(false);
      }
    }
  }, [claimId]);

  // Polling logic with backoff & visibility check
  useEffect(() => {
    isMounted.current = true;

    const runPoll = async () => {
      if (document.visibilityState === "hidden") return;

      await fetchClaim();
      setPollCount((prev) => prev + 1);
    };

    runPoll();

    return () => {
      isMounted.current = false;
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, [fetchClaim]);

  useEffect(() => {
    if (!claim || claim.progress?.is_terminal) {
      return;
    }

    // Back off polling interval: 1.5s for first 5 polls, then 5s
    const delay = pollCount < 5 ? 1500 : 5000;

    pollTimerRef.current = setTimeout(() => {
      if (document.visibilityState !== "hidden" && isMounted.current) {
        fetchClaim().then(() => setPollCount((p) => p + 1));
      }
    }, delay);

    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, [claim, pollCount, fetchClaim]);

  const handleCopyClaimId = () => {
    navigator.clipboard.writeText(claimId);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <AppShell>
      <div className="space-y-8">
        {/* Top Header & Demo Tools */}
        <div className="p-6 rounded-card bg-canvas neu-raised border border-hairline flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div className="space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-xs font-bold text-violet">
                Claim ID: {claimId}
              </span>
              {claim && <ClaimStageBadge status={claim.lifecycle_status} />}
            </div>

            {claim && (
              <p className="text-xs text-copy font-mono">
                Member: <strong className="text-ink">{claim.member_id}</strong> |{" "}
                Policy: <strong className="text-ink">{claim.policy_id}</strong> |{" "}
                Category:{" "}
                <strong className="text-ink">{claim.claim_category}</strong> (v
                {claim.version})
              </p>
            )}
          </div>

          {/* Demo Helper Links */}
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={handleCopyClaimId}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-control bg-canvas hover:bg-violet-pale text-xs font-semibold text-ink neu-raised-sm border border-hairline transition-all"
              title="Copy Claim ID for Demo"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-teal" />
                  <span className="text-teal">Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-violet" />
                  <span>Copy Claim ID</span>
                </>
              )}
            </button>

            <a
              href={phoenixUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-control bg-canvas hover:bg-violet-pale text-xs font-semibold text-ink neu-raised-sm border border-hairline transition-all"
              title="Open Phoenix Tracing (Demo)"
            >
              <ExternalLink className="w-3.5 h-3.5 text-teal" />
              <span>Open Phoenix</span>
            </a>

            <button
              onClick={fetchClaim}
              className="p-1.5 rounded-control bg-canvas hover:bg-violet-pale text-copy hover:text-violet neu-raised-sm border border-hairline transition-colors"
              title="Manual Status Refresh"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {error && <ErrorCallout error={error} title="Failed to load claim" />}

        {loading && !claim ? (
          <div className="p-12 text-center rounded-card bg-canvas neu-inset border border-hairline space-y-3">
            <RefreshCw className="w-8 h-8 text-violet animate-spin mx-auto" />
            <p className="text-sm font-semibold text-ink">Fetching claim status...</p>
          </div>
        ) : claim ? (
          <div className="space-y-8">
            {/* Status Rail */}
            <ClaimStatusRail
              status={claim.lifecycle_status}
              currentStage={claim.progress?.current_stage || ""}
              isTerminal={claim.progress?.is_terminal || false}
              label={claim.progress?.label}
              percent={claim.progress?.percent}
              events={claim.progress?.events}
            />

            {/* Primary Page Composition: Left Status / Right Decision & Evidence */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
              {/* Left Column: Claim Packet & Details (5 cols) */}
              <div className="lg:col-span-5 space-y-6">
                <div className="p-6 rounded-card bg-canvas neu-raised border border-hairline space-y-4">
                  <h3 className="text-xs font-semibold text-ink uppercase tracking-wider flex items-center gap-2 border-b border-hairline pb-3">
                    <FileText className="w-4 h-4 text-violet" />
                    Submitted Claim Packet
                  </h3>

                  <div className="space-y-3 text-xs font-mono">
                    <div className="flex justify-between p-2 rounded-control bg-white/60">
                      <span className="text-copy">Treatment Date:</span>
                      <strong className="text-ink">{claim.treatment_date}</strong>
                    </div>
                    <div className="flex justify-between p-2 rounded-control bg-white/60">
                      <span className="text-copy">Claimed Amount:</span>
                      <strong className="text-ink">
                        ₹{claim.claimed_amount} {claim.currency}
                      </strong>
                    </div>
                    <div className="flex justify-between p-2 rounded-control bg-white/60">
                      <span className="text-copy">Lifecycle Status:</span>
                      <strong className="text-violet">{claim.lifecycle_status}</strong>
                    </div>
                    <div className="flex justify-between p-2 rounded-control bg-white/60">
                      <span className="text-copy">Is Terminal:</span>
                      <strong className={claim.progress?.is_terminal ? "text-teal" : "text-amber-600"}>
                        {claim.progress?.is_terminal ? "True (Complete)" : "False (Polling...)"}
                      </strong>
                    </div>
                  </div>
                </div>

                <AmountProgressPanel claim={claim} />
                <WorkflowEvidencePanel claim={claim} />

                {/* Raw Claim JSON Disclosure */}
                <JsonDisclosure title="Raw Claim Object" data={claim} />
              </div>

              {/* Right Column: State Render (7 cols) */}
              <div className="lg:col-span-7 space-y-6">
                {/* 1. QUEUED / RECEIVED */}
                {(claim.lifecycle_status === "QUEUED" || claim.lifecycle_status === "RECEIVED") && (
                  <div className="p-8 rounded-card bg-violet-pale/50 border-2 border-violet/30 neu-raised text-center space-y-4">
                    <div className="w-12 h-12 rounded-control bg-violet text-white flex items-center justify-center neu-raised-sm mx-auto">
                      <Clock className="w-6 h-6 animate-pulse" />
                    </div>
                    <div className="space-y-1">
                      <h3 className="font-display font-semibold text-lg text-ink">
                        Asynchronous Processing in Progress
                      </h3>
                      <p className="text-xs text-copy max-w-md mx-auto">
                        The claims worker is extracting document evidence and evaluating adjudication policies. Auto-polling every few seconds...
                      </p>
                    </div>
                  </div>
                )}

                {/* 2. ACTION_REQUIRED */}
                {claim.lifecycle_status === "ACTION_REQUIRED" && (
                  <ActionRequiredPanel claim={claim} onRefresh={fetchClaim} />
                )}

                {/* 3. IN_REVIEW */}
                {claim.lifecycle_status === "IN_REVIEW" && (
                  <div className="p-8 rounded-card bg-teal/10 border-2 border-teal/30 neu-raised space-y-4">
                    <div className="flex items-center gap-4">
                      <div className="w-12 h-12 rounded-control bg-teal text-white flex items-center justify-center neu-raised-sm shrink-0">
                        <UserCheck className="w-6 h-6" />
                      </div>
                      <div>
                        <h3 className="font-display font-semibold text-lg text-ink">
                          Pending Human Review
                        </h3>
                        <p className="text-xs text-copy mt-1">
                          This claim requires human reviewer adjudication. Adjudication details are withheld until resolved by an operator.
                        </p>
                      </div>
                    </div>

                    <div className="pt-3 border-t border-teal/20 flex justify-end">
                      <Link
                        href="/review"
                        className="px-4 py-2 rounded-control bg-teal text-white font-semibold text-xs neu-raised-sm hover:bg-teal/90 transition-all inline-flex items-center gap-2"
                      >
                        <UserCheck className="w-3.5 h-3.5" />
                        Go to Reviewer Console
                      </Link>
                    </div>
                  </div>
                )}

                {/* 4. DECIDED */}
                {claim.lifecycle_status === "DECIDED" && (
                  <DecisionSummary claim={claim} />
                )}

                {/* 5. PROCESSING_FAILED */}
                {claim.lifecycle_status === "PROCESSING_FAILED" && (
                  <ProcessingFailedPanel claim={claim} onRetry={fetchClaim} />
                )}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
