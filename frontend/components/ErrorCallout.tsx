import { ApiErrorResponse, ApiErrorBody } from "@/lib/claims-types";
import { AlertCircle, FileX, Info } from "lucide-react";

interface ErrorCalloutProps {
  error: ApiErrorResponse | ApiErrorBody | string | null;
  title?: string;
}

export function ErrorCallout({ error, title = "Action Failed" }: ErrorCalloutProps) {
  if (!error) return null;

  let code = "ERROR";
  let message = typeof error === "string" ? error : "An unexpected error occurred.";
  let details: Array<{ location?: (string | number)[]; message: string }> = [];
  let currentVersion: number | undefined;

  if (typeof error === "object") {
    const errorObj = "error" in error ? error.error : error;
    if (errorObj) {
      code = errorObj.code || "ERROR";
      message = errorObj.message || message;
      details = errorObj.details || [];
      currentVersion = errorObj.current_version;
    }
  }

  return (
    <div className="p-4 rounded-card bg-danger/10 border border-danger/30 neu-inset-sm space-y-2">
      <div className="flex items-start gap-3">
        <AlertCircle className="w-5 h-5 text-danger shrink-0 mt-0.5" />
        <div className="flex-1 space-y-1">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <h4 className="font-semibold text-danger text-sm">{title}</h4>
            <span className="px-2 py-0.5 rounded-label bg-danger/20 text-danger text-[11px] font-mono font-semibold">
              {code}
            </span>
          </div>
          <p className="text-xs text-ink/90 font-medium">{message}</p>

          {currentVersion !== undefined && (
            <p className="text-xs text-copy flex items-center gap-1 mt-1">
              <Info className="w-3.5 h-3.5 text-violet" />
              Latest server claim version:{" "}
              <strong className="text-violet font-mono">{currentVersion}</strong>
            </p>
          )}

          {details.length > 0 && (
            <div className="pt-2 mt-2 border-t border-danger/20 space-y-1">
              <p className="text-[11px] font-semibold text-copy uppercase tracking-wider">
                Validation Details
              </p>
              <ul className="space-y-1">
                {details.map((d, i) => (
                  <li
                    key={i}
                    className="text-xs font-mono text-ink/80 flex items-start gap-2 bg-white/40 p-1.5 rounded-label"
                  >
                    {d.location && d.location.length > 0 && (
                      <span className="text-violet font-semibold shrink-0">
                        [{d.location.join(".")}]
                      </span>
                    )}
                    <span>{d.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
