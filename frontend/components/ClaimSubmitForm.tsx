"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { FileDropzone } from "./FileDropzone";
import { DocumentManifestEditor } from "./DocumentManifestEditor";
import { ErrorCallout } from "./ErrorCallout";
import {
  ClaimCategory,
  DocumentManifestItem,
  ClaimMetadata,
  ApiErrorResponse,
} from "@/lib/claims-types";
import { PlusCircle, RefreshCw, Shield, UserCheck } from "lucide-react";
import {
  DEV_IDENTITY_CHANGED_EVENT,
  DEV_IDENTITY_STORAGE_KEY,
  readStoredDevIdentity,
} from "@/lib/dev-identities";

export function ClaimSubmitForm() {
  const router = useRouter();

  // Default values specified in assignment prompt
  const [memberId, setMemberId] = useState("EMP001");
  const [policyId, setPolicyId] = useState("PLUM_GHI_2024");
  const [claimCategory, setClaimCategory] = useState<ClaimCategory>("CONSULTATION");
  const [treatmentDate, setTreatmentDate] = useState("2024-11-01");
  const [claimedAmount, setClaimedAmount] = useState("1500.00");
  const [currency, setCurrency] = useState<"INR">("INR");
  const [devIdentityLabel, setDevIdentityLabel] = useState("member.emp001 / EMP001");

  useEffect(() => {
    const syncMemberFromDevIdentity = () => {
      const identity = readStoredDevIdentity();
      setDevIdentityLabel(
        identity.memberId
          ? `${identity.username} / ${identity.memberId} / ${identity.displayName}`
          : `${identity.username} / ${identity.displayName}`
      );
      if (identity.memberId) {
        setMemberId(identity.memberId);
      }
    };

    syncMemberFromDevIdentity();
    window.addEventListener(DEV_IDENTITY_CHANGED_EVENT, syncMemberFromDevIdentity);
    window.addEventListener("storage", syncMemberFromDevIdentity);
    return () => {
      window.removeEventListener(DEV_IDENTITY_CHANGED_EVENT, syncMemberFromDevIdentity);
      window.removeEventListener("storage", syncMemberFromDevIdentity);
    };
  }, []);

  const [files, setFiles] = useState<File[]>([]);
  const [manifest, setManifest] = useState<DocumentManifestItem[]>([]);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<ApiErrorResponse | string | null>(null);

  const handleFilesChange = (newFiles: File[]) => {
    setFiles(newFiles);

    // Synchronize document manifest items
    const updatedManifest: DocumentManifestItem[] = newFiles.map((_, index) => {
      // Retain existing client_document_id if available
      if (manifest[index]) return { ...manifest[index], upload_index: index };
      return {
        upload_index: index,
        client_document_id: `doc-${crypto.randomUUID().slice(0, 8)}`,
      };
    });
    setManifest(updatedManifest);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) {
      setError("Please select at least one supporting document (PDF, JPEG, or PNG).");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const metadata: ClaimMetadata = {
        member_id: memberId.trim(),
        policy_id: policyId.trim(),
        claim_category: claimCategory,
        treatment_date: treatmentDate,
        claimed_amount: claimedAmount.trim(),
        currency: "INR",
        documents: manifest,
      };

      const formData = new FormData();
      formData.set("metadata", JSON.stringify(metadata));
      files.forEach((file) => formData.append("files", file));

      const devUsername =
        localStorage.getItem(DEV_IDENTITY_STORAGE_KEY) || "member.emp001";

      const res = await fetch("/api/claims", {
        method: "POST",
        headers: {
          "Idempotency-Key": crypto.randomUUID(),
          "X-Dev-Username": devUsername,
        },
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data);
      } else {
        // Save claim ID to localStorage for demo tracking convenience
        const claimId = data.claim_id;
        if (claimId) {
          const recent: string[] = JSON.parse(
            localStorage.getItem("plum_recent_claims") || "[]"
          );
          if (!recent.includes(claimId)) {
            recent.unshift(claimId);
            localStorage.setItem("plum_recent_claims", JSON.stringify(recent.slice(0, 20)));
          }
          // Redirect to status page
          router.push(`/claims/${claimId}`);
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Network error during claim submission");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Form Section Header */}
      <div className="flex items-center justify-between border-b border-hairline pb-4">
        <div>
          <h2 className="font-display font-semibold text-xl text-ink flex items-center gap-2">
            <PlusCircle className="w-5 h-5 text-violet" />
            Submit Health Insurance Claim
          </h2>
          <p className="text-xs text-copy mt-0.5">
            Submit claim packet & supporting documents for automated explainable triage
          </p>
        </div>

        <span className="px-3 py-1 rounded-label bg-violet-pale text-violet font-mono text-xs font-semibold neu-raised-sm">
          Multipart API Ingest
        </span>
      </div>

      <div className="rounded-card bg-violet-pale/45 border border-violet/20 px-4 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 w-8 h-8 rounded-control bg-canvas text-violet flex items-center justify-center neu-raised-sm shrink-0">
            <UserCheck className="w-4 h-4" />
          </div>
          <div>
            <p className="text-xs font-semibold text-ink">Active dev identity</p>
            <p className="text-xs text-copy font-mono">{devIdentityLabel}</p>
          </div>
        </div>
        <p className="text-[11px] text-copy max-w-md">
          Change the identity in the top-right switcher. The member id below updates automatically so TC001–TC012 submissions use the correct <code className="text-violet">X-Dev-Username</code>.
        </p>
      </div>

      {/* Claim Metadata Form Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-copy uppercase tracking-wider">
            Member ID
          </label>
          <input
            type="text"
            required
            value={memberId}
            onChange={(e) => setMemberId(e.target.value)}
            className="w-full px-3.5 py-2.5 rounded-control bg-canvas border border-hairline font-mono text-xs text-ink neu-inset-sm focus:ring-2 focus:ring-violet focus:outline-none"
            placeholder="EMP001"
          />
        </div>

        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-copy uppercase tracking-wider">
            Policy ID
          </label>
          <input
            type="text"
            required
            value={policyId}
            onChange={(e) => setPolicyId(e.target.value)}
            className="w-full px-3.5 py-2.5 rounded-control bg-canvas border border-hairline font-mono text-xs text-ink neu-inset-sm focus:ring-2 focus:ring-violet focus:outline-none"
            placeholder="PLUM_GHI_2024"
          />
        </div>

        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-copy uppercase tracking-wider">
            Claim Category
          </label>
          <select
            value={claimCategory}
            onChange={(e) => setClaimCategory(e.target.value as ClaimCategory)}
            className="w-full px-3.5 py-2.5 rounded-control bg-canvas border border-hairline text-xs font-semibold text-ink neu-inset-sm focus:ring-2 focus:ring-violet focus:outline-none cursor-pointer"
          >
            <option value="CONSULTATION">CONSULTATION</option>
            <option value="PHARMACY">PHARMACY</option>
            <option value="DIAGNOSTIC">DIAGNOSTIC</option>
            <option value="DENTAL">DENTAL</option>
            <option value="ALTERNATIVE_MEDICINE">ALTERNATIVE_MEDICINE</option>
          </select>
        </div>

        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-copy uppercase tracking-wider">
            Treatment Date
          </label>
          <input
            type="date"
            required
            value={treatmentDate}
            onChange={(e) => setTreatmentDate(e.target.value)}
            className="w-full px-3.5 py-2.5 rounded-control bg-canvas border border-hairline text-xs text-ink font-mono neu-inset-sm focus:ring-2 focus:ring-violet focus:outline-none"
          />
        </div>

        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-copy uppercase tracking-wider">
            Claimed Amount (INR)
          </label>
          <div className="relative">
            <span className="absolute left-3.5 top-2.5 text-xs font-bold text-copy">
              ₹
            </span>
            <input
              type="text"
              required
              value={claimedAmount}
              onChange={(e) => setClaimedAmount(e.target.value)}
              className="w-full pl-8 pr-3.5 py-2.5 rounded-control bg-canvas border border-hairline font-mono text-xs font-bold text-ink neu-inset-sm focus:ring-2 focus:ring-violet focus:outline-none"
              placeholder="1500.00"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-copy uppercase tracking-wider">
            Currency
          </label>
          <input
            type="text"
            readOnly
            value={currency}
            className="w-full px-3.5 py-2.5 rounded-control bg-canvas border border-hairline font-mono text-xs text-copy neu-inset-sm cursor-not-allowed"
          />
        </div>
      </div>

      {/* Supporting File Dropzone */}
      <div className="space-y-2">
        <label className="block text-xs font-semibold text-copy uppercase tracking-wider">
          Claim Document Files
        </label>
        <FileDropzone files={files} onFilesChange={handleFilesChange} />
      </div>

      {/* Document Manifest Editor */}
      <DocumentManifestEditor
        files={files}
        manifest={manifest}
        onManifestChange={setManifest}
      />

      <ErrorCallout error={error} title="Claim Submission Error" />

      {/* Submit Button */}
      <div className="pt-4 flex items-center justify-end">
        <button
          type="submit"
          disabled={isSubmitting || files.length === 0}
          className="h-12 px-8 rounded-control bg-violet text-white font-display font-semibold text-sm neu-raised hover:bg-violet-accent disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2"
        >
          {isSubmitting ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              Submitting Claim...
            </>
          ) : (
            <>
              <Shield className="w-4 h-4" />
              Submit Claim for Processing (202 QUEUED)
            </>
          )}
        </button>
      </div>
    </form>
  );
}
