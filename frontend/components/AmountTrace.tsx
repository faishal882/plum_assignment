interface AmountTraceProps {
  beforePaise?: number;
  adjustmentPaise?: number;
  afterPaise?: number;
  currency?: string;
}

export function AmountTrace({
  beforePaise,
  adjustmentPaise,
  afterPaise,
  currency = "INR",
}: AmountTraceProps) {
  if (
    beforePaise === undefined &&
    adjustmentPaise === undefined &&
    afterPaise === undefined
  ) {
    return null;
  }

  const formatPaise = (p?: number) => {
    if (p === undefined) return "-";
    return (p / 100).toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

  const isDeduction = (adjustmentPaise || 0) < 0;

  return (
    <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-control bg-canvas neu-inset-sm border border-hairline font-mono text-xs text-ink">
      <span>Before: ₹{formatPaise(beforePaise)}</span>
      {adjustmentPaise !== undefined && adjustmentPaise !== 0 && (
        <span
          className={`font-semibold ${
            isDeduction ? "text-danger" : "text-teal"
          }`}
        >
          ({isDeduction ? "" : "+"}₹{formatPaise(adjustmentPaise)})
        </span>
      )}
      <span className="text-copy font-sans">➔</span>
      <span className="font-bold text-violet">
        After: ₹{formatPaise(afterPaise)}
      </span>
    </div>
  );
}
