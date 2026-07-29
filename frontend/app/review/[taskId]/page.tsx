"use client";

import { use, useEffect, useState, useCallback } from "react";
import { AppShell } from "@/components/AppShell";
import { ReviewTaskDetail } from "@/components/ReviewTaskDetail";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ReviewTaskDetail as ReviewTaskDetailType, ApiErrorResponse } from "@/lib/claims-types";
import { RefreshCw, ArrowLeft } from "lucide-react";
import Link from "next/link";

interface ReviewTaskDetailPageProps {
  params: Promise<{ taskId: string }>;
}

export default function ReviewTaskDetailPage({ params }: ReviewTaskDetailPageProps) {
  const { taskId } = use(params);

  const [taskDetail, setTaskDetail] = useState<ReviewTaskDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiErrorResponse | string | null>(null);

  const fetchTaskDetail = useCallback(async () => {
    setLoading(true);
    try {
      const devUsername =
        localStorage.getItem("plum_dev_username") || "reviewer.local";

      const res = await fetch(`/api/review-tasks/${taskId}`, {
        headers: {
          "X-Dev-Username": devUsername,
        },
        cache: "no-store",
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data);
      } else {
        setTaskDetail(data as ReviewTaskDetailType);
        setError(null);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load review task detail");
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    fetchTaskDetail();
  }, [fetchTaskDetail]);

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Back Link Header */}
        <div className="flex items-center justify-between">
          <Link
            href="/review"
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-control bg-canvas hover:bg-violet-pale text-xs font-semibold text-ink neu-raised-sm border border-hairline transition-all"
          >
            <ArrowLeft className="w-4 h-4 text-violet" />
            <span>Back to Review Queue</span>
          </Link>

          <button
            onClick={fetchTaskDetail}
            className="p-1.5 rounded-control bg-canvas hover:bg-violet-pale text-copy hover:text-violet neu-raised-sm border border-hairline transition-colors"
            title="Refresh Task Detail"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>

        {error && <ErrorCallout error={error} title="Failed to load review task" />}

        {loading && !taskDetail ? (
          <div className="p-12 text-center rounded-card bg-canvas neu-inset border border-hairline space-y-3">
            <RefreshCw className="w-8 h-8 text-violet animate-spin mx-auto" />
            <p className="text-sm font-semibold text-ink">
              Fetching task evidence and rule trace...
            </p>
          </div>
        ) : taskDetail ? (
          <ReviewTaskDetail taskDetail={taskDetail} onRefresh={fetchTaskDetail} />
        ) : null}
      </div>
    </AppShell>
  );
}
