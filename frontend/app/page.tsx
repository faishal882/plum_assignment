"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import Link from "next/link";
import { PlusCircle, ClipboardList, Shield, ArrowRight, History, FileText } from "lucide-react";
import { ClaimStageBadge } from "@/components/ClaimStageBadge";

export default function HomePage() {
  const [recentClaims, setRecentClaims] = useState<string[]>([]);

  useEffect(() => {
    const saved = localStorage.getItem("plum_recent_claims");
    if (saved) {
      try {
        setRecentClaims(JSON.parse(saved));
      } catch {
        setRecentClaims([]);
      }
    }
  }, []);

  return (
    <AppShell>
      <div className="space-y-8">
        {/* Welcome Operational Banner */}
        <div className="p-8 rounded-card bg-canvas neu-raised border border-hairline flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div className="space-y-2 max-w-2xl">
            <span className="px-3 py-1 rounded-label bg-violet-pale text-violet text-xs font-semibold uppercase tracking-widest">
              Claims Operations Console
            </span>
            <h1 className="font-display font-bold text-3xl sm:text-4xl text-ink leading-tight">
              Explainable Health Insurance Claims Adjudication
            </h1>
            <p className="text-sm text-copy leading-relaxed">
              Submit claim packets, inspect real-time worker execution stages, review rules engine calculations, and resolve operational review tasks.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row gap-3 shrink-0">
            <Link
              href="/claims/new"
              className="h-11 px-5 rounded-control bg-violet text-white font-display font-semibold text-sm neu-raised hover:bg-violet-accent transition-all flex items-center justify-center gap-2"
            >
              <PlusCircle className="w-4 h-4" />
              New Claim
            </Link>

            <Link
              href="/review"
              className="h-11 px-5 rounded-control bg-canvas text-ink font-display font-semibold text-sm neu-raised-sm hover:bg-violet-pale transition-all flex items-center justify-center gap-2 border border-hairline"
            >
              <ClipboardList className="w-4 h-4 text-violet" />
              Review Queue
            </Link>
          </div>
        </div>

        {/* Quick Launch Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Link
            href="/claims/new"
            className="group p-6 rounded-card bg-canvas neu-raised border border-hairline hover:border-violet/50 hover:bg-violet-pale/10 transition-all space-y-3"
          >
            <div className="flex items-center justify-between">
              <div className="w-10 h-10 rounded-control bg-violet-pale text-violet flex items-center justify-center neu-raised-sm group-hover:bg-violet group-hover:text-white transition-colors">
                <PlusCircle className="w-5 h-5" />
              </div>
              <ArrowRight className="w-5 h-5 text-copy group-hover:text-violet transition-colors" />
            </div>
            <div>
              <h3 className="font-display font-semibold text-lg text-ink">
                Submit Member Claim
              </h3>
              <p className="text-xs text-copy mt-1">
                Upload claim document manifest, member details, and track asynchronous worker triage (202 QUEUED).
              </p>
            </div>
          </Link>

          <Link
            href="/review"
            className="group p-6 rounded-card bg-canvas neu-raised border border-hairline hover:border-violet/50 hover:bg-violet-pale/10 transition-all space-y-3"
          >
            <div className="flex items-center justify-between">
              <div className="w-10 h-10 rounded-control bg-teal/15 text-teal flex items-center justify-center neu-raised-sm group-hover:bg-teal group-hover:text-white transition-colors">
                <ClipboardList className="w-5 h-5" />
              </div>
              <ArrowRight className="w-5 h-5 text-copy group-hover:text-teal transition-colors" />
            </div>
            <div>
              <h3 className="font-display font-semibold text-lg text-ink">
                Reviewer Task Queue
              </h3>
              <p className="text-xs text-copy mt-1">
                Inspect decision traces, evidence conflicts, and execute version-fenced resolution commands.
              </p>
            </div>
          </Link>
        </div>

        {/* Recent Submitted Claims (LocalStorage Tracked) */}
        {recentClaims.length > 0 && (
          <div className="p-6 rounded-card bg-canvas neu-inset border border-hairline space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold text-ink uppercase tracking-wider flex items-center gap-2">
                <History className="w-4 h-4 text-violet" />
                Recent Submitted Claims ({recentClaims.length})
              </h3>
              <button
                onClick={() => {
                  localStorage.removeItem("plum_recent_claims");
                  setRecentClaims([]);
                }}
                className="text-[11px] text-copy hover:text-danger underline"
              >
                Clear local history
              </button>
            </div>

            <div className="space-y-2">
              {recentClaims.map((cid) => (
                <Link
                  key={cid}
                  href={`/claims/${cid}`}
                  className="p-3 rounded-control bg-white/60 border border-hairline neu-raised-sm hover:bg-white flex items-center justify-between gap-3 text-xs transition-all"
                >
                  <div className="flex items-center gap-2 font-mono">
                    <FileText className="w-4 h-4 text-violet" />
                    <span className="font-semibold text-ink">{cid}</span>
                  </div>
                  <div className="flex items-center gap-2 text-copy text-[11px]">
                    <span>Track Status</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
