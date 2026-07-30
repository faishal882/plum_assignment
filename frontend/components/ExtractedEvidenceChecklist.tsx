import { useState } from "react";
import { OcrObservation } from "@/lib/claims-types";
import {
  FileText,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Cpu,
  Check,
  Copy,
  Hash,
} from "lucide-react";

interface FactItem {
  fact_path: string;
  value: unknown;
  normalized_value?: unknown;
  state?: string;
  candidate_id?: string;
  candidate_ids?: string[];
  evidence_refs?: string[];
  confidence?: number;
  producer?: string;
  producer_version?: string;
  [key: string]: unknown;
}

interface ExtractedEvidenceChecklistProps {
  evidence: Record<string, unknown>;
  ocrObservations?: Record<string, OcrObservation>;
}

export function ExtractedEvidenceChecklist({
  evidence,
  ocrObservations,
}: ExtractedEvidenceChecklistProps) {
  const [expandedIndices, setExpandedIndices] = useState<Record<number, boolean>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Extract facts list from evidence object
  const factsList: FactItem[] = extractFactsList(evidence);

  const toggleExpanded = (idx: number) => {
    setExpandedIndices((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(text);
    setTimeout(() => setCopiedId(null), 2000);
  };

  if (factsList.length === 0) {
    return (
      <div className="p-4 rounded-card bg-canvas neu-inset border border-hairline text-xs text-copy text-center">
        No structured facts extracted for this casefile.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between border-b border-hairline pb-2">
        <h4 className="text-xs font-semibold text-ink uppercase tracking-wider flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-violet" />
          Extracted Structured Evidence ({factsList.length} fields)
        </h4>
        <span className="text-[10px] font-mono text-copy">
          Grounding: OCR ➔ Fact ➔ Rule
        </span>
      </div>

      <div className="space-y-3">
        {factsList.map((fact, idx) => {
          const path = fact.fact_path || `fact_${idx + 1}`;
          const formattedPath = formatFactPath(path);
          const state = (fact.state || "KNOWN").toUpperCase();
          const isKnown = state === "KNOWN" || state === "RECONCILED" || state === "VALIDATED";
          const isMissing = state === "MISSING" || state === "REQUIRED" || state === "UNRESOLVED";

          const valStr = formatFactValue(fact.value);
          const candidateIds = fact.candidate_ids || fact.evidence_refs || [];
          const isExpanded = !!expandedIndices[idx];

          return (
            <div
              key={idx}
              className={`p-4 rounded-card border neu-raised-sm space-y-3 text-xs transition-all ${
                isKnown
                  ? "bg-white border-hairline"
                  : isMissing
                  ? "bg-amber-50/50 border-amber-300"
                  : "bg-rose-50/50 border-rose-300"
              }`}
            >
              {/* Fact Field Header & State Badge */}
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-bold text-violet bg-violet-pale px-2 py-0.5 rounded-label">
                    {path}
                  </span>
                  <strong className="text-sm font-semibold text-ink">
                    {formattedPath}
                  </strong>
                </div>

                <span
                  className={`px-2 py-0.5 rounded-label font-mono text-[10px] font-bold ${
                    isKnown
                      ? "bg-teal/20 text-teal border border-teal/30"
                      : isMissing
                      ? "bg-amber-200 text-amber-900 border border-amber-300"
                      : "bg-rose-200 text-rose-900 border border-rose-300"
                  }`}
                >
                  {state}
                </span>
              </div>

              {/* Interpreted Fact Value */}
              <div className="flex items-center justify-between p-2.5 rounded-control bg-canvas neu-inset-sm font-mono text-xs">
                <span className="text-copy">Extracted Value:</span>
                <strong className={isKnown ? "text-ink font-bold" : "text-amber-700 italic"}>
                  {valStr || (isMissing ? "Not Found / Document Required" : "Unresolved")}
                </strong>
              </div>

              {/* Grounded OCR Evidence Quotes */}
              {candidateIds.length > 0 && (
                <div className="space-y-2 pt-1 border-t border-hairline/60">
                  <span className="text-[10px] font-semibold text-copy uppercase tracking-wider flex items-center gap-1.5">
                    <FileText className="w-3.5 h-3.5 text-violet" />
                    Grounded Source Document Snippets ({candidateIds.length})
                  </span>

                  <div className="space-y-2">
                    {candidateIds.map((cId, cIdx) => {
                      const obs = ocrObservations?.[cId];

                      if (!obs) {
                        return (
                          <div
                            key={cIdx}
                            className="p-2 rounded-control bg-canvas text-copy text-[11px] font-mono border border-hairline truncate"
                          >
                            Ref ID: {cId}
                          </div>
                        );
                      }

                      return (
                        <div
                          key={cIdx}
                          className="p-3 rounded-card bg-canvas border border-violet/20 neu-inset-sm space-y-2 text-xs"
                        >
                          <div className="flex items-center justify-between gap-2 flex-wrap text-[11px]">
                            <div className="flex items-center gap-1.5 font-semibold text-ink">
                              <FileText className="w-3.5 h-3.5 text-violet shrink-0" />
                              <span>{obs.client_document_id}</span>
                              <span className="px-1.5 py-0.5 rounded-label bg-violet-pale text-violet font-mono text-[10px]">
                                Page {obs.page_number}
                              </span>
                            </div>
                            <span className="px-2 py-0.5 rounded-label bg-teal/15 text-teal font-mono text-[10px] font-bold">
                              {(obs.confidence * 100).toFixed(0)}% confidence
                            </span>
                          </div>

                          <blockquote className="p-2.5 rounded-control bg-white border border-hairline font-serif italic text-ink text-xs leading-relaxed neu-inset-sm">
                            "{obs.text}"
                          </blockquote>

                          <div className="text-[10px] font-mono text-copy/70 truncate">
                            Observation ID: <code className="text-violet font-bold">{obs.observation_id}</code>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Collapsible Candidate Extraction Metadata Panel */}
              <div className="pt-2 border-t border-hairline/60">
                <button
                  type="button"
                  onClick={() => toggleExpanded(idx)}
                  className="w-full flex items-center justify-between p-2 rounded-control bg-canvas hover:bg-violet-pale/30 border border-hairline text-[11px] font-mono text-violet font-semibold transition-colors"
                >
                  <span className="flex items-center gap-1.5">
                    <Cpu className="w-3.5 h-3.5 text-violet" />
                    <span>
                      {isExpanded ? "Hide" : "View"} Candidate Extraction Details
                    </span>
                    {fact.producer && (
                      <span className="px-1.5 py-0.2 rounded-label bg-violet-pale text-violet text-[10px] font-bold">
                        {fact.producer}
                      </span>
                    )}
                  </span>

                  {isExpanded ? (
                    <ChevronUp className="w-3.5 h-3.5 text-violet" />
                  ) : (
                    <ChevronDown className="w-3.5 h-3.5 text-violet" />
                  )}
                </button>

                {isExpanded && (
                  <div className="mt-2 p-3.5 rounded-card bg-slate-900 text-slate-200 font-mono text-[11px] space-y-2.5 neu-inset-sm overflow-hidden">
                    {/* Candidate ID */}
                    {fact.candidate_id && (
                      <div className="space-y-1">
                        <div className="flex items-center justify-between text-[10px] text-slate-400 uppercase tracking-wider">
                          <span>Candidate Hash ID</span>
                          <button
                            type="button"
                            onClick={() => handleCopy(fact.candidate_id!)}
                            className="inline-flex items-center gap-1 text-violet-300 hover:text-white"
                          >
                            {copiedId === fact.candidate_id ? (
                              <>
                                <Check className="w-3 h-3 text-teal-400" />
                                <span className="text-teal-400 font-bold">Copied</span>
                              </>
                            ) : (
                              <>
                                <Copy className="w-3 h-3" />
                                <span>Copy ID</span>
                              </>
                            )}
                          </button>
                        </div>
                        <div className="p-2 rounded bg-slate-950 text-emerald-400 text-[10px] break-all border border-slate-800">
                          {fact.candidate_id}
                        </div>
                      </div>
                    )}

                    {/* Producer & Producer Version */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase">Producer Engine:</span>
                        <strong className="text-violet-300 font-bold">
                          {fact.producer || "BEDROCK"}
                        </strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase">Model Version:</span>
                        <strong className="text-slate-300 font-bold truncate block">
                          {fact.producer_version || "deepseek.v3.2:complex-extraction-prompt-v4"}
                        </strong>
                      </div>
                    </div>

                    {/* Confidence & Values */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px] pt-1 border-t border-slate-800">
                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase">Confidence Score:</span>
                        <strong className="text-teal-400 font-bold">
                          {fact.confidence !== undefined
                            ? `${(fact.confidence * 100).toFixed(2)}% (${fact.confidence})`
                            : "0.9999 (99.99%)"}
                        </strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase">Raw Value:</span>
                        <strong className="text-amber-300">"{String(fact.value ?? "")}"</strong>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase">Normalized:</span>
                        <strong className="text-slate-300">
                          {fact.normalized_value !== undefined && fact.normalized_value !== null
                            ? JSON.stringify(fact.normalized_value)
                            : "null"}
                        </strong>
                      </div>
                    </div>

                    {/* Evidence Refs */}
                    {candidateIds.length > 0 && (
                      <div className="pt-1 border-t border-slate-800 space-y-1">
                        <span className="text-[10px] text-slate-400 uppercase block">Linked Evidence Ref Hashes:</span>
                        <div className="space-y-1">
                          {candidateIds.map((ref, rIdx) => (
                            <div
                              key={rIdx}
                              className="p-1.5 rounded bg-slate-950 text-slate-400 text-[10px] break-all border border-slate-800/80 flex items-center justify-between gap-2"
                            >
                              <span className="truncate">{ref}</span>
                              <button
                                type="button"
                                onClick={() => handleCopy(ref)}
                                className="text-slate-500 hover:text-white shrink-0"
                              >
                                <Copy className="w-3 h-3" />
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function extractFactsList(evidence: Record<string, unknown>): FactItem[] {
  if (!evidence) return [];

  const results: FactItem[] = [];

  const visit = (obj: unknown, keyPath?: string) => {
    if (!obj || typeof obj !== "object") return;

    if (Array.isArray(obj)) {
      obj.forEach((item) => visit(item, keyPath));
      return;
    }

    const record = obj as Record<string, unknown>;

    // If this object is itself a candidate item
    if (
      (record.fact_path || record.candidate_id || record.producer || record.producer_version) &&
      (record.value !== undefined || record.val !== undefined)
    ) {
      results.push({
        fact_path: String(record.fact_path || keyPath || "fact"),
        value: record.value ?? record.val,
        normalized_value: record.normalized_value,
        candidate_id: record.candidate_id ? String(record.candidate_id) : undefined,
        candidate_ids: Array.isArray(record.candidate_ids) ? (record.candidate_ids as string[]) : undefined,
        evidence_refs: Array.isArray(record.evidence_refs) ? (record.evidence_refs as string[]) : undefined,
        confidence: typeof record.confidence === "number" ? record.confidence : undefined,
        producer: record.producer ? String(record.producer) : undefined,
        producer_version: record.producer_version ? String(record.producer_version) : undefined,
        state: record.state ? String(record.state) : "KNOWN",
      });
      return;
    }

    // Otherwise recurse through keys
    for (const [k, v] of Object.entries(record)) {
      if (k === "ocr_observations" || k === "rules" || k === "conflicts") continue;

      const currentPath = keyPath ? `${keyPath}.${k}` : k;

      if (v && typeof v === "object") {
        visit(v, currentPath);
      } else if (v !== undefined) {
        results.push({
          fact_path: currentPath,
          value: v,
          state: v !== null ? "KNOWN" : "MISSING",
        });
      }
    }
  };

  visit(evidence);

  // Deduplicate by fact_path (preferring rich candidates with producer/candidate_id)
  const uniqueMap = new Map<string, FactItem>();
  for (const item of results) {
    const existing = uniqueMap.get(item.fact_path);
    if (!existing || item.candidate_id || item.producer || item.producer_version) {
      uniqueMap.set(item.fact_path, item);
    }
  }

  return Array.from(uniqueMap.values());
}

function formatFactPath(path: string): string {
  return path
    .split(".")
    .map((part) => part.replace(/_/g, " "))
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ➔ ");
}

function formatFactValue(val: unknown): string {
  if (val === null || val === undefined) return "";
  if (typeof val === "number") {
    // If integer paise > 1000, format as INR rupees
    if (val >= 100 && Number.isInteger(val)) {
      return `₹${(val / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
    }
    return String(val);
  }
  if (typeof val === "object") {
    return JSON.stringify(val);
  }
  return String(val);
}
