"use client";

import { useState } from "react";
import { ErrorCallout } from "./ErrorCallout";
import { UploadCloud, RefreshCw, CheckCircle2, FileText } from "lucide-react";
import { ApiErrorResponse } from "@/lib/claims-types";
import { createUuid } from "@/lib/ids";

interface ReplacementUploadFormProps {
  claimId: string;
  expectedVersion: number;
  clientDocumentId: string;
  onSuccess: () => void;
}

export function ReplacementUploadForm({
  claimId,
  expectedVersion,
  clientDocumentId,
  onSuccess,
}: ReplacementUploadFormProps) {
  const [file, setFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<ApiErrorResponse | string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    setIsSubmitting(true);
    setError(null);
    setSuccessMsg(null);

    try {
      const command = {
        type: "REPLACE_DOCUMENT",
        expected_version: expectedVersion,
        client_document_id: clientDocumentId,
      };

      const formData = new FormData();
      formData.set("command", JSON.stringify(command));
      formData.append("file", file);

      const devUsername =
        localStorage.getItem("plum_dev_username") || "member.emp001";

      const res = await fetch(`/api/claims/${claimId}/actions`, {
        method: "POST",
        headers: {
          "Idempotency-Key": createUuid(),
          "X-Dev-Username": devUsername,
        },
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data);
      } else {
        setSuccessMsg("Replacement document uploaded! Processing re-queued.");
        setFile(null);
        setTimeout(() => {
          onSuccess();
        }, 1500);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Network error during replacement upload");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="p-4 rounded-card bg-canvas neu-inset border border-hairline space-y-4"
    >
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold text-ink uppercase tracking-wider flex items-center gap-2">
          <UploadCloud className="w-4 h-4 text-violet" />
          Submit Replacement Document
        </h4>
        <span className="text-[11px] text-copy font-mono">
          Target: <strong className="text-violet">{clientDocumentId}</strong>
        </span>
      </div>

      <div className="space-y-2">
        <label className="block text-xs font-semibold text-copy">
          Select replacement PDF, JPEG, or PNG file:
        </label>
        <input
          type="file"
          accept=".pdf,.jpeg,.jpg,.png"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
          className="w-full text-xs text-ink file:mr-3 file:py-2 file:px-4 file:rounded-control file:border-0 file:bg-violet file:text-white file:font-semibold hover:file:bg-violet-accent cursor-pointer border border-hairline rounded-control p-1 bg-white/40 neu-inset-sm"
        />
        {file && (
          <p className="text-xs text-teal font-medium flex items-center gap-1.5 pt-1">
            <FileText className="w-3.5 h-3.5" />
            Selected: {file.name} ({(file.size / (1024 * 1024)).toFixed(2)} MB)
          </p>
        )}
      </div>

      <ErrorCallout error={error} title="Replacement Upload Failed" />

      {successMsg && (
        <div className="p-3 rounded-control bg-teal/15 text-teal text-xs font-medium flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      <button
        type="submit"
        disabled={!file || isSubmitting}
        className="w-full h-11 px-4 rounded-control bg-violet text-white font-display font-semibold text-sm neu-raised-sm hover:bg-violet-accent disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
      >
        {isSubmitting ? (
          <>
            <RefreshCw className="w-4 h-4 animate-spin" />
            Uploading Replacement...
          </>
        ) : (
          <>
            <UploadCloud className="w-4 h-4" />
            Upload Replacement & Resume Processing
          </>
        )}
      </button>
    </form>
  );
}
