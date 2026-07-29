import { ClaimLifecycle } from "@/lib/claims-types";
import { CheckCircle2, Clock, AlertTriangle, UserCheck, ShieldCheck, XCircle } from "lucide-react";

interface ClaimStatusRailProps {
  status: ClaimLifecycle;
  currentStage: string;
  isTerminal: boolean;
}

export function ClaimStatusRail({
  status,
  currentStage,
  isTerminal,
}: ClaimStatusRailProps) {
  const stages = [
    { key: "RECEIVED", label: "Ingest", icon: Clock },
    { key: "QUEUED", label: "Triage & OCR", icon: Clock },
    {
      key: "ACTION_REQUIRED",
      label: status === "ACTION_REQUIRED" ? "Action Required" : "Evidence Check",
      icon: AlertTriangle,
    },
    { key: "IN_REVIEW", label: "Human Review", icon: UserCheck },
    {
      key: status === "PROCESSING_FAILED" ? "PROCESSING_FAILED" : "DECIDED",
      label: status === "PROCESSING_FAILED" ? "System Failed" : "Decision",
      icon: status === "PROCESSING_FAILED" ? XCircle : ShieldCheck,
    },
  ];

  const getStageState = (stageKey: string) => {
    if (status === stageKey) return "current";

    // Ordering logic
    const order = ["RECEIVED", "QUEUED", "ACTION_REQUIRED", "IN_REVIEW", "DECIDED"];
    const currentIndex = order.indexOf(status);
    const stageIndex = order.indexOf(stageKey);

    if (status === "PROCESSING_FAILED" && stageKey === "PROCESSING_FAILED")
      return "failed";

    if (currentIndex > stageIndex || (isTerminal && status === "DECIDED"))
      return "completed";

    return "upcoming";
  };

  return (
    <div className="p-4 sm:p-6 rounded-card bg-canvas neu-inset border border-hairline space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-ink uppercase tracking-wider flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-violet animate-pulse" />
          Workflow Status Rail
        </h3>
        <span className="text-xs font-mono font-medium text-copy">
          Stage: <strong className="text-ink">{currentStage || status}</strong>
        </span>
      </div>

      {/* Rail Timeline Bar */}
      <div className="grid grid-cols-5 gap-2 sm:gap-4 relative">
        {stages.map((stage, idx) => {
          const state = getStageState(stage.key);
          const Icon = stage.icon;

          return (
            <div
              key={stage.key}
              className={`flex flex-col items-center text-center space-y-2 p-2 sm:p-3 rounded-card transition-all ${
                state === "current"
                  ? "bg-violet-pale border-2 border-violet neu-raised-sm animate-pulse-violet"
                  : state === "completed"
                  ? "bg-white/40 border border-hairline text-ink"
                  : state === "failed"
                  ? "bg-danger/15 border border-danger text-danger"
                  : "opacity-60 bg-transparent border border-transparent text-copy"
              }`}
            >
              <div
                className={`w-7 h-7 sm:w-9 sm:h-9 rounded-control flex items-center justify-center neu-raised-sm text-xs font-bold ${
                  state === "current"
                    ? "bg-violet text-white"
                    : state === "completed"
                    ? "bg-teal text-white"
                    : state === "failed"
                    ? "bg-danger text-white"
                    : "bg-canvas text-copy border border-hairline"
                }`}
              >
                {state === "completed" ? (
                  <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" />
                ) : (
                  <Icon className="w-4 h-4 sm:w-5 sm:h-5" />
                )}
              </div>
              <span className="text-[11px] sm:text-xs font-semibold leading-tight">
                {stage.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
