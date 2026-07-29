"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ReviewTaskList } from "@/components/ReviewTaskList";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ReviewTaskSummary, ApiErrorResponse } from "@/lib/claims-types";
import { RefreshCw } from "lucide-react";

export default function ReviewQueuePage() {
  const [tasks, setTasks] = useState<ReviewTaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiErrorResponse | string | null>(null);

  const fetchReviewTasks = async () => {
    setLoading(true);
    try {
      const devUsername =
        localStorage.getItem("plum_dev_username") || "reviewer.local";

      const res = await fetch("/api/review-tasks", {
        headers: {
          "X-Dev-Username": devUsername,
        },
        cache: "no-store",
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data);
      } else {
        setTasks(data as ReviewTaskSummary[]);
        setError(null);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load review queue");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReviewTasks();
  }, []);

  return (
    <AppShell>
      <div className="space-y-6">
        {error && <ErrorCallout error={error} title="Review Queue Error" />}

        {loading ? (
          <div className="p-12 text-center rounded-card bg-canvas neu-inset border border-hairline space-y-3">
            <RefreshCw className="w-8 h-8 text-violet animate-spin mx-auto" />
            <p className="text-sm font-semibold text-ink">
              Loading review task queue...
            </p>
          </div>
        ) : (
          <ReviewTaskList tasks={tasks} />
        )}
      </div>
    </AppShell>
  );
}
