import { ClaimLifecycle } from "@/lib/claims-types";
import { Clock, AlertTriangle, UserCheck, CheckCircle2, XCircle, RefreshCw } from "lucide-react";

interface ClaimStageBadgeProps {
  status: ClaimLifecycle;
  size?: "sm" | "md" | "lg";
}

export function ClaimStageBadge({ status, size = "md" }: ClaimStageBadgeProps) {
  const configs: Record<
    ClaimLifecycle,
    { label: string; icon: React.ReactNode; className: string }
  > = {
    RECEIVED: {
      label: "RECEIVED",
      icon: <Clock className="w-3.5 h-3.5" />,
      className: "bg-blue-100 text-blue-800 border-blue-200",
    },
    QUEUED: {
      label: "QUEUED",
      icon: <RefreshCw className="w-3.5 h-3.5 animate-spin" />,
      className: "bg-violet-pale text-violet border-violet/30",
    },
    ACTION_REQUIRED: {
      label: "ACTION REQUIRED",
      icon: <AlertTriangle className="w-3.5 h-3.5" />,
      className: "bg-amber-100 text-amber-800 border-amber-300",
    },
    IN_REVIEW: {
      label: "IN HUMAN REVIEW",
      icon: <UserCheck className="w-3.5 h-3.5" />,
      className: "bg-teal/15 text-teal border-teal/30 font-semibold",
    },
    DECIDED: {
      label: "DECIDED",
      icon: <CheckCircle2 className="w-3.5 h-3.5" />,
      className: "bg-emerald-100 text-emerald-800 border-emerald-300 font-bold",
    },
    PROCESSING_FAILED: {
      label: "PROCESSING FAILED",
      icon: <XCircle className="w-3.5 h-3.5" />,
      className: "bg-danger/15 text-danger border-danger/30 font-semibold",
    },
  };

  const config = configs[status] || {
    label: status,
    icon: null,
    className: "bg-gray-100 text-gray-700 border-gray-300",
  };

  const sizeClasses = {
    sm: "px-2 py-0.5 text-[10px] gap-1",
    md: "px-2.5 py-1 text-xs gap-1.5",
    lg: "px-3.5 py-1.5 text-sm gap-2",
  };

  return (
    <span
      className={`inline-flex items-center rounded-label border neu-raised-sm tracking-wide ${config.className} ${sizeClasses[size]}`}
    >
      {config.icon}
      <span>{config.label}</span>
    </span>
  );
}
