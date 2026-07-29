import { Claim } from "@/lib/claims-types";
import { AlertOctagon, RefreshCw, Cpu, CheckCircle2, ShieldX } from "lucide-react";

interface ProcessingFailedPanelProps {
  claim: Claim;
  onRetry?: () => void;
}

export function ProcessingFailedPanel({
  claim,
  onRetry,
}: ProcessingFailedPanelProps) {
  const failure = claim.processing_failure;
  const quality = claim.processing_quality;

  return (
    <div className="p-6 rounded-card bg-rose-50/80 border-2 border-rose-300 neu-raised space-y-6">
      <div className="flex items-start gap-4">
        <div className="w-10 h-10 rounded-control bg-danger text-white flex items-center justify-center neu-raised-sm shrink-0">
          <AlertOctagon className="w-5 h-5" />
        </div>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h3 className="font-display font-semibold text-base text-rose-950">
              System Processing Issue
            </h3>
            {failure?.code && (
              <span className="px-2 py-0.5 rounded-label bg-rose-200 text-rose-900 font-mono text-[11px] font-bold">
                {failure.code}
              </span>
            )}
          </div>
          <p className="text-xs text-rose-900 font-medium">
            This is a system/provider processing failure, <strong>not a claim rejection</strong>.
          </p>
        </div>
      </div>

      {failure?.retry_guidance && (
        <div className="p-4 rounded-card bg-white/80 border border-rose-200 text-xs space-y-2 neu-inset-sm">
          <h4 className="font-semibold text-rose-950 uppercase tracking-wider">
            Safe Retry Guidance
          </h4>
          <p className="text-ink font-medium leading-relaxed">
            {failure.retry_guidance}
          </p>
        </div>
      )}

      {/* Degradation / Component Quality Info */}
      {quality && (
        <div className="p-4 rounded-card bg-white/60 border border-rose-200 space-y-3 text-xs">
          <h4 className="font-semibold text-rose-950 uppercase tracking-wider flex items-center gap-2">
            <Cpu className="w-4 h-4 text-violet" />
            System Quality Diagnostics
          </h4>

          <div className="grid grid-cols-2 gap-3 font-mono">
            <div className="p-2 rounded-control bg-canvas neu-inset-sm">
              <span className="text-[10px] text-copy">Completeness:</span>{" "}
              <strong>{(quality.completeness * 100).toFixed(0)}%</strong>
            </div>
            <div className="p-2 rounded-control bg-canvas neu-inset-sm">
              <span className="text-[10px] text-copy">Confidence:</span>{" "}
              <strong>{(quality.confidence * 100).toFixed(0)}%</strong>
            </div>
          </div>

          {quality.degraded_components.length > 0 && (
            <div className="space-y-1.5 pt-2 border-t border-rose-100">
              <p className="text-[11px] font-semibold text-copy uppercase">
                Degraded Components ({quality.degraded_components.length})
              </p>
              {quality.degraded_components.map((comp, idx) => (
                <div
                  key={idx}
                  className="p-2 rounded-control bg-rose-100/50 border border-rose-200 flex items-center justify-between text-xs"
                >
                  <span className="font-semibold text-rose-900">
                    {comp.component}
                  </span>
                  <span className="font-mono text-rose-800 text-[11px]">
                    {comp.failure_code} ({comp.attempts} attempts)
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {onRetry && (
        <button
          onClick={onRetry}
          className="w-full h-11 px-4 rounded-control bg-violet text-white font-display font-semibold text-sm neu-raised-sm hover:bg-violet-accent transition-all flex items-center justify-center gap-2"
        >
          <RefreshCw className="w-4 h-4" />
          Re-evaluate Claim Status
        </button>
      )}
    </div>
  );
}
