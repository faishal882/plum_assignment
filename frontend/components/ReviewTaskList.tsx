"use client";

import { useState } from "react";
import { ReviewTaskSummary } from "@/lib/claims-types";
import Link from "next/link";
import { ClipboardList, ArrowRight, CheckCircle2, Clock, ShieldAlert, Award } from "lucide-react";
import { EmptyState } from "./EmptyState";

interface ReviewTaskListProps {
  tasks: ReviewTaskSummary[];
}

export function ReviewTaskList({ tasks }: ReviewTaskListProps) {
  const [filter, setFilter] = useState<"ALL" | "OPEN" | "RESOLVED">("OPEN");

  const filteredTasks = tasks.filter((t) => {
    if (filter === "OPEN") return t.status === "OPEN";
    if (filter === "RESOLVED") return t.status === "RESOLVED";
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Header & Filter Controls */}
      <div className="flex items-center justify-between gap-4 flex-wrap pb-4 border-b border-hairline">
        <div>
          <h2 className="font-display font-semibold text-xl text-ink flex items-center gap-2">
            <ClipboardList className="w-5 h-5 text-violet" />
            Review Queue
          </h2>
          <p className="text-xs text-copy mt-0.5">
            Operational review tasks requiring human adjudication or resolution
          </p>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1.5 p-1 rounded-control bg-canvas neu-inset-sm border border-hairline">
          {(["ALL", "OPEN", "RESOLVED"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded-control text-xs font-semibold transition-all ${
                filter === f
                  ? "bg-violet text-white neu-raised-sm"
                  : "text-copy hover:text-ink hover:bg-violet-pale/40"
              }`}
            >
              {f === "ALL"
                ? `All (${tasks.length})`
                : f === "OPEN"
                ? `Open (${tasks.filter((t) => t.status === "OPEN").length})`
                : `Resolved (${tasks.filter((t) => t.status === "RESOLVED").length})`}
            </button>
          ))}
        </div>
      </div>

      {/* Task Cards Grid */}
      {filteredTasks.length === 0 ? (
        <EmptyState
          icon={<ClipboardList className="w-6 h-6" />}
          title={`No ${filter !== "ALL" ? filter.toLowerCase() : ""} review tasks`}
          description="There are currently no tasks matching your selected filter."
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filteredTasks.map((task) => {
            const isOpen = task.status === "OPEN";
            return (
              <Link
                key={task.id}
                href={`/review/${task.id}`}
                className="group block p-5 rounded-card bg-canvas neu-raised border border-hairline hover:border-violet/50 hover:bg-violet-pale/10 transition-all space-y-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-violet">
                        Task #{task.id.slice(0, 8)}
                      </span>
                      <span
                        className={`px-2 py-0.5 rounded-label text-[10px] font-semibold ${
                          isOpen
                            ? "bg-amber-100 text-amber-800 border border-amber-300"
                            : "bg-teal/20 text-teal border border-teal/30"
                        }`}
                      >
                        {task.status}
                      </span>
                    </div>
                    <p className="text-xs text-copy font-mono">
                      Claim ID: <span className="text-ink">{task.claim_id}</span>{" "}
                      (v{task.claim_version})
                    </p>
                  </div>

                  <div className="w-8 h-8 rounded-control bg-violet-pale text-violet flex items-center justify-center neu-raised-sm group-hover:bg-violet group-hover:text-white transition-colors">
                    <ArrowRight className="w-4 h-4" />
                  </div>
                </div>

                {/* Machine Recommendation & Amount */}
                <div className="p-3 rounded-control bg-white/60 border border-hairline neu-inset-sm flex items-center justify-between gap-3 text-xs">
                  <div>
                    <span className="text-[10px] font-semibold text-copy uppercase tracking-wider block">
                      Machine Rec
                    </span>
                    <span className="font-display font-semibold text-ink">
                      {task.machine_recommendation}
                    </span>
                  </div>
                  <div className="text-right">
                    <span className="text-[10px] font-semibold text-copy uppercase tracking-wider block">
                      Approved Amt
                    </span>
                    <span className="font-mono font-bold text-teal">
                      ₹{task.machine_approved_amount} {task.currency}
                    </span>
                  </div>
                </div>

                {/* Signal Codes */}
                {task.signal_codes.length > 0 && (
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[10px] font-semibold text-copy uppercase">
                      Signals:
                    </span>
                    {task.signal_codes.map((sc, i) => (
                      <span
                        key={i}
                        className="px-2 py-0.5 rounded-label bg-amber-100/80 text-amber-900 font-mono text-[10px] font-medium"
                      >
                        {sc}
                      </span>
                    ))}
                  </div>
                )}

                {/* Allowed Actions */}
                <div className="flex items-center justify-between text-[11px] text-copy pt-2 border-t border-hairline/60">
                  <div className="flex items-center gap-1">
                    <span>Actions:</span>
                    <span className="font-mono text-ink">
                      {task.allowed_actions.join(", ")}
                    </span>
                  </div>
                  <span className="font-mono">
                    {new Date(task.created_at).toLocaleDateString()}
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
