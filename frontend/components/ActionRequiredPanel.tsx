import { Claim } from "@/lib/claims-types";
import { AlertTriangle, FileWarning, UserX, HelpCircle } from "lucide-react";
import { ReplacementUploadForm } from "./ReplacementUploadForm";

interface ActionRequiredPanelProps {
  claim: Claim;
  onRefresh: () => void;
}

export function ActionRequiredPanel({
  claim,
  onRefresh,
}: ActionRequiredPanelProps) {
  const action = claim.action;

  if (!action) {
    return (
      <div className="p-4 rounded-card bg-amber-50 border border-amber-200 text-amber-900 text-xs">
        Action is required, but details are missing. Please refresh.
      </div>
    );
  }

  const affectedDocs = action.affected_documents || [];
  const identityConflicts = action.identity_conflict || [];

  return (
    <div className="p-6 rounded-card bg-amber-50/80 border-2 border-amber-300 neu-raised space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="w-10 h-10 rounded-control bg-amber-500 text-white flex items-center justify-center neu-raised-sm shrink-0">
          <AlertTriangle className="w-5 h-5" />
        </div>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h3 className="font-display font-semibold text-base text-amber-950">
              Member Action Required
            </h3>
            <span className="px-2 py-0.5 rounded-label bg-amber-200 text-amber-900 font-mono text-[11px] font-bold">
              {action.code}
            </span>
          </div>
          <p className="text-sm text-amber-900 font-medium">{action.message}</p>
        </div>
      </div>

      {/* Identity Conflict Warnings */}
      {identityConflicts.length > 0 && (
        <div className="p-4 rounded-card bg-rose-100/80 border border-rose-300 text-rose-950 space-y-2 text-xs">
          <h4 className="font-semibold flex items-center gap-1.5 text-rose-900 uppercase tracking-wider">
            <UserX className="w-4 h-4 text-rose-600" />
            Identity Conflict Discovered
          </h4>
          <ul className="space-y-1 pl-5 list-disc">
            {identityConflicts.map((ic, i) => (
              <li key={i}>
                Document <code className="font-bold">{ic.client_document_id}</code>{" "}
                belongs to patient <strong className="underline">{ic.patient_name}</strong>{" "}
                which does not match policy member identity.
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Affected Documents & Replacement Upload Forms */}
      {affectedDocs.length > 0 ? (
        <div className="space-y-4">
          <h4 className="text-xs font-semibold text-amber-950 uppercase tracking-wider flex items-center gap-2">
            <FileWarning className="w-4 h-4 text-amber-700" />
            Affected Document Actions ({affectedDocs.length})
          </h4>

          <div className="space-y-4">
            {affectedDocs.map((doc) => (
              <div
                key={doc.client_document_id}
                className="p-4 rounded-card bg-white/80 border border-amber-300 neu-raised-sm space-y-3"
              >
                <div className="flex items-center justify-between text-xs border-b border-amber-100 pb-2">
                  <div>
                    <span className="text-copy">Document ID: </span>
                    <strong className="font-mono text-ink">
                      {doc.client_document_id}
                    </strong>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded-label bg-amber-100 text-amber-800 text-[11px]">
                      Observed: {doc.observed_role}
                    </span>
                  </div>
                </div>

                <p className="text-xs text-ink/90 font-medium">
                  Requested Action:{" "}
                  <strong className="text-violet">{doc.requested_action}</strong>
                </p>

                {/* Embedded Replacement Upload Form */}
                <ReplacementUploadForm
                  claimId={claim.claim_id}
                  expectedVersion={claim.version}
                  clientDocumentId={doc.client_document_id}
                  onSuccess={onRefresh}
                />
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="p-4 rounded-card bg-white/60 text-xs text-amber-900 border border-amber-200">
          <p>
            Please review your submitted claim materials and submit a replacement document if applicable.
          </p>
        </div>
      )}
    </div>
  );
}
