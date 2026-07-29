import { Money } from "@/lib/claims-types";
import { MinusCircle, ListFilter, AlertCircle } from "lucide-react";

interface DeductionListProps {
  deductions: Array<{
    code: string;
    label: string;
    amount: Money;
  }>;
  lineItems: Array<{
    concept: string;
    label: string;
    claimed_amount: Money;
    approved_amount: Money;
    status: string;
    reason_code: string;
  }>;
}

export function DeductionList({ deductions, lineItems }: DeductionListProps) {
  if (deductions.length === 0 && lineItems.length === 0) return null;

  return (
    <div className="space-y-6">
      {/* Deductions Breakdown */}
      {deductions.length > 0 && (
        <div className="p-4 rounded-card bg-canvas neu-inset border border-hairline space-y-3">
          <h4 className="text-xs font-semibold text-ink uppercase tracking-wider flex items-center gap-2">
            <MinusCircle className="w-4 h-4 text-danger" />
            Applied Deductions ({deductions.length})
          </h4>

          <div className="space-y-2">
            {deductions.map((d, i) => (
              <div
                key={i}
                className="p-3 rounded-control bg-white/60 border border-hairline neu-raised-sm flex items-center justify-between gap-3 text-xs"
              >
                <div className="space-y-0.5">
                  <span className="font-semibold text-ink">{d.label}</span>
                  <div className="flex items-center gap-2">
                    <span className="px-1.5 py-0.5 rounded-label bg-danger/10 text-danger font-mono text-[10px] font-semibold">
                      {d.code}
                    </span>
                  </div>
                </div>
                <div className="font-mono font-bold text-danger text-sm">
                  -₹{d.amount}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Line Items Table */}
      {lineItems.length > 0 && (
        <div className="p-4 rounded-card bg-canvas neu-inset border border-hairline space-y-3">
          <h4 className="text-xs font-semibold text-ink uppercase tracking-wider flex items-center gap-2">
            <ListFilter className="w-4 h-4 text-violet" />
            Line Item Breakdown ({lineItems.length})
          </h4>

          <div className="overflow-x-auto rounded-control border border-hairline">
            <table className="w-full text-xs text-left">
              <thead className="bg-violet-pale text-ink font-display uppercase tracking-wider text-[10px]">
                <tr>
                  <th className="p-2.5">Concept / Label</th>
                  <th className="p-2.5">Claimed</th>
                  <th className="p-2.5">Approved</th>
                  <th className="p-2.5">Status</th>
                  <th className="p-2.5">Reason Code</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline bg-white/50">
                {lineItems.map((item, idx) => (
                  <tr key={idx} className="hover:bg-white/80 transition-colors">
                    <td className="p-2.5">
                      <div className="font-semibold text-ink">{item.label}</div>
                      <div className="text-[10px] text-copy font-mono">{item.concept}</div>
                    </td>
                    <td className="p-2.5 font-mono">₹{item.claimed_amount}</td>
                    <td className="p-2.5 font-mono font-semibold text-teal">
                      ₹{item.approved_amount}
                    </td>
                    <td className="p-2.5">
                      <span
                        className={`px-2 py-0.5 rounded-label text-[10px] font-semibold ${
                          item.status === "APPROVED"
                            ? "bg-teal/20 text-teal"
                            : item.status === "PARTIAL"
                            ? "bg-amber-100 text-amber-800"
                            : "bg-danger/20 text-danger"
                        }`}
                      >
                        {item.status}
                      </span>
                    </td>
                    <td className="p-2.5 font-mono text-[10px] text-copy">
                      {item.reason_code || "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
