"use client";

import { useState } from "react";
import { ChevronRight, Code, Copy, Check } from "lucide-react";

interface JsonDisclosureProps {
  title: string;
  data: unknown;
  defaultOpen?: boolean;
}

export function JsonDisclosure({
  title,
  data,
  defaultOpen = false,
}: JsonDisclosureProps) {
  const [copied, setCopied] = useState(false);

  const jsonString = JSON.stringify(data, null, 2);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(jsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <details
      open={defaultOpen}
      className="group rounded-card bg-canvas border border-hairline neu-inset-sm overflow-hidden transition-all"
    >
      <summary className="px-4 py-3 cursor-pointer flex items-center justify-between gap-3 bg-white/30 hover:bg-violet-pale/30 select-none font-semibold text-xs text-ink transition-colors">
        <div className="flex items-center gap-2">
          <ChevronRight className="w-4 h-4 text-violet transition-transform group-open:rotate-90" />
          <Code className="w-4 h-4 text-copy" />
          <span>{title}</span>
        </div>
        <button
          onClick={handleCopy}
          type="button"
          className="inline-flex items-center gap-1 px-2 py-1 rounded-control bg-canvas hover:bg-violet-pale text-[11px] text-copy hover:text-violet neu-raised-sm border border-hairline transition-all"
        >
          {copied ? (
            <>
              <Check className="w-3 h-3 text-teal" />
              <span className="text-teal">Copied!</span>
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" />
              <span>Copy JSON</span>
            </>
          )}
        </button>
      </summary>
      <div className="p-4 bg-darkContrast text-slate-200 overflow-x-auto text-xs font-mono border-t border-hairline max-h-96">
        <pre className="whitespace-pre-wrap break-words">{jsonString}</pre>
      </div>
    </details>
  );
}
