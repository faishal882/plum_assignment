import { useState, useMemo } from "react";
import { OcrObservation } from "@/lib/claims-types";
import { FileSearch, Search, Filter, ChevronDown, ChevronUp, Copy, Check } from "lucide-react";

interface AllOcrObservationsRegistryProps {
  observations: Record<string, OcrObservation>;
  title?: string;
  defaultOpen?: boolean;
}

export function AllOcrObservationsRegistry({
  observations,
  title = "All Extracted OCR Observations (Audit Registry)",
  defaultOpen = false,
}: AllOcrObservationsRegistryProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedDoc, setSelectedDoc] = useState<string>("ALL");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const obsList = useMemo(() => Object.values(observations || {}), [observations]);

  const documentNames = useMemo(() => {
    const set = new Set<string>();
    obsList.forEach((obs) => {
      if (obs.client_document_id) set.add(obs.client_document_id);
    });
    return Array.from(set);
  }, [obsList]);

  const filteredList = useMemo(() => {
    return obsList.filter((obs) => {
      const matchesDoc = selectedDoc === "ALL" || obs.client_document_id === selectedDoc;
      const q = searchQuery.toLowerCase().trim();
      const matchesQuery =
        !q ||
        obs.text.toLowerCase().includes(q) ||
        obs.observation_id.toLowerCase().includes(q) ||
        (obs.field_type && obs.field_type.toLowerCase().includes(q)) ||
        (obs.kind && obs.kind.toLowerCase().includes(q));
      return matchesDoc && matchesQuery;
    });
  }, [obsList, selectedDoc, searchQuery]);

  const handleCopy = (id: string) => {
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  if (obsList.length === 0) {
    return null;
  }

  return (
    <div className="rounded-card bg-canvas neu-raised border border-hairline overflow-hidden space-y-0">
      {/* Accordion Header */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full p-4 flex items-center justify-between gap-4 text-left hover:bg-violet-pale/30 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <FileSearch className="w-4 h-4 text-violet" />
          <div>
            <h4 className="text-xs font-semibold text-ink uppercase tracking-wider">
              {title}
            </h4>
            <p className="text-[11px] text-copy">
              {obsList.length} total OCR snippets extracted across {documentNames.length} document(s)
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 rounded-label bg-canvas border border-hairline font-mono text-[10px] text-copy">
            {isOpen ? "Click to Collapse" : "Expand Debug Registry"}
          </span>
          {isOpen ? (
            <ChevronUp className="w-4 h-4 text-violet" />
          ) : (
            <ChevronDown className="w-4 h-4 text-violet" />
          )}
        </div>
      </button>

      {/* Accordion Body */}
      {isOpen && (
        <div className="p-4 border-t border-hairline space-y-4 bg-white/40">
          {/* Controls: Search Box & Document Filter Tabs */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            {/* Search Input */}
            <div className="relative flex-1">
              <Search className="w-3.5 h-3.5 text-copy absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search OCR text, field, or observation ID..."
                className="w-full pl-9 pr-3 py-1.5 rounded-control bg-canvas border border-hairline font-mono text-xs text-ink neu-inset-sm focus:outline-none focus:ring-1 focus:ring-violet"
              />
            </div>

            {/* Document Filter Pill Buttons */}
            {documentNames.length > 1 && (
              <div className="flex items-center gap-1.5 flex-wrap shrink-0">
                <button
                  type="button"
                  onClick={() => setSelectedDoc("ALL")}
                  className={`px-2.5 py-1 rounded-control text-[11px] font-semibold border transition-all ${
                    selectedDoc === "ALL"
                      ? "bg-violet text-white border-violet neu-raised-sm"
                      : "bg-canvas text-copy border-hairline hover:bg-violet-pale"
                  }`}
                >
                  All Docs ({obsList.length})
                </button>

                {documentNames.map((docName) => {
                  const count = obsList.filter((o) => o.client_document_id === docName).length;
                  return (
                    <button
                      key={docName}
                      type="button"
                      onClick={() => setSelectedDoc(docName)}
                      className={`px-2.5 py-1 rounded-control text-[11px] font-semibold border transition-all ${
                        selectedDoc === docName
                          ? "bg-violet text-white border-violet neu-raised-sm"
                          : "bg-canvas text-copy border-hairline hover:bg-violet-pale"
                      }`}
                    >
                      {docName} ({count})
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Results List */}
          <div className="space-y-2.5 max-h-[500px] overflow-y-auto pr-1">
            {filteredList.length === 0 ? (
              <div className="p-8 text-center text-xs text-copy bg-canvas rounded-control border border-hairline font-mono">
                No OCR observations matched "{searchQuery}"
              </div>
            ) : (
              filteredList.map((obs) => (
                <div
                  key={obs.observation_id}
                  className="p-3.5 rounded-card bg-white border border-hairline neu-raised-sm space-y-2 text-xs"
                >
                  <div className="flex items-center justify-between gap-2 flex-wrap text-[11px]">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-ink flex items-center gap-1.5">
                        <FileSearch className="w-3.5 h-3.5 text-violet" />
                        {obs.client_document_id}
                      </span>
                      <span className="px-1.5 py-0.5 rounded-label bg-violet-pale text-violet font-mono text-[10px]">
                        Page {obs.page_number}
                      </span>
                      {obs.field_type && (
                        <span className="px-1.5 py-0.5 rounded-label bg-canvas border border-hairline font-mono text-[10px] text-copy">
                          {obs.field_type}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded-label bg-teal/15 text-teal font-mono text-[10px] font-bold">
                        {(obs.confidence * 100).toFixed(0)}% confidence
                      </span>
                      {obs.kind && (
                        <span className="px-1.5 py-0.5 rounded-label bg-canvas font-mono text-[10px] text-copy border border-hairline uppercase">
                          {obs.kind}
                        </span>
                      )}
                    </div>
                  </div>

                  <blockquote className="p-2.5 rounded-control bg-canvas border border-hairline font-serif italic text-ink text-xs leading-relaxed neu-inset-sm">
                    "{obs.text}"
                  </blockquote>

                  <div className="flex items-center justify-between text-[10px] font-mono text-copy/70 pt-0.5">
                    <button
                      type="button"
                      onClick={() => handleCopy(obs.observation_id)}
                      className="inline-flex items-center gap-1 text-violet hover:underline"
                    >
                      {copiedId === obs.observation_id ? (
                        <>
                          <Check className="w-3 h-3 text-teal" />
                          <span className="text-teal font-bold">Copied ID!</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3 h-3" />
                          <span>ID: {obs.observation_id}</span>
                        </>
                      )}
                    </button>

                    {obs.region && Object.keys(obs.region).length > 0 && (
                      <span className="text-copy/60 shrink-0 ml-2">
                        Region: {JSON.stringify(obs.region)}
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
