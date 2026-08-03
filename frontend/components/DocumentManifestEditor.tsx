"use client";

import { DocumentManifestItem } from "@/lib/claims-types";
import { createUuid } from "@/lib/ids";
import { FileCode2, ArrowUp, ArrowDown, RefreshCw } from "lucide-react";

interface DocumentManifestEditorProps {
  files: File[];
  manifest: DocumentManifestItem[];
  onManifestChange: (manifest: DocumentManifestItem[]) => void;
}

export function DocumentManifestEditor({
  files,
  manifest,
  onManifestChange,
}: DocumentManifestEditorProps) {
  if (files.length === 0) return null;

  const handleIdChange = (index: number, newId: string) => {
    const updated = [...manifest];
    updated[index] = { ...updated[index], client_document_id: newId };
    onManifestChange(updated);
  };

  const regenerateId = (index: number) => {
    const updated = [...manifest];
    updated[index] = {
      ...updated[index],
      client_document_id: `doc-${createUuid().slice(0, 8)}`,
    };
    onManifestChange(updated);
  };

  return (
    <div className="space-y-3 p-4 rounded-card bg-canvas neu-inset border border-hairline">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold text-ink flex items-center gap-1.5 uppercase tracking-wider">
          <FileCode2 className="w-4 h-4 text-violet" />
          Document Manifest ({manifest.length} items)
        </h4>
        <span className="text-[11px] text-copy">
          Client IDs mapped to file indices
        </span>
      </div>

      <div className="space-y-2">
        {manifest.map((item, index) => {
          const file = files[index];
          return (
            <div
              key={index}
              className="p-3 rounded-control bg-white/60 border border-hairline neu-raised-sm grid grid-cols-1 sm:grid-cols-12 gap-3 items-center text-xs"
            >
              <div className="sm:col-span-1 font-mono font-bold text-violet text-center">
                #{item.upload_index}
              </div>

              <div className="sm:col-span-5 truncate text-ink font-medium">
                {file ? file.name : `File ${index}`}
              </div>

              <div className="sm:col-span-6 flex items-center gap-2">
                <input
                  type="text"
                  value={item.client_document_id}
                  onChange={(e) => handleIdChange(index, e.target.value)}
                  className="w-full px-2.5 py-1.5 rounded-control bg-canvas border border-hairline neu-inset-sm font-mono text-xs text-ink focus:outline-none focus:ring-2 focus:ring-violet"
                  placeholder="client_document_id"
                />
                <button
                  type="button"
                  onClick={() => regenerateId(index)}
                  className="p-1.5 rounded-control bg-canvas hover:bg-violet-pale text-copy hover:text-violet neu-raised-sm border border-hairline transition-colors shrink-0"
                  title="Regenerate random client document ID"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
