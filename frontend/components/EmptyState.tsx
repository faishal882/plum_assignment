import { ReactNode } from "react";
import { Inbox } from "lucide-react";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: EmptyStateProps) {
  return (
    <div className="p-12 text-center rounded-card bg-canvas neu-inset border border-hairline flex flex-col items-center justify-center space-y-4 max-w-md mx-auto">
      <div className="w-12 h-12 rounded-control bg-violet-pale text-violet flex items-center justify-center neu-raised-sm">
        {icon || <Inbox className="w-6 h-6" />}
      </div>
      <div className="space-y-1">
        <h3 className="font-display font-semibold text-lg text-ink">{title}</h3>
        <p className="text-sm text-copy">{description}</p>
      </div>
      {action && <div className="pt-2">{action}</div>}
    </div>
  );
}
