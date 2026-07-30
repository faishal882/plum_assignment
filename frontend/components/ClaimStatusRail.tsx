import { ClaimLifecycle, ProgressEvent } from "@/lib/claims-types";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Eye,
  FileScan,
  FileText,
  Fingerprint,
  Loader2,
  Microscope,
  ScanText,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";

interface ClaimStatusRailProps {
  status: ClaimLifecycle;
  currentStage: string;
  isTerminal: boolean;
  label?: string;
  percent?: number;
  events?: ProgressEvent[];
}

const stageIcons: Record<string, typeof FileText> = {
  ingest_claim: FileText,
  render_documents: FileScan,
  classify_documents: Fingerprint,
  read_documents: ScanText,
  extract_evidence: Sparkles,
  check_policy: ShieldCheck,
  finalize_claim: ClipboardCheck,
};

const animationCopy: Record<string, string> = {
  ingest_claim: "Building the immutable claim packet",
  render_documents: "Turning uploads into auditable page images",
  classify_documents: "Sorting each document by role and patient identity",
  read_documents: "Scanning pages and capturing OCR observations",
  extract_evidence: "Linking OCR snippets to claim facts",
  check_policy: "Running deterministic policy clauses",
  finalize_claim: "Writing the final outcome",
};

function fallbackEvents(status: ClaimLifecycle, currentStage: string): ProgressEvent[] {
  return [
    {
      stage: currentStage || status,
      label: currentStage || status,
      status: status === "PROCESSING_FAILED" ? "FAILED" : status === "QUEUED" ? "RUNNING" : "COMPLETED",
      summary: "Waiting for backend workflow events.",
    },
  ];
}

function statusTone(status: ProgressEvent["status"]): string {
  if (status === "COMPLETED") return "bg-teal text-white";
  if (status === "RUNNING") return "bg-violet text-white";
  if (status === "FAILED") return "bg-danger text-white";
  return "bg-canvas text-copy border border-hairline";
}

function cardTone(status: ProgressEvent["status"]): string {
  if (status === "COMPLETED") return "bg-white/60 border-hairline text-ink";
  if (status === "RUNNING") return "bg-violet-pale border-violet text-ink neu-raised-sm";
  if (status === "FAILED") return "bg-danger/15 border-danger text-danger";
  return "bg-transparent border-transparent text-copy opacity-70";
}

function statusIcon(event: ProgressEvent) {
  const Icon = stageIcons[event.stage] || FileText;
  if (event.status === "COMPLETED") return <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" />;
  if (event.status === "FAILED") return <XCircle className="w-4 h-4 sm:w-5 sm:h-5" />;
  if (event.status === "RUNNING") return <Loader2 className="w-4 h-4 sm:w-5 sm:h-5 animate-spin" />;
  return <Icon className="w-4 h-4 sm:w-5 sm:h-5" />;
}

function currentEvent(events: ProgressEvent[], currentStage: string): ProgressEvent {
  return (
    events.find((event) => event.stage === currentStage) ||
    [...events].reverse().find((event) => event.status === "RUNNING" || event.status === "FAILED") ||
    [...events].reverse().find((event) => event.status === "COMPLETED") ||
    events[0]
  );
}

function formatDuration(durationMs?: number | null): string | null {
  if (durationMs === undefined || durationMs === null) return null;
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${(durationMs / 1000).toFixed(1)}s`;
}

export function ClaimStatusRail({
  status,
  currentStage,
  isTerminal,
  label,
  percent,
  events,
}: ClaimStatusRailProps) {
  const projectedEvents = events && events.length > 0 ? events : fallbackEvents(status, currentStage);
  const active = currentEvent(projectedEvents, currentStage);
  const ActiveIcon = stageIcons[active.stage] || Eye;
  const safePercent = Math.max(0, Math.min(100, percent ?? 0));

  return (
    <div className="p-4 sm:p-6 rounded-card bg-canvas neu-inset border border-hairline space-y-5 overflow-hidden">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h3 className="text-xs font-semibold text-ink uppercase tracking-wider flex items-center gap-2">
            <span className="relative flex w-2.5 h-2.5">
              {!isTerminal && <span className="absolute inline-flex h-full w-full rounded-full bg-violet opacity-60 animate-ping" />}
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-violet" />
            </span>
            Workflow Status Rail
          </h3>
          <p className="mt-1 text-[11px] text-copy">
            {label || active.label || currentStage || status}
          </p>
        </div>
        <div className="text-right text-xs font-mono">
          <div className="font-bold text-ink">{safePercent}%</div>
          <div className="text-copy">{isTerminal ? "Terminal" : "Processing"}</div>
        </div>
      </div>

      <div className="relative p-4 rounded-card bg-white/50 border border-hairline neu-raised-sm overflow-hidden">
        <div className="absolute inset-y-0 left-0 bg-violet-pale/70 transition-all duration-700 ease-out" style={{ width: `${safePercent}%` }} />
        <div className="relative flex items-center gap-4">
          <div className={`w-12 h-12 rounded-control flex items-center justify-center neu-raised-sm ${statusTone(active.status)}`}>
            {active.status === "RUNNING" ? <ActiveIcon className="w-6 h-6 animate-pulse" /> : statusIcon(active)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <strong className="text-sm text-ink">{active.label}</strong>
              <span className={`px-2 py-0.5 rounded-label text-[10px] font-bold border ${
                active.status === "COMPLETED"
                  ? "bg-teal/15 text-teal border-teal/30"
                  : active.status === "RUNNING"
                    ? "bg-violet text-white border-violet"
                    : active.status === "FAILED"
                      ? "bg-danger/15 text-danger border-danger/30"
                      : "bg-canvas text-copy border-hairline"
              }`}>
                {active.status}
              </span>
            </div>
            <p className="mt-1 text-xs text-copy leading-relaxed">
              {active.summary}
            </p>
            <p className="mt-1 text-[11px] text-violet font-medium">
              {animationCopy[active.stage] || "Projecting durable workflow progress from backend events"}
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 sm:gap-3">
        {projectedEvents.map((event) => {
          const Icon = stageIcons[event.stage] || FileText;
          const duration = formatDuration(event.duration_ms);
          return (
            <div
              key={event.stage}
              className={`min-h-[126px] flex flex-col justify-between p-3 rounded-card border transition-all ${cardTone(event.status)}`}
            >
              <div className="space-y-2">
                <div className={`w-8 h-8 rounded-control flex items-center justify-center neu-raised-sm ${statusTone(event.status)}`}>
                  {event.status === "COMPLETED" ? (
                    <CheckCircle2 className="w-4 h-4" />
                  ) : event.status === "FAILED" ? (
                    <XCircle className="w-4 h-4" />
                  ) : event.status === "RUNNING" ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Icon className="w-4 h-4" />
                  )}
                </div>
                <div>
                  <div className="text-[11px] font-bold text-ink leading-tight">{event.label}</div>
                  <div className="mt-1 text-[10px] text-copy leading-snug line-clamp-3">{event.summary}</div>
                </div>
              </div>
              <div className="mt-2 flex items-center justify-between gap-2 text-[10px] font-mono text-copy">
                <span>{event.attempt_number ? `try ${event.attempt_number}` : event.status.toLowerCase()}</span>
                {duration && <span>{duration}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
